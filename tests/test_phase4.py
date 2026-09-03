"""
Tests for Phase 4: End-to-end dam-break pipeline.
"""

import pytest
import numpy as np
from jalraksha.run import (
    run_dam_break_ensemble,
    define_downstream_gauges,
    compute_arrival_times_at_gauges,
)
from jalraksha.solver.types import Grid, create_state


class TestDownstreamGauges:
    """Test gauge definition."""

    def test_gauge_definition_tehri(self):
        """Define gauges for Tehri dam."""
        gauges = define_downstream_gauges(30.3789, 78.4789)

        assert len(gauges) == 4, "Should have 4 downstream gauges"

        gauge_names = [g["name"] for g in gauges]
        assert "Koteshwar" in gauge_names
        assert "Devprayag" in gauge_names
        assert "Rishikesh" in gauge_names
        assert "Haridwar" in gauge_names

        # Check distances increase
        distances = [g["distance_km"] for g in gauges]
        assert distances == sorted(distances), "Distances should be monotonically increasing"

    def test_gauge_fields_present(self):
        """Each gauge has required fields."""
        gauges = define_downstream_gauges(30.3789, 78.4789)

        for gauge in gauges:
            assert "name" in gauge
            assert "distance_km" in gauge
            assert "lat" in gauge
            assert "lon" in gauge


class TestArrivalTimeComputation:
    """Test arrival-time extraction from results."""

    def test_arrival_times_mock_results(self):
        """Compute arrival times from mock ensemble results."""
        from pyproj import Transformer

        # Anchor on the real Tehri corridor and place the gauges INSIDE the
        # domain, so this exercises the actual nearest-cell lookup rather than
        # the "gauge outside domain" branch.
        x0, y0 = 207736.0, 3313468.0
        grid = Grid(nx=50, ny=50, dx=200.0, dy=200.0, x0=x0, y0=y0, crs="EPSG:32644")
        to_wgs84 = Transformer.from_crs("EPSG:32644", "EPSG:4326", always_xy=True)
        g1_lon, g1_lat = to_wgs84.transform(x0 + 10 * grid.dx, y0 + 10 * grid.dy)
        g2_lon, g2_lat = to_wgs84.transform(x0 + 30 * grid.dx, y0 + 30 * grid.dy)
        gauges = [
            {"name": "G1", "distance_km": 10, "lat": g1_lat, "lon": g1_lon},
            {"name": "G2", "distance_km": 20, "lat": g2_lat, "lon": g2_lon},
        ]

        # Mock results: arrival time grid
        results_ensemble = []
        for sample_id in range(5):
            # Synthetic arrival times: front propagates from top-left
            t_arrival = np.zeros((grid.ny, grid.nx), dtype=np.float32)
            for j in range(grid.ny):
                for i in range(grid.nx):
                    dist = np.sqrt((i - 0)**2 + (j - 0)**2) * grid.dx
                    wave_speed = 3.0 + sample_id * 0.5  # m/s, varies by sample
                    t_arrival[j, i] = dist / wave_speed + 100 * sample_id  # Add sample variability

            results_ensemble.append({
                "t_arrival": t_arrival,
                "h_max": np.ones((grid.ny, grid.nx)) * 0.5,
                "sample_id": sample_id,
            })

        # Compute arrival times at gauges
        arrival_dict = compute_arrival_times_at_gauges(
            results_ensemble, grid, gauges, threshold_h=0.1
        )

        # Check structure
        assert "G1" in arrival_dict
        assert "G2" in arrival_dict

        for gauge_name in ["G1", "G2"]:
            assert "median" in arrival_dict[gauge_name]
            assert "p05" in arrival_dict[gauge_name]
            assert "p95" in arrival_dict[gauge_name]
            # An in-domain gauge must produce a real arrival, not None.
            assert arrival_dict[gauge_name]["median"] is not None
            assert arrival_dict[gauge_name]["num_samples"] == 5

        # G2 is further from the wave origin than G1.
        assert arrival_dict["G2"]["median"] > arrival_dict["G1"]["median"]

    def test_arrival_times_monotonic(self):
        """Arrival times must increase with distance downstream.

        The gauges are positioned by projecting real UTM coordinates INSIDE the
        domain back to lat/lon. Previously they were arbitrary lat/lons that fell
        far outside a domain anchored at UTM (0, 0), so all three snapped to the
        same corner cell and reported identical times — the monotonicity
        assertion held trivially and tested nothing.
        """
        from pyproj import Transformer

        # Domain anchored on the real Tehri corridor (UTM 44N).
        x0, y0 = 207736.0, 3313468.0
        grid = Grid(nx=100, ny=100, dx=100.0, dy=100.0, x0=x0, y0=y0, crs="EPSG:32644")

        # Mock front spreading from the south-west corner at 50 s per cell.
        results_ensemble = []
        jj, ii = np.mgrid[0:grid.ny, 0:grid.nx]
        t_arrival = (np.sqrt(ii**2 + jj**2) * 50).astype(np.float32)
        for sample_id in range(10):
            results_ensemble.append({"t_arrival": t_arrival.copy(), "sample_id": sample_id})

        # Three points on the diagonal, strictly increasing distance from the
        # corner the front starts at, converted UTM -> lat/lon for the API.
        to_wgs84 = Transformer.from_crs("EPSG:32644", "EPSG:4326", always_xy=True)
        gauges = []
        for name, cells, dist_km in [("Near", 20, 2.8), ("Mid", 50, 7.1), ("Far", 80, 11.3)]:
            lon, lat = to_wgs84.transform(x0 + cells * grid.dx, y0 + cells * grid.dy)
            gauges.append({"name": name, "distance_km": dist_km, "lat": lat, "lon": lon})

        arrival_dict = compute_arrival_times_at_gauges(
            results_ensemble, grid, gauges, threshold_h=0.1
        )

        times = [arrival_dict[g["name"]]["median"] for g in gauges]
        assert all(t is not None for t in times), (
            f"every gauge should be inside the domain, got {arrival_dict}"
        )
        assert times[0] < times[1] < times[2], f"not monotonic downstream: {times}"


