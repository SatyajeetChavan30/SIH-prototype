"""
Tests for the observation-conditioned DEM update.

The claim these guard is a labelling claim as much as a numerical one. An
updated DEM is a file that outlives this repository: it gets downloaded, emailed
and opened in QGIS by people who never read a docstring. So the provenance is
asserted at the FILE level — open the GeoTIFF, read its tags — not at the dict
level, because the dict is not what reaches them.

Three tests carry most of the weight:

- ``test_every_updated_dem_carries_the_not_a_survey_tag`` — the file must say it
  is not photogrammetry, in its own metadata.
- ``test_manual_source_is_never_labelled_sentinel`` — a barrier somebody typed in
  must never come back wearing a satellite scene id.
- ``test_unmodified_pixels_are_bit_identical_to_the_source`` — the delta-add
  design's whole point, and the reason a reprojection round trip was rejected.

No network, no Earth Engine. The source DEM is written by the test.
"""

import json
from pathlib import Path

import numpy as np
import pytest
import rasterio
from affine import Affine
from rasterio.crs import CRS

from jalraksha.terrain.dem_update import (
    NOT_A_SURVEY_NOTICE,
    BlockageSpec,
    DemUpdateError,
    cache_key,
    dam_config_updates_from_provenance,
    write_observation_conditioned_dem,
)

# A valley in the Alaknanda basin, near enough to Rishi Ganga to exercise the
# same UTM zone (43N/44N boundary country) without pretending to be that site.
BARRIER_LAT = 30.4000
BARRIER_LON = 79.6000
DOMAIN_RADIUS_KM = 6.0
TARGET_RESOLUTION_M = 100.0


@pytest.fixture
def stale_dem(tmp_path):
    """
    A pre-event GLO-30-like clip: a V-valley in EPSG:4326 at 1 arc-second.

    Written rather than fetched so the test runs offline and so the exact pixel
    values are known — ``test_unmodified_pixels_are_bit_identical_to_the_source``
    needs a source it can compare against byte for byte.
    """
    arcsecond = 1.0 / 3600.0
    half_span_deg = 0.12
    n = int(round(2 * half_span_deg / arcsecond))

    west = BARRIER_LON - half_span_deg
    north = BARRIER_LAT + half_span_deg
    transform = Affine.translation(west, north) * Affine.scale(arcsecond, -arcsecond)

    columns = np.arange(n)[None, :]
    rows = np.arange(n)[:, None]
    lon = west + (columns + 0.5) * arcsecond
    lat = north - (rows + 0.5) * arcsecond

    # Metres per degree, near enough at this latitude for a synthetic valley.
    east_m = (lon - BARRIER_LON) * 96000.0
    # Row 0 is north; the valley descends northward, so upstream is +south.
    upstream_m = (lat - BARRIER_LAT) * -111000.0

    bed = 1000.0 + 0.01 * upstream_m + 0.12 * np.abs(east_m)
    bed = np.clip(bed, 900.0, 3000.0).astype(np.float32)

    path = tmp_path / "dem_30.40_79.60_clipped.tif"
    with rasterio.open(
        str(path), "w", driver="GTiff", height=n, width=n, count=1,
        dtype="float32", crs=CRS.from_epsg(4326), transform=transform,
        nodata=-32767.0, compress="deflate",
    ) as dst:
        dst.write(bed, 1)
    return path


@pytest.fixture
def spec():
    return BlockageSpec(
        barrier_lat=BARRIER_LAT,
        barrier_lon=BARRIER_LON,
        crest_height_m=55.0,
        width_m=1200.0,
        direction_search_radius_cells=(5, 12),
    )


def _write(stale_dem, spec, out_dir, **kwargs):
    kwargs.setdefault("target_resolution", TARGET_RESOLUTION_M)
    kwargs.setdefault("domain_radius_km", DOMAIN_RADIUS_KM)
    kwargs.setdefault("register_cache", False)
    return write_observation_conditioned_dem(stale_dem, spec, out_dir, **kwargs)


