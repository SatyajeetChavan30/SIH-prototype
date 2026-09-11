"""
Phase 11 Hardening Test Suite.

Tests:
  - TestDamConfigValidation: required fields, range checks, failure mode
  - TestEnsembleParams: ensemble/solver/resolution bounds
  - TestDemPath: path existence, extension checks
  - TestOutputDir: creation, write-access
  - TestForbiddenSources: geo-fenced source detection
  - TestSafeRun: exception wrapping
"""

import os
import pytest
import tempfile

from jalraksha.hardening import (
    HardeningError,
    validate_dam_config,
    validate_ensemble_params,
    validate_dem_path,
    validate_output_dir,
    safe_run,
    check_forbidden_sources,
)


# ─── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def valid_config():
    return {
        "name": "Tehri",
        "lat": 30.3789,
        "lon": 78.4789,
        "height_m": 260.0,
        "storage_mm3": 3540.0,
        "dam_type": "embankment",
        "failure_mode": "overtopping",
    }


# ─── TestDamConfigValidation ──────────────────────────────────────────────────

class TestDamConfigValidation:
    def test_valid_config_passes(self, valid_config):
        """Valid Tehri config must pass without exception."""
        validate_dam_config(valid_config)  # Should not raise

    def test_missing_name_raises(self, valid_config):
        del valid_config["name"]
        with pytest.raises(HardeningError, match="Missing required dam config key"):
            validate_dam_config(valid_config)

    def test_empty_name_raises(self, valid_config):
        valid_config["name"] = "   "
        with pytest.raises(HardeningError, match="non-empty string"):
            validate_dam_config(valid_config)

    def test_lat_out_of_range_raises(self, valid_config):
        valid_config["lat"] = 91.0
        with pytest.raises(HardeningError, match="latitude"):
            validate_dam_config(valid_config)

    def test_lon_out_of_range_raises(self, valid_config):
        valid_config["lon"] = -181.0
        with pytest.raises(HardeningError, match="longitude"):
            validate_dam_config(valid_config)

    def test_height_too_small_raises(self, valid_config):
        valid_config["height_m"] = 5.0
        with pytest.raises(HardeningError, match="height"):
            validate_dam_config(valid_config)

    def test_height_too_large_raises(self, valid_config):
        valid_config["height_m"] = 500.0
        with pytest.raises(HardeningError, match="height"):
            validate_dam_config(valid_config)

    def test_invalid_failure_mode_raises(self, valid_config):
        valid_config["failure_mode"] = "magic"
        with pytest.raises(HardeningError, match="failure_mode"):
            validate_dam_config(valid_config)

    def test_invalid_dam_type_raises(self, valid_config):
        valid_config["dam_type"] = "bamboo"
        with pytest.raises(HardeningError, match="dam_type"):
            validate_dam_config(valid_config)

    def test_all_failure_modes_valid(self, valid_config):
        for mode in ["overtopping", "piping", "seismic", "foundation", "other"]:
            valid_config["failure_mode"] = mode
            validate_dam_config(valid_config)  # Should not raise


# ─── TestEnsembleParams ───────────────────────────────────────────────────────

class TestEnsembleParams:
    def test_valid_params_pass(self):
        validate_ensemble_params(100, 10800.0, 200.0)  # Should not raise

    def test_zero_ensemble_raises(self):
        with pytest.raises(HardeningError, match="ensemble_size"):
            validate_ensemble_params(0, 10800.0, 200.0)

    def test_negative_duration_raises(self):
        with pytest.raises(HardeningError, match="solver_duration"):
            validate_ensemble_params(10, -1.0, 200.0)

    def test_negative_resolution_raises(self):
        with pytest.raises(HardeningError, match="target_resolution"):
            validate_ensemble_params(10, 3600.0, -50.0)

    def test_zero_resolution_raises(self):
        with pytest.raises(HardeningError, match="target_resolution"):
            validate_ensemble_params(10, 3600.0, 0.0)


# ─── TestDemPath ──────────────────────────────────────────────────────────────

class TestDemPath:
    def test_none_path_passes(self):
        validate_dem_path(None)  # Offline/synthetic mode — always valid

    def test_nonexistent_path_raises(self):
        with pytest.raises(HardeningError, match="not found"):
            validate_dem_path("/nonexistent/path/dem.tif")

    def test_wrong_extension_raises(self, tmp_path):
        bad_file = tmp_path / "dem.csv"
        bad_file.write_text("fake")
        with pytest.raises(HardeningError, match="recognised raster extension"):
            validate_dem_path(str(bad_file))

    def test_valid_tif_path_passes(self, tmp_path):
        tif_file = tmp_path / "dem.tif"
        tif_file.write_bytes(b"\x00" * 16)  # Dummy content
        validate_dem_path(str(tif_file))  # Should not raise (only checks extension+existence)


# ─── TestOutputDir ────────────────────────────────────────────────────────────

class TestOutputDir:
    def test_creates_missing_dir(self, tmp_path):
        new_dir = str(tmp_path / "results" / "nested")
        result = validate_output_dir(new_dir)
        assert os.path.isdir(result)

    def test_returns_absolute_path(self, tmp_path):
        result = validate_output_dir(str(tmp_path))
        assert os.path.isabs(result)


# ─── TestForbiddenSources ─────────────────────────────────────────────────────

class TestForbiddenSources:
    def test_clean_string_returns_empty(self):
        assert check_forbidden_sources("copernicus dem from aws") == []

    def test_india_wris_flagged(self):
        found = check_forbidden_sources("https://india-wris.nrsc.gov.in/api/dem")
        assert "india-wris" in found

    def test_bhuvan_flagged(self):
        found = check_forbidden_sources("fetch data from bhuvan portal")
        assert "bhuvan" in found

    def test_mullaperiyar_flagged(self):
        found = check_forbidden_sources("simulate Mullaperiyar dam break")
        assert "mullaperiyar" in found

    def test_multiple_forbidden_flagged(self):
        text = "Using bhuvan and cartodem for DEM data"
        found = check_forbidden_sources(text)
        assert "bhuvan" in found
        assert "cartodem" in found


# ─── TestSafeRun ─────────────────────────────────────────────────────────────

class TestSafeRun:
    def test_successful_call_returns_value(self):
        result = safe_run(lambda x: x * 2, 21, context="double")
        assert result == 42

    def test_memory_error_becomes_hardening_error(self):
        def raise_oom():
            raise MemoryError("out of memory")
        with pytest.raises(HardeningError, match="Out of memory"):
            safe_run(raise_oom, context="test")

    def test_unexpected_exception_becomes_hardening_error(self):
        def raise_runtime():
            raise RuntimeError("boom")
        with pytest.raises(HardeningError, match="Unexpected error"):
            safe_run(raise_runtime, context="test_ctx")

    def test_hardening_error_not_double_wrapped(self):
        def raise_hardening():
            raise HardeningError("original message")
        with pytest.raises(HardeningError, match="original message"):
            safe_run(raise_hardening, context="test")