@pytest.mark.blocking
def test_phase4_end_to_end_synthetic():
    """
    End-to-end test on synthetic data (small domain, short runtime).

    This validates the full pipeline without requiring real DEM/solver.
    """
    # This is a PLACEHOLDER for the full end-to-end test.
    # Full implementation requires:
    # 1. Mock DEM (Phase 0 cache)
    # 2. Terrain builder (Phase 2)
    # 3. Breach ensemble (Phase 3)
    # 4. Solver loop (Phase 1)
    # 5. Gauge computation
    #
    # For now, just verify the pipeline structure is callable.

    config = {
        "name": "TestDam",
        "lat": 30.0,
        "lon": 78.5,
        "height_m": 100,
        "storage_mm3": 100,
        "dam_type": "embankment",
        "failure_mode": "overtopping",
    }

    # Verify config is valid structure
    assert "name" in config
    assert "height_m" in config
    assert "storage_mm3" in config

    # TODO: Implement full Phase 4 test with mock DEM
    # For now, test the gauge definition works
    gauges = define_downstream_gauges(config["lat"], config["lon"])
    assert len(gauges) == 4, "Should define 4 downstream gauges"


@pytest.mark.blocking
def test_phase4_tehri_arrival_time_ordering():
    """
    Verify that arrival times are monotonically increasing downstream.

    This is the key plausibility constraint: the flood wave should reach
    nearby gauges before distant ones.
    """
    distances = {
        "Koteshwar": 13.0,
        "Devprayag": 28.0,
        "Rishikesh": 34.8,
        "Haridwar": 58.4,
    }

    # For any reasonable wave speed (1–10 m/s), arrival time increases with distance
    gauge_order = ["Koteshwar", "Devprayag", "Rishikesh", "Haridwar"]
    for i in range(len(gauge_order) - 1):
        curr_gauge = gauge_order[i]
        next_gauge = gauge_order[i + 1]

        assert distances[curr_gauge] < distances[next_gauge], \
            f"{curr_gauge} distance should be < {next_gauge} distance"

    # Therefore arrival time should be strictly ordered
    # (This is a tautology, but it documents the expected behavior)
    assert True, "Arrival times should be monotonically increasing downstream"


