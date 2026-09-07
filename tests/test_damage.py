"""
Depth-damage and economic loss (Phase 6).

These tests are OFFLINE by construction: `floodview.impact` must not import
`floodview.gee`, so nothing here needs Earth Engine, a network, or a
monkeypatched client. The exposure arrays are supplied directly, which is the
same seam `tasks.py` uses in production.

What is pinned here is mostly PROVENANCE rather than numbers, because the
numbers rest on an unpublished curve and an unvetted unit cost. The tests that
matter are the ones that would fail if a figure ever escaped without its label,
if the unit cost stopped being rescalable, or if the exposure term were
multiplied by the cell area twice.
"""

import json

import numpy as np
import pytest

from floodview.impact import damage as dmg
from floodview.impact.damage import (
    HUIZINGA_2017_VERIFIED,
    SECTORS,
    DepthDamageCurveUnverified,
    UnknownSectorError,
    calculate_economic_loss,
    compute_depth_damage,
    estimate_sector_damage,
    huizinga_2017_damage_fraction,
)


class TestQuarantine:
    """Huizinga (2017) is present in shape and must stay unreachable."""

    def test_flag_is_false(self):
        assert HUIZINGA_2017_VERIFIED is False

    def test_calling_it_raises(self):
        with pytest.raises(DepthDamageCurveUnverified):
            huizinga_2017_damage_fraction(np.array([1.0, 2.0]))

    def test_the_refusal_names_an_alternative_and_cites_the_queue(self):
        with pytest.raises(DepthDamageCurveUnverified) as excinfo:
            huizinga_2017_damage_fraction(np.array([1.0]))
        message = str(excinfo.value)
        assert "estimate_sector_damage" in message
        assert "VERIFICATION_LOG.md" in message

    def test_the_deleted_class_is_really_gone(self):
        # DepthDamageAnalyzer carried coefficients attributed to a study that
        # appears in no bibliography here. If it comes back, so does the
        # fabricated r-squared.
        assert not hasattr(dmg, "DepthDamageAnalyzer")


class TestCurve:
    """The unpublished saturating curve: shape properties only."""

    def test_monotonic_bounded_and_zero_at_zero(self):
        depths = np.linspace(0.0, 12.0, 60)
        ratios = compute_depth_damage(depths, sector="residential")
        assert ratios[0] == 0.0
        assert np.all(np.diff(ratios) >= 0.0)
        assert ratios[-1] <= 1.0

    def test_unknown_sector_raises_rather_than_defaulting(self):
        # The previous version did `.get(sector, 0.8)`, so "residental" got the
        # residential curve and the result reported the misspelt sector back.
        with pytest.raises(UnknownSectorError):
            compute_depth_damage(np.array([1.0]), sector="residental")

    def test_sector_ordering_is_residential_fastest(self):
        depth = np.array([1.0])
        residential = compute_depth_damage(depth, "residential")[0]
        non_residential = compute_depth_damage(depth, "non_residential")[0]
        agricultural = compute_depth_damage(depth, "agricultural")[0]
        assert residential > non_residential > agricultural


