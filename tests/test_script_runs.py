"""
A script-launched run must be registered, listed and PLAYABLE.

The project used to force a choice between a run that survives and one that is
visible. A dashboard-submitted run got a `run_id` but died with the server; a
script-launched run survived anything but had no database row, so `GET /runs`
could not list it and the dashboard could not load it. Two finished Khadakwasla
drainage runs sat in that state with 50 exports and 60 keyframes each.

These tests pin the four conditions a run must satisfy to be both listed and
animate, because each of them fails in a way that looks like something else:

- status not exactly "done"        -> HTTP 409, reads as "run still going"
- zero exports                     -> silently absent from the picker
- missing/!existing keyframe row   -> run lists but shows no imagery
- a gauge row with a null distance -> HTTP 500 on the whole result

Nothing here touches the network or runs a solver.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "services" / "api"))

pytest.importorskip("jalraksha_service", reason="API service not importable")


@pytest.fixture
def service(tmp_path, monkeypatch):
    """
    A private database and DATA_DIR, so these tests never touch the real run
    history. `db._connect` resolves a RELATIVE sqlite path against the process
    CWD, so the chdir is what actually isolates it.
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("JALRAKSHA_DATA_DIR", "./data")

    from jalraksha_service import db
    from jalraksha_service.config import settings

    monkeypatch.setattr(settings, "DATA_DIR", tmp_path / "data", raising=False)
    monkeypatch.setattr(settings, "DATABASE_URL",
                        f"sqlite:///{(tmp_path / 'test.db').as_posix()}",
                        raising=False)
    db.init_db()
    return db


def _fake_result(tmp_path):
    """The subset of a solver result the registration path actually reads."""
    return {
        "raster_paths": {},
        "arrival_times": {
            "Shivajinagar": {"distance_km": 12.1, "median": 900.0,
                             "p05": 800.0, "p95": 1000.0},
        },
        "depth_series": [],
    }


# --------------------------------------------------------------- lifecycle

def test_run_is_visible_while_it_is_still_solving(service, tmp_path):
    """
    The whole point of registering at START. A five-hour run that only appears
    once finished is invisible for the part of its life you would want to watch.
    """
    from jalraksha_service.script_runs import registered_run

    with registered_run("khadakwasla", {"name": "Test run"}, "swe",
                        {"ensemble_size": 1}) as run:
        listed = {r["run_id"]: r for r in service.list_runs(50)}
        assert run.run_id in listed
        assert listed[run.run_id]["status"] == "running"

        run.progress(42.0, "Solving member 3/7")
        stored = service.get_run(run.run_id)
        assert stored["params"]["progress_pct"] == 42.0
        assert stored["params"]["phase"] == "Solving member 3/7"

        run._finished = True  # stand in for finish(), tested separately


def test_worker_pid_is_recorded_so_the_stale_sweep_spares_a_live_run(service):
    """
    THE SUBTLE ONE. The API calls mark_stale_runs_failed() at startup, which
    marks every running/queued row failed unless a LIVE pid is recorded. Without
    this, restarting the API would kill the row of a script run that is still
    solving — defeating the exact durability scripts exist for.
    """
    from jalraksha_service.script_runs import registered_run

    with registered_run("khadakwasla", {"name": "Live"}, "swe", {}) as run:
        assert service.get_run(run.run_id)["params"]["worker_pid"] == os.getpid()

        service.mark_stale_runs_failed()

        assert service.get_run(run.run_id)["status"] == "running", (
            "a live script run was reaped by the stale-run sweep"
        )
        run._finished = True


def test_a_crash_marks_the_run_failed_rather_than_leaving_it_running(service):
    """
    A permanently "running" row is indistinguishable from a live one to the
    stale sweep, so it would linger forever.
    """
    from jalraksha_service.script_runs import registered_run

    run_id = None
    with pytest.raises(ValueError):
        with registered_run("khadakwasla", {"name": "Doomed"}, "swe", {}) as run:
            run_id = run.run_id
            raise ValueError("solver exploded")

    stored = service.get_run(run_id)
    assert stored["status"] == "failed"
    assert "solver exploded" in (stored.get("error") or "")


