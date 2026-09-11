"""
mark_stale_runs_failed must not kill a run whose worker is still solving.

It used to fail EVERY running/queued row on API startup, justified by a
docstring claiming "tasks run in-process (CELERY_EAGER), so a process exit
kills them". That stopped being true when run_worker.py moved solving into a
Popen subprocess which OUTLIVES the API. Starting the API therefore reached
into the database and marked a healthy, actively-solving run as failed — it
cost a Tehri flash-flood run at member 1/4, and blamed an orphaning that had
not happened.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time

import pytest

# The service package lives under services/api, which nothing else in the test
# suite imports, so it is not on sys.path by default.
_SERVICE_ROOT = str(
    __import__("pathlib").Path(__file__).resolve().parents[1] / "services" / "api"
)
if _SERVICE_ROOT not in sys.path:
    sys.path.insert(0, _SERVICE_ROOT)

from jalraksha_service import db  # noqa: E402


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    """Point the service at a throwaway SQLite file."""
    from jalraksha_service import config

    monkeypatch.setattr(config.settings, "DATABASE_URL", f"sqlite:///{tmp_path}/t.db")
    monkeypatch.setattr(config.settings, "DATA_DIR", tmp_path)
    db.init_db()
    return tmp_path


def _make_running_run(pid: int | None) -> str:
    """Create a run sitting at 'running', optionally claimed by `pid`."""
    run_id = db.create_run("tehri", {"name": "Tehri Dam"}, "swe")
    db.update_run_status(run_id, "running", 25.0, phase="Solving")
    if pid is not None:
        db.record_worker_pid(run_id, pid)
    return run_id


def _dead_pid() -> int:
    """
    A pid belonging to a process that really did exit.

    Not a made-up large number: on Windows an unused pid and an exited one are
    different cases, and only the second is what a crashed worker leaves.
    """
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    child.wait()
    time.sleep(0.2)
    return child.pid


class TestProcessLiveness:
    def test_this_process_is_alive(self):
        assert db._process_is_alive(os.getpid()) is True

    def test_a_dead_pid_is_not_alive(self):
        assert db._process_is_alive(_dead_pid()) is False

    @pytest.mark.parametrize("pid", [0, -1])
    def test_non_pids_are_not_alive(self, pid):
        assert db._process_is_alive(pid) is False


class TestStaleSweep:
    def test_a_live_worker_is_left_alone(self, isolated_db):
        """The defect, in one assertion."""
        run_id = _make_running_run(os.getpid())
        assert db.mark_stale_runs_failed() == 0
        assert db.get_run(run_id)["status"] == "running"

    def test_a_dead_worker_is_failed(self, isolated_db):
        run_id = _make_running_run(_dead_pid())
        assert db.mark_stale_runs_failed() == 1
        row = db.get_run(run_id)
        assert row["status"] == "failed"
        assert "no live worker" in (row["error"] or "")

    def test_a_run_with_no_pid_keeps_the_old_behaviour(self, isolated_db):
        """
        Rows written before pids were recorded, and rows queued but never
        dispatched, have nothing to check — failing them is still correct.
        """
        run_id = _make_running_run(None)
        assert db.mark_stale_runs_failed() == 1
        assert db.get_run(run_id)["status"] == "failed"

    def test_only_the_dead_run_is_touched(self, isolated_db):
        live = _make_running_run(os.getpid())
        dead = _make_running_run(_dead_pid())

        assert db.mark_stale_runs_failed() == 1
        assert db.get_run(live)["status"] == "running"
        assert db.get_run(dead)["status"] == "failed"

    def test_the_pid_survives_a_status_update(self, isolated_db):
        """
        update_run_status rewrites params_json wholesale, so a progress write
        must not drop the pid the sweep depends on.
        """
        run_id = _make_running_run(os.getpid())
        db.update_run_status(run_id, "running", 62.0, phase="Solving member 3/4")
        assert db.get_run(run_id)["params"]["worker_pid"] == os.getpid()
        assert db.mark_stale_runs_failed() == 0
