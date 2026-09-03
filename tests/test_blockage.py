"""
Tests for landslide-dam geometry (jalraksha.terrain.blockage).

These assert against closed-form truth and against invariants, never against a
band chosen to make the current implementation pass. Two of them are worth
naming up front:

- ``test_volume_matches_an_analytic_prism`` scores the hypsometric fill against
  the exact capacity of a sloping V-valley. A fill that is merely
  self-consistent would pass a monotonicity test and still be wrong by a factor;
  only a closed form catches that.

- ``test_crest_height_is_relative_to_the_valley_floor_not_sea_level`` shifts the
  whole DEM by a kilometre. Confusing a height above the bed with an absolute
  elevation is the single most likely bug in this module, the two look equally
  plausible in Himalayan terrain, and the symptom is a lake volume that is
  silently wrong rather than an error.

Everything here is pure numpy geometry: no network, no Earth Engine, no rasterio,
and no DEM on disk.
"""

import numpy as np
import pytest

from jalraksha.solver.types import Grid
from jalraksha.terrain.blockage import (
    BlockageError,
    NATURAL_DAM_VOLUME_RANGE_M3,
    burn_barrier,
    compare_fill_to_observation,
    flow_direction,
    hypsometric_fill,
    locate_barrier_cell,
    natural_dam_indices,
    observed_lake_surface_elevation,
    stage_storage_table,
)

# ── Synthetic terrain ─────────────────────────────────────────────────────────

CELL_M = 30.0
CROSS_SLOPE = 0.1  # valley wall gradient, dimensionless (m rise per m across)
LONG_SLOPE = 0.01  # channel gradient, rising upstream
FLOOR_ELEVATION_M = 1000.0
CREST_HEIGHT_M = 60.0


def _prism_valley(
    cell_m: float = CELL_M,
    cross_slope: float = CROSS_SLOPE,
    long_slope: float = LONG_SLOPE,
    floor_elevation_m: float = FLOOR_ELEVATION_M,
    half_width_m: float = 1500.0,
    upstream_m: float = 9000.0,
    downstream_m: float = 3000.0,
):
    """
    A straight V-valley descending toward +y, with an exact capacity.

    Bed elevation at cross-channel offset ``x`` and upstream distance ``s`` from
    the barrier row:

        z(x, s) = floor + long_slope * s + cross_slope * |x|

    Filled to a depth ``H`` above the barrier-row thalweg, the impounded volume
    between upstream distances ``s0`` and ``H / long_slope`` is

        V = (H - long_slope * s0)**3 / (3 * cross_slope * long_slope)

    which is what ``test_volume_matches_an_analytic_prism`` scores against.

    Returns (bed_elevation, grid, i_barrier, j_barrier).
    """
    nx = int(round(2.0 * half_width_m / cell_m)) + 1
    ny = int(round((upstream_m + downstream_m) / cell_m)) + 1

    # Row 0 is southernmost and the valley descends toward +y (north), so the
    # barrier sits `upstream_m` from the southern edge with the lake to its south.
    j_barrier = int(round(upstream_m / cell_m))
    i_barrier = nx // 2

    columns = np.arange(nx)[None, :]
    rows = np.arange(ny)[:, None]

    offset_m = (columns - i_barrier) * cell_m
    upstream_distance_m = (j_barrier - rows) * cell_m

    bed = (
        floor_elevation_m
        + long_slope * upstream_distance_m
        + cross_slope * np.abs(offset_m)
    ).astype(np.float64)

    grid = Grid(nx=nx, ny=ny, dx=cell_m, dy=cell_m, x0=0.0, y0=0.0, crs="EPSG:32644")
    return bed, grid, i_barrier, j_barrier


def _analytic_prism_volume_m3(
    depth_m: float,
    s_min_m: float,
    cross_slope: float = CROSS_SLOPE,
    long_slope: float = LONG_SLOPE,
) -> float:
    """Exact capacity of the sloping V-valley above upstream distance ``s_min_m``."""
    effective_depth = depth_m - long_slope * s_min_m
    if effective_depth <= 0.0:
        return 0.0
    return effective_depth**3 / (3.0 * cross_slope * long_slope)


