"""
Tests for Phase 3 breach regressions, level-pool routing, and ensembles.

The anchor for this file is Teton (1976), the tallest well-documented
embankment-dam failure and the only one whose peak outflow is known well
enough to test transcription against:

    V_w = 356 MCM (3.56e8 m^3)      reservoir volume at breach initiation
    h_w = 86.9 m                    depth of water above the breach invert
    h_d = 93 m                      dam height
    Q_p = 65,120 m^3/s              measured peak outflow

Every peak-outflow equation in jalraksha.terrain.breach is checked against it.
That is the point of the file: a mis-transcribed coefficient or a MCM/m^3 unit
slip moves the Teton prediction by a factor of 2 to 59, which these tests
catch. An earlier version of the module encoded regressions that were
reverse-engineered to land Tehri in a pre-chosen band, and the tests it shipped
with asserted that band — so they passed while the science was wrong. These
tests assert against measurement instead.

Source for the Teton figures and for the equations: Wahl, T.L. (1998),
"Prediction of Embankment Dam Breach Parameters", USBR DSO-98-004, Table 5.
"""

import numpy as np
import pytest

from jalraksha.terrain.breach import (
    CALIBRATION_MAX_HEIGHT_M,
    DEFAULT_REGRESSION_FAMILIES,
    MCM_TO_M3,
    XU_ZHANG_2009_VERIFIED,
    _breach_weir_discharge,
    _route_breach_fine,
    costa_1985_peak_outflow,
    ensemble_statistics,
    extrapolation_ratio,
    froehlich_1995_peak_outflow,
    level_pool_routing,
    macdonald_langridge_1984_peak_outflow,
    reservoir_storage_curve,
    scs_1981_peak_outflow,
    synthesize_breach_ensemble,
    synthesize_scenario_ensemble,
    von_thun_gillette_1990_breach_geometry,
    von_thun_gillette_1990_peak_outflow,
    xu_zhang_2009_peak_outflow,
)

# Teton Dam, Idaho, 5 June 1976.
TETON_VOLUME_MCM = 356.0
TETON_WATER_DEPTH_M = 86.9
TETON_DAM_HEIGHT_M = 93.0
TETON_MEASURED_PEAK_M3_S = 65120.0

# Tehri Dam, Uttarakhand — the project's demo case. 2.8x beyond the tallest
# dam in any of these regressions' calibration sets, so a target range rather
# than a target value.
TEHRI_HEIGHT_M = 260.0
TEHRI_STORAGE_MCM = 3540.0


def _blockage_config(**overrides):
    """
    A river_blockage config whose storage came from a hypsometric fill.

    The elevations are absolute, as the burned geometry produces them: a valley
    floor at 1000 m with a 60 m deposit on it. Passing a height where an
    elevation belongs is the failure mode test_blockage.py's kilometre-shift
    test guards in the geometry; here the equivalent guard is that these fields
    are required at all.
    """
    config = {
        "name": "Landslide-dammed lake",
        "height_m": 60.0,
        "storage_mm3": 72.0,
        "dam_type": "landslide",
        "scenario_type": "river_blockage",
        "hydrograph_duration_s": 3600.0,
        "storage_source": "hypsometric_fill",
        "surface_area_km2": 3.6,
        "breach_bottom_elev_m": 1000.0,
        "initial_surface_elev_m": 1060.0,
    }
    config.update(overrides)
    return config


class TestRiverOverflowScreening:
    """
    The overflow scenario is still a screening pulse, and says so.

    It is deliberately NOT upgraded alongside river_blockage: modelling a
    controlled spillway release needs a gate rating curve and an operating rule,
    neither of which this project has. The test pins the label, so the day
    somebody wires real routing in, the claim has to be updated with it.
    """

    def test_screening_scenario_is_volume_conserving_and_labelled(self):
        config = {
            "name": "Mutha River, Pune",
            "height_m": 39.6,
            "storage_mm3": 85.31,
            "dam_type": "gravity",
            "scenario_type": "river_overflow",
            "hydrograph_duration_s": 3600.0,
        }
        hydrograph = synthesize_scenario_ensemble(config, num_samples=1, random_seed=7)[0]
        metadata = hydrograph["metadata"]

        assert metadata["scenario_type"] == "river_overflow"
        assert metadata["failure_time_assumed"] is True
        assert metadata["q_peak_m3_s"] > 0.0
        assert "screening" in metadata["method"]
        released = np.trapezoid(hydrograph["Q_t"], hydrograph["t_array"])
        assert released == pytest.approx(metadata["released_volume_m3"], rel=0.01)


class TestBlockageEnsemble:
    """
    A landslide-dam outburst is modelled, not assumed.

    Before this it was a sin^2 pulse releasing 85% of whatever the dashboard's
    storage slider said. These tests exist so it cannot quietly become that
    again: the storage refusal and the family restriction are both asserted, and
    neither depends on a coefficient that might later be transcribed.
    """

    def test_storage_from_the_ui_is_refused(self):
        """
        The decision that makes the whole feature meaningful. A landslide dam has
        no published gross storage, so a config that supplies one instead of
        measuring it must fail loudly rather than route a slider value and label
        the output a modelled result.
        """
        from jalraksha.hardening import HardeningError

        for storage_source in (None, "user_input", "preset"):
            config = _blockage_config(storage_source=storage_source)
            with pytest.raises(HardeningError, match="measured from the terrain"):
                synthesize_scenario_ensemble(config, num_samples=2, random_seed=7)

    def test_barrier_crest_and_valley_floor_are_required(self):
        from jalraksha.hardening import HardeningError

        for missing in ("initial_surface_elev_m", "breach_bottom_elev_m"):
            config = _blockage_config(**{missing: None})
            with pytest.raises(HardeningError, match=missing):
                synthesize_scenario_ensemble(config, num_samples=2, random_seed=7)

    def test_only_the_natural_dam_family_runs(self):
        """
        Froehlich, MacDonald and Von Thun are embankment fits. Running them on an
        unengineered landslide deposit would report an engineered-dam answer.
        """
        members = synthesize_scenario_ensemble(
            _blockage_config(), num_samples=8, random_seed=7
        )
        regressions = {m["metadata"]["regression"] for m in members}
        assert regressions == {"costa_1985"}

    def test_released_volume_never_exceeds_the_hypsometric_storage(self):
        """
        The same invariant the dam-break routing holds, now against a volume read
        off the terrain rather than a published figure.
        """
        config = _blockage_config()
        storage_m3 = config["storage_mm3"] * MCM_TO_M3
        members = synthesize_scenario_ensemble(config, num_samples=12, random_seed=7)

        for member in members:
            released = np.trapezoid(member["Q_t"], member["t_array"])
            assert released <= storage_m3 * 1.001, (
                f"Member {member['metadata']['member_id']} released "
                f"{released:.3e} m3 from a lake holding {storage_m3:.3e} m3."
            )
            assert member["metadata"]["released_volume_m3"] == pytest.approx(
                released, rel=1e-9
            )

    def test_every_member_carries_the_natural_dam_scatter_note(self):
        from jalraksha.terrain.natural_dam import NATURAL_DAM_SCATTER_NOTE

        members = synthesize_scenario_ensemble(
            _blockage_config(), num_samples=4, random_seed=7
        )
        for member in members:
            assert member["metadata"]["natural_dam_note"] == NATURAL_DAM_SCATTER_NOTE
            assert member["metadata"]["scenario_type"] == "river_blockage"
            assert member["metadata"]["storage_source"] == "hypsometric_fill"

        stats = ensemble_statistics(members)
        assert stats["natural_dam_note"] == NATURAL_DAM_SCATTER_NOTE
        assert stats["scenario_type"] == "river_blockage"
        assert stats["storage_source"] == "hypsometric_fill"

    def test_the_dam_class_flag_inverts_for_a_blockage(self):
        """
        An embankment is in-population for a dam break and OUT of it for a
        landslide-dam outburst. Reporting one sense with the other scenario's
        explanation would be the right warning attached to the wrong reason.
        """
        from jalraksha.terrain.breach import DAM_CLASS_EXTRAPOLATION_NOTE
        from jalraksha.terrain.natural_dam import NATURAL_DAM_SCATTER_NOTE

        landslide = synthesize_scenario_ensemble(
            _blockage_config(dam_type="landslide"), num_samples=2, random_seed=7
        )[0]["metadata"]
        embankment = synthesize_scenario_ensemble(
            _blockage_config(dam_type="embankment"), num_samples=2, random_seed=7
        )[0]["metadata"]

        assert landslide["dam_class_outside_fitted_population"] is False
        assert embankment["dam_class_outside_fitted_population"] is True
        assert embankment["dam_class_note"] == NATURAL_DAM_SCATTER_NOTE
        assert embankment["dam_class_note"] != DAM_CLASS_EXTRAPOLATION_NOTE

    def test_the_ensemble_spreads_across_the_prediction_band(self):
        """
        With one active family there is no inter-method disagreement to supply
        the spread, so the members are sampled across Costa's natural-dam band
        instead. An ensemble that came back nearly identical would be reporting a
        false precision.
        """
        members = synthesize_scenario_ensemble(
            _blockage_config(), num_samples=60, random_seed=7
        )
        stats = ensemble_statistics(members)

        assert stats["q_peak_p95"] / stats["q_peak_p05"] > 3.0
        assert all(
            m["metadata"]["peak_sampling"].startswith("prediction_band")
            for m in members
        )


