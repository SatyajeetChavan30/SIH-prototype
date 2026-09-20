"""
The registry reports readiness it computed, and refuses what it cannot model.

Two failures this pins, both of which look like something else when they happen:

- **A cache hit is not coverage.** Tiles are fetched as windows and cached under
  the full tile's URL, so a file can exist and still not contain the domain. A
  registry that reported "ready" on file existence alone would send a run into
  rasterio.mask's "Input shapes do not overlap raster".
- **A dam with no terrain must not be selectable.** bhakra, idukki and hirakud
  are in DEMO_DAMS with no preset and no DEM. Published with runnable: false
  they are honest; offered in the picker they produce a run that dies in the
  worker with a FileNotFoundError minutes later.

Offline by construction: no fetch, no solver, no network.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "services" / "api"))

pytest.importorskip("jalraksha_service", reason="API service not importable")

from jalraksha.presets import BLOCKAGE_PRESETS, PRESETS, get_gauges  # noqa: E402

KHADAKWASLA_DEM = "dem_18.44_73.77_clipped.tif"


@pytest.fixture
def service(tmp_path, monkeypatch):
    """A private database and DATA_DIR, so readiness is decided by this fixture."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("JALRAKSHA_DATA_DIR", "./data")

    from jalraksha_service import db, registry
    from jalraksha_service.config import settings

    monkeypatch.setattr(settings, "DATA_DIR", tmp_path / "data", raising=False)
    monkeypatch.setattr(settings, "DATABASE_URL",
                        f"sqlite:///{(tmp_path / 'test.db').as_posix()}", raising=False)
    (tmp_path / "data" / "dem").mkdir(parents=True, exist_ok=True)
    registry._BOUNDS_CACHE.clear()
    db.init_db()
    return db


def _write_dem(tmp_path, name, bounds):
    """A 2x2 GeoTIFF with the given (west, south, east, north) bounds."""
    rasterio = pytest.importorskip("rasterio")
    from rasterio.transform import from_bounds

    path = tmp_path / "data" / "dem" / name
    west, south, east, north = bounds
    with rasterio.open(
        path, "w", driver="GTiff", width=2, height=2, count=1, dtype="float32",
        crs="EPSG:4326", transform=from_bounds(west, south, east, north, 2, 2),
    ) as dst:
        import numpy as np

        dst.write(np.zeros((2, 2), dtype="float32"), 1)
    return path


def _rows():
    from jalraksha_service.registry import registry_rows

    return {row["id"]: row for row in registry_rows()}


class TestScope:
    def test_exactly_the_four_sites_with_terrain_behind_them(self, service):
        assert set(_rows()) == {"khadakwasla", "tehri", "rishi_ganga", "mutha_temghar"}

    def test_no_dam_without_a_preset_appears(self, service):
        rows = _rows()
        for absent in ("bhakra", "idukki", "hirakud", "mullaperiyar", "srisailam"):
            assert absent not in rows

    def test_gauge_counts_come_from_the_presets(self, service):
        for site_id, row in _rows().items():
            assert row["gauge_count"] == len(get_gauges(site_id))

    def test_a_blockage_site_publishes_no_height_or_storage(self, service):
        row = _rows()["rishi_ganga"]
        assert row["height_m"] is None and row["storage_mm3"] is None
        assert row["scenario_types"] == ["river_blockage"]

    def test_the_hypothetical_site_says_so_from_its_own_barrier_source(self, service):
        assert _rows()["mutha_temghar"]["hypothetical"] is True
        assert _rows()["rishi_ganga"]["hypothetical"] is False
        assert "hypothetical" in (BLOCKAGE_PRESETS["mutha_temghar"].barrier_source or "").lower()

    def test_frl_is_verbatim_including_its_source(self, service):
        tehri = _rows()["tehri"]
        assert tehri["frl"]["frl_m"] == PRESETS["tehri"].frl_m
        assert tehri["frl"]["frl_source"] == PRESETS["tehri"].frl_source
        # Khadakwasla publishes no FRL; the registry must not invent one.
        assert _rows()["khadakwasla"]["frl"]["frl_m"] is None


