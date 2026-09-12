"""
Choosing CPU or GPU for a run, from the dashboard.

The solver has had a backend switch since the CUDA port, but only code and
JALRAKSHA_SOLVER_BACKEND could reach it: every dashboard run took "auto". These
tests pin the path that carries an operator's choice from the run form to the
ensemble, and the two refusals that keep it honest —

- an unknown backend name is rejected, like an unknown solver;
- backend="cuda" on a machine that cannot run a float64 CUDA kernel is refused
  AT SUBMISSION, with the probe's own reason, rather than after the terrain and
  the breach ensemble have already been built.

Nothing here solves, spawns a worker, touches the GPU or writes to the run
database.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "services" / "api"))

pytest.importorskip("jalraksha_service", reason="API service not importable")
pytest.importorskip("fastapi", reason="FastAPI not installed")

from fastapi import HTTPException  # noqa: E402

from jalraksha.solver.types import Grid, create_state  # noqa: E402


# ----------------------------------------------------------------------
# The pipeline carries the choice to the ensemble
# ----------------------------------------------------------------------


def test_run_dam_break_ensemble_forwards_the_backend(monkeypatch):
    """
    What the API sets must reach run_ensemble. Terrain and the solver are
    stubbed out: this is about the wiring, and the wiring is what silently
    breaks.
    """
    import jalraksha.run as run_module

    grid = Grid(nx=6, ny=6, dx=500.0, dy=500.0, x0=500000.0, y0=3350000.0)
    state = create_state(grid, np.zeros((6, 6)), b_init=np.zeros((6, 6)))
    monkeypatch.setattr(
        run_module, "build_domain",
        lambda *a, **k: (grid, state, np.full((6, 6), 0.03)),
    )
    # Geometry is not what this test is about: the stub grid has no real UTM
    # origin, so place the breach by hand rather than through the lat/lon map.
    monkeypatch.setattr(run_module, "compute_breach_location", lambda *a, **k: (3, 3, 0.0))

    seen = {}

    def fake_run_ensemble(*args, **kwargs):
        seen.update(kwargs)
        # One failed member: run.py then returns its "nothing completed" error
        # before any export runs, which is all this test needs.
        return [{"sample_id": 0, "error": "stubbed", "success": False}]

    monkeypatch.setattr(run_module, "run_ensemble", fake_run_ensemble)

    result = run_module.run_dam_break_ensemble(
        {"name": "Stub", "lat": 18.44, "lon": 73.77, "height_m": 40.0,
         "storage_mm3": 85.0, "dam_type": "embankment"},
        dem_path="unused-stub.tif",
        ensemble_size=1,
        solver_duration_s=10.0,
        target_resolution=500.0,
        backend="cpu",
    )

    assert seen.get("backend") == "cpu"
    assert "error" in result


def test_backend_defaults_to_auto():
    """Omitting it must keep today's behaviour exactly."""
    import inspect

    from jalraksha.run import run_dam_break_ensemble

    assert inspect.signature(run_dam_break_ensemble).parameters["backend"].default == "auto"


# ----------------------------------------------------------------------
# The API surface
# ----------------------------------------------------------------------


@pytest.fixture
def api(monkeypatch):
    """
    The route functions, with the worker and the database stubbed out.

    Called directly rather than through fastapi.testclient: that needs httpx2,
    which is not installed here, and the routes are plain functions whose
    refusals are HTTPExceptions.
    """
    from jalraksha_service import main as main_module

    captured = {}

    def fake_create_run(dam_id, run_record, solver):
        captured["dam_id"] = dam_id
        captured["run_record"] = run_record
        captured["solver"] = solver
        return "0" * 32

    monkeypatch.setattr(main_module.db, "create_run", fake_create_run)
    monkeypatch.setattr(main_module, "_spawn_run_subprocess",
                        lambda run_id, task_args: captured.setdefault("task_args", task_args))
    monkeypatch.setattr(main_module.celery_app, "send_task",
                        lambda *a, **k: captured.setdefault("sent", (a, k)))
    return main_module, captured


def _set_probe(main_module, monkeypatch, available: bool, reason: str = "stubbed probe"):
    monkeypatch.setattr(
        main_module, "solver_backend_info",
        lambda: {
            "cuda_available": available,
            "cuda_device": "Stub GPU" if available else None,
            "cuda_reason": reason,
            "available": ["auto", "cpu"] + (["cuda"] if available else []),
            "default": "auto",
        },
    )


def _request(main_module, **overrides):
    """A minimal, valid POST /runs payload for the first preset dam."""
    from jalraksha_service.schemas import RunRequest

    body = {"dam_id": main_module.settings.DEMO_DAMS[0]["id"], "solver": "swe",
            "ensemble_size": 1, "solver_duration_s": 60.0,
            "target_resolution": 500.0}
    body.update(overrides)
    return RunRequest(**body)


def test_backends_endpoint_reports_what_this_machine_can_run(api, monkeypatch):
    main_module, _ = api
    monkeypatch.setattr(
        main_module, "_probe_cuda_out_of_process",
        lambda: {"cuda_available": False, "cuda_device": None,
                 "cuda_reason": "no driver in this test"},
    )
    main_module._BACKEND_PROBE.clear()
    try:
        payload = main_module.list_backends()
    finally:
        main_module._BACKEND_PROBE.clear()

    assert payload["default"] == "auto"
    assert "cpu" in payload["available"]
    # The option is withheld, and it says why.
    assert "cuda" not in payload["available"]
    assert "no driver in this test" in payload["cuda_reason"]


def test_unknown_backend_is_rejected(api, monkeypatch):
    main_module, _ = api
    _set_probe(main_module, monkeypatch, available=True)
    with pytest.raises(HTTPException) as refused:
        main_module.submit_run(_request(main_module, backend="tpu"))
    assert refused.value.status_code == 422
    assert "tpu" in refused.value.detail


def test_gpu_request_is_refused_at_submission_when_there_is_no_gpu(api, monkeypatch):
    main_module, _ = api
    _set_probe(main_module, monkeypatch, available=False, reason="nvvm.dll is missing")
    with pytest.raises(HTTPException) as refused:
        main_module.submit_run(_request(main_module, backend="cuda"))
    assert refused.value.status_code == 422
    # The probe's own words, so the operator can act on it.
    assert "nvvm.dll is missing" in refused.value.detail


def test_cpu_choice_is_recorded_on_the_run(api, monkeypatch):
    main_module, captured = api
    _set_probe(main_module, monkeypatch, available=True)
    status = main_module.submit_run(_request(main_module, backend="cpu"))
    assert status.status == "queued"

    record = captured["run_record"]
    # On dam_config, the channel tasks.py reads, and in the run's own
    # parameters, so a finished run says which hardware it asked for.
    assert record["solver_backend"] == "cpu"
    assert record["_solver_params"]["solver_backend"] == "cpu"


def test_default_request_still_asks_for_auto(api, monkeypatch):
    main_module, captured = api
    _set_probe(main_module, monkeypatch, available=True)
    main_module.submit_run(_request(main_module))
    assert captured["run_record"]["solver_backend"] == "auto"