class TestNaturalDamRegressions:
    """
    Walder & O'Connor (1997) and Peng & Zhang (2012) are implemented in shape
    and quarantined until their coefficients are transcribed — the same
    treatment Xu & Zhang (2009) gets, for the same reason.
    """

    def test_unverified_natural_dam_equations_are_quarantined(self):
        from jalraksha.terrain.natural_dam import (
            NATURAL_DAM_REGRESSION_FAMILIES,
            PENG_ZHANG_2012_VERIFIED,
            WALDER_OCONNOR_1997_VERIFIED,
            NaturalDamRegressionUnverified,
            peng_zhang_2012_peak_outflow,
            walder_oconnor_1997_peak_outflow,
        )

        assert WALDER_OCONNOR_1997_VERIFIED is False
        assert PENG_ZHANG_2012_VERIFIED is False
        assert "walder_oconnor" not in NATURAL_DAM_REGRESSION_FAMILIES
        assert "peng_zhang" not in NATURAL_DAM_REGRESSION_FAMILIES

        with pytest.raises(NaturalDamRegressionUnverified, match="row 19"):
            walder_oconnor_1997_peak_outflow(60.0, 7.2e7)
        with pytest.raises(NaturalDamRegressionUnverified, match="row 20"):
            peng_zhang_2012_peak_outflow(60.0, 400.0, 5.4e6, 7.2e7)

    def test_costa_is_the_only_active_natural_dam_family(self):
        from jalraksha.terrain.natural_dam import NATURAL_DAM_REGRESSION_FAMILIES

        assert NATURAL_DAM_REGRESSION_FAMILIES == ("costa",)

    def test_natural_dam_bands_are_wider_than_the_embankment_bands(self):
        """
        Asserts the RELATIONSHIP the literature states, not the placeholder
        numbers, so it survives transcription unchanged: natural-dam scatter is
        wider than Wahl's embankment scatter because the dams are unengineered
        and the case databases are smaller.
        """
        from jalraksha.terrain.breach import UNCERTAINTY_LOG_CYCLES
        from jalraksha.terrain.natural_dam import NATURAL_DAM_LOG_CYCLES

        widest_embankment = max(UNCERTAINTY_LOG_CYCLES.values())
        narrowest_natural = min(NATURAL_DAM_LOG_CYCLES.values())

        assert narrowest_natural > widest_embankment, (
            f"The narrowest natural-dam band ({narrowest_natural}) must exceed "
            f"the widest embankment band ({widest_embankment})."
        )

    def test_an_unknown_band_key_raises_rather_than_defaulting(self):
        """
        breach._wahl_bounds falls back to 0.50 log cycles for an unknown key.
        Silently defaulting a natural-dam band would let a new regression ship
        with an embankment-width interval nobody chose.
        """
        from jalraksha.terrain.natural_dam import natural_dam_bounds

        with pytest.raises(KeyError):
            natural_dam_bounds(1000.0, "some_new_equation")

    def test_the_natural_dam_class_population_is_the_mirror_of_the_embankment_one(self):
        from jalraksha.terrain.breach import (
            dam_class_outside_fitted_population as embankment_outside,
        )
        from jalraksha.terrain.natural_dam import (
            dam_class_outside_fitted_population as natural_outside,
        )

        assert embankment_outside("embankment") is False
        assert natural_outside("embankment") is True
        assert natural_outside("landslide") is False
        assert embankment_outside("landslide") is True

    def test_dimensionless_peak_outflow_is_scale_free(self):
        """
        Q_p / (g^0.5 * H^2.5) is how a landslide-dam discharge is compared with a
        published case of a different size. Two geometrically similar events must
        map to the same number.
        """
        from jalraksha.terrain.natural_dam import dimensionless_peak_outflow

        small = dimensionless_peak_outflow(1000.0, 30.0)
        large = dimensionless_peak_outflow(1000.0 * 2.0**2.5, 60.0)
        assert small == pytest.approx(large, rel=1e-12)