class TestReadiness:
    def test_no_dem_reads_metadata_only_with_the_reason(self, service):
        row = _rows()["khadakwasla"]
        assert row["dem"]["cached"] is False
        assert row["tier"] == "metadata_only"
        assert "DEM not cached" in row["tier_reason"]

    def test_a_dem_that_covers_the_domain_lifts_the_tier(self, service, tmp_path):
        preset = PRESETS["khadakwasla"]
        _write_dem(tmp_path, KHADAKWASLA_DEM,
                   (preset.lon - 1.0, preset.lat - 1.0, preset.lon + 1.0, preset.lat + 1.0))
        row = _rows()["khadakwasla"]
        assert row["dem"]["cached"] is True and row["dem"]["covers_domain"] is True
        assert row["tier"] == "dem_cached"

    def test_a_cache_hit_is_not_coverage(self, service, tmp_path):
        """The measured failure: a window cached under the full tile's URL."""
        preset = PRESETS["khadakwasla"]
        _write_dem(tmp_path, KHADAKWASLA_DEM,
                   (preset.lon - 0.01, preset.lat - 0.01, preset.lon + 0.01, preset.lat + 0.01))
        row = _rows()["khadakwasla"]
        assert row["dem"]["cached"] is True
        assert row["dem"]["covers_domain"] is False
        assert row["tier"] == "metadata_only"
        assert "corners" in row["dem"]["reason"]

    def test_the_domain_box_is_widened_by_the_diagonal(self):
        """A square domain reaches its radius times root two at the corners."""
        from jalraksha_service.registry import domain_bbox

        lon_min, lat_min, lon_max, lat_max = domain_bbox(18.44, 73.77, 27.0)
        north_km = (lat_max - 18.44) * 111.0
        assert north_km == pytest.approx(27.0 * 2 ** 0.5, rel=0.01)
        assert lon_max > 73.77 and lon_min < 73.77

    def test_a_completed_run_is_what_makes_a_site_verified(self, service, tmp_path):
        preset = PRESETS["khadakwasla"]
        _write_dem(tmp_path, KHADAKWASLA_DEM,
                   (preset.lon - 1.0, preset.lat - 1.0, preset.lon + 1.0, preset.lat + 1.0))
        run_id = service.create_run("khadakwasla", {"name": "Khadakwasla Dam"}, "swe")
        service.insert_exports(run_id, [{"kind": "run_summary", "path_or_url": "x.json"}])
        service.update_run_status(run_id, "done", 100.0)

        row = _rows()["khadakwasla"]
        assert row["tier"] == "verified_run"
        assert row["runs"]["completed"] == 1
        assert row["runs"]["latest_run_id"] == run_id

    def test_a_run_without_exports_does_not_verify_a_site(self, service, tmp_path):
        """export_count > 0 is the run picker's own rule; the registry follows it."""
        run_id = service.create_run("khadakwasla", {"name": "Khadakwasla Dam"}, "swe")
        service.update_run_status(run_id, "done", 100.0)
        assert _rows()["khadakwasla"]["runs"]["completed"] == 0


class TestSelectability:
    def test_dams_import(self, service):
        from jalraksha_service.config import settings

        by_id = {d["id"]: d for d in settings.DEMO_DAMS}
        assert by_id["tehri"]["runnable"] is True
        assert by_id["khadakwasla"]["runnable"] is True
        for unbacked in ("bhakra", "idukki", "hirakud"):
            assert by_id[unbacked]["runnable"] is False
            assert by_id[unbacked]["unrunnable_reason"]

    def test_the_wire_model_carries_the_flag(self):
        """response_model drops undeclared fields, so this has to be on DamPreset."""
        from jalraksha_service.schemas import DamPreset

        assert "runnable" in DamPreset.model_fields
        assert "unrunnable_reason" in DamPreset.model_fields

    def test_submitting_an_unrunnable_dam_is_refused_at_submission(self, service, monkeypatch):
        from fastapi import HTTPException
        from jalraksha_service import main
        from jalraksha_service.schemas import RunRequest

        monkeypatch.setattr(main, "solver_backend_info",
                            lambda: {"cuda_available": True, "sph_gpu_available": True})
        with pytest.raises(HTTPException) as excinfo:
            main.submit_run(RunRequest(dam_id="bhakra", ensemble_size=1, solver="swe"))
        assert excinfo.value.status_code == 422
        assert "cannot be run on this install" in excinfo.value.detail