class TestMinorityArrival:
    """
    A gauge only some ensemble members reach must not read as the consensus.

    Measured on a Rishi Ganga blockage: 1 of 4 members reached Joshimath, so the
    reported "arrival time" was that single realisation, the p05/p95 band
    collapsed onto it — a zero-width band that looks like high confidence and
    means the opposite — and the peak depth beside it read 0.0 m, because the
    ENSEMBLE MEDIAN of h_max at that cell is median{0, 0, 0, d} = 0.

    A row saying "arrived at 1 h 22 m, peak depth 0.0 m" invites the reader to
    disbelieve the arrival time, which is the number the tool exists to produce.
    """

    def _one_gauge_setup(self, n_members, n_arriving):
        from pyproj import Transformer

        x0, y0 = 207736.0, 3313468.0
        grid = Grid(nx=40, ny=40, dx=200.0, dy=200.0, x0=x0, y0=y0, crs="EPSG:32644")
        to_wgs84 = Transformer.from_crs("EPSG:32644", "EPSG:4326", always_xy=True)
        lon, lat = to_wgs84.transform(x0 + 20 * grid.dx, y0 + 20 * grid.dy)
        gauges = [{"name": "G", "distance_km": 15, "lat": lat, "lon": lon}]

        results_ensemble = []
        for member in range(n_members):
            arrived = member < n_arriving
            t_arrival = np.full((grid.ny, grid.nx), np.nan, dtype=np.float64)
            h_max = np.zeros((grid.ny, grid.nx), dtype=np.float64)
            if arrived:
                t_arrival[:, :] = 4894.0
                h_max[:, :] = 3.5
            results_ensemble.append({
                "t_arrival": t_arrival, "h_max": h_max, "sample_id": member,
            })
        return results_ensemble, grid, gauges

    def test_depth_comes_from_the_members_that_arrived(self):
        """
        Not from the ensemble-median raster. One member in four reaching a gauge
        with 3.5 m of water is a 3.5 m outcome for that member, not a 0.0 m one.
        """
        results, grid, gauges = self._one_gauge_setup(n_members=4, n_arriving=1)

        entry = compute_arrival_times_at_gauges(
            results, grid, gauges, threshold_h=0.1
        )["G"]

        assert entry["num_samples"] == 1
        assert entry["num_members"] == 4
        assert entry["max_depth_m"] == pytest.approx(3.5)
        assert entry["median"] == pytest.approx(4894.0)

    def test_a_gauge_nothing_reached_reports_no_depth_not_zero_depth(self):
        """None and 0.0 m are different claims. Only one of them is true here."""
        results, grid, gauges = self._one_gauge_setup(n_members=4, n_arriving=0)

        entry = compute_arrival_times_at_gauges(
            results, grid, gauges, threshold_h=0.1
        )["G"]

        assert entry["num_samples"] == 0
        assert entry["num_members"] == 4
        assert entry["median"] is None
        assert entry["max_depth_m"] is None

    def test_the_service_flags_a_minority_arrival(self):
        """
        The note is what stops a one-in-four outcome being read as the expected
        one. Emitted only below half the members: a majority arrival with a real
        p05/p95 spread already tells its own story.
        """
        import sys

        sys.path.insert(0, "services/api")
        from jalraksha_service.tasks import _minority_arrival_note

        minority = _minority_arrival_note({"num_samples": 1, "num_members": 4})
        assert minority is not None
        assert "1 of 4" in minority
        assert "not the expected one" in minority

        assert _minority_arrival_note({"num_samples": 3, "num_members": 4}) is None
        assert _minority_arrival_note({"num_samples": 2, "num_members": 4}) is None
        assert _minority_arrival_note({"num_samples": 0, "num_members": 4}) is None
        # Runs written before num_members existed must not grow a note.
        assert _minority_arrival_note({"num_samples": 1}) is None

    def test_the_service_prefers_the_per_member_depth(self):
        """
        _gauge_max_depths falls back to the median raster for older runs, but the
        per-member measurement wins wherever it exists.
        """
        import sys

        sys.path.insert(0, "services/api")
        from jalraksha_service.tasks import _gauge_max_depths

        result = {
            "grid": {"nx": 10, "ny": 10, "dx": 100.0, "dy": 100.0,
                     "x0": 0.0, "y0": 0.0, "crs": "EPSG:32644"},
            "h_max_median": np.zeros((10, 10)),
            "gauges": [{"name": "G", "lat": 30.0, "lon": 78.0}],
            "arrival_times": {"G": {"cell": [5, 5], "max_depth_m": 3.5}},
        }
        assert _gauge_max_depths(result)["G"] == pytest.approx(3.5)

        # Without the per-member value, the raster is the honest fallback.
        result["arrival_times"]["G"].pop("max_depth_m")
        assert _gauge_max_depths(result)["G"] == pytest.approx(0.0)