class TestUnits:
    """The MCM/m^3 boundary — the module's single most dangerous unit slip."""

    def test_froehlich_matches_published_formula_exactly(self):
        """
        Froehlich (1995b) is Q = 0.607 * V_w^0.295 * h_w^1.24 with V_w in m^3.

        Asserted against the formula evaluated independently here, so a
        refactor that folds a unit conversion into a coefficient fails.
        """
        volume_m3 = TETON_VOLUME_MCM * MCM_TO_M3
        expected = 0.607 * (volume_m3**0.295) * (TETON_WATER_DEPTH_M**1.24)

        actual, _, _ = froehlich_1995_peak_outflow(
            TETON_WATER_DEPTH_M, 0.0, TETON_VOLUME_MCM, "central"
        )

        assert actual == pytest.approx(expected, rel=1e-12)

    def test_mcm_conversion_is_applied(self):
        """
        Feeding MCM where the source wants m^3 understates Q by 10^(6*0.295).

        This is the specific error recorded in docs/DECISIONS.md line 238, and
        it is a factor of 59 — large enough to look plausible on a log plot and
        wrong enough to invalidate every downstream inundation extent.
        """
        actual, _, _ = froehlich_1995_peak_outflow(
            TETON_WATER_DEPTH_M, 0.0, TETON_VOLUME_MCM, "central"
        )
        if_mcm_were_m3 = 0.607 * (TETON_VOLUME_MCM**0.295) * (
            TETON_WATER_DEPTH_M**1.24
        )

        assert actual / if_mcm_were_m3 == pytest.approx(MCM_TO_M3**0.295, rel=1e-9)
        assert actual / if_mcm_were_m3 > 50.0


@pytest.mark.blocking
class TestTetonBenchmark:
    """
    Every verified equation must bracket the measured Teton peak.

    Bracketing, not matching: these are empirical fits with a factor-of-2-to-3
    scatter, and Wahl (2004) publishes prediction bands rather than standard
    errors for exactly that reason. An equation whose *band* misses the
    observation is mis-transcribed.
    """

    # (label, callable returning (central, lower, upper), expected ratio)
    VERIFIED_METHODS = [
        (
            "froehlich_1995",
            lambda: froehlich_1995_peak_outflow(
                TETON_WATER_DEPTH_M, 0.0, TETON_VOLUME_MCM, "central"
            ),
            0.79,
        ),
        (
            "macdonald_1984",
            lambda: macdonald_langridge_1984_peak_outflow(
                TETON_WATER_DEPTH_M, TETON_VOLUME_MCM, "embankment", "central"
            ),
            0.37,
        ),
        (
            "costa_1985",
            lambda: costa_1985_peak_outflow(
                TETON_DAM_HEIGHT_M, TETON_VOLUME_MCM, "central"
            ),
            0.40,
        ),
        (
            "scs_1981",
            lambda: scs_1981_peak_outflow(TETON_WATER_DEPTH_M, "central"),
            0.99,
        ),
        (
            "von_thun_1990_routed",
            lambda: von_thun_gillette_1990_peak_outflow(
                TETON_WATER_DEPTH_M, TETON_VOLUME_MCM, "central"
            ),
            1.55,
        ),
    ]

    @pytest.mark.parametrize("label,method,expected_ratio", VERIFIED_METHODS)
    def test_band_contains_measured_peak(self, label, method, expected_ratio):
        """The Wahl (2004) prediction band must contain the observation."""
        central, lower, upper = method()

        assert lower <= TETON_MEASURED_PEAK_M3_S <= upper, (
            f"{label}: band [{lower:.0f}, {upper:.0f}] misses the measured "
            f"{TETON_MEASURED_PEAK_M3_S:.0f} m3/s (central {central:.0f}). "
            "A band this far off means the coefficients are mis-transcribed."
        )

    @pytest.mark.parametrize("label,method,expected_ratio", VERIFIED_METHODS)
    def test_central_estimate_ratio_is_stable(self, label, method, expected_ratio):
        """
        Pin the central/measured ratio so any coefficient edit shows up.

        Tolerance is 10% on the ratio: enough to absorb a change of integration
        detail in the routed method, tight enough that changing an exponent
        fails.
        """
        central, _, _ = method()
        ratio = central / TETON_MEASURED_PEAK_M3_S

        assert ratio == pytest.approx(expected_ratio, abs=0.10), (
            f"{label}: Teton ratio moved to {ratio:.2f} from {expected_ratio:.2f} "
            f"(Q = {central:.0f} m3/s)"
        )

    def test_macdonald_pair_brackets_where_best_fit_alone_does_not(self):
        """
        MLM's best fit under-predicts Teton 2.7x; its published envelope is the
        reason both are exposed. The pair must straddle the observation.
        """
        best_fit, _, upper = macdonald_langridge_1984_peak_outflow(
            TETON_WATER_DEPTH_M, TETON_VOLUME_MCM, "embankment", "central"
        )
        _, _, envelope = macdonald_langridge_1984_peak_outflow(
            TETON_WATER_DEPTH_M, TETON_VOLUME_MCM, "embankment", "upper"
        )

        assert best_fit < TETON_MEASURED_PEAK_M3_S < envelope
        assert upper == pytest.approx(envelope, rel=1e-12)

    def test_ensemble_of_verified_methods_straddles_measurement(self):
        """
        The deliverable is the ensemble range, so that range is what is tested:
        at least one method above and one below the observation.
        """
        centrals = [method()[0] for _, method, _ in self.VERIFIED_METHODS]

        assert min(centrals) < TETON_MEASURED_PEAK_M3_S < max(centrals)
        # And the spread is wide — this is the honest uncertainty, not noise.
        assert max(centrals) / min(centrals) > 2.0


class TestXuZhangQuarantine:
    """
    Xu & Zhang (2009) is implemented but excluded pending verification.

    These tests assert the quarantine holds, and record the size of the miss so
    that whoever verifies the coefficients has a number to check against.
    """

    def test_quarantine_flag_is_false(self):
        assert XU_ZHANG_2009_VERIFIED is False

    def test_excluded_from_default_ensemble(self):
        """A quarantined family must not be drawn on when no family is named."""
        assert "xu_zhang" not in DEFAULT_REGRESSION_FAMILIES
        assert "xu_zhang_2009" not in DEFAULT_REGRESSION_FAMILIES

    def test_teton_miss_is_the_documented_factor(self):
        """
        The coefficients over-predict Teton by ~5.6x, consistent with the
        back-solve in the function docstring: matching Teton requires
        exp(B_4) = 0.0900 (B_4 = -2.41), while the tabulated categories give
        exp(-0.704) = 0.495 — a factor of 5.5.

        If someone corrects the coefficients, this test fails and should be
        replaced by a normal bracketing test plus flipping
        XU_ZHANG_2009_VERIFIED.
        """
        central, _, _ = xu_zhang_2009_peak_outflow(
            TETON_WATER_DEPTH_M, TETON_VOLUME_MCM, "embankment", "piping", "central"
        )
        ratio = central / TETON_MEASURED_PEAK_M3_S

        assert ratio == pytest.approx(5.6, abs=0.4), (
            f"Xu & Zhang Teton ratio is now {ratio:.2f}. If the coefficients "
            "were corrected, set XU_ZHANG_2009_VERIFIED = True, add it to "
            "DEFAULT_REGRESSION_FAMILIES, and move it to TestTetonBenchmark."
        )

    def test_still_returns_a_usable_number(self):
        """Quarantined, not broken: callers that ask for it get a value."""
        central, lower, upper = xu_zhang_2009_peak_outflow(
            100.0, 500.0, "embankment", "overtopping", "central"
        )
        assert np.isfinite(central) and central > 0.0
        assert lower < central < upper