# ── Provenance ────────────────────────────────────────────────────────────────


class TestProvenance:
    def test_every_updated_dem_carries_the_not_a_survey_tag(
        self, stale_dem, spec, tmp_path
    ):
        """
        Asserted on the file, not on the return value. The GeoTIFF is what a
        judge opens; a correct dict inside a process nobody is running is not a
        label.
        """
        path, _ = _write(stale_dem, spec, tmp_path / "updated")

        with rasterio.open(path) as src:
            tags = src.tags()

        assert tags["JALRAKSHA_PRODUCT"] == "observation_conditioned_dem_update"
        assert tags["JALRAKSHA_NOT_A_SURVEY"] == NOT_A_SURVEY_NOTICE
        for forbidden in ("photogrammetr", "insar", "derived from imagery"):
            assert forbidden in tags["JALRAKSHA_NOT_A_SURVEY"].lower()
        assert tags["SOURCE_DEM_MD5"]
        assert tags["OBSERVATION_SOURCE"] in (
            "sentinel1_grd", "cached", "manual_operator_input",
        )
        assert tags["VOLUME_DATUM"].startswith("above pre-event water surface")

    def test_manual_source_is_never_labelled_sentinel(self, stale_dem, spec, tmp_path):
        path, provenance = _write(stale_dem, spec, tmp_path / "updated")

        assert provenance.observation_source == "manual_operator_input"
        assert provenance.observation_scene_id is None

        with rasterio.open(path) as src:
            tags = src.tags()
        assert "OBSERVATION_SCENE_ID" not in tags
        assert "sentinel" not in tags["OBSERVATION_SOURCE"].lower()

    def test_a_manual_barrier_carrying_a_scene_id_is_refused(
        self, stale_dem, spec, tmp_path
    ):
        """
        The label is the only thing telling a reader whether anything was
        actually observed. Letting a hand-placed barrier borrow a scene id would
        make the honest and dishonest cases indistinguishable in the file.
        """
        with pytest.raises(DemUpdateError, match="never be labelled"):
            _write(
                stale_dem, spec, tmp_path / "updated",
                observation={
                    "source": "manual_operator_input",
                    "scene_id": "S1A_IW_GRDH_1SDV_20210208T003345",
                },
            )

    def test_an_unknown_observation_source_is_refused(self, stale_dem, spec, tmp_path):
        with pytest.raises(DemUpdateError, match="no fourth state"):
            _write(
                stale_dem, spec, tmp_path / "updated",
                observation={"source": "synthetic"},
            )

    def test_a_sentinel_observation_reaches_the_file(self, stale_dem, spec, tmp_path):
        observation = {
            "source": "sentinel1_grd",
            "scene_id": "S1A_IW_GRDH_1SDV_20210208T003345",
            "acquired_at": "2021-02-08T00:33:45+00:00",
            "threshold_db": -16.4,
            "collection": "COPERNICUS/S1_GRD",
            "bbox": [79.5, 30.3, 79.7, 30.5],
        }
        path, provenance = _write(
            stale_dem, spec, tmp_path / "updated", observation=observation
        )

        with rasterio.open(path) as src:
            tags = src.tags()

        assert tags["OBSERVATION_SCENE_ID"] == observation["scene_id"]
        assert tags["OBSERVATION_ACQUIRED_AT"] == observation["acquired_at"]
        assert tags["OBSERVATION_THRESHOLD_DB"] == "-16.4"
        assert provenance.observation_source == "sentinel1_grd"

    def test_the_sidecar_carries_the_stage_storage_curve(
        self, stale_dem, spec, tmp_path
    ):
        """
        A curve does not fit in a flat GeoTIFF tag, so it lives in the sidecar.
        The dashboard plots it and the routing needs its exponent.
        """
        path, provenance = _write(stale_dem, spec, tmp_path / "updated")
        sidecar = path.with_suffix(".provenance.json")

        payload = json.loads(sidecar.read_text("utf-8"))
        table = payload["stage_storage"]

        assert len(table["levels_m"]) == len(table["volumes_m3"]) > 10
        assert table["volumes_m3"] == sorted(table["volumes_m3"])
        assert payload["barrier"]["downstream_leak_cells"] == 0
        assert provenance.stage_storage["fit_b"] > 1.0


