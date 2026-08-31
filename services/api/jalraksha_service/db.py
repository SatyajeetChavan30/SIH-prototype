"""
Thin run/job metadata store (integration brief §5.2).

Three tables only:
  runs(run_id, dam_id, params_json, status, created_at, solver)
  gauge_results(run_id, gauge_name, distance_km, arrival_time_s, max_depth_m, par_estimate)
  exports(run_id, kind, path_or_url)

Everything else (rasters, GeoTIFFs, shapefiles, Cesium tiles, keyframe PNGs)
stays on disk, referenced by path/URL — exactly as the existing exports work.
No geometry columns: this is metadata + time series only.

Uses sqlite3 for local/dev (stdlib, zero extra deps) and psycopg (if installed)
for the Postgres URL used in Docker. The schema is intentionally portable.
"""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from jalraksha_service.config import settings


def _connect() -> Any:
    url = settings.DATABASE_URL
    if url.startswith("sqlite"):
        path = url.replace("sqlite:///", "").replace("sqlite://", "")
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        return sqlite3.connect(path)
    # Postgres path (Docker). psycopg is installed in the api image.
    try:
        import psycopg
    except ImportError as exc:  # pragma: no cover - docker only
        raise RuntimeError("Postgres DATABASE_URL set but psycopg not installed") from exc
    return psycopg.connect(url)


def _placeholder(n: int) -> str:
    return ",".join(["%s"] * n) if settings.DATABASE_URL.startswith("postgres") else ",".join(["?"] * n)