class TestVonThunGilletteGeometry:
    """
    Von Thun & Gillette (1990) supplies geometry and failure time, not a peak.

    The previous module encoded VTG as Q = 0.6 * H^0.80 * V^0.30, which is not
    a relation VTG publish. These tests pin what they actually publish.
    """

    def test_breach_width_relation(self):
        """B_avg = 2.5 * h_w + C_b, with C_b = 54.9 m above 12.3 MCM."""
        geometry = von_thun_gillette_1990_breach_geometry(
            TETON_WATER_DEPTH_M, TETON_VOLUME_MCM
        )
        assert geometry["breach_width_m"] == pytest.approx(
            2.5 * TETON_WATER_DEPTH_M + 54.9
        )

    @pytest.mark.parametrize(
        "storage_mcm,expected_offset_m",
        [(0.5, 6.1), (3.0, 18.3), (10.0, 42.7), (100.0, 54.9)],
    )
    def test_storage_offset_bands(self, storage_mcm, expected_offset_m):
        """VTG Table 1 offsets: 6.1 / 18.3 / 42.7 / 54.9 m."""
        geometry = von_thun_gillette_1990_breach_geometry(50.0, storage_mcm)
        assert geometry["breach_width_m"] == pytest.approx(
            2.5 * 50.0 + expected_offset_m
        )

    def test_failure_time_relations(self):
        """t_f = 0.020*h_w + 0.25 h resistant; 0.015*h_w h erodible."""
        resistant = von_thun_gillette_1990_breach_geometry(
            TETON_WATER_DEPTH_M, TETON_VOLUME_MCM, "erosion_resistant"
        )
        erodible = von_thun_gillette_1990_breach_geometry(
            TETON_WATER_DEPTH_M, TETON_VOLUME_MCM, "easily_erodible"
        )

        assert resistant["failure_time_s"] == pytest.approx(
            (0.020 * TETON_WATER_DEPTH_M + 0.25) * 3600.0
        )
        assert erodible["failure_time_s"] == pytest.approx(
            0.015 * TETON_WATER_DEPTH_M * 3600.0
        )

    def test_erodible_failure_time_matches_teton_observation(self):
        """
        Teton's breach formed in roughly 1.25 h; VTG's easily-erodible relation
        gives 1.30 h for its 86.9 m head. Worth pinning: it is the one
        independent check available on the failure-time side.
        """
        erodible = von_thun_gillette_1990_breach_geometry(
            TETON_WATER_DEPTH_M, TETON_VOLUME_MCM, "easily_erodible"
        )
        hours = erodible["failure_time_s"] / 3600.0
        assert 1.1 < hours < 1.5

    def test_weir_at_full_breach_grossly_overpredicts(self):
        """
        Documents *why* the VTG peak is routed rather than read off a weir.

        A broad-crested weir at full head over the full final breach ignores
        the drawdown that happens while the breach is still forming, and
        over-predicts Teton by ~7x. Routing brings it to 1.55x. If this test
        ever fails, the routing has stopped doing its job.
        """
        geometry = von_thun_gillette_1990_breach_geometry(
            TETON_WATER_DEPTH_M, TETON_VOLUME_MCM, "easily_erodible"
        )
        unrouted = _breach_weir_discharge(
            TETON_WATER_DEPTH_M, geometry["breach_width_m"], geometry["side_slope"]
        )
        routed, _, _ = von_thun_gillette_1990_peak_outflow(
            TETON_WATER_DEPTH_M, TETON_VOLUME_MCM, "central"
        )

        assert unrouted / TETON_MEASURED_PEAK_M3_S > 5.0
        assert routed < unrouted / 3.0


class TestReservoirStorageCurve:
    """S(d) = k * d^b, with b derived from surface area when it is known."""

    def test_curve_reproduces_the_storage_it_was_fitted_to(self):
        coefficient, exponent = reservoir_storage_curve(
            TETON_VOLUME_MCM, TETON_WATER_DEPTH_M
        )
        assert coefficient * TETON_WATER_DEPTH_M**exponent == pytest.approx(
            TETON_VOLUME_MCM * MCM_TO_M3, rel=1e-9
        )

    def test_exponent_derived_from_surface_area(self):
        """
        For S = k*d^b the area is A = dS/dd = b*S/d, so b = A0*d0/S0. Teton
        held 356 MCM at 86.9 m over ~28 km^2, implying b = 6.8 — its mean
        depth was only 15% of its maximum, which a cone (b = 3) cannot
        represent.
        """
        _, exponent = reservoir_storage_curve(
            TETON_VOLUME_MCM, TETON_WATER_DEPTH_M, surface_area_km2=28.0
        )
        expected = 28.0e6 * TETON_WATER_DEPTH_M / (TETON_VOLUME_MCM * MCM_TO_M3)
        assert exponent == pytest.approx(expected, rel=1e-9)
        assert 6.0 < exponent < 7.5

    def test_exponent_kept_physical(self):
        """b < 1 would mean surface area shrinking with depth; clamp at 1."""
        _, exponent = reservoir_storage_curve(1000.0, 10.0, surface_area_km2=0.001)
        assert exponent >= 1.0