def _burn(bed, grid, i_barrier, j_barrier, **kwargs):
    """burn_barrier with this fixture's downstream direction supplied."""
    kwargs.setdefault("crest_height_m", CREST_HEIGHT_M)
    kwargs.setdefault("width_m", 1800.0)
    kwargs.setdefault("direction", (0.0, 1.0))
    return burn_barrier(bed, grid, i_barrier, j_barrier, **kwargs)


# ── Barrier burn ──────────────────────────────────────────────────────────────


class TestBarrierBurn:
    def test_barrier_spans_the_valley_or_the_call_fails(self):
        """
        A deposit too narrow to reach the valley walls must raise, not return a
        small lake. This is the failure that does not announce itself: the fill
        runs around the barrier's ends, the volume comes back low but plausible,
        and nothing in the output says the dam never held.
        """
        bed, grid, i_barrier, j_barrier = _prism_valley()

        with pytest.raises(BlockageError, match="still leaks"):
            _burn(
                bed,
                grid,
                i_barrier,
                j_barrier,
                width_m=120.0,  # 4 cells against a ~1200 m wide valley at crest
                max_growth_iterations=0,
            )

    def test_a_narrow_barrier_is_widened_until_it_spans(self):
        """Given room to grow, the burn widens rather than failing."""
        bed, grid, i_barrier, j_barrier = _prism_valley()

        barrier = _burn(bed, grid, i_barrier, j_barrier, width_m=120.0)

        assert barrier.growth_iterations > 0
        assert barrier.downstream_leak_cells == 0
        assert barrier.width_m_final > barrier.width_m_requested

    def test_a_returned_barrier_never_leaks(self):
        bed, grid, i_barrier, j_barrier = _prism_valley()
        barrier = _burn(bed, grid, i_barrier, j_barrier)
        assert barrier.downstream_leak_cells == 0

    def test_burn_only_raises_never_lowers(self):
        """
        The deposit is material added to the valley. A burn that lowered any cell
        would be carving a channel, which is a different operation with the
        opposite effect on the flood.
        """
        bed, grid, i_barrier, j_barrier = _prism_valley()
        barrier = _burn(bed, grid, i_barrier, j_barrier)

        assert np.all(barrier.bed_with_barrier >= bed)
        assert barrier.max_elevation_change_m > 0.0

    def test_the_source_array_is_not_mutated(self):
        bed, grid, i_barrier, j_barrier = _prism_valley()
        original = bed.copy()
        _burn(bed, grid, i_barrier, j_barrier)
        np.testing.assert_array_equal(bed, original)

    def test_barrier_volume_equals_the_integrated_delta(self):
        """
        Peng & Zhang (2012) and the stability indices both take deposit volume as
        an input, so it has to be the actual integral of what was added, not an
        approximation from the nominal width and height.
        """
        bed, grid, i_barrier, j_barrier = _prism_valley()
        barrier = _burn(bed, grid, i_barrier, j_barrier)

        delta = barrier.bed_with_barrier - bed
        expected = float(delta.sum() * grid.dx * grid.dy)

        assert barrier.barrier_volume_m3 == pytest.approx(expected, rel=1e-12)
        assert barrier.cells_modified == int(np.count_nonzero(delta > 0))

    def test_a_zero_or_negative_crest_height_is_refused(self):
        bed, grid, i_barrier, j_barrier = _prism_valley()
        for crest_height_m in (0.0, -10.0):
            with pytest.raises(BlockageError, match="must be positive"):
                _burn(bed, grid, i_barrier, j_barrier, crest_height_m=crest_height_m)

    def test_crest_height_is_relative_to_the_valley_floor_not_sea_level(self):
        """
        Shift the entire DEM up by a kilometre. Every geometric result must be
        identical, because a deposit 60 m tall is 60 m tall whether the valley
        floor is at 200 m or 1200 m.

        Reading crest_height_m as an absolute elevation instead would, on the
        shifted terrain, place the crest a kilometre below the bed and impound
        nothing — or, with the sign the other way, impound a lake the size of the
        domain. Both are plausible-looking numbers, which is exactly why this is
        asserted rather than assumed.
        """
        bed_low, grid, i_barrier, j_barrier = _prism_valley(floor_elevation_m=200.0)
        bed_high, _, _, _ = _prism_valley(floor_elevation_m=1200.0)
        np.testing.assert_allclose(bed_high - bed_low, 1000.0)

        low = _burn(bed_low, grid, i_barrier, j_barrier)
        high = _burn(bed_high, grid, i_barrier, j_barrier)

        assert low.crest_height_m == high.crest_height_m
        assert high.crest_elevation_m - low.crest_elevation_m == pytest.approx(1000.0)
        assert low.barrier_volume_m3 == pytest.approx(high.barrier_volume_m3, rel=1e-12)

        lake_low = hypsometric_fill(
            low.bed_with_barrier, grid, low.seed_ij, low.crest_elevation_m,
            barrier_mask=low.barrier_mask,
        )
        lake_high = hypsometric_fill(
            high.bed_with_barrier, grid, high.seed_ij, high.crest_elevation_m,
            barrier_mask=high.barrier_mask,
        )
        assert lake_low.volume_m3 == pytest.approx(lake_high.volume_m3, rel=1e-12)
        assert lake_low.n_cells == lake_high.n_cells