class TestSectorDamage:
    """The figure that reaches the dashboard."""

    def _fields(self, exposure=100.0, depth=2.0, shape=(4, 4)):
        return (np.full(shape, depth), np.full(shape, exposure))

    def test_every_result_is_labelled_unpublished(self):
        depth, exposure = self._fields()
        for sector in SECTORS:
            result = estimate_sector_damage(depth, exposure, sector)
            assert result["model_is_published"] is False
            assert "VERIFICATION_LOG.md" in result["model_note"]

    def test_every_result_echoes_its_unit_cost_and_price_year(self):
        depth, exposure = self._fields()
        for sector in SECTORS:
            result = estimate_sector_damage(depth, exposure, sector)
            assert result["unit_cost_inr_per_m2"] > 0.0
            assert result["unit_cost_price_year"] >= 1900
            assert result["unit_cost_basis"]

    def test_doubling_the_unit_cost_doubles_the_figure(self):
        # This is the whole point of echoing the cost: an unvetted constant is
        # tolerable only while a reader can divide it back out.
        depth, exposure = self._fields()
        base = estimate_sector_damage(depth, exposure, "residential")
        doubled = estimate_sector_damage(
            depth, exposure, "residential",
            unit_cost_inr_per_m2=base["unit_cost_inr_per_m2"] * 2.0)
        assert doubled["damage_crore_inr"] == pytest.approx(
            base["damage_crore_inr"] * 2.0)
        assert base["unit_cost_is_default"] is True
        assert doubled["unit_cost_is_default"] is False

    def test_no_exposure_gives_no_damage_and_no_crash(self):
        depth = np.full((6, 6), 3.0)
        result = estimate_sector_damage(depth, np.zeros((6, 6)), "residential")
        assert result["damage_crore_inr"] == 0.0
        assert result["exposed_area_m2"] == 0.0
        assert result["exposure_weighted_damage_ratio"] == 0.0

    def test_dry_domain_gives_no_damage(self):
        result = estimate_sector_damage(
            np.zeros((5, 5)), np.full((5, 5), 500.0), "residential")
        assert result["damage_crore_inr"] == 0.0
        assert result["flooded_cells"] == 0

    def test_payload_is_json_serialisable_with_no_default_hook(self):
        # impact.json is written with json.dumps and read back by the API. A
        # numpy array in here would either raise or, with default=str, be
        # written as a stringified array.
        depth, exposure = self._fields()
        for sector in SECTORS:
            payload = estimate_sector_damage(depth, exposure, sector)
            json.dumps(payload)  # no default= on purpose
            assert not any(isinstance(v, np.ndarray) for v in payload.values())

    def test_exposure_is_an_area_per_cell_not_a_density(self):
        # GHS-BUILT-S gives m2 of built-up INSIDE each cell. Multiplying that
        # by the cell area squares the area term — 40,000x at 200 m. The same
        # built-up array on a 200 m and a 400 m grid must give the SAME damage,
        # because the grid spacing never enters the calculation.
        depth = np.full((4, 4), 2.0)
        built_up_m2 = np.full((4, 4), 900.0)
        coarse = estimate_sector_damage(depth, built_up_m2, "residential")
        fine = estimate_sector_damage(depth, built_up_m2, "residential")
        assert coarse["damage_crore_inr"] == fine["damage_crore_inr"]

        # A cropland FRACTION is the other case: it becomes an area only once
        # the caller multiplies by the cell area, so it must scale with it.
        fraction = np.full((4, 4), 0.5)
        at_200 = estimate_sector_damage(
            depth, fraction * (200.0 ** 2), "agricultural")
        at_400 = estimate_sector_damage(
            depth, fraction * (400.0 ** 2), "agricultural")
        assert at_400["damage_crore_inr"] == pytest.approx(
            at_200["damage_crore_inr"] * 4.0)

    def test_mismatched_grids_are_refused(self):
        with pytest.raises(ValueError):
            estimate_sector_damage(np.zeros((4, 4)), np.zeros((4, 5)),
                                   "residential")

    def test_shallow_water_below_the_threshold_contributes_nothing(self):
        # The threshold matches compute_population_exposure's 0.1 m, so
        # "exposed" means the same depth in the damage figure and in the
        # headcount printed beside it.
        depth = np.full((3, 3), 0.05)
        result = estimate_sector_damage(depth, np.full((3, 3), 1000.0),
                                        "residential")
        assert result["flooded_cells"] == 0
        assert result["damage_crore_inr"] == 0.0

    def test_the_band_brackets_the_central_figure(self):
        depth, exposure = self._fields()
        result = estimate_sector_damage(depth, exposure, "residential")
        assert (result["damage_lower_crore_inr"]
                < result["damage_crore_inr"]
                < result["damage_upper_crore_inr"])

    def test_damage_ratio_is_exposure_weighted_not_cell_averaged(self):
        # One deep city block beside eight shallow empty cells: a plain mean
        # over wet cells would describe the domain, not the assets.
        depth = np.full((3, 3), 0.2)
        depth[1, 1] = 8.0
        exposure = np.zeros((3, 3))
        exposure[1, 1] = 10000.0
        result = estimate_sector_damage(depth, exposure, "residential")
        deep_ratio = float(compute_depth_damage(np.array([8.0]),
                                                "residential")[0])
        assert result["exposure_weighted_damage_ratio"] == pytest.approx(
            deep_ratio)


class TestCallerCurrencyLoss:
    """calculate_economic_loss keeps the caller's units, and says so."""

    def test_currency_is_not_claimed(self):
        result = calculate_economic_loss(
            np.full((10, 10), 1.0), np.full((10, 10), 5.0),
            sector="residential", cell_area_m2=400.0)
        assert "total_loss" in result
        assert "crore" not in " ".join(result.keys())
        assert "caller-defined" in result["currency"]
        assert result["model_is_published"] is False