class TestLevelPoolRouting:
    """The router must conserve mass, resolve its peak, and hit its target."""

    def test_output_shape_and_span(self):
        times, discharge = level_pool_routing(
            initial_surface_elev_m=100.0,
            breach_bottom_elev_m=50.0,
            storage_mm3=500.0,
            dem_bounds=(0, 0, 1, 1),
            q_peak_m3_s=2000.0,
            failure_time_s=600.0,
            total_duration_s=3600.0,
            dt_s=10.0,
        )
        assert len(times) == len(discharge)
        assert times[0] == 0.0
        assert times[-1] == pytest.approx(3600.0)

    def test_discharge_finite_and_non_negative(self):
        _, discharge = level_pool_routing(
            100.0, 50.0, 500.0, (0, 0, 1, 1), 2000.0, 600.0, 3600.0
        )
        assert np.all(np.isfinite(discharge))
        assert np.all(discharge >= 0.0)

    @pytest.mark.blocking
    @pytest.mark.parametrize(
        "storage_mcm,exponent",
        [(500.0, 3.0), (3540.0, 3.0), (356.0, 6.8), (10.0, 2.0), (0.5, 2.0)],
    )
    def test_routed_volume_never_exceeds_storage(self, storage_mcm, exponent):
        """
        Mass conservation, measured on the fine grid that carries the state.

        This is the assertion the previous implementation claimed in its
        docstring ("the integral is bounded by the available storage") while
        never reading the storage argument at all. Here storage IS the state
        variable and is clipped at zero, so the bound is an identity.
        """
        coefficient, fitted_exponent = reservoir_storage_curve(
            storage_mcm, 50.0, None, exponent
        )
        times, discharge = _route_breach_fine(
            coefficient, fitted_exponent, 50.0, 50.0, 1.0, 600.0, 3600.0, 720
        )
        released_m3 = float(np.sum(discharge) * (times[1] - times[0]))

        assert released_m3 <= storage_mcm * MCM_TO_M3 * (1.0 + 1e-9), (
            f"released {released_m3 / MCM_TO_M3:.3f} MCM from a "
            f"{storage_mcm:.3f} MCM reservoir"
        )

    def test_peak_is_grid_independent(self):
        """
        Reported peak must not depend on the caller's dt_s.

        It did: internal integration was tied to the output grid, and a 100 s
        grid and a 141 s grid disagreed by 44% on this hydrograph because the
        peak is a cusp at full breach formation. Internal and output grids are
        now decoupled.
        """
        peaks = []
        for dt_s in (200.0, 141.0, 100.0, 50.0, 10.0):
            _, discharge = level_pool_routing(
                TETON_WATER_DEPTH_M,
                0.0,
                TETON_VOLUME_MCM,
                (0, 0, 1, 1),
                0.0,
                4692.6,
                28000.0,
                dt_s=dt_s,
                breach_width_m=272.15,
            )
            peaks.append(float(np.max(discharge)))

        spread = (max(peaks) - min(peaks)) / np.mean(peaks)
        assert spread < 0.02, f"peak varies {spread:.1%} across dt_s: {peaks}"

    @pytest.mark.parametrize("target", [500.0, 5000.0, 65120.0, 393289.0, 2.0e6])
    def test_inversion_hits_the_requested_peak(self, target):
        """
        With no breach width given, the router sizes the breach so the routed
        peak matches the regression peak.

        The knob scales bottom width and side slope together. Scaling width
        alone could not reach small targets: the trapezoidal side term
        1.4*z*H^2.5 is width-independent, so a zero-width breach with 1H:1V
        sides at 260 m head still passes 1.3e6 m^3/s, and every target below
        that silently returned the same floor.
        """
        _, discharge = level_pool_routing(
            TEHRI_HEIGHT_M,
            0.0,
            TEHRI_STORAGE_MCM,
            (0, 0, 1, 1),
            target,
            1620.0,
            10800.0,
            dt_s=10.8,
        )
        assert float(np.max(discharge)) == pytest.approx(target, rel=0.01)

    def test_storage_limited_target_undershoots_rather_than_inventing_water(self):
        """
        A peak the reservoir cannot supply must come back low, not high.

        0.5 MCM behind a 50 m dam cannot sustain 2000 m^3/s; the router
        returns the storage-limited maximum.
        """
        _, discharge = level_pool_routing(
            100.0, 50.0, 0.5, (0, 0, 1, 1), 2000.0, 600.0, 3600.0, dt_s=5.0,
            storage_exponent=2.0,
        )
        peak = float(np.max(discharge))
        assert peak < 2000.0
        assert peak > 1500.0

    def test_hydrograph_rises_then_falls(self):
        """Single-peaked: monotone up to the peak, monotone down after it."""
        _, discharge = level_pool_routing(
            TETON_WATER_DEPTH_M,
            0.0,
            TETON_VOLUME_MCM,
            (0, 0, 1, 1),
            0.0,
            4692.6,
            28000.0,
            dt_s=100.0,
            breach_width_m=272.15,
        )
        peak_index = int(np.argmax(discharge))

        assert discharge[0] == pytest.approx(0.0)
        assert np.all(np.diff(discharge[: peak_index + 1]) >= -1e-9)
        assert np.all(np.diff(discharge[peak_index:]) <= 1e-9)

    def test_empty_reservoir_gives_no_outflow(self):
        """Head at or below the invert: zeros, not a crash or a NaN."""
        _, no_head = level_pool_routing(
            50.0, 50.0, 500.0, (0, 0, 1, 1), 2000.0, 600.0, 3600.0
        )
        _, no_storage = level_pool_routing(
            100.0, 50.0, 0.0, (0, 0, 1, 1), 2000.0, 600.0, 3600.0
        )
        assert np.all(no_head == 0.0)
        assert np.all(no_storage == 0.0)

    def test_kernel_agrees_with_the_documented_weir_formula(self):
        """
        The weir law is written out twice — once in _breach_weir_discharge for
        documentation and testing, once inline in the JIT kernel where numba
        needs it. This guards that duplication.
        """
        for head, width, slope in [(1.0, 10.0, 1.0), (50.0, 272.0, 1.0), (86.9, 0.0, 0.5)]:
            reference = _breach_weir_discharge(head, width, slope)
            inline = 1.7 * width * head**1.5 + 1.4 * slope * head**2.5
            assert reference == pytest.approx(inline, rel=1e-12)

        assert _breach_weir_discharge(0.0, 100.0, 1.0) == 0.0
        assert _breach_weir_discharge(-5.0, 100.0, 1.0) == 0.0


class TestExtrapolationReporting:
    """Tehri is outside every calibration set; the module must say so."""

    def test_extrapolation_ratio(self):
        assert extrapolation_ratio(TEHRI_HEIGHT_M) == pytest.approx(
            TEHRI_HEIGHT_M / CALIBRATION_MAX_HEIGHT_M
        )
        assert extrapolation_ratio(TEHRI_HEIGHT_M) > 2.5
        assert extrapolation_ratio(50.0) < 1.0

    def test_tehri_peaks_are_of_the_right_order(self):
        """
        Teton (93 m, 356 MCM) peaked at 65,120 m^3/s. Tehri has 10x the volume
        and 2.8x the height, so Froehlich scales it by
        10^0.295 * 2.8^1.24 ~ 7.2x, giving several hundred thousand m^3/s.

        The previous tests asserted 500-20,000 m^3/s here, citing an unsourced
        "literature suggests 2000-8000". That is below Tehri's *spillway*
        design flood (~15,000 m^3/s) and two orders of magnitude below any
        published regression — it was the fabricated coefficients' output being
        used as the expectation.
        """
        froehlich, _, _ = froehlich_1995_peak_outflow(
            TEHRI_HEIGHT_M, 0.0, TEHRI_STORAGE_MCM, "central"
        )
        assert 1.0e5 < froehlich < 1.0e6
        assert froehlich > 5.0 * TETON_MEASURED_PEAK_M3_S

    def test_methods_diverge_more_at_tehri_than_at_teton(self):
        """
        Extrapolation should widen the inter-method spread. If it does not, the
        equations are not being extrapolated independently.
        """

        def spread(height_m, storage_mcm):
            values = [
                froehlich_1995_peak_outflow(height_m, 0.0, storage_mcm, "central")[0],
                macdonald_langridge_1984_peak_outflow(
                    height_m, storage_mcm, "embankment", "central"
                )[0],
                costa_1985_peak_outflow(height_m, storage_mcm, "central")[0],
                scs_1981_peak_outflow(height_m, "central")[0],
            ]
            return max(values) / min(values)

        assert spread(TEHRI_HEIGHT_M, TEHRI_STORAGE_MCM) > spread(
            TETON_WATER_DEPTH_M, TETON_VOLUME_MCM
        )


