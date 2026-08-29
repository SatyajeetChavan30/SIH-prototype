"""
Out-of-process runner for a single simulation.

WHY THIS EXISTS
---------------
The eager dev path used to run each task on a ``threading.Thread`` inside the
uvicorn process. That is fine for a task that waits on IO and wrong for this
one: a dam-break run is CPU-bound from end to end, and none of it releases the
GIL for long.

  * the flux kernels are ``@njit`` **without** ``nogil=True``, so each call
    holds the interpreter lock for its whole duration;
  * the ``delft3d`` / ``both`` path is pure Python plus PySPH plus matplotlib,
    which holds it throughout.

The measured symptom was a ``GET /validation`` that returned nothing after 120
seconds while a run was in flight, and a dashboard whose every request crawled.
A demo where clicking a tab hangs the page for minutes is not usable, and the
cause is structural rather than a slow query somewhere.

Running the task in a SEPARATE PROCESS gives it its own interpreter and its own
GIL, so the API keeps answering at full speed no matter what the solver is
doing. That is the entire purpose of this module.

WHY NOT JUST USE CELERY
-----------------------
A real broker is the architecture's intended answer and remains available via
``scripts/run_api.py --broker``. It is not the DEFAULT because it makes Redis a
hard dependency of demo day, and CLAUDE.md's offline-first rule is explicit that
demo-day network and service reliability are assumed low. This module keeps the
zero-dependency path while removing its one serious flaw.

STATUS REPORTING
----------------
The child writes progress straight to the same SQLite database the API reads.
That is safe because ``db.py`` opens and closes a connection per call rather
than holding one open, so there is no connection shared across the fork, and
SQLite's own locking serialises the writes. Progress writes are small and
infrequent (a handful per member), so contention is not a concern.
"""

from __future__ import annotations

import json
import os
import sys
import traceback
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    """
    Entry point: ``python -m jalraksha_service.run_worker <payload.json>``.

    The payload carries the task arguments. It is passed as a FILE rather than
    on the command line because a dam config plus solver parameters can exceed
    the Windows command-length limit, and because quoting JSON through a shell
    is a reliable source of corruption.
    """
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) != 1:
        print("usage: python -m jalraksha_service.run_worker <payload.json>",
              file=sys.stderr)
        return 2

    payload_path = Path(argv[0])
    payload = json.loads(payload_path.read_text(encoding="utf-8"))

    # Import AFTER the payload is read: importing tasks pulls in numpy, numba
    # and the solver, which is seconds of startup we should not pay before we
    # know there is work to do.
    from jalraksha_service import db
    from jalraksha_service.worker import celery_app

    run_id = payload["run_id"]
    try:
        # .apply(), not a direct call. The task is declared bind=True, so its
        # underlying function takes `self` first; invoking it directly would
        # shift every argument by one and pass None as the run_id. .apply() is
        # Celery's own eager path and does the binding correctly - it is what
        # the previous in-process thread used, for the same reason.
        result = celery_app.tasks["jalraksha.run_dam_break"].apply(args=[
            run_id,
            payload["dam_config"],
            payload["ensemble_size"],
            payload["solver"],
            payload["solver_duration_s"],
            payload["target_resolution"],
        ])
        # apply() swallows the exception into the result rather than raising,
        # so a failure here would otherwise exit 0 and look like success.
        if result.failed():
            raise RuntimeError(f"task failed: {result.result}")
        return 0
    except BaseException as exc:  # noqa: BLE001 - must record every failure
        # The task records its own failures, but a crash BEFORE its try block
        # (an import error, an OOM kill) would otherwise leave the run stuck at
        # "running" forever, which is exactly the state the run picker had to be
        # taught to clean up. Record it here too; a double write is harmless.
        detail = f"{type(exc).__name__}: {exc}"
        print(f"[run_worker] run {run_id} FAILED - {detail}", file=sys.stderr)
        traceback.print_exc()
        try:
            db.update_run_status(run_id, "failed", 0.0, error=detail,
                                 phase="Failed")
        except Exception:
            pass
        return 1
    finally:
        # The payload is scratch; leave no litter behind in the data directory.
        try:
            payload_path.unlink(missing_ok=True)
        except OSError:
            pass


if __name__ == "__main__":
    # The service package lives under services/api, which is on sys.path when
    # the API imports it but not when Python is launched fresh on this file.
    package_root = Path(__file__).resolve().parents[1]
    if str(package_root) not in sys.path:
        sys.path.insert(0, str(package_root))
    # Same for the repo root, which holds the `jalraksha` library.
    repo_root = package_root.parents[1]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    os.environ.setdefault("JALRAKSHA_DATA_DIR", "./data")
    raise SystemExit(main())
