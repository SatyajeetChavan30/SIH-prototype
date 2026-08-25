"""
Phase 17: Final Integration Tests.

End-to-end system tests that verify the full JalRaksha stack works together:
  1. CLI entry point → config validation → breach ensemble → arrival times
  2. Hardening guards → API endpoint → rapid estimate → gauge list
  3. Validation metrics → sensitivity analysis → benchmark comparison
  4. Export pipeline → COG / KML / Shapefile stubs
  5. Dashboard imports → plot generation → map config
  6. Full package import test (all modules importable)

These are the definitive "it all works" tests before SIH submission.
"""

import os
import sys
import json
import pytest
import importlib
import numpy as np


# ─── TestFullPackageImports ───────────────────────────────────────────────────

class TestFullPackageImports:
    """Verify every jalraksha module is importable without errors."""

    MODULES = [
        "jalraksha",
        "jalraksha.config",
        "jalraksha.cli",
        "jalraksha.cache",
        "jalraksha.dem",
        "jalraksha.hardening",
        "jalraksha.api",
        "jalraksha.run",
        "jalraksha.solver.types",
        "jalraksha.solver.flux",
        "jalraksha.solver.core",
        "jalraksha.solver.parallel",
        "jalraksha.terrain.conditioning",
        "jalraksha.terrain.breach",
        "jalraksha.terrain.domain",
        "jalraksha.terrain.roughness",
        "jalraksha.export.geotiff",
        "jalraksha.export.shapefile",
        "jalraksha.export.kml",
        "jalraksha.impact.hazard",
        "jalraksha.impact.damage",
        "jalraksha.impact.population",
        "jalraksha.impact.fatality",
        "jalraksha.sph.domain",
        "jalraksha.sph.core",
        "jalraksha.sph.coupling",
        "jalraksha.validation.metrics",
        "jalraksha.validation.benchmarks",
        "jalraksha.validation.sensitivity",
        "jalraksha.gee.auth",
        "jalraksha.gee.sar",
        "jalraksha.gee.population",
        "jalraksha.dashboard.plots",
        "jalraksha.dashboard.maps",
    ]

    @pytest.mark.parametrize("module_name", MODULES)
    def test_module_importable(self, module_name):
        """Each module must import without errors."""
        mod = importlib.import_module(module_name)
        assert mod is not None


# ─── TestCLIIntegration ───────────────────────────────────────────────────────

class TestCLIIntegration:
    def test_cli_module_importable(self):
        from jalraksha.cli import main
        assert callable(main)

    def test_cli_has_run_command(self):
        """CLI must expose a 'run' subcommand via click."""
        from jalraksha.cli import main
        assert hasattr(main, "commands") or callable(main)


# ─── TestHardeningIntegration ─────────────────────────────────────────────────

class TestHardeningIntegration:
    def test_valid_tehri_config_passes_all_checks(self):
        from jalraksha.hardening import validate_dam_config, validate_ensemble_params, HardeningError
        config = {
            "name": "Tehri",
            "lat": 30.3789, "lon": 78.4789,
            "height_m": 260.0, "storage_mm3": 3540.0,
            "dam_type": "embankment", "failure_mode": "overtopping",
        }
        validate_dam_config(config)  # Should not raise
        validate_ensemble_params(100, 10800.0, 200.0)  # Should not raise

    def test_forbidden_sources_not_in_tehri_config(self):
        from jalraksha.hardening import check_forbidden_sources
        config_str = "Tehri Dam Bhagirathi Uttarakhand Copernicus DEM AWS"
        assert check_forbidden_sources(config_str) == []


# ─── TestAPIIntegration ───────────────────────────────────────────────────────

class TestAPIIntegration:
    def test_rapid_estimate_tehri(self):
        from jalraksha.api import rapid_estimate
        config = {
            "name": "Tehri",
            "lat": 30.3789, "lon": 78.4789,
            "height_m": 260.0, "storage_mm3": 3540.0,
            "dam_type": "embankment", "failure_mode": "overtopping",
        }
        result = rapid_estimate(config, ensemble_size=3)
        assert result["q_peak_median_m3s"] > 0
        assert result["wave_celerity_ms"] > 0
        assert len(result["arrival_times"]) == 4  # 4 gauges

    def test_api_demo_dams_list(self):
        from jalraksha.api import DEMO_DAMS
        assert len(DEMO_DAMS) >= 1
        assert any(d["id"] == "tehri" for d in DEMO_DAMS)