class TestRegressionMonotonicity:
    """Sanity properties every peak-outflow equation must satisfy."""

    @pytest.mark.parametrize(
        "method",
        [
            lambda h, s: froehlich_1995_peak_outflow(h, 0.0, s, "central")[0],
            lambda h, s: macdonald_langridge_1984_peak_outflow(
                h, s, "embankment", "central"
            )[0],
            lambda h, s: costa_1985_peak_outflow(h, s, "central")[0],
        ],
    )
    def test_increases_with_height(self, method):
        assert method(200.0, 1000.0) > method(100.0, 1000.0)

    def test_von_thun_increases_with_height_at_realistic_storage(self):
        """
        The routed VTG method is monotone along the physical locus where a
        taller dam impounds more water, which is the only locus it is ever
        evaluated on.

        It is NOT monotone in height at *fixed* storage — see
        test_von_thun_is_drain_limited_at_fixed_storage for why that is
        correct behaviour rather than a defect.
        """
        heights_and_storages = [
            (50.0, 50.0),
            (100.0, 300.0),
            (150.0, 900.0),
            (200.0, 2000.0),
            (260.0, 3540.0),
        ]
        peaks = [
            von_thun_gillette_1990_peak_outflow(h, s, "central")[0]
            for h, s in heights_and_storages
        ]
        assert peaks == sorted(peaks), f"not monotone along the physical locus: {peaks}"

    def test_von_thun_is_drain_limited_at_fixed_storage(self):
        """
        Holding storage fixed and raising the dam eventually *lowers* the
        routed peak, and that is physics, not a bug.

        VTG's breach grows over t_f = 0.020*h_w + 0.25 hours, so a taller dam
        takes longer to breach — but its head drives a far larger weir
        discharge. At 1000 MCM and 260 m the full-head weir would pass
        6.5e6 m^3/s, draining the reservoir in ~150 s against a 19,600 s
        formation time: the reservoir is empty long before the breach finishes
        opening, so the peak is set by the drain/formation race and falls with
        further height.

        This is exactly the behaviour a peak-outflow *regression* cannot
        express (they are monotone by construction) and is one reason the
        routed method is kept alongside them.
        """
        peaks = [
            von_thun_gillette_1990_peak_outflow(h, 1000.0, "central")[0]
            for h in (50.0, 100.0, 150.0, 200.0, 260.0)
        ]
        # Rises out of the formation-limited regime, then falls once draining
        # outpaces breach growth.
        assert peaks[1] > peaks[0]
        assert peaks[-1] < peaks[1]
        # And never exceeds what the reservoir holds divided by the formation
        # time by an implausible margin — the peak stays bounded.
        assert all(np.isfinite(peak) and peak > 0.0 for peak in peaks)

    @pytest.mark.parametrize(
        "method",
        [
            lambda h, s: froehlich_1995_peak_outflow(h, 0.0, s, "central")[0],
            lambda h, s: macdonald_langridge_1984_peak_outflow(
                h, s, "embankment", "central"
            )[0],
            lambda h, s: costa_1985_peak_outflow(h, s, "central")[0],
        ],
    )
    def test_increases_with_storage(self, method):
        assert method(100.0, 2000.0) > method(100.0, 500.0)

    def test_scs_ignores_storage_by_construction(self):
        """
        SCS (1981) is depth-only. It is in the module precisely as a check
        that the volume-dependent equations are not being driven by a
        mis-specified storage figure, so its storage-independence is a feature
        to pin, not an oversight.
        """
        assert (
            scs_1981_peak_outflow(100.0, "central")[0]
            == scs_1981_peak_outflow(100.0, "central")[0]
        )

    @pytest.mark.parametrize(
        "method",
        [
            lambda mode: froehlich_1995_peak_outflow(100.0, 0.0, 500.0, mode),
            lambda mode: macdonald_langridge_1984_peak_outflow(
                100.0, 500.0, "embankment", mode
            ),
            lambda mode: costa_1985_peak_outflow(100.0, 500.0, mode),
            lambda mode: scs_1981_peak_outflow(100.0, mode),
        ],
    )
    def test_uncertainty_modes_are_ordered(self, method):
        lower = method("lower")[0]
        central = method("central")[0]
        upper = method("upper")[0]
        assert 0.0 < lower < central < upper

    def test_bands_are_multiplicative_log_cycles(self):
        """
        Wahl (2004) expresses uncertainty in log10 cycles, so the band must be
        geometrically centred on the estimate, not arithmetically.
        """
        central, lower, upper = froehlich_1995_peak_outflow(
            100.0, 0.0, 500.0, "central"
        )
        assert np.sqrt(lower * upper) == pytest.approx(central, rel=1e-9)


class TestEnsembleGeneration:
    """Ensemble contract: shapes, metadata, and where the spread comes from."""

    CONFIG = {
        "name": "TestDam",
        "height_m": 100.0,
        "storage_mm3": 500.0,
        "dam_type": "embankment",
        "failure_mode": "overtopping",
        "breach_bottom_elev_m": 0.0,
        "initial_surface_elev_m": 100.0,
    }

    TEHRI_CONFIG = {
        "name": "Tehri",
        "height_m": TEHRI_HEIGHT_M,
        "storage_mm3": TEHRI_STORAGE_MCM,
        "dam_type": "embankment",
        "failure_mode": "overtopping",
        "breach_bottom_elev_m": 0.0,
        "initial_surface_elev_m": TEHRI_HEIGHT_M,
    }

    @pytest.mark.parametrize("num_samples", [10, 50])
    def test_ensemble_size(self, num_samples):
        ensemble = synthesize_breach_ensemble(
            self.CONFIG, num_samples=num_samples, random_seed=1
        )
        assert len(ensemble) == num_samples

    def test_members_well_formed(self):
        ensemble = synthesize_breach_ensemble(
            self.CONFIG, num_samples=12, random_seed=1
        )
        for member in ensemble:
            assert set(("t_array", "Q_t", "metadata")) <= set(member)
            assert len(member["t_array"]) == len(member["Q_t"])
            assert np.all(np.isfinite(member["Q_t"]))
            assert np.all(member["Q_t"] >= 0.0)

    def test_default_ensemble_draws_on_every_verified_family(self):
        """
        A single-family ensemble only samples Manning and peak noise, which
        understates the real uncertainty: the published equations disagree with
        each other by 3-4x and that inter-method spread dominates.
        """
        ensemble = synthesize_breach_ensemble(
            self.CONFIG, num_samples=len(DEFAULT_REGRESSION_FAMILIES) * 3,
            random_seed=1,
        )
        used = {member["metadata"]["regression"] for member in ensemble}
        assert len(used) == len(DEFAULT_REGRESSION_FAMILIES)

    def test_no_member_claims_a_nonexistent_regression(self):
        """
        The old default recorded "wahl_2004" as its method. Wahl (2004) is an
        uncertainty analysis, not a peak-outflow equation — there is nothing to
        cite under that name.
        """
        ensemble = synthesize_breach_ensemble(
            self.CONFIG, num_samples=20, random_seed=1
        )
        for member in ensemble:
            assert member["metadata"]["regression"] != "wahl_2004"
            # and no misspelled Froehlich, which the old code also emitted
            assert member["metadata"]["regression"] != "frohlich_1995"

    def test_metadata_carries_extrapolation_and_provenance(self):
        ensemble = synthesize_breach_ensemble(
            self.TEHRI_CONFIG, num_samples=8, random_seed=1
        )
        for member in ensemble:
            metadata = member["metadata"]
            assert metadata["extrapolation_ratio"] > 2.5
            assert "source_note" in metadata
            assert metadata["q_peak"] > 0.0
            # The routed peak and the raw regression peak are both reported.
            assert metadata["q_peak_regression_m3_s"] > 0.0

    def test_member_volume_bounded_by_storage(self):
        """Routed members inherit the router's mass bound."""
        ensemble = synthesize_breach_ensemble(
            self.CONFIG, num_samples=8, random_seed=1
        )
        for member in ensemble:
            if member["metadata"].get("fallback"):
                continue  # unrouted triangle, documented as unbounded
            released = float(np.trapezoid(member["Q_t"], member["t_array"]))
            assert released <= self.CONFIG["storage_mm3"] * MCM_TO_M3 * 1.01

    def test_reproducible_under_seed(self):
        first = synthesize_breach_ensemble(self.CONFIG, num_samples=6, random_seed=7)
        second = synthesize_breach_ensemble(self.CONFIG, num_samples=6, random_seed=7)
        for a, b in zip(first, second):
            np.testing.assert_allclose(a["Q_t"], b["Q_t"])

    def test_missing_required_config_raises(self):
        from jalraksha.hardening import HardeningError

        with pytest.raises(HardeningError):
            synthesize_breach_ensemble({"name": "NoNumbers"}, num_samples=2)