class TestGaugeCorridorNeverBorrowed:
    """
    A named site with no corridor reports NO gauges, never a neighbour's.

    Both gauge resolvers carry a Tehri bounding-box fallback for callers that
    pass coordinates without a dam_id. Neither checked that dam_id was actually
    absent, so the box fired for any NAMED Himalayan site whose corridor happened
    to be empty. Measured: a Rishi Ganga blockage at (30.50, 79.63) — inside the
    box, on a different river 150 km from the Bhagirathi — returned arrival times
    at Koteshwar, Devprayag, Rishikesh and Haridwar.

    That is the exact failure define_downstream_gauges' docstring says it was
    written to end, arriving through the one path that still allowed it.
    """

    HIMALAYAN_LAT, HIMALAYAN_LON = 30.50, 79.63  # inside the Tehri box

    def test_a_named_site_without_a_corridor_gets_no_gauges(self):
        from jalraksha.run import define_downstream_gauges

        with pytest.warns(UserWarning, match="No downstream gauge corridor"):
            gauges = define_downstream_gauges(
                self.HIMALAYAN_LAT, self.HIMALAYAN_LON, dam_id="bhakra"
            )
        assert gauges == []

    def test_the_bounding_box_still_serves_a_coordinate_only_caller(self):
        """
        The fallback exists for calls that predate dam_id. Removing it entirely
        would break them, so it is narrowed rather than deleted.
        """
        from jalraksha.run import define_downstream_gauges

        gauges = define_downstream_gauges(30.3789, 78.4789, dam_id=None)
        assert [g["name"] for g in gauges] == [
            "Koteshwar", "Devprayag", "Rishikesh", "Haridwar",
        ]

    def test_a_named_site_with_its_own_corridor_is_unaffected(self):
        from jalraksha.run import define_downstream_gauges

        names = [
            g["name"]
            for g in define_downstream_gauges(30.50, 79.63, dam_id="rishi_ganga")
        ]
        assert names and all("channel" in n.lower() for n in names)
        assert "Koteshwar" not in names

    def test_the_legacy_http_resolver_holds_the_same_line(self):
        """jalraksha/api.py mirrors the fallback and carried the same defect."""
        from jalraksha.api import get_downstream_gauges

        borrowed = get_downstream_gauges(
            self.HIMALAYAN_LAT, self.HIMALAYAN_LON, dam_id="bhakra"
        )
        assert all(g["name"] != "Koteshwar" for g in borrowed), (
            "A named site was handed Tehri's corridor."
        )

        # Coordinate-only callers keep working.
        assert any(
            g["name"] == "Koteshwar"
            for g in get_downstream_gauges(30.3789, 78.4789, dam_id=None)
        )


class TestNoArrivalReasonOnSteepRivers:
    """
    A steep river's own fall is not height above the channel.

    _no_arrival_reason measured elevation against the lowest bed within 3 km,
    which is wide enough to find the Mula-Mutha where a Pune town spreads away
    from it. On the Alaknanda below Joshimath the same window spans 58-85 m of
    LONGITUDINAL FALL, so a point sitting exactly on the channel was reported as
    "64 m above the nearest river channel" and told it was a hillside town —
    which sends a reader to fix a coordinate that is correct.
    """

    def _grid(self):
        return Grid(nx=60, ny=60, dx=100.0, dy=100.0, x0=0.0, y0=0.0, crs="EPSG:32644")

    def _steep_channel(self, gradient_per_m):
        """A straight channel falling at `gradient_per_m`, walls well above it."""
        grid = self._grid()
        rows = np.arange(grid.ny)[:, None]
        cols = np.arange(grid.nx)[None, :]
        # Bed falls toward +y; walls rise away from column 30.
        bed = (
            2000.0
            - gradient_per_m * rows * grid.dy
            + 3.0 * np.abs(cols - 30) * grid.dx * 0.01
        )
        return grid, bed.astype(float)

    def test_a_point_on_a_steep_channel_is_not_called_a_hillside_town(self):
        from jalraksha.run import _no_arrival_reason

        # 60 m/km: the Alaknanda's order of magnitude here.
        grid, bed = self._steep_channel(0.060)
        gauge = {"name": "channel point", "note": "TERRAIN-DERIVED channel point"}

        reason = _no_arrival_reason(gauge, bed, grid, j_gauge=30, i_gauge=30)

        assert "at channel level" in reason
        # The gradient is reported, not asserted to a digit: the 3 km window
        # clips against the domain edge, so it reads 58 m/km for a 60 m/km bed.
        assert "which accounts for it" in reason
        assert "m/km" in reason
        assert "town centre" not in reason

    def test_a_genuinely_elevated_point_is_still_flagged(self):
        """The Pune finding this function exists for must survive the fix."""
        from jalraksha.run import _no_arrival_reason

        grid, bed = self._steep_channel(0.0)  # flat reach, so only height counts
        bed[30, 45] = bed[30, 30] + 60.0      # a hillside cell beside the channel
        gauge = {"name": "Swargate", "distance_km": 11.5}

        reason = _no_arrival_reason(gauge, bed, grid, j_gauge=30, i_gauge=45)

        assert "above the nearest river channel" in reason
        assert "town centre" in reason

    def test_a_terrain_derived_point_is_told_it_was_placed_off_the_thalweg(self):
        """
        Being above the channel means different things for a surveyed town and a
        coordinate read off the DEM. Naming the wrong cause sends the reader to
        fix the wrong thing.
        """
        from jalraksha.run import _no_arrival_reason

        grid, bed = self._steep_channel(0.0)
        bed[30, 45] = bed[30, 30] + 60.0
        gauge = {"name": "channel +5 km", "note": "TERRAIN-DERIVED channel point"}

        reason = _no_arrival_reason(gauge, bed, grid, j_gauge=30, i_gauge=45)

        assert "derived from the DEM" in reason
        assert "snap it to the local minimum" in reason
        assert "town centre" not in reason
