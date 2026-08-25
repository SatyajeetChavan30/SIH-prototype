"""
Phase 6 Impact Analysis & Loss-of-Life Test Suite.

Tests:
  - TestFD2320HazardRating: Hazard rating computation & classification
  - TestDepthDamage: JRC damage functions & economic loss calculations
  - TestPopulationExposure: Population exposure & PAR metrics
  - TestFatalityModels: Graham (1989) & Jonkman (2008) fatality calculations
"""

import numpy as np
import pytest
from jalraksha.impact.hazard import compute_fd2320_hazard_rating, categorize_hazard_zones
from jalraksha.impact.damage import compute_depth_damage, calculate_economic_loss
from jalraksha.impact.population import compute_population_exposure, compute_par
from jalraksha.impact.fatality import estimate_loss_of_life_graham, estimate_loss_of_life_jonkman


class TestFD2320HazardRating:
    """Test FD2320 hazard rating calculation & classification."""

    def test_dry_cells_zero_hazard(self):
        depth = np.zeros((5, 5), dtype=np.float32)
        vx = np.zeros((5, 5), dtype=np.float32)
        vy = np.zeros((5, 5), dtype=np.float32)

        hr = compute_fd2320_hazard_rating(depth, vx, vy)
        assert np.all(hr == 0.0)

        classes = categorize_hazard_zones(hr)
        assert np.all(classes == 0)

    def test_low_hazard_rating(self):
        depth = np.full((5, 5), 0.2, dtype=np.float32)
        vx = np.full((5, 5), 0.1, dtype=np.float32)
        vy = np.zeros((5, 5), dtype=np.float32)

        # HR = 0.2 * (0.1 + 0.5) + 0.5 = 0.2 * 0.6 + 0.5 = 0.62 < 0.75 (Low)
        hr = compute_fd2320_hazard_rating(depth, vx, vy)
        assert np.allclose(hr, 0.62, atol=1e-2)

        classes = categorize_hazard_zones(hr)
        assert np.all(classes == 0)

    def test_extreme_hazard_rating(self):
        depth = np.full((5, 5), 3.0, dtype=np.float32)  # High depth
        vx = np.full((5, 5), 2.5, dtype=np.float32)    # High velocity
        vy = np.zeros((5, 5), dtype=np.float32)

        # HR = 3.0 * (2.5 + 0.5) + 2.0 = 9.0 + 2.0 = 11.0 >= 2.5 (Extreme)
        hr = compute_fd2320_hazard_rating(depth, vx, vy)
        assert np.all(hr >= 2.5)

        classes = categorize_hazard_zones(hr)
        assert np.all(classes == 3)


class TestDepthDamage:
    """Test JRC depth-damage functions & economic loss estimation."""

    def test_depth_damage_monotonicity(self):
        depths = np.array([0.0, 0.5, 1.0, 2.0, 5.0], dtype=np.float32)
        ratios = compute_depth_damage(depths, sector="residential")

        # Must be monotonic non-decreasing
        assert ratios[0] == 0.0
        assert np.all(np.diff(ratios) >= 0.0)
        assert ratios[-1] <= 1.0

    def test_economic_loss_calculation(self):
        depth = np.ones((10, 10), dtype=np.float32) * 1.5  # 1.5m depth
        asset_grid = np.ones((10, 10), dtype=np.float32) * 500.0  # $500/m2 asset value

        loss = calculate_economic_loss(depth, asset_grid, sector="residential", cell_area_m2=400.0)
        assert loss["total_loss"] > 0
        assert loss["damaged_cell_count"] == 100
        assert 0.0 < loss["mean_damage_ratio"] <= 1.0


class TestPopulationExposure:
    """Test Population exposure & PAR metrics."""

    def test_population_exposure_by_class(self):
        depth = np.full((10, 10), 2.0, dtype=np.float32)
        vx = np.full((10, 10), 1.0, dtype=np.float32)
        vy = np.zeros((10, 10), dtype=np.float32)
        pop_grid = np.full((10, 10), 50.0, dtype=np.float32)  # 50 people per cell

        exposure = compute_population_exposure(depth, vx, vy, pop_grid)
        assert exposure["total_exposed_population"] == 5000.0
        assert exposure["total_flooded_cells"] == 100

    def test_par_lead_time_urgency(self):
        pop_grid = np.full((10, 10), 10.0, dtype=np.float32)
        # Arrival time = 1200 s (20 min)
        t_arr = np.full((10, 10), 1200.0, dtype=np.float32)
        h_max = np.full((10, 10), 1.0, dtype=np.float32)

        # Case A: Warning issued at t=0 s -> Lead time = 1200 s (20 min -> Medium urgency)
        par_a = compute_par(pop_grid, t_arr, warning_lead_time_s=0.0, h_max_grid=h_max)
        assert par_a["par_medium_urgency_15_60min"] == 1000.0

        # Case B: Warning issued at t=600 s (10 min) -> Lead time = 600 s (<15 min -> High urgency)
        par_b = compute_par(pop_grid, t_arr, warning_lead_time_s=600.0, h_max_grid=h_max)
        assert par_b["par_high_urgency_under_15min"] == 1000.0


class TestFatalityModels:
    """Test Graham (1989) & Jonkman (2008) loss-of-life estimation."""

    def test_graham_loss_of_life(self):
        # 1000 people at risk, 10 min warning (<15 min), severe flood
        res_short = estimate_loss_of_life_graham(1000, warning_time_min=10.0, flood_severity="high")
        # 1000 people at risk, 90 min warning (>60 min), severe flood
        res_long = estimate_loss_of_life_graham(1000, warning_time_min=90.0, flood_severity="high")

        assert res_short["estimated_fatalities"] > res_long["estimated_fatalities"]
        assert res_short["fatality_rate"] == 0.75
        assert res_long["fatality_rate"] == 0.01

    def test_jonkman_loss_of_life(self):
        depth = np.full((10, 10), 3.0, dtype=np.float32)  # Severe depth
        vx = np.full((10, 10), 2.0, dtype=np.float32)     # Severe velocity
        vy = np.zeros((10, 10), dtype=np.float32)
        pop_grid = np.full((10, 10), 10.0, dtype=np.float32)

        res = estimate_loss_of_life_jonkman(depth, vx, vy, pop_grid, warning_time_min=15.0)
        assert res["total_fatalities"] > 0
        assert res["total_par"] == 1000.0