class TestEnsembleStatistics:
    """Statistics must be ordered, complete, and reflect the inter-method spread."""

    CONFIG = TestEnsembleGeneration.CONFIG

    def test_required_fields_present(self):
        stats = ensemble_statistics(
            synthesize_breach_ensemble(self.CONFIG, num_samples=20, random_seed=1)
        )
        for key in (
            "q_peak_median",
            "q_peak_mean",
            "q_peak_std",
            "q_peak_p05",
            "q_peak_p95",
            "t_fail_median",
            "t_fail_p05",
            "t_fail_p95",
            "num_samples",
            "regressions_used",
        ):
            assert key in stats

    def test_percentiles_ordered(self):
        stats = ensemble_statistics(
            synthesize_breach_ensemble(self.CONFIG, num_samples=30, random_seed=1)
        )
        assert stats["q_peak_p05"] < stats["q_peak_median"] < stats["q_peak_p95"]
        assert stats["t_fail_p05"] < stats["t_fail_median"] < stats["t_fail_p95"]

    def test_spread_reflects_inter_method_disagreement(self):
        """
        With four families in play the 5-95 spread should exceed what the 15%
        per-member peak noise alone could produce (~0.5 of the median).
        """
        stats = ensemble_statistics(
            synthesize_breach_ensemble(self.CONFIG, num_samples=80, random_seed=1)
        )
        spread = (stats["q_peak_p95"] - stats["q_peak_p05"]) / stats["q_peak_median"]
        assert spread > 0.5

    def test_empty_ensemble_returns_empty_dict(self):
        assert ensemble_statistics([]) == {}


# ─── Dam-class extrapolation ───────────────────────────────────────────────
# Every regression in the ensemble is an embankment fit. A masonry gravity dam
# fails by monolith sliding, not erosion, so the peak is a screening figure —
# and the existing height-based extrapolation_ratio cannot detect that.


class TestDamClassOutsideFittedPopulation:
    KHADAKWASLA = {
        "name": "Khadakwasla Dam", "height_m": 51.3, "storage_mm3": 33.5,
        "dam_type": "gravity", "failure_mode": "overtopping",
    }

    def test_gravity_dam_is_flagged(self):
        from jalraksha.terrain.breach import (
            ensemble_statistics, synthesize_breach_ensemble,
        )

        stats = ensemble_statistics(
            synthesize_breach_ensemble(self.KHADAKWASLA, num_samples=4, random_seed=1)
        )
        assert stats["dam_class_outside_fitted_population"] is True
        assert "EMBANKMENT" in stats["dam_class_note"]

    def test_embankment_dam_is_not_flagged(self):
        from jalraksha.terrain.breach import (
            ensemble_statistics, synthesize_breach_ensemble,
        )

        stats = ensemble_statistics(
            synthesize_breach_ensemble(
                {**self.KHADAKWASLA, "dam_type": "embankment"},
                num_samples=4, random_seed=1,
            )
        )
        assert stats["dam_class_outside_fitted_population"] is False
        assert stats["dam_class_note"] is None

    def test_flag_does_not_shift_the_central_estimate(self):
        """
        The flag must REPORT the problem, not silently correct for it. There is
        no published dam-type coefficient in Froehlich/MacDonald/Costa/Von Thun,
        so adjusting the peak here would be fabricating one. Same seed, same
        dam, different class => identical peak.
        """
        from jalraksha.terrain.breach import (
            ensemble_statistics, synthesize_breach_ensemble,
        )

        peaks = [
            ensemble_statistics(
                synthesize_breach_ensemble(
                    {**self.KHADAKWASLA, "dam_type": dam_type},
                    num_samples=4, random_seed=1,
                )
            )["q_peak_median"]
            for dam_type in ("gravity", "embankment")
        ]
        assert peaks[0] == pytest.approx(peaks[1])

    def test_height_extrapolation_alone_would_have_read_green(self):
        """
        The reason this flag exists at all. Khadakwasla is comfortably inside
        the regressions' fitted HEIGHT range, so extrapolation_ratio reports no
        problem while the dam is the wrong class entirely.
        """
        from jalraksha.terrain.breach import (
            dam_class_outside_fitted_population, extrapolation_ratio,
        )

        assert extrapolation_ratio(51.3) < 1.0
        assert dam_class_outside_fitted_population("gravity") is True
        assert dam_class_outside_fitted_population("masonry") is True
        assert dam_class_outside_fitted_population("embankment") is False


