"""
The impact artifact: written, served, and never quietly complete.

`main.py` has read an export of kind "impact" since the endpoint was written,
and nothing ever produced one — so `RunResult.impact` was None for all 40 runs
in the shipped database. These tests pin the contract of the writer that now
fills it, and the three ways it is allowed to say nothing:

- no aggregated fields          -> None, no artifact, no export row
- exposure unavailable          -> a reason per sector and NO figure
- one sector missing            -> a NULL total, never a total short a sector

Nothing here touches the network. Earth Engine is forced unavailable, which is
also the state a demo machine is in.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "services" / "api"))

pytest.importorskip("jalraksha_service", reason="API service not importable")

from jalraksha.gee.auth import GEE_PROJECT_ENV, reset_gee_status  # noqa: E402

GRID = {"nx": 8, "ny": 6, "dx": 400.0, "dy": 400.0,
        "x0": 600000.0, "y0": 3350000.0, "crs": "EPSG:32644"}


@pytest.fixture
def offline(monkeypatch):
    """No Earth Engine, whatever the host is configured for."""
    monkeypatch.delenv(GEE_PROJECT_ENV, raising=False)
    reset_gee_status()
    yield
    reset_gee_status()


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    from jalraksha_service.config import settings
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path / "data", raising=False)
    return tmp_path / "data"


def _result(depth: float = 3.0):
    return {"grid": dict(GRID),
            "h_max_median": np.full((GRID["ny"], GRID["nx"]), depth)}


class TestRefusal:

    def test_no_aggregated_fields_yields_no_artifact(self, data_dir):
        from jalraksha_service.tasks import _damage_estimate, impact_exports

        assert _damage_estimate("r1", {"grid": dict(GRID)}, {}) is None
        assert _damage_estimate("r1", {"h_max_median": np.zeros((2, 2))}, {}) is None
        assert impact_exports("r1", {}, {}) == []
        assert not (data_dir / "exports" / "r1").exists()

    def test_unavailable_exposure_publishes_a_reason_and_no_figure(
            self, offline, data_dir):
        from jalraksha_service.tasks import _damage_estimate

        payload = _damage_estimate("r2", _result(), {"name": "Test Dam"})
        assert payload["available"] is False
        sectors = payload["damage"]["sectors"]
        assert set(sectors) == {"residential", "non_residential", "agricultural"}
        for name, block in sectors.items():
            assert block["available"] is False
            assert block["reason"]
            # The absence of a figure is the point: a zero here would read as
            # "no damage" rather than "not measured".
            assert "damage_crore_inr" not in block
        assert payload["damage"]["total_crore_inr"] is None
        assert sorted(payload["damage"]["missing_sectors"]) == [
            "agricultural", "non_residential", "residential"]

    def test_a_partial_payload_withholds_the_total(self, offline, data_dir,
                                                   monkeypatch):
        """
        Built-up available, cropland not. The buildings figure must survive —
        refusing the whole payload would suppress a good measurement — and the
        TOTAL must not, because a total silently missing agriculture reads as a
        complete one.
        """
        import jalraksha_service.tasks as tasks

        ny, nx = GRID["ny"], GRID["nx"]
        monkeypatch.setattr(
            "jalraksha.gee.built_up.fetch_built_up_on_grid",
            lambda **kwargs: {
                "built_surface_m2": np.full((ny, nx), 1000.0),
                "built_surface_nres_m2": np.full((ny, nx), 200.0),
                "built_surface_res_m2": np.full((ny, nx), 800.0),
                "nres_exceeded_total_cells": 0,
                "source": "GHSL_BUILT_S_P2023A", "collection": "c",
                "epoch": "2020", "aggregation": "a", "attribution": "attr",
            })

        payload = tasks._damage_estimate("r3", _result(), {"name": "Test Dam"})
        sectors = payload["damage"]["sectors"]

        assert payload["available"] is True
        assert sectors["residential"]["available"] is True
        assert sectors["residential"]["damage_crore_inr"] > 0.0
        assert sectors["non_residential"]["damage_crore_inr"] > 0.0
        assert sectors["agricultural"]["available"] is False
        assert payload["damage"]["missing_sectors"] == ["agricultural"]
        assert payload["damage"]["total_crore_inr"] is None


class TestArtifact:

    def test_the_written_file_round_trips_with_its_caveats(
            self, offline, data_dir, monkeypatch):
        """
        The label has to survive the whole path — writer, JSON, reader, schema.
        `RunResult.impact` is an untyped dict precisely so a pydantic model
        cannot silently drop `model_is_published` or the unit-cost echo.
        """
        import jalraksha_service.tasks as tasks
        from jalraksha_service.main import _read_export_json
        from jalraksha_service.schemas import RunResult

        ny, nx = GRID["ny"], GRID["nx"]
        monkeypatch.setattr(
            "jalraksha.gee.built_up.fetch_built_up_on_grid",
            lambda **kwargs: {
                "built_surface_m2": np.full((ny, nx), 1000.0),
                "built_surface_nres_m2": np.full((ny, nx), 200.0),
                "built_surface_res_m2": np.full((ny, nx), 800.0),
                "nres_exceeded_total_cells": 0,
                "source": "GHSL_BUILT_S_P2023A", "collection": "c",
                "epoch": "2020", "aggregation": "a", "attribution": "attr",
            })

        rows = tasks.impact_exports("r4", _result(), {"name": "Test Dam"})
        kinds = {row["kind"] for row in rows}
        assert "impact" in kinds

        path = Path(next(r["path_or_url"] for r in rows if r["kind"] == "impact"))
        assert path.exists()
        # Written with a plain json.dumps: an ndarray would have raised here.
        on_disk = json.loads(path.read_text(encoding="utf-8"))

        served = _read_export_json(rows, "impact", "r4")
        assert served == on_disk

        result = RunResult(run_id="r4", dam_name="Test Dam", exports=[],
                           gauges=[], impact=served)
        residential = result.impact["damage"]["sectors"]["residential"]
        assert residential["model_is_published"] is False
        assert residential["unit_cost_inr_per_m2"] > 0.0
        assert residential["unit_cost_price_year"] >= 1900
        assert "VERIFICATION_LOG.md" in result.impact["note"]

    def test_a_broken_builder_does_not_lose_the_run(self, data_dir, monkeypatch):
        """
        An impact artifact is not worth failing a solved run over — the compute
        is already spent and every other product is written.
        """
        import jalraksha_service.tasks as tasks

        def explode(*args, **kwargs):
            raise RuntimeError("exposure service on fire")

        monkeypatch.setattr(tasks, "_damage_estimate", explode)
        monkeypatch.setattr(tasks, "_population_at_risk", explode)
        assert tasks.impact_exports("r5", _result(), {}) == []