def test_exiting_without_finish_is_also_a_failure(service):
    """
    Falling out of the block without calling finish() means no exports and no
    gauges were recorded. Marking it done would list an empty run as complete.
    """
    with __import__("jalraksha_service.script_runs", fromlist=["x"]).registered_run(
        "khadakwasla", {"name": "Forgot"}, "swe", {}
    ) as run:
        run_id = run.run_id

    assert service.get_run(run_id)["status"] == "failed"


# ---------------------------------------------------------------- contract

def test_finished_run_satisfies_the_picker_and_playback_contract(service, tmp_path):
    """
    All four conditions at once, because a run that satisfies three of them
    fails in a way that looks like a different bug entirely.
    """
    from jalraksha_service.config import settings
    from jalraksha_service.script_runs import registered_run

    with registered_run("khadakwasla", {"name": "Contract run"}, "swe",
                        {"ensemble_size": 1}) as run:
        # Stand in for export_keyframes: a manifest with the three fields the
        # frontend reads, and a sibling PNG.
        run.keyframe_dir.mkdir(parents=True, exist_ok=True)
        (run.keyframe_dir / "keyframe_0000_000000s.png").write_bytes(b"\x89PNG\r\n")
        (run.keyframe_dir / "manifest.json").write_text(json.dumps({
            "keyframes": [{
                "time_s": 0.0,
                "png_url": "keyframe_0000_000000s.png",
                "bounds": [73.4, 18.2, 74.1, 18.7],
                "hazard_summary": {"low": {"count": 3, "color": [100, 200, 100]}},
            }],
        }), encoding="utf-8")

        run.finish(_fake_result(tmp_path), keyframes_already_exported=True)
        run_id = run.run_id

    # 1. status is EXACTLY "done" — the result endpoint 409s on anything else.
    row = service.get_run(run_id)
    assert row["status"] == "done"

    # 2. the picker's client-side filter also needs export_count > 0.
    listed = {r["run_id"]: r for r in service.list_runs(50)}
    assert listed[run_id]["export_count"] > 0

    # 3. a keyframe_manifest row whose file EXISTS and lies under DATA_DIR,
    #    or _to_file_url cannot turn it into a /files/ URL.
    exports = {e["kind"]: e["path_or_url"] for e in service.get_exports(run_id)}
    assert "keyframe_manifest" in exports
    manifest_path = Path(exports["keyframe_manifest"])
    assert manifest_path.exists()
    manifest_path.resolve().relative_to(settings.DATA_DIR.resolve())

    # the PNG must be a SIBLING — the frontend resolves png_url against the
    # manifest's own URL, not against any recorded path.
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert (manifest_path.parent / manifest["keyframes"][0]["png_url"]).exists()

    # 4. every gauge row carries non-null name and distance, or GaugeResult
    #    raises and the endpoint 500s.
    for g in service.get_gauge_results(run_id):
        assert g["gauge_name"] is not None
        assert g["distance_km"] is not None


def test_a_run_without_keyframes_still_registers_but_says_so(service, tmp_path, capsys):
    """
    Registering an unplayable run is allowed — a delft3d run legitimately has no
    depth series — but it must be visible in the output, because the symptom is
    a run that lists and then shows nothing.
    """
    from jalraksha_service.script_runs import registered_run

    with registered_run("khadakwasla", {"name": "No frames"}, "delft3d", {}) as run:
        run.finish({"raster_paths": {}, "arrival_times": {}})
        run_id = run.run_id

    assert service.get_run(run_id)["status"] == "done"
    assert "NOT play back" in capsys.readouterr().out


# ------------------------------------------------------------ shared helpers

def test_the_gauge_mapping_is_shared_with_the_api_path():
    """
    tasks.py must import this rather than keep its own copy: two versions would
    eventually disagree about what a minority arrival is, and that note is what
    stops "1 of 4 members arrived" reading as a confident median.
    """
    import inspect

    from jalraksha_service import tasks

    source = inspect.getsource(tasks.run_dam_break_task)
    assert "gauge_rows_from_result" in source
    assert "write_run_summary" in source