def init_db() -> None:
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS runs (
                run_id      TEXT PRIMARY KEY,
                dam_id      TEXT,
                params_json TEXT,
                status      TEXT,
                created_at  TEXT,
                solver      TEXT
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS gauge_results (
                run_id       TEXT,
                gauge_name   TEXT,
                distance_km  REAL,
                arrival_time_s REAL,
                max_depth_m REAL,
                par_estimate REAL
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS exports (
                run_id       TEXT,
                kind         TEXT,
                path_or_url  TEXT
            )
            """
        )
        # Additive migrations. The demo database already exists and holds the
        # pre-baked Tehri run, so these columns are added in place rather than
        # by recreating the table - dropping it would delete the one complete
        # run the offline demo depends on.
        _add_column(cur, "gauge_results", "arrival_p05_s", "REAL")
        _add_column(cur, "gauge_results", "arrival_p95_s", "REAL")
        _add_column(cur, "gauge_results", "note", "TEXT")
        _add_column(cur, "runs", "error", "TEXT")
        conn.commit()
    finally:
        conn.close()


def _add_column(cur: Any, table: str, column: str, coltype: str) -> None:
    """
    ADD COLUMN if it is not already there.

    Both backends raise on a duplicate column and neither offers a portable
    IF NOT EXISTS for this, so that one error is caught and swallowed.
    Anything else propagates.
    """
    try:
        cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}")
    except Exception as exc:
        if "duplicate column" not in str(exc).lower():
            raise


def create_run(dam_id: Optional[str], params: Dict[str, Any], solver: str) -> str:
    run_id = uuid.uuid4().hex
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(
            f"INSERT INTO runs (run_id, dam_id, params_json, status, created_at, solver) "
            f"VALUES ({_placeholder(6)})",
            (run_id, dam_id, json.dumps(params), "queued",
             datetime.now(timezone.utc).isoformat(), solver),
        )
        conn.commit()
    finally:
        conn.close()
    return run_id


def _process_is_alive(pid: int) -> bool:
    """
    Whether `pid` names a live process, without taking a psutil dependency.

    PID REUSE is the known weakness: a recycled pid reads as alive and would
    leave a genuinely dead run marked "running". That is the SAFE direction of
    the two — a stuck row is visible and correctable, whereas the failure this
    guards against silently discards a run that is still computing.
    """
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        # PROCESS_QUERY_LIMITED_INFORMATION: enough to ask whether it exists,
        # and permitted for processes this one did not create.
        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, int(pid))
        if not handle:
            return False
        try:
            exit_code = ctypes.c_ulong()
            ok = ctypes.windll.kernel32.GetExitCodeProcess(
                handle, ctypes.byref(exit_code))
            # 259 == STILL_ACTIVE. A handle can outlive the process, so the
            # handle opening is not on its own proof of life.
            return bool(ok) and exit_code.value == 259
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, ValueError):
        return False
    except PermissionError:
        return True
    return True


def record_worker_pid(run_id: str, pid: int) -> None:
    """
    Stamp the OS pid of the process actually solving this run.

    mark_stale_runs_failed reads it to tell a genuinely orphaned run from one
    whose worker is still running. Stored in params_json for the same reason
    progress_pct and phase are: it keeps the table schema minimal.
    """
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute("SELECT params_json FROM runs WHERE run_id = %s"
                    % ("?" if not settings.DATABASE_URL.startswith("postgres") else "%s"),
                    (run_id,))
        row = cur.fetchone()
        if not row:
            return
        params = json.loads(row[0])
        params["worker_pid"] = int(pid)
        cur.execute(
            f"UPDATE runs SET params_json = {_placeholder(1)} "
            f"WHERE run_id = {_placeholder(1)}",
            (json.dumps(params), run_id),
        )
        conn.commit()
    finally:
        conn.close()


def update_run_status(run_id: str, status: str, progress_pct: float = 0.0,
                      error: Optional[str] = None,
                      phase: Optional[str] = None) -> None:
    # progress is stored inside params_json to keep the schema minimal.
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute("SELECT params_json FROM runs WHERE run_id = %s" % ("?" if not settings.DATABASE_URL.startswith("postgres") else "%s"), (run_id,))
        row = cur.fetchone()
        params = json.loads(row[0]) if row else {}
        params["progress_pct"] = progress_pct
        # A percentage alone cannot distinguish a slow stage from a hung one,
        # and this pipeline has stages that legitimately run for many minutes.
        # Stored in params_json for the same reason progress_pct is: it keeps
        # the table schema minimal.
        if phase is not None:
            params["phase"] = phase
        cur.execute(
            f"UPDATE runs SET status = {_placeholder(1)}, params_json = {_placeholder(1)}, "
            f"error = {_placeholder(1)} WHERE run_id = {_placeholder(1)}",
            (status, json.dumps(params), error, run_id),
        )
        conn.commit()
    finally:
        conn.close()


def list_runs(limit: int = 50) -> List[Dict[str, Any]]:
    """
    Every run, newest first, with its export count.

    Backs the dashboard's run picker. Before this there was no collection
    endpoint at all, so loading a previous run meant typing a 32-character hex
    id by hand - unusable in a live demo. export_count is what lets the UI show
    which runs are actually loadable: a run with zero exports has nothing to
    display no matter what its status says.
    """
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT r.run_id, r.dam_id, r.status, r.created_at, r.solver, r.error, "
            "  (SELECT COUNT(*) FROM exports e WHERE e.run_id = r.run_id), "
            "  (SELECT COUNT(*) FROM gauge_results g WHERE g.run_id = r.run_id), "
            "  r.params_json "
            "FROM runs r ORDER BY r.created_at DESC"
        )
        rows = cur.fetchall()[:limit]
        out = []
        for r in rows:
            try:
                params = json.loads(r[8]) if r[8] else {}
            except (TypeError, ValueError):
                params = {}
            out.append({
                "run_id": r[0], "dam_id": r[1], "status": r[2],
                "created_at": r[3], "solver": r[4], "error": r[5],
                "export_count": r[6], "gauge_count": r[7],
                "dam_name": params.get("name"),
            })
        return out
    finally:
        conn.close()


def mark_stale_runs_failed() -> int:
    """
    Mark as failed only those running/queued rows whose worker is really gone.

    This used to fail EVERY running or queued row unconditionally, justified by
    a docstring that said "tasks run in-process (CELERY_EAGER), so a process
    exit kills them". That stopped being true when run_worker.py moved solving
    into a subprocess: the worker is spawned with Popen and OUTLIVES the API.
    So restarting the API — or merely starting a second one — reached into the
    database and marked a healthy, actively-solving run as failed, while the
    worker carried on writing exports nobody would look at. It cost a Tehri run
    at member 1/4 and reported the cause as an orphaning that had not happened.

    A run is now failed here only when its recorded worker pid is absent or
    names no live process. Rows with no pid (written before this existed, or
    queued before dispatch) keep the old behaviour, because for those there is
    genuinely nothing to check.

    Returns how many were corrected.
    """
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute("SELECT run_id, params_json FROM runs "
                    "WHERE status IN ('running', 'queued')")
        rows = cur.fetchall()

        orphaned = []
        for run_id, params_json in rows:
            try:
                pid = int(json.loads(params_json or "{}").get("worker_pid") or 0)
            except (ValueError, TypeError):
                pid = 0
            if pid and _process_is_alive(pid):
                continue
            orphaned.append(run_id)

        for run_id in orphaned:
            cur.execute(
                f"UPDATE runs SET status = {_placeholder(1)}, "
                f"error = {_placeholder(1)} WHERE run_id = {_placeholder(1)}",
                ("failed",
                 "Orphaned: no live worker process for this run when the API "
                 "started, and it was still marked running.",
                 run_id),
            )
        conn.commit()
        return len(orphaned)
    finally:
        conn.close()


def get_run(run_id: str) -> Optional[Dict[str, Any]]:
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute("SELECT run_id, dam_id, params_json, status, created_at, solver, error FROM runs WHERE run_id = %s" % ("?" if not settings.DATABASE_URL.startswith("postgres") else "%s"), (run_id,))
        row = cur.fetchone()
        if not row:
            return None
        return {
            "run_id": row[0], "dam_id": row[1], "params": json.loads(row[2]),
            "status": row[3], "created_at": row[4], "solver": row[5],
            "error": row[6],
        }
    finally:
        conn.close()


def insert_gauge_results(run_id: str, gauges: List[Dict[str, Any]]) -> None:
    conn = _connect()
    try:
        cur = conn.cursor()
        for g in gauges:
            cur.execute(
                f"INSERT INTO gauge_results (run_id, gauge_name, distance_km, "
                f"arrival_time_s, max_depth_m, par_estimate, arrival_p05_s, "
                f"arrival_p95_s, note) VALUES ({_placeholder(9)})",
                (run_id, g.get("gauge_name"), g.get("distance_km"),
                 g.get("arrival_time_s"), g.get("max_depth_m"), g.get("par_estimate"),
                 g.get("arrival_p05_s"), g.get("arrival_p95_s"), g.get("note")),
            )
        conn.commit()
    finally:
        conn.close()


def get_gauge_results(run_id: str) -> List[Dict[str, Any]]:
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute("SELECT gauge_name, distance_km, arrival_time_s, max_depth_m, par_estimate, arrival_p05_s, arrival_p95_s, note FROM gauge_results WHERE run_id = %s" % ("?" if not settings.DATABASE_URL.startswith("postgres") else "%s"), (run_id,))
        rows = cur.fetchall()
        return [
            {"gauge_name": r[0], "distance_km": r[1], "arrival_time_s": r[2],
             "max_depth_m": r[3], "par_estimate": r[4],
             "arrival_p05_s": r[5], "arrival_p95_s": r[6], "note": r[7]}
            for r in rows
        ]
    finally:
        conn.close()


def insert_exports(run_id: str, exports: List[Dict[str, Any]]) -> None:
    conn = _connect()
    try:
        cur = conn.cursor()
        for e in exports:
            cur.execute(
                f"INSERT INTO exports (run_id, kind, path_or_url) VALUES ({_placeholder(3)})",
                (run_id, e["kind"], e["path_or_url"]),
            )
        conn.commit()
    finally:
        conn.close()


def get_exports(run_id: str) -> List[Dict[str, Any]]:
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute("SELECT kind, path_or_url FROM exports WHERE run_id = %s" % ("?" if not settings.DATABASE_URL.startswith("postgres") else "%s"), (run_id,))
        return [{"kind": r[0], "path_or_url": r[1]} for r in cur.fetchall()]
    finally:
        conn.close()