# ── Hypsometric fill ──────────────────────────────────────────────────────────


class TestHypsometricFill:
    def test_volume_matches_an_analytic_prism(self):
        """
        Score the fill against the closed-form capacity of the V-valley.

        The pool starts one row beyond the deposit footprint, so the analytic
        integral starts at the same place: the barrier occupies channel volume,
        and pretending otherwise would build a tolerance around a known offset.
        """
        bed, grid, i_barrier, j_barrier = _prism_valley()
        barrier = _burn(bed, grid, i_barrier, j_barrier)

        lake = hypsometric_fill(
            barrier.bed_with_barrier,
            grid,
            barrier.seed_ij,
            barrier.crest_elevation_m,
            barrier_mask=barrier.barrier_mask,
        )

        # Midpoint rule: the first wet row's cell centre sits half a cell beyond
        # the last barrier row's centre.
        s_min_m = (barrier.thickness_cells + 0.5) * grid.dy
        expected = _analytic_prism_volume_m3(CREST_HEIGHT_M, s_min_m)

        # Measured: 0.127% high at 30 m cells. The tolerance is four times the
        # measurement, not a band picked to accommodate whatever came out.
        assert lake.volume_m3 == pytest.approx(expected, rel=0.005)

    def test_volume_error_shrinks_as_the_grid_refines(self):
        """
        The discretisation error must be a discretisation error. If the fill were
        wrong for a structural reason, refining the grid would not help.
        """
        errors = {}
        for cell_m in (60.0, 30.0, 15.0):
            bed, grid, i_barrier, j_barrier = _prism_valley(cell_m=cell_m)
            barrier = _burn(bed, grid, i_barrier, j_barrier)
            lake = hypsometric_fill(
                barrier.bed_with_barrier, grid, barrier.seed_ij,
                barrier.crest_elevation_m, barrier_mask=barrier.barrier_mask,
            )
            s_min_m = (barrier.thickness_cells + 0.5) * grid.dy
            expected = _analytic_prism_volume_m3(CREST_HEIGHT_M, s_min_m)
            errors[cell_m] = abs(lake.volume_m3 - expected) / expected

        assert errors[15.0] < errors[60.0], (
            f"Refining 60 m -> 15 m did not reduce the error: {errors}"
        )
        # Measured 0.523% / 0.127% / 0.031% — roughly a factor of four per
        # halving, i.e. second order, which is what a cell-centred sum over a
        # smooth cross-section should give. A first-order trend would mean the
        # fill is losing a boundary row somewhere.
        assert errors[60.0] / errors[30.0] > 2.0
        assert errors[30.0] / errors[15.0] > 2.0

    def test_fill_never_leaks_downstream_of_the_barrier(self):
        bed, grid, i_barrier, j_barrier = _prism_valley()
        barrier = _burn(bed, grid, i_barrier, j_barrier)

        lake = hypsometric_fill(
            barrier.bed_with_barrier, grid, barrier.seed_ij,
            barrier.crest_elevation_m, barrier_mask=barrier.barrier_mask,
        )
        # Downstream is +j from the barrier row, past the deposit footprint.
        downstream = lake.mask[j_barrier + barrier.thickness_cells + 2 :, :]
        assert not downstream.any()

    def test_a_steep_gorge_seeds_in_the_channel_not_up_the_bank(self):
        """
        The failure this arc-scan seed exists for, reproduced.

        A single point at a fixed offset along the flow vector lands above the
        crest in steep terrain, and the fill then reports "no pool to grow from"
        for a barrier that is perfectly sound. Measured on the Dhauliganga gorge
        below Tapovan: barrier cell 1,703 m, crest 1,758 m, and the cell four
        steps up the flow vector at 1,789 m — 31 m above the water it was
        supposed to seed.

        The valley here has a 12% longitudinal slope, so 400 m upstream is 48 m
        higher and a 40 m barrier's crest is already below it.
        """
        bed, grid, i_barrier, j_barrier = _prism_valley(
            long_slope=0.12, cross_slope=0.4, upstream_m=3000.0, half_width_m=900.0
        )
        barrier = _burn(
            bed, grid, i_barrier, j_barrier, crest_height_m=40.0, width_m=1500.0
        )

        seed_i, seed_j = barrier.seed_ij
        assert bed[seed_j, seed_i] <= barrier.crest_elevation_m, (
            f"The seed at {bed[seed_j, seed_i]:.1f} m sits above the "
            f"{barrier.crest_elevation_m:.1f} m crest."
        )

        lake = hypsometric_fill(
            barrier.bed_with_barrier, grid, barrier.seed_ij,
            barrier.crest_elevation_m, barrier_mask=barrier.barrier_mask,
        )
        assert lake.volume_m3 > 0.0

    def test_a_barrier_too_short_for_the_reach_gradient_says_so(self):
        """
        When nothing upstream is below the crest the refusal must name the
        cause, because "no pool to grow from" reads as a broken barrier when the
        real answer is that the reach is simply too steep for a deposit this size.
        """
        bed, grid, i_barrier, j_barrier = _prism_valley(
            long_slope=0.25, cross_slope=0.4, upstream_m=3000.0, half_width_m=900.0
        )
        with pytest.raises(BlockageError, match="longitudinal slope"):
            _burn(bed, grid, i_barrier, j_barrier, crest_height_m=5.0, width_m=1500.0)

    def test_a_seed_above_the_fill_level_is_refused(self):
        bed, grid, i_barrier, j_barrier = _prism_valley()
        barrier = _burn(bed, grid, i_barrier, j_barrier)

        with pytest.raises(BlockageError, match="no pool to grow from"):
            hypsometric_fill(
                barrier.bed_with_barrier, grid, barrier.seed_ij,
                barrier.floor_elevation_m - 5.0, barrier_mask=barrier.barrier_mask,
            )


