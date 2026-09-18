"""
Stop the runs this data directory still has in flight.

Used by the Windows desktop app when the user quits with a simulation running
and chooses "Stop runs and quit". Run workers are deliberately DETACHED from the
API (main.py::_spawn_run_subprocess) so a long run survives the server; that
same property means stopping the API does not stop them, and killing the API's
process tree does not reach them either. So they are found the way
db.mark_stale_runs_failed finds them — by the worker pid each one records — and
terminated with their own children (the ensemble's process pool).

The other choice the desktop app offers, "Keep running in background", needs no
code: the worker finishes, writes its results, and the next launch lists it.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
from typing import Any, Dict, List, Optional

STOPPED_ERROR = "Stopped by the user when quitting the JalRaksha desktop app."


def active_runs() -> List[Dict[str, Any]]:
    """Running or queued rows, with the worker pid each recorded (0 if none)."""
    from jalraksha_service import db

    conn = db._connect()
    try:
        cur = conn.cursor()
        cur.execute("SELECT run_id, params_json FROM runs WHERE status IN ('running', 'queued')")
        rows = cur.fetchall()
    finally:
        conn.close()
    out = []
    for run_id, params_json in rows:
        try:
            pid = int(json.loads(params_json or "{}").get("worker_pid") or 0)
        except (TypeError, ValueError):
            pid = 0
        out.append({"run_id": run_id, "worker_pid": pid})
    return out


def _terminate_tree(pid: int) -> bool:
    """Terminate a process and its descendants. True if a signal was delivered."""
    if os.name == "nt":
        proc = subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                              capture_output=True, text=True,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return proc.returncode == 0
    try:
        # Workers start with start_new_session, so the pid leads its own group.
        os.killpg(pid, signal.SIGTERM)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def stop_active_runs() -> Dict[str, Any]:
    """Terminate every live worker and mark its run failed with STOPPED_ERROR."""
    from jalraksha_service import db

    stopped, not_running = [], []
    for run in active_runs():
        pid = run["worker_pid"]
        if pid and db._process_is_alive(pid):
            _terminate_tree(pid)
            stopped.append(run["run_id"])
        else:
            not_running.append(run["run_id"])
        # Marked failed either way: a queued row with no live worker would
        # otherwise be failed as "Orphaned" at the next start, which misstates
        # what happened.
        db.update_run_status(run["run_id"], "failed", 0.0, error=STOPPED_ERROR, phase="Stopped")
    return {"stopped_runs": stopped, "marked_without_live_worker": not_running}


def main(argv: Optional[List[str]] = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args == ["--list"]:
        print(json.dumps({"ok": True, "active_runs": active_runs()}))
        return 0
    if args:
        print("usage: run_control [--list]", file=sys.stderr)
        return 2
    print(json.dumps({"ok": True, **stop_active_runs()}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