class TestDeltaAdd:
    def test_unmodified_pixels_are_bit_identical_to_the_source(
        self, stale_dem, spec, tmp_path
    ):
        """
        The strongest statement this design can make: outside the barrier
        footprint nothing was resampled, smoothed, or nudged.

        A reprojection round trip through UTM would fail this on every pixel in
        the raster while still looking entirely correct in a viewer, which is
        why the writer adds a delta instead.
        """
        path, _ = _write(stale_dem, spec, tmp_path / "updated")

        with rasterio.open(stale_dem) as src:
            original = src.read(1)
        with rasterio.open(path) as src:
            updated = src.read(1)

        assert updated.shape == original.shape
        changed = updated != original
        assert changed.any(), "The update changed nothing at all."

        np.testing.assert_array_equal(updated[~changed], original[~changed])
        # And the change is a raise, never a lowering, for an overtop barrier.
        assert np.all(updated[changed] > original[changed])

    def test_the_lake_mask_is_written_and_labelled_an_initial_condition(
        self, stale_dem, spec, tmp_path
    ):
        """
        The lake is the extent a satellite would see once the barrier fills. It
        is NOT simulated inundation, and a viewer who mistakes one for the other
        reads a constructed initial condition as a modelled result.
        """
        path, provenance = _write(stale_dem, spec, tmp_path / "updated")

        lake = Path(provenance.lake_mask)
        assert lake.exists()
        assert lake.name.endswith("_lake.tif")

        with rasterio.open(lake) as src, rasterio.open(stale_dem) as ref:
            mask = src.read(1)
            tags = src.tags()
            assert src.crs == ref.crs
            assert src.transform == ref.transform
            assert src.dtypes[0] == "uint8"

        assert set(np.unique(mask)).issubset({0, 1}), "A mask must stay a mask."
        assert mask.sum() > 0
        assert tags["JALRAKSHA_PRODUCT"] == "impounded_lake_extent"
        assert "INITIAL CONDITION" in tags["JALRAKSHA_LAYER_MEANING"]
        assert "not a solver output" in tags["JALRAKSHA_LAYER_MEANING"]
        # The not-a-survey notice travels with every product, not only the DEM.
        assert tags["JALRAKSHA_NOT_A_SURVEY"] == NOT_A_SURVEY_NOTICE

    def test_the_lake_mask_area_agrees_with_the_reported_volume(
        self, stale_dem, spec, tmp_path
    ):
        """
        Two independently produced numbers for the same lake: the area the
        stage-storage sweep reported, and the area of the raster written from
        the mask. A large disagreement means the reprojection lost or invented
        cells.
        """
        _, provenance = _write(stale_dem, spec, tmp_path / "updated")

        with rasterio.open(provenance.lake_mask) as src:
            mask = src.read(1)
            cell_area_m2 = abs(src.transform.a * src.transform.e) * (111_320.0**2) * abs(
                np.cos(np.radians(BARRIER_LAT))
            )
        raster_area_km2 = mask.sum() * cell_area_m2 / 1e6

        assert raster_area_km2 == pytest.approx(
            provenance.lake["area_km2"], rel=0.25
        ), (
            f"The written mask covers {raster_area_km2:.3f} km2 but the sweep "
            f"reported {provenance.lake['area_km2']:.3f} km2."
        )

    def test_the_source_dem_is_never_modified(self, stale_dem, spec, tmp_path):
        with rasterio.open(stale_dem) as src:
            before = src.read(1).copy()
        _write(stale_dem, spec, tmp_path / "updated")
        with rasterio.open(stale_dem) as src:
            after = src.read(1)
        np.testing.assert_array_equal(before, after)

    def test_the_updated_dem_keeps_the_sources_crs_and_transform(
        self, stale_dem, spec, tmp_path
    ):
        """A drop-in replacement, so load_dem_as_grid needs no special case."""
        path, _ = _write(stale_dem, spec, tmp_path / "updated")

        with rasterio.open(stale_dem) as src, rasterio.open(path) as dst:
            assert dst.crs == src.crs
            assert dst.transform == src.transform
            assert dst.shape == src.shape
            assert dst.nodata == src.nodata