# ── Stage-storage ─────────────────────────────────────────────────────────────


class TestStageStorage:
    def _table(self, **valley_kwargs):
        bed, grid, i_barrier, j_barrier = _prism_valley(**valley_kwargs)
        barrier = _burn(bed, grid, i_barrier, j_barrier)
        table = stage_storage_table(
            barrier.bed_with_barrier, grid, barrier.seed_ij,
            barrier.floor_elevation_m, barrier.crest_elevation_m,
            barrier_mask=barrier.barrier_mask,
        )
        return table, barrier, grid

    def test_stage_storage_is_monotone_and_starts_at_zero(self):
        table, _, _ = self._table()

        assert table.volumes_m3[0] == pytest.approx(0.0, abs=1e-9)
        assert np.all(np.diff(table.volumes_m3) >= -1e-9)
        assert np.all(np.diff(table.areas_m2) >= -1e-9)
        assert np.all(np.diff(table.levels_m) > 0)

    def test_the_power_law_exponent_recovers_the_prisms_cubic_capacity(self):
        """
        For a V-valley with a constant longitudinal slope the exact capacity is
        cubic in depth, V = H**3 / (3*m*S). The fitted exponent must land on 3,
        and the residual must be small enough to say the power law describes this
        valley rather than merely being fitted to it.
        """
        table, _, _ = self._table()

        assert table.fit_b == pytest.approx(3.0, abs=0.15)
        assert table.fit_residual < 0.05

    def test_lateral_spill_is_detected_not_absorbed(self):
        """
        Cut a saddle through one valley wall into a second basin. Above the sill
        the pool drains sideways into a catchment nobody modelled, and the volume
        simply keeps growing. The sweep must flag the sill and cap the usable
        crest there instead of reporting the combined basins as one lake.
        """
        bed, grid, i_barrier, j_barrier = _prism_valley()

        # A notch through the east wall at half the crest height, opening into a
        # flat neighbouring basin that sits below the sill. Below the sill the
        # basin is a separate component and contributes nothing; the moment the
        # level crosses it, the pool gains the whole basin at once.
        sill_elevation = FLOOR_ELEVATION_M + 0.5 * CREST_HEIGHT_M
        j_gap = j_barrier - 40
        i_wall = i_barrier + int(round(700.0 / grid.dx))

        notch = bed[j_gap - 2 : j_gap + 3, i_barrier:]
        bed[j_gap - 2 : j_gap + 3, i_barrier:] = np.minimum(notch, sill_elevation)

        basin = bed[j_gap - 12 : j_gap + 13, i_wall:]
        bed[j_gap - 12 : j_gap + 13, i_wall:] = np.minimum(basin, sill_elevation - 5.0)

        barrier = _burn(bed, grid, i_barrier, j_barrier)
        table = stage_storage_table(
            barrier.bed_with_barrier, grid, barrier.seed_ij,
            barrier.floor_elevation_m, barrier.crest_elevation_m,
            barrier_mask=barrier.barrier_mask,
        )

        assert table.spill_detected_at_m is not None
        assert table.usable_crest_m < table.crest_elevation_m
        assert table.spill_detected_at_m == pytest.approx(sill_elevation, abs=3.0)

    def test_a_clean_valley_reports_no_spill(self):
        table, barrier, _ = self._table()
        assert table.spill_detected_at_m is None
        assert table.usable_crest_m == pytest.approx(barrier.crest_elevation_m)

    def test_a_crest_at_or_below_the_floor_is_refused(self):
        bed, grid, i_barrier, j_barrier = _prism_valley()
        barrier = _burn(bed, grid, i_barrier, j_barrier)

        with pytest.raises(BlockageError, match="nothing to impound"):
            stage_storage_table(
                barrier.bed_with_barrier, grid, barrier.seed_ij,
                barrier.floor_elevation_m, barrier.floor_elevation_m,
                barrier_mask=barrier.barrier_mask,
            )

    def test_the_table_survives_a_json_round_trip(self):
        """The provenance sidecar carries this curve; it must serialise."""
        import json

        table, _, _ = self._table()
        payload = json.loads(json.dumps(table.to_dict()))

        assert len(payload["levels_m"]) == len(table.levels_m)
        assert payload["volume_datum"].startswith("above pre-event water surface")


