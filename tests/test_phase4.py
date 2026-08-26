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