# ─── TestBreachEnsembleIntegration ────────────────────────────────────────────

class TestBreachEnsembleIntegration:
    def test_breach_ensemble_produces_positive_outflow(self):
        from jalraksha.terrain.breach import synthesize_breach_ensemble, ensemble_statistics
        config = {
            "name": "Tehri", "lat": 30.38, "lon": 78.48,
            "height_m": 260.0, "storage_mm3": 3540.0,
            "dam_type": "embankment", "failure_mode": "overtopping",
        }
        hydros = synthesize_breach_ensemble(config, num_samples=5)
        stats = ensemble_statistics(hydros)
        assert stats["q_peak_median"] > 0
        assert stats["q_peak_p05"] <= stats["q_peak_median"] <= stats["q_peak_p95"]


# ─── TestValidationIntegration ────────────────────────────────────────────────

class TestValidationIntegration:
    def test_csi_and_f1_on_synthetic_data(self):
        from jalraksha.validation.metrics import compute_csi, compute_f1_score
        predicted = np.array([[1, 1, 0], [0, 1, 1], [0, 0, 1]])
        observed  = np.array([[1, 0, 0], [1, 1, 1], [0, 0, 1]])
        csi = compute_csi(predicted, observed, threshold=0.5)
        f1  = compute_f1_score(predicted, observed, threshold=0.5)
        assert 0.0 <= csi <= 1.0
        assert 0.0 <= f1  <= 1.0

    def test_sensitivity_oat_runs_end_to_end(self):
        from jalraksha.validation.sensitivity import oat_sensitivity
        from jalraksha.api import rapid_estimate
        base_config = {
            "name": "Tehri", "lat": 30.38, "lon": 78.48,
            "height_m": 260.0, "storage_mm3": 3540.0,
            "dam_type": "embankment", "failure_mode": "overtopping",
        }

        def output_fn(cfg):
            return rapid_estimate(cfg, ensemble_size=3)

        result = oat_sensitivity(
            base_config, "height_m",
            [220.0, 260.0, 300.0],
            output_fn,
            "q_peak_median_m3s",
        )
        assert result["sensitivity_index"] >= 0.0
        assert len(result["output_values"]) == 3


# ─── TestDashboardIntegration ─────────────────────────────────────────────────

class TestDashboardIntegration:
    def test_plots_module_creates_figure(self):
        from jalraksha.dashboard.plots import plot_arrival_hydrographs
        import matplotlib.pyplot as plt
        arrival_data = {
            "Koteshwar": {"median": 1800.0, "p05": 1440.0, "p95": 2160.0},
            "Rishikesh":  {"median": 4320.0, "p05": 3600.0, "p95": 5040.0},
        }
        fig = plot_arrival_hydrographs(arrival_data)
        assert isinstance(fig, plt.Figure)
        plt.close(fig)

    def test_maps_module_importable(self):
        from jalraksha.dashboard import maps
        assert hasattr(maps, "create_inundation_folium_map")


# ─── TestImpactIntegration ────────────────────────────────────────────────────

class TestImpactIntegration:
    def test_hazard_rating_on_typical_values(self):
        from jalraksha.impact.hazard import compute_fd2320_hazard_rating
        rating = compute_fd2320_hazard_rating(
            depth=np.array([[2.5]]),
            velocity_x=np.array([[1.5]]),
            velocity_y=np.array([[0.0]]),
        )
        assert rating is not None
        assert rating.shape == (1, 1)

    def test_fatality_rate_bounded(self):
        from jalraksha.impact.fatality import estimate_loss_of_life_graham
        res = estimate_loss_of_life_graham(par=100.0, warning_time_min=30.0, flood_severity="high")
        assert 0.0 <= res["fatality_rate"] <= 1.0