# ── Observation conditioning ──────────────────────────────────────────────────


class TestObservationConditioning:
    def test_observed_shoreline_sets_the_lake_surface(self):
        """
        The satellite sees where the water is; the stale DEM knows how high the
        ground is. Sampling the DEM along the observed shoreline recovers the
        water level, because the shoreline IS the contour the surface intersects.
        """
        bed, grid, i_barrier, j_barrier = _prism_valley()
        barrier = _burn(bed, grid, i_barrier, j_barrier)

        true_level = barrier.floor_elevation_m + 40.0
        observed = hypsometric_fill(
            barrier.bed_with_barrier, grid, barrier.seed_ij, true_level,
            barrier_mask=barrier.barrier_mask,
        ).mask

        elevation, diagnostics = observed_lake_surface_elevation(bed, observed)

        # Within a cell's worth of cross-slope rise: the shoreline ring samples
        # cells whose centres sit just inside the true contour.
        assert elevation == pytest.approx(true_level, abs=CROSS_SLOPE * CELL_M * 2)
        assert diagnostics["shoreline_cells"] > 0
        assert diagnostics["statistic"] == "median"

    def test_an_empty_observation_is_refused(self):
        bed, _, _, _ = _prism_valley()
        with pytest.raises(BlockageError, match="empty"):
            observed_lake_surface_elevation(bed, np.zeros_like(bed, dtype=bool))

    def test_iou_is_one_for_a_perfect_match_and_zero_for_disjoint_masks(self):
        mask = np.zeros((10, 10), dtype=bool)
        mask[2:5, 2:5] = True
        other = np.zeros((10, 10), dtype=bool)
        other[6:9, 6:9] = True

        assert compare_fill_to_observation(mask, mask)["iou"] == pytest.approx(1.0)
        assert compare_fill_to_observation(mask, other)["iou"] == pytest.approx(0.0)

    def test_the_bed_beneath_an_observed_lake_is_never_overwritten(self):
        """
        Raising the bed to the observed water surface would flatten the very
        valley the storage is measured in, leaving nothing to impound. The
        observation calibrates the crest; it does not rewrite the terrain.
        """
        import inspect

        import jalraksha.terrain.blockage as blockage

        source = inspect.getsource(blockage)
        assert "condition_bed_to_observed_lake" not in source, (
            "A bed-conditioning entry point reappeared. Raising the bed under the "
            "observed lake destroys the storage the hypsometric fill measures — "
            "see this module's docstring."
        )


