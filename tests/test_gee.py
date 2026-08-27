"""
Phase 9 Google Earth Engine test suite.

WHAT CHANGED AND WHY. These tests used to assert only that the GEE modules
returned arrays of the right shape. They passed while the modules were
returning `np.random` output from a silent fallback, because shape is exactly
what a fabricated array gets right. The assertions here are about PROVENANCE
instead: that a live query is really attempted, that failure is reported rather
than papered over, and that synthetic data can only be produced when a caller
explicitly asks for it and is always labelled as such.

Nothing here touches the network by default. The live paths are marked and
skipped unless Earth Engine is genuinely configured, so the suite stays
runnable offline (CLAUDE.md).
"""

import os

import numpy as np
import pytest

from jalraksha.gee.auth import (
    GEE_PROJECT_ENV, gee_project, gee_status, init_gee, is_gee_available,
    reset_gee_status,
)
from jalraksha.gee.population import (
    PopulationUnavailableError, fetch_ghsl_population_grid,
    fetch_population_on_grid,
)
from jalraksha.gee.sar import (
    MIN_TILE_SEPARABILITY, SarUnavailableError, derive_threshold_from_tiles,
    latest_observed_extent, otsu_separability, otsu_threshold,
    process_sentinel1_sar_flood,
)

BBOX = (78.40, 30.30, 78.56, 30.46)   # Tehri reach — steep gorge

#: Hirakud on the Mahanadi: a large reservoir on a flat Odisha plain, and the
#: reach the live tests use. VV thresholding works here (measured precision 0.77
#: against JRC) and does NOT work over Tehri (0.01), which is a property of the
#: terrain rather than of the code — see test_steep_terrain_is_refused.
LIVE_BBOX = (83.77, 21.44, 83.97, 21.64)

GEE_LIVE, GEE_DETAIL = gee_status()
requires_live_gee = pytest.mark.skipif(
    not GEE_LIVE, reason=f"Earth Engine not configured: {GEE_DETAIL}")


@pytest.fixture
def no_gee(monkeypatch):
    """A process with no usable Earth Engine, whatever the host is configured for."""
    monkeypatch.delenv(GEE_PROJECT_ENV, raising=False)
    reset_gee_status()
    yield
    reset_gee_status()


# ─── TestGEEAuth ──────────────────────────────────────────────────────────────

class TestGEEAuth:
    """Availability must mean a session was established, not that `import ee` worked."""

    def test_status_returns_bool_and_reason(self):
        available, reason = gee_status()
        assert isinstance(available, bool)
        assert isinstance(reason, str) and reason, "a reason is always required"

    def test_unavailable_reason_is_actionable(self, no_gee):
        available, reason = gee_status()
        assert available is False
        # The reason has to name the thing to fix, not just say "unavailable".
        assert GEE_PROJECT_ENV in reason

    def test_missing_project_is_not_reported_as_available(self, no_gee):
        """
        The regression this whole rewrite exists for.

        The old is_gee_available() returned True whenever `earthengine-api` was
        importable, without initializing anything. Callers took their live
        branch, failed inside, and returned synthetic data labelled offline.
        """
        assert gee_project() == ""
        assert is_gee_available() is False

    def test_init_gee_offline_fallback(self, no_gee):
        success, msg = init_gee(offline_fallback=True)
        assert success is False
        assert isinstance(msg, str) and msg

    def test_init_gee_raises_without_fallback(self, no_gee):
        with pytest.raises(RuntimeError):
            init_gee(offline_fallback=False)

    def test_status_is_cached_until_reset(self, no_gee):
        first = gee_status()
        assert gee_status() == first
        reset_gee_status()
        assert gee_status() == first  # same answer, freshly computed


# ─── TestOtsuThreshold ────────────────────────────────────────────────────────

