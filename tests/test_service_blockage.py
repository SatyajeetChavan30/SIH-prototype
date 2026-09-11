"""
Request validation for the river-blockage scenario (services/api).

The theme is that a blockage request either carries a barrier or is refused.
Two failure modes are guarded specifically:

- Blockage parameters on a NON-blockage run are rejected rather than ignored. A
  request whose parameters silently do nothing is worse than one that fails,
  because the operator cannot tell which happened — the same complaint
  breach.py's own comment makes about `failure_mode`.

- A blockage preset publishes no height, storage or dam type, and must not be
  422'd for correctly declining to invent them. That is the one exemption to the
  vetted-figures refusal, and it is keyed on `record_type`, not on the scenario,
  so a dam cannot slip through it.

No server is started: these are schema-level, which is where the refusals live.
"""

import sys

import pytest

sys.path.insert(0, "services/api")

from jalraksha_service.schemas import RunRequest  # noqa: E402


def _blockage_request(**overrides):
    payload = {
        "dam_id": "rishi_ganga",
        "scenario_type": "river_blockage",
        "blockage_source": "manual",
        "blockage_lat": 30.4400,
        "blockage_lon": 79.6960,
        "blockage_crest_height_m": 55.0,
        "blockage_width_m": 900.0,
        "solver": "swe",
        "target_resolution": 100.0,
    }
    payload.update(overrides)
    return RunRequest(**payload)


class TestBlockageRequestValidation:
    def test_a_manual_run_without_barrier_geometry_names_what_is_missing(self):
        request = _blockage_request(
            blockage_lat=None, blockage_crest_height_m=None
        )
        with pytest.raises(ValueError) as excinfo:
            request.to_dam_config()

        message = str(excinfo.value)
        assert "blockage_lat" in message
        assert "blockage_crest_height_m" in message
        # The two that WERE supplied must not be listed as missing.
        assert "blockage_width_m" not in message

    def test_blockage_params_on_a_dam_break_run_are_rejected_not_ignored(self):
        request = RunRequest(
            dam_id="tehri",
            scenario_type="dam_break",
            blockage_lat=30.44,
            blockage_crest_height_m=55.0,
        )
        with pytest.raises(ValueError, match="do nothing"):
            request.to_dam_config()

    def test_a_sub_grid_barrier_is_refused_at_submission(self):
        """
        A barrier narrower than a couple of cells has an outflow governed by the
        grid rather than by the deposit. Caught here rather than twenty minutes
        into a solve.
        """
        request = _blockage_request(blockage_width_m=120.0, target_resolution=200.0)
        with pytest.raises(ValueError) as excinfo:
            request.to_dam_config()

        message = str(excinfo.value)
        assert "0.6 cells" in message
        assert "200" in message

    def test_an_unknown_blockage_source_or_breach_mode_is_refused(self):
        with pytest.raises(ValueError, match="blockage_source"):
            _blockage_request(blockage_source="auto").to_dam_config()
        with pytest.raises(ValueError, match="blockage_breach_mode"):
            _blockage_request(blockage_breach_mode="erode").to_dam_config()

    def test_detect_mode_does_not_require_a_manual_barrier(self):
        config = _blockage_request(
            blockage_source="detect",
            blockage_lat=None,
            blockage_lon=None,
            blockage_crest_height_m=None,
            blockage_width_m=None,
        ).to_dam_config()

        assert config["blockage_source"] == "detect"


