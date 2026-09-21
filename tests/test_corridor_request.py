"""
Corridor conditioning is reachable from the dashboard, and off by default.

`run.py` has accepted `condition_corridor_m` since it was built, but nothing on
the API path passed it — so the flagship drainage run, the one that reaches zero
severe cells, could be produced only by a script. A demo run submitted from the
dashboard could not reproduce it.

Two properties matter and neither is cosmetic:

- **Default 0 is OFF**, so a run submitted without it is what it always was.
  `test_no_mask_is_byte_identical_to_before` pins the terrain side of that;
  this pins the request side.
- **Above 0 it is MODIFIED TERRAIN**, and the pipeline labels it. Nothing here
  invents that labelling; it checks the value travels to the code that does.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "services" / "api"))

pytest.importorskip("jalraksha_service", reason="API service not importable")


@pytest.fixture
def submitted(monkeypatch):
    """submit_run with its dispatch stubbed, capturing the dam_config it built."""
    from jalraksha_service import main
    from jalraksha_service.worker import celery_app

    captured = {}

    def fake_create_run(dam_id, params, solver):
        captured["params"] = params
        return "run-0"

    monkeypatch.setattr(main.db, "create_run", fake_create_run)
    monkeypatch.setattr(main, "_spawn_run_subprocess", lambda *a, **k: None)
    monkeypatch.setattr(celery_app, "send_task", lambda *a, **k: None)
    monkeypatch.setattr(main, "solver_backend_info",
                        lambda: {"cuda_available": True, "sph_gpu_available": True})
    return main, captured


def _request(**overrides):
    from jalraksha_service.schemas import RunRequest

    body = {"dam_id": "khadakwasla", "ensemble_size": 1, "solver": "swe"}
    body.update(overrides)
    return RunRequest(**body)


def test_the_default_is_off(submitted):
    main, captured = submitted
    main.submit_run(_request())
    assert _request().condition_corridor_m == 0.0
    assert captured["params"]["condition_corridor_m"] == 0.0


def test_a_requested_corridor_reaches_the_pipeline_config(submitted):
    main, captured = submitted
    main.submit_run(_request(condition_corridor_m=10.0))
    assert captured["params"]["condition_corridor_m"] == 10.0


def test_a_negative_corridor_is_refused(submitted):
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        _request(condition_corridor_m=-1.0)


def test_the_task_forwards_it_to_the_solver():
    """Carried on dam_config, like every other per-request override."""
    import inspect

    from jalraksha_service import tasks

    source = inspect.getsource(tasks.run_dam_break_task)
    assert 'condition_corridor_m=float(dam_config.get("condition_corridor_m", 0.0))' in source


def test_the_pipeline_still_defaults_it_off():
    """The library's own default must stay 0, or every script run changes."""
    import inspect

    from jalraksha.run import run_dam_break_ensemble

    assert inspect.signature(
        run_dam_break_ensemble).parameters["condition_corridor_m"].default == 0.0