class TestContentAddressing:
    def test_spec_hash_changes_when_any_input_changes(self, stale_dem, tmp_path):
        base = BlockageSpec(BARRIER_LAT, BARRIER_LON, 55.0, 1200.0)
        variants = [
            BlockageSpec(BARRIER_LAT, BARRIER_LON, 60.0, 1200.0),
            BlockageSpec(BARRIER_LAT, BARRIER_LON, 55.0, 1500.0),
            BlockageSpec(BARRIER_LAT + 0.002, BARRIER_LON, 55.0, 1200.0),
            BlockageSpec(BARRIER_LAT, BARRIER_LON, 55.0, 1200.0, breach_mode="full_notch"),
        ]

        _, base_provenance = _write(stale_dem, base, tmp_path / "updated")
        hashes = {base_provenance.spec_hash}
        for variant in variants:
            _, provenance = _write(stale_dem, variant, tmp_path / "updated")
            hashes.add(provenance.spec_hash)

        assert len(hashes) == len(variants) + 1

    def test_the_scene_id_is_part_of_the_address(self, stale_dem, spec, tmp_path):
        """
        Re-running the same barrier against a NEWER scene must produce a new
        product, not silently serve yesterday's.
        """
        _, first = _write(
            stale_dem, spec, tmp_path / "updated",
            observation={"source": "sentinel1_grd", "scene_id": "SCENE_A"},
        )
        _, second = _write(
            stale_dem, spec, tmp_path / "updated",
            observation={"source": "sentinel1_grd", "scene_id": "SCENE_B"},
        )
        assert first.spec_hash != second.spec_hash
        assert first.updated_dem != second.updated_dem

    def test_an_identical_spec_reuses_the_written_product(
        self, stale_dem, spec, tmp_path
    ):
        out_dir = tmp_path / "updated"
        first_path, _ = _write(stale_dem, spec, out_dir)
        mtime = first_path.stat().st_mtime_ns

        second_path, provenance = _write(stale_dem, spec, out_dir)

        assert second_path == first_path
        assert second_path.stat().st_mtime_ns == mtime
        assert provenance.spec_hash

    def test_the_cache_key_names_the_product_not_the_dam(self):
        key = cache_key(BARRIER_LAT, BARRIER_LON, DOMAIN_RADIUS_KM, "abc123")
        assert key.startswith("jalraksha://dem/observation-conditioned/")
        assert "abc123" in key


class TestNamingCollisions:
    def test_updated_dem_is_not_discoverable_by_get_cached_dem(
        self, stale_dem, spec, tmp_path
    ):
        """
        cache.get_cached_dem ends in a SORTED glob over dem_{lat}_{lon}*.tif and
        returns the first match. An updated product written alongside the clipped
        originals would sort ahead of "..._clipped.tif" on the letter 'b' and
        silently become the DEM for every run at that location — dam-break runs
        included. Writing to a subdirectory makes that structurally impossible,
        and this test is what keeps it there.
        """
        from jalraksha.cache import get_cached_dem

        dem_dir = stale_dem.parent
        _write(stale_dem, spec, dem_dir / "updated")

        resolved = get_cached_dem(BARRIER_LAT, BARRIER_LON, dem_dir)

        assert resolved is not None
        # Compare the FILENAME, not the whole path: pytest's tmp_path is named
        # after the test, so the path legitimately contains "updated".
        resolved_name = Path(resolved).name
        assert resolved_name.endswith("_clipped.tif")
        assert "obscond" not in resolved_name
        assert Path(resolved).parent == dem_dir

    def test_the_writer_refuses_nothing_but_still_writes_outside_the_cache_root(
        self, stale_dem, spec, tmp_path
    ):
        """The product path always lands under the directory it was given."""
        out_dir = tmp_path / "dem" / "updated"
        path, _ = _write(stale_dem, spec, out_dir)
        assert path.parent == out_dir