# ── Stability indices ─────────────────────────────────────────────────────────


class TestNaturalDamIndices:
    def test_no_stability_verdict_is_issued_from_unvetted_thresholds(self):
        """
        The index values are computable; the envelopes that turn them into a
        stable/unstable call are in the verification queue and are not applied.
        """
        indices = natural_dam_indices(
            barrier_volume_m3=2.0e7, barrier_height_m=60.0, lake_volume_m3=7.0e7
        )
        assert indices["verdict"] is None
        assert "UNVETTED" in indices["note"]

    def test_catchment_dependent_indices_are_omitted_not_estimated(self):
        indices = natural_dam_indices(2.0e7, 60.0, 7.0e7, catchment_area_km2=None)
        assert indices["blockage_index"] is None
        assert indices["dimensionless_blockage_index"] is None
        assert "catchment_note" in indices

        with_catchment = natural_dam_indices(2.0e7, 60.0, 7.0e7, catchment_area_km2=250.0)
        assert with_catchment["blockage_index"] is not None
        assert with_catchment["dimensionless_blockage_index"] is not None

    def test_a_burned_barrier_reports_whether_its_volume_is_physically_plausible(self):
        """
        Costa & Schuster (1988) put surveyed natural-dam volumes at roughly 1e6
        to 1e8 m3. A burn implying 1e10 m3 of rock means the requested width was
        wrong, and that is reported rather than silently accepted.
        """
        bed, grid, i_barrier, j_barrier = _prism_valley()
        barrier = _burn(bed, grid, i_barrier, j_barrier)

        low, high = NATURAL_DAM_VOLUME_RANGE_M3
        assert barrier.volume_is_plausible_for_a_natural_dam == (
            low <= barrier.barrier_volume_m3 <= high
        )