class TestHydrographWindow:
    """
    The routing window must follow the run, not a module literal.

    `_generate_single_hydrograph` pinned it at 10800 s with no override, and
    the solver injects from the array it returns — so a large reservoir could
    never be drained however long the caller asked the solver to run. Tehri
    released 51% of its 3,540 MCM at every duration on offer.
    """

    CFG = {
        "name": "Tehri Dam",
        "height_m": TEHRI_HEIGHT_M,
        "storage_mm3": TEHRI_STORAGE_MCM,
        "dam_type": "embankment",
        "failure_mode": "overtopping",
        # As services/api/jalraksha_service/schemas.py builds them.
        "breach_bottom_elev_m": TEHRI_HEIGHT_M * 0.1,
        "initial_surface_elev_m": TEHRI_HEIGHT_M,
    }

    @staticmethod
    def _released_mcm(hydrograph) -> float:
        return float(
            np.trapezoid(hydrograph["Q_t"], hydrograph["t_array"]) / 1.0e6
        )

    def test_default_window_is_unchanged_at_three_hours(self):
        """A run that asks for nothing must behave exactly as it did before."""
        member = synthesize_breach_ensemble(
            dict(self.CFG), num_samples=1, random_seed=7
        )[0]
        assert member["t_array"][-1] == pytest.approx(10800.0)

    def test_a_longer_window_actually_releases_more_water(self):
        """
        The defect in one assertion: same dam, same seed, longer window, and
        the volume that leaves the reservoir must increase. It did not before,
        because the window was a literal.
        """
        short = synthesize_breach_ensemble(
            dict(self.CFG), num_samples=4, random_seed=7
        )
        long = synthesize_breach_ensemble(
            {**self.CFG, "hydrograph_duration_s": 86400.0},
            num_samples=4, random_seed=7,
        )
        assert sum(map(self._released_mcm, long)) > sum(
            map(self._released_mcm, short)
        )

    def test_a_full_day_drains_the_reservoir(self):
        """
        Every ensemble member empties Tehri given 24 h.

        The window has to be this long because the four regression families
        disagree by ~4.8x on peak outflow: Von Thun's 452,000 m3/s empties the
        reservoir in about 6 h, while Costa's 95,000 m3/s needs the better part
        of a day. Both are in the published ensemble, so "time to empty" is
        itself a range and the slowest member sets this bound.
        """
        members = synthesize_breach_ensemble(
            {**self.CFG, "hydrograph_duration_s": 86400.0},
            num_samples=4, random_seed=7,
        )
        for member in members:
            released = self._released_mcm(member)
            assert released >= 0.99 * TEHRI_STORAGE_MCM, (
                f"{member['metadata']['method']} released only "
                f"{released:.0f} of {TEHRI_STORAGE_MCM} MCM"
            )

    def test_routed_volume_never_exceeds_the_storage(self):
        """
        A longer window must not invent water. The reservoir is the state
        variable in level_pool_routing, so the routed volume is bounded by it
        no matter how long the routing continues.
        """
        for member in synthesize_breach_ensemble(
            {**self.CFG, "hydrograph_duration_s": 172800.0},
            num_samples=4, random_seed=7,
        ):
            assert self._released_mcm(member) <= 1.01 * TEHRI_STORAGE_MCM

    def test_formation_time_does_not_stretch_with_the_window(self):
        """
        Breach FORMATION time is a property of the dam, not of how long we
        watch. It was `failure_time_frac * total_time`; had total_time become
        the window, an 8 h run would have eroded the embankment more slowly
        than a 3 h one and moved the peak, making the two different events.
        """
        short = synthesize_breach_ensemble(
            dict(self.CFG), num_samples=4, random_seed=7
        )
        long = synthesize_breach_ensemble(
            {**self.CFG, "hydrograph_duration_s": 28800.0},
            num_samples=4, random_seed=7,
        )
        for a, b in zip(short, long):
            assert a["metadata"]["failure_time_s"] == pytest.approx(
                b["metadata"]["failure_time_s"]
            )


class TestBreachFormationTime:
    """
    Breach formation time controls how ABRUPT the release is, and it was not
    settable: fixed at CRITICAL_FAILURE_FRAC of a hardcoded 3 h, ~27 min for
    every dam. That mattered because `failure_mode` — the field the API and the
    dashboard both present as the scenario selector — reaches only
    xu_zhang_2009_peak_outflow, which is not in DEFAULT_REGRESSION_FAMILIES. So
    "piping" and "overtopping" produced identical hydrographs.
    """

    CFG = {
        "name": "Tehri Dam",
        "height_m": TEHRI_HEIGHT_M,
        "storage_mm3": TEHRI_STORAGE_MCM,
        "dam_type": "embankment",
        "breach_bottom_elev_m": TEHRI_HEIGHT_M * 0.1,
        "initial_surface_elev_m": TEHRI_HEIGHT_M,
    }

    @staticmethod
    def _rise_time_s(hydrograph) -> float:
        """When the release reaches 90% of its peak — i.e. how sudden it is."""
        discharge = np.asarray(hydrograph["Q_t"])
        times = np.asarray(hydrograph["t_array"])
        return float(times[np.argmax(discharge >= 0.9 * discharge.max())])

    def test_failure_mode_alone_still_changes_nothing(self):
        """
        Documents the limitation rather than papering over it. If xu_zhang is
        ever verified and added to the defaults, this test fails and whoever
        does that will know the scenario selector has become live.
        """
        overtopping = synthesize_breach_ensemble(
            {**self.CFG, "failure_mode": "overtopping"}, num_samples=4, random_seed=7
        )
        piping = synthesize_breach_ensemble(
            {**self.CFG, "failure_mode": "piping"}, num_samples=4, random_seed=7
        )
        for a, b in zip(overtopping, piping):
            assert np.array_equal(a["Q_t"], b["Q_t"])

    def test_a_shorter_formation_time_gives_a_more_sudden_release(self):
        rapid = synthesize_breach_ensemble(
            {**self.CFG, "breach_formation_time_s": 600.0},
            num_samples=4, random_seed=7,
        )
        default = synthesize_breach_ensemble(
            dict(self.CFG), num_samples=4, random_seed=7
        )
        rapid_rise = np.mean([self._rise_time_s(h) for h in rapid])
        default_rise = np.mean([self._rise_time_s(h) for h in default])
        assert rapid_rise < 0.5 * default_rise

    def test_formation_time_is_honoured_as_the_ensemble_median(self):
        """The requested value is the median, with the lognormal spread kept."""
        members = synthesize_breach_ensemble(
            {**self.CFG, "breach_formation_time_s": 600.0},
            num_samples=24, random_seed=7,
        )
        median = float(np.median([m["metadata"]["failure_time_s"] for m in members]))
        assert median == pytest.approx(600.0, rel=0.25)

    def test_a_rapid_breach_is_flagged_as_an_assumption(self):
        """
        A pinned formation time is a stated scenario, not a derived result, and
        the exports have to be able to say which they are looking at.
        """
        assumed = synthesize_breach_ensemble(
            {**self.CFG, "breach_formation_time_s": 600.0},
            num_samples=2, random_seed=7,
        )
        derived = synthesize_breach_ensemble(
            dict(self.CFG), num_samples=2, random_seed=7
        )
        assert all(m["metadata"]["failure_time_assumed"] for m in assumed)
        assert not any(m["metadata"]["failure_time_assumed"] for m in derived)

    def test_the_released_volume_is_unchanged_by_how_fast_it_leaves(self):
        """
        A faster breach empties the same reservoir sooner; it must not empty a
        LARGER one. The storage is the state variable, so this is a check that
        the formation-time knob did not become a volume knob.
        """
        for formation_s in (600.0, 1620.0, 12636.0):
            members = synthesize_breach_ensemble(
                {**self.CFG, "breach_formation_time_s": formation_s,
                 "hydrograph_duration_s": 86400.0},
                num_samples=4, random_seed=7,
            )
            for member in members:
                released = float(
                    np.trapezoid(member["Q_t"], member["t_array"]) / 1.0e6
                )
                assert released <= 1.01 * TEHRI_STORAGE_MCM