class TestOfflinePath:
    def test_manual_update_never_touches_gee(self, stale_dem, spec, tmp_path, monkeypatch):
        """
        The offline path is the demo's guaranteed floor, so it must not consult
        Earth Engine even to ask whether it is available.
        """
        import jalraksha.gee.auth as auth

        def _explode(*args, **kwargs):
            raise AssertionError(
                "The manual DEM-update path called into Earth Engine. It must "
                "run with no network and with earthengine-api uninstalled."
            )

        monkeypatch.setattr(auth, "gee_status", _explode)
        monkeypatch.setattr(auth, "is_gee_available", _explode)

        path, provenance = _write(stale_dem, spec, tmp_path / "updated")
        assert path.exists()
        assert provenance.observation_source == "manual_operator_input"

    def test_a_missing_source_dem_raises_rather_than_inventing_terrain(
        self, spec, tmp_path
    ):
        with pytest.raises(DemUpdateError, match="Source DEM not found"):
            _write(tmp_path / "nothing.tif", spec, tmp_path / "updated")


class TestSpecValidation:
    def test_a_non_positive_crest_height_is_refused(self):
        for crest_height_m in (0.0, -5.0, None):
            with pytest.raises(DemUpdateError, match="positive height"):
                BlockageSpec(BARRIER_LAT, BARRIER_LON, crest_height_m, 1200.0)

    def test_a_non_positive_width_is_refused(self):
        with pytest.raises(DemUpdateError, match="positive crest length"):
            BlockageSpec(BARRIER_LAT, BARRIER_LON, 55.0, 0.0)

    def test_an_unknown_breach_mode_is_refused(self):
        with pytest.raises(DemUpdateError, match="overtop"):
            BlockageSpec(BARRIER_LAT, BARRIER_LON, 55.0, 1200.0, breach_mode="erode")


class TestDamConfigHandoff:
    def test_storage_and_elevations_come_from_the_burned_geometry(
        self, stale_dem, spec, tmp_path
    ):
        """
        The handoff that makes breach._synthesize_blockage_ensemble's refusal
        satisfiable: storage measured from the terrain, crest and floor as
        absolute elevations, dam class 'landslide'.
        """
        _, provenance = _write(stale_dem, spec, tmp_path / "updated")
        updates = dam_config_updates_from_provenance(provenance)

        assert updates["storage_source"] == "hypsometric_fill"
        assert updates["storage_mm3"] > 0.0
        assert updates["surface_area_km2"] > 0.0
        assert updates["dam_type"] == "landslide"
        assert updates["initial_surface_elev_m"] > updates["breach_bottom_elev_m"]
        assert updates["height_m"] == pytest.approx(
            updates["initial_surface_elev_m"] - updates["breach_bottom_elev_m"],
            abs=1.0,
        )

    def test_the_handoff_satisfies_the_blockage_ensembles_refusal(
        self, stale_dem, spec, tmp_path
    ):
        from jalraksha.terrain.breach import synthesize_scenario_ensemble

        _, provenance = _write(stale_dem, spec, tmp_path / "updated")
        dam_config = {
            "name": "Blockage",
            "scenario_type": "river_blockage",
            "hydrograph_duration_s": 3600.0,
            **dam_config_updates_from_provenance(provenance),
        }

        members = synthesize_scenario_ensemble(dam_config, num_samples=3, random_seed=7)

        assert len(members) == 3
        assert all(m["metadata"]["storage_source"] == "hypsometric_fill" for m in members)
        assert all(m["metadata"]["regression"] == "costa_1985" for m in members)
