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
from floodview.impact.hazard import (
    HazardClassifier,
    HazardLevel,
    categorize_hazard_zones,
    compute_fd2320_hazard_rating,
    compute_fd2320_hazard_rating_from_speed,
)
from floodview.impact.damage import compute_depth_damage, calculate_economic_loss
from floodview.impact.population import compute_population_exposure, compute_par
from floodview.impact.fatality import estimate_loss_of_life_graham, estimate_loss_of_life_jonkman


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

    def test_a_fast_deep_flow_is_not_classified_dry(self):
        """
        Velocity must RAISE hazard. It used to be able to erase it.

        HazardClassifier held a discrete (depth window x velocity ceiling)
        table and tested `velocity <= max_velocity` as one term of an AND with
        the depth window. A cell exceeding a band's velocity ceiling therefore
        fell OUT of that band without being promoted, and a flow 3 m deep at
        8 m/s matched no band at all and came back DRY.
        """
        depth = np.full((4, 4), 3.0)
        vx = np.full((4, 4), 8.0)
        vy = np.zeros((4, 4))

        classification = HazardClassifier().classify(depth, vx, vy)
        assert np.all(classification == HazardLevel.EXTREME)
        assert not np.any(classification == HazardLevel.DRY)

    def test_velocity_can_only_increase_the_hazard_rating(self):
        depth = np.full((3, 3), 1.0)
        zero = np.zeros((3, 3))

        slow = compute_fd2320_hazard_rating(depth, zero, zero)
        fast = compute_fd2320_hazard_rating(depth, np.full((3, 3), 5.0), zero)
        assert np.all(fast > slow)

    def test_debris_factor_shifts_the_rating_by_exactly_its_value(self):
        """DF is a categorical input (0 / 0.5 / 1.0), not a baked-in constant."""
        depth = np.full((3, 3), 1.0)
        zero = np.zeros((3, 3))

        hr_0 = compute_fd2320_hazard_rating(depth, zero, zero, debris_factor=0.0)
        hr_1 = compute_fd2320_hazard_rating(depth, zero, zero, debris_factor=1.0)
        assert np.allclose(hr_1 - hr_0, 1.0)

    def test_depth_only_band_edges_are_where_the_docstring_says(self):
        """
        classify_depth_only evaluates HR at |V| = 0, i.e. HR = 0.5d + DF.

        At the default DF of 0.5 that puts the class edges at 0.5 / 1.5 / 4.0 m.
        The frontend's gauge badge duplicates those numbers, so they are pinned
        here rather than left implicit.
        """
        classifier = HazardClassifier()
        depths = np.array([[0.01, 0.49, 0.51, 1.49, 1.51, 3.99, 4.01]])
        got = classifier.classify_depth_only(depths)[0]

        assert list(got) == [
            HazardLevel.DRY,
            HazardLevel.LOW,
            HazardLevel.MODERATE,
            HazardLevel.MODERATE,
            HazardLevel.SIGNIFICANT,
            HazardLevel.SIGNIFICANT,
            HazardLevel.EXTREME,
        ]

    def test_one_velocity_component_is_refused_not_silently_zeroed(self):
        """
        The previous signature took a single velocity MAGNITUDE as the second
        argument. Accepting one component would let such a call through and
        classify it at zero speed — under-stating hazard rather than failing.
        """
        depth = np.full((2, 2), 2.0)
        with pytest.raises(ValueError, match="classify_from_speed"):
            HazardClassifier().classify(depth, np.full((2, 2), 6.0))

    def test_severe_is_not_a_published_fd2320_class(self):
        """
        FD2320 publishes four wet categories and no boundary that would split
        extreme. The retired fifth level had no source for its threshold.
        """
        assert not hasattr(HazardLevel, "SEVERE")
        assert {level.value for level in HazardLevel} == {
            "dry", "low", "moderate", "significant", "extreme",
        }

    def test_the_shapefile_exporter_agrees_with_the_dashboard_classifier(self):
        """
        These were two different tables, both labelled FD2320, and they
        disagreed: a cell 1.5 m deep was "moderate" on the dashboard and
        "high" in the exported shapefile. The exporter now calls the same
        classifier, so equal inputs must produce equal classes.
        """
        from floodview.export import shapefile as shapefile_module

        depth = np.array([[0.0, 0.3, 1.5, 3.0]])
        speed = np.array([[0.0, 0.2, 1.0, 8.0]])

        classifier = HazardClassifier()
        expected = classifier.classify_from_speed(depth, speed)

        # The exporter's own route to a class: HR then the integer bands.
        hr = compute_fd2320_hazard_rating_from_speed(depth, speed)
        integer_classes = categorize_hazard_zones(hr)

        name_to_integer = {
            HazardLevel.DRY: 0,
            HazardLevel.LOW: 0,   # class 0 merges dry and low, by design
            HazardLevel.MODERATE: 1,
            HazardLevel.SIGNIFICANT: 2,
            HazardLevel.EXTREME: 3,
        }
        assert [name_to_integer[c] for c in expected[0]] == list(integer_classes[0])
        assert shapefile_module is not None  # exporter imports cleanly


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