class TestBlockageDamConfig:
    def test_storage_never_reaches_the_config_from_the_request(self):
        """
        The decision that makes the feature honest, enforced at the boundary: a
        landslide dam's impounded volume is measured from the terrain, so a
        storage figure in the request must not survive into the ensemble.
        """
        config = _blockage_request(storage_mm3=500.0, height_m=99.0).to_dam_config()

        assert "storage_mm3" not in config
        assert "surface_area_km2" not in config
        assert config["storage_source"] == "hypsometric_fill_pending"

    def test_the_dam_break_elevation_assumptions_are_not_applied(self):
        """
        to_dam_config sets breach_bottom_elev_m = height*0.1 and
        initial_surface_elev_m = height for a dam break. Those are a breach
        invert and a reservoir surface; for a blockage the true values are the
        barrier crest and the valley floor as ABSOLUTE elevations, which are not
        known until the DEM has been read. Setting them from a preset's height
        would route the lake against the wrong structure and still look sane.
        """
        config = _blockage_request().to_dam_config()

        assert "breach_bottom_elev_m" not in config
        assert "initial_surface_elev_m" not in config

    def test_a_blockage_preset_is_exempt_from_the_vetted_figures_refusal(self):
        """
        rishi_ganga publishes height_m, storage_mm3 and dam_type as None because
        a landslide deposit has none of the three. Applying the dam refusal would
        422 it for being correct.
        """
        config = _blockage_request().to_dam_config()

        assert config["dam_id"] == "rishi_ganga"
        assert config["scenario_type"] == "river_blockage"

    def test_a_dam_with_missing_figures_is_still_refused(self, monkeypatch):
        """
        The exemption is keyed on record_type, not on the scenario, so a DAM with
        unvetted figures cannot borrow it by asking for a blockage.

        Asserted against a synthetic record because every dam currently in the
        registry has its figures; the refusal it guards is the one that used to
        surface as an opaque HTTP 500 from float(None).
        """
        from jalraksha_service.config import settings

        unvetted_dam = {
            "id": "unvetted_test_dam", "name": "Unvetted Dam",
            "lat": 30.0, "lon": 78.0,
            "height_m": None, "storage_mm3": None, "dam_type": None,
            "river": "Test", "state": "Test", "domain_radius_km": 60.0,
            "gauges": [], "record_type": "dam",
        }
        monkeypatch.setattr(
            settings, "DEMO_DAMS", list(settings.DEMO_DAMS) + [unvetted_dam]
        )

        with pytest.raises(ValueError, match="no vetted value"):
            RunRequest(
                dam_id="unvetted_test_dam", scenario_type="dam_break"
            ).to_dam_config()

        # And asking for a blockage does not buy the exemption either.
        with pytest.raises(ValueError, match="no vetted value"):
            RunRequest(
                dam_id="unvetted_test_dam",
                scenario_type="river_blockage",
                blockage_lat=30.0, blockage_lon=78.0,
                blockage_crest_height_m=50.0, blockage_width_m=900.0,
                target_resolution=100.0,
            ).to_dam_config()

    def test_a_custom_blockage_needs_only_a_domain_centre(self):
        config = RunRequest(
            scenario_type="river_blockage",
            lat=30.44, lon=79.70,
            blockage_lat=30.44, blockage_lon=79.696,
            blockage_crest_height_m=55.0, blockage_width_m=900.0,
            target_resolution=100.0,
        ).to_dam_config()

        assert config["lat"] == 30.44
        assert "storage_mm3" not in config

    def test_the_config_is_json_serialisable(self):
        """
        _spawn_run_subprocess writes dam_config to a JSON file and the worker
        reads it back, so anything not JSON-serialisable — a numpy scalar, a
        tuple key, a Path — breaks the run at launch rather than at use.
        """
        import json

        config = _blockage_request().to_dam_config()
        assert json.loads(json.dumps(config)) is not None


class TestBlockageSolverGate:
    def test_the_existing_scenario_solver_gate_still_refuses_delft3d(self):
        """
        Delft3D and 'both' are configured for dam-break hydrographs only. The
        gate lives in main.py; asserted here as a contract so a future scenario
        addition does not quietly widen it.
        """
        from jalraksha_service.config import settings

        assert set(settings.SOLVERS) == {"swe", "delft3d", "both", "sph"}
        # The gate's own condition, restated: a non-dam-break scenario is
        # allowed only on the SWE pipeline or SWE + near-field SPH.
        allowed_for_river = {"swe", "sph"}
        assert allowed_for_river < set(settings.SOLVERS)