class TestOtsuThreshold:
    """
    The water/land split is derived per scene, so there is no dB constant to vet.

    Otsu (1979) maximises between-class variance. These check it against a
    known bimodal distribution and against a brute-force search over every
    possible split.
    """

    def _bimodal(self):
        centres = np.linspace(-30.0, 0.0, 256)
        water = 4000 * np.exp(-0.5 * ((centres + 22.0) / 1.5) ** 2)
        land = 9000 * np.exp(-0.5 * ((centres + 8.0) / 2.5) ** 2)
        return water + land, centres

    def test_threshold_falls_between_the_modes(self):
        counts, centres = self._bimodal()
        threshold = otsu_threshold(counts, centres)
        assert -22.0 < threshold < -8.0

    def test_matches_brute_force_search(self):
        counts, centres = self._bimodal()
        best, best_variance = None, -np.inf
        for split in range(1, len(centres)):
            w0, w1 = counts[:split].sum(), counts[split:].sum()
            if w0 == 0 or w1 == 0:
                continue
            m0 = (counts[:split] * centres[:split]).sum() / w0
            m1 = (counts[split:] * centres[split:]).sum() / w1
            variance = w0 * w1 * (m0 - m1) ** 2
            if variance > best_variance:
                best_variance, best = variance, centres[split - 1]
        assert otsu_threshold(counts, centres) == pytest.approx(best)

    def test_separability_distinguishes_bimodal_from_unimodal(self):
        """
        The measure that decides whether an Otsu split means anything.

        Otsu always returns a threshold. Separability says whether the two sides
        are two populations or one arbitrarily bisected — which is what stops a
        unimodal mountain-terrain histogram from producing a confident,
        meaningless water mask.
        """
        counts, centres = self._bimodal()
        bimodal_eta = otsu_separability(counts, centres, otsu_threshold(counts, centres))

        unimodal = 12000 * np.exp(-0.5 * ((centres + 10.0) / 5.0) ** 2)
        unimodal_eta = otsu_separability(
            unimodal, centres, otsu_threshold(unimodal, centres))

        assert bimodal_eta > MIN_TILE_SEPARABILITY > unimodal_eta

    def test_empty_histogram_raises(self):
        with pytest.raises(ValueError, match="empty"):
            otsu_threshold(np.zeros(16), np.linspace(-30, 0, 16))

    def test_single_valued_histogram_raises(self):
        counts = np.zeros(8)
        counts[3] = 100.0
        with pytest.raises(ValueError, match="single-valued"):
            otsu_threshold(counts, np.linspace(-30, 0, 8))


class TestSplitBasedThreshold:
    """
    The threshold comes only from sub-tiles that are genuinely bimodal.

    Measured over Tehri, the WHOLE-SCENE histogram is unimodal and Otsu cut
    through the middle of the land mode at -10.1 dB, calling 45% of a mountain
    valley water. Tiles are how the method finds the parts of a scene where a
    water/land split actually exists (Martinis et al. 2009; Chini et al. 2017).
    """

    def _tiles(self, n_bimodal, n_unimodal):
        centres = np.linspace(-30.0, 0.0, 256)
        bimodal = (4000 * np.exp(-0.5 * ((centres + 22.0) / 1.5) ** 2)
                   + 9000 * np.exp(-0.5 * ((centres + 8.0) / 2.5) ** 2))
        unimodal = 12000 * np.exp(-0.5 * ((centres + 10.0) / 5.0) ** 2)
        return ([(bimodal, centres)] * n_bimodal
                + [(unimodal, centres)] * n_unimodal)

    def test_uses_only_the_bimodal_tiles(self):
        result = derive_threshold_from_tiles(self._tiles(2, 6))
        assert result["n_tiles_used"] == 2
        assert result["n_tiles_total"] == 8
        assert -22.0 < result["threshold_db"] < -8.0

    def test_refuses_when_no_tile_is_bimodal(self):
        """
        The Tehri case. Refusing is the correct answer, not a failure to try.
        """
        with pytest.raises(ValueError, match="bimodal enough"):
            derive_threshold_from_tiles(self._tiles(0, 8))

    def test_ignores_tiles_with_too_few_pixels(self):
        centres = np.linspace(-30.0, 0.0, 256)
        sparse = np.zeros_like(centres)
        sparse[10] = 3.0
        with pytest.raises(ValueError, match="bimodal enough"):
            derive_threshold_from_tiles([(sparse, centres)] * 4)