# ── Locating the barrier ──────────────────────────────────────────────────────


class TestLocateBarrier:
    def _utm_grid(self):
        """A 200 m grid over the Bhagirathi, in the CRS load_dem_as_grid produces."""
        from jalraksha.terrain.domain import latlon_to_utm

        _, easting, northing = latlon_to_utm(30.38, 79.20)
        return Grid(
            nx=200, ny=200, dx=200.0, dy=200.0,
            x0=easting - 20000.0, y0=northing - 20000.0, crs="EPSG:32644",
        )

    def test_a_barrier_outside_the_domain_raises_rather_than_clamping(self):
        """
        Clamping to the domain edge would produce a complete, plausible-looking
        flood starting somewhere nobody asked for — the same failure class the
        DEM resolver's no-fallback rule exists to prevent.
        """
        grid = self._utm_grid()
        bed = np.full((grid.ny, grid.nx), 1500.0)

        with pytest.raises(BlockageError, match="outside the"):
            locate_barrier_cell(bed, grid, 25.0, 79.20)

    def test_the_barrier_snaps_to_the_thalweg(self):
        grid = self._utm_grid()
        bed = np.full((grid.ny, grid.nx), 1500.0)
        bed[100, 98] = 1400.0  # a channel two cells west of the requested point

        from jalraksha.terrain.domain import latlon_to_utm
        from pyproj import Transformer

        transformer = Transformer.from_crs("EPSG:32644", "EPSG:4326", always_xy=True)
        lon, lat = transformer.transform(
            grid.x0 + (100 + 0.5) * grid.dx, grid.y0 + (100 + 0.5) * grid.dy
        )
        _ = latlon_to_utm  # imported to pin the projection path used above

        i, j, elevation = locate_barrier_cell(bed, grid, lat, lon, snap_radius_cells=3)

        assert (i, j) == (98, 100)
        assert elevation == pytest.approx(1400.0)

    def test_snapping_can_be_disabled(self):
        grid = self._utm_grid()
        bed = np.full((grid.ny, grid.nx), 1500.0)
        bed[100, 98] = 1400.0

        from pyproj import Transformer

        transformer = Transformer.from_crs("EPSG:32644", "EPSG:4326", always_xy=True)
        lon, lat = transformer.transform(
            grid.x0 + (100 + 0.5) * grid.dx, grid.y0 + (100 + 0.5) * grid.dy
        )

        i, j, _ = locate_barrier_cell(bed, grid, lat, lon, snap_radius_cells=0)
        assert (i, j) == (100, 100)

    def test_a_geographic_grid_is_refused(self):
        """
        Every length in this module is metres. On a degree grid the barrier width
        would be read as degrees and the fill would silently span half a country.
        """
        grid = Grid(nx=10, ny=10, dx=0.001, dy=0.001, crs="EPSG:4326")
        bed = np.full((10, 10), 100.0)

        with pytest.raises(BlockageError, match="not a UTM zone"):
            locate_barrier_cell(bed, grid, 30.38, 79.20)


class TestFlowDirection:
    def test_direction_points_downhill(self):
        bed, grid, i_barrier, j_barrier = _prism_valley()
        di, dj = flow_direction(bed, i_barrier, j_barrier, radius_cells=(5, 12))

        # The fixture valley descends toward +y.
        assert dj > 0.9
        assert abs(di) < 0.4

    def test_a_flat_or_rising_neighbourhood_is_refused(self):
        bed = np.full((60, 60), 100.0)
        grid = Grid(nx=60, ny=60, dx=CELL_M, dy=CELL_M, crs="EPSG:32644")
        _ = grid

        with pytest.raises(BlockageError, match="no downstream direction"):
            flow_direction(bed, 30, 30, radius_cells=(5, 12))