# ─── TestSARProvenance ────────────────────────────────────────────────────────

class TestSARProvenance:
    """No observation is better than a fabricated one."""

    def test_no_gee_and_no_cache_raises(self, no_gee, tmp_path):
        with pytest.raises(SarUnavailableError) as excinfo:
            latest_observed_extent("tehri", BBOX, tmp_path)
        assert "No synthetic substitute" in str(excinfo.value)

    def test_change_detection_refuses_without_gee(self, no_gee):
        with pytest.raises(SarUnavailableError):
            process_sentinel1_sar_flood(BBOX, grid_shape=(20, 20))

    def test_synthetic_must_be_asked_for_and_is_labelled(self, no_gee):
        result = process_sentinel1_sar_flood(
            BBOX, grid_shape=(20, 20), allow_synthetic=True)
        assert result["water_mask"].shape == (20, 20)
        assert result["water_mask"].dtype == bool
        # The label must make the nature of the data unmistakable to anything
        # that reads it, including a careless caller.
        assert "SYNTHETIC" in result["source"]
        assert "observed" not in result["source"].lower().replace("not_observed", "")

    def test_synthetic_thresholding_is_self_consistent(self, no_gee):
        result = process_sentinel1_sar_flood(
            BBOX, threshold_db=-3.0, grid_shape=(20, 20), allow_synthetic=True)
        assert np.all(result["water_mask"] == (result["backscatter_delta_db"] <= -3.0))

    @requires_live_gee
    @pytest.mark.slow
    def test_live_scene_has_real_provenance(self, tmp_path):
        observed = latest_observed_extent("hirakud", LIVE_BBOX, tmp_path)
        assert observed["source"] == "sentinel1_grd"
        assert observed["scene_id"]
        assert observed["acquired_at"].startswith("20")
        assert observed["threshold_method"] == "otsu_split_based"
        assert -40.0 < observed["threshold_db"] < 5.0
        assert os.path.exists(observed["geotiff_path"])
        # A published mask has been measured against JRC Global Surface Water.
        assert observed["precision_vs_jrc"] >= 0.5

    @requires_live_gee
    @pytest.mark.slow
    def test_cache_serves_when_live_is_unavailable(self, tmp_path, monkeypatch):
        """A fetched scene stays usable offline, labelled as cached."""
        latest_observed_extent("hirakud", LIVE_BBOX, tmp_path)

        import jalraksha.gee.sar as sar_module
        monkeypatch.setattr(sar_module, "gee_status",
                            lambda: (False, "simulated outage"))
        cached = latest_observed_extent("hirakud", LIVE_BBOX, tmp_path)
        assert cached["source"] == "cached"
        assert cached["scene_id"]          # still the real scene
        assert "simulated outage" in cached["reason"]


    @requires_live_gee
    @pytest.mark.slow
    def test_steep_terrain_is_refused(self, tmp_path):
        """
        Over the Tehri gorge, VV thresholding must produce NO mask.

        This is the single most important behaviour in this module, and it is a
        real measurement rather than a guess: the derived mask reaches recall
        ~0.94 against JRC permanent water but precision ~0.01-0.03, because
        radar shadow on a Himalayan hillside is as dark in VV as a reservoir.
        The mask it would publish covers half a mountain valley and looks
        entirely credible. Refusing is the correct output.
        """
        with pytest.raises(SarUnavailableError) as excinfo:
            latest_observed_extent("tehri", BBOX, tmp_path)
        message = str(excinfo.value)
        assert "precision" in message
        assert "No mask is produced" in message


# ─── TestPopulationProvenance ─────────────────────────────────────────────────

class TestPopulationProvenance:
    """A fabricated headcount behind a 'people at risk' figure is the worst case."""

    def test_refuses_without_gee(self, no_gee):
        with pytest.raises(PopulationUnavailableError):
            fetch_ghsl_population_grid(BBOX, grid_shape=(40, 40))

    def test_grid_aligned_fetch_refuses_without_gee_or_cache(self, no_gee, tmp_path):
        grid = {"nx": 10, "ny": 8, "dx": 400.0, "dy": 400.0,
                "x0": 600000.0, "y0": 3350000.0}
        with pytest.raises(PopulationUnavailableError) as excinfo:
            fetch_population_on_grid(grid, 32644, tmp_path)
        assert "No synthetic population is substituted" in str(excinfo.value)

    def test_synthetic_must_be_asked_for_and_is_labelled(self, no_gee):
        result = fetch_ghsl_population_grid(
            BBOX, grid_shape=(40, 40), allow_synthetic=True)
        assert result["population_grid"].shape == (40, 40)
        assert result["total_population"] > 0.0
        assert np.all(result["population_grid"] >= 0.0)
        assert "SYNTHETIC" in result["source"]
        assert "census" not in result["source"].replace("not_census_derived", "")


# ─── TestPopulationAtRisk ─────────────────────────────────────────────────────

class TestPopulationAtRisk:
    """The impact figures the GHSL grid feeds."""

    def test_estimator_refuses_to_invent_settlements(self):
        from jalraksha.impact.population import PopulationEstimator

        depth = np.zeros((20, 20))
        depth[5:15, 5:15] = 2.0
        with pytest.raises(ValueError, match="describes nobody"):
            PopulationEstimator().estimate_population(depth)

    def test_estimator_labels_an_explicitly_synthetic_layout(self):
        from jalraksha.impact.population import PopulationEstimator

        depth = np.zeros((20, 20))
        depth[5:15, 5:15] = 2.0
        result = PopulationEstimator().estimate_population(
            depth, allow_synthetic_settlements=True, cell_size_m=400.0)
        assert result["settlement_source"] == "SYNTHETIC_random_layout"
        assert result["cell_size_m"] == 400.0

    def test_zero_affected_population_is_not_an_error(self):
        """
        A flood over empty ground is a real outcome, not a crash.

        _calculate_vulnerability_index divided by the affected total unguarded
        and raised ZeroDivisionError for exactly this case.
        """
        from jalraksha.impact.population import PopulationEstimator

        result = PopulationEstimator().estimate_population(
            np.zeros((20, 20)), allow_synthetic_settlements=True)
        assert result["population_affected"] == 0
        assert result["vulnerability_index"] == 0.0

    def test_par_counts_real_people_from_a_real_grid(self):
        from jalraksha.impact.population import compute_par

        population = np.full((20, 20), 50.0)
        arrival = np.full((20, 20), np.inf)
        arrival[5:15, 5:15] = 600.0          # 10 minutes
        depth = np.zeros((20, 20))
        depth[5:15, 5:15] = 2.0

        par = compute_par(population, arrival, warning_lead_time_s=0.0,
                          h_max_grid=depth)
        # 100 flooded cells x 50 people, all inside the 15-minute bucket.
        assert par["total_par"] == pytest.approx(5000.0)
        assert par["par_high_urgency_under_15min"] == pytest.approx(5000.0)

    def test_dry_domain_puts_nobody_at_risk(self):
        from jalraksha.impact.population import compute_par

        par = compute_par(np.full((10, 10), 100.0),
                          np.full((10, 10), np.inf),
                          warning_lead_time_s=0.0,
                          h_max_grid=np.zeros((10, 10)))
        assert par["total_par"] == 0.0
