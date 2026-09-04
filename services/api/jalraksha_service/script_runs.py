"""
Register a script-launched simulation so the dashboard can list and play it.

WHY THIS EXISTS

The project used to force a choice between a run that SURVIVES and one that is
VISIBLE, and you could not have both.

A run submitted through ``POST /runs`` gets a ``run_id``, appears in the picker
and plays back — but its worker was an ordinary child of uvicorn, so it died
whenever the server did. Three runs were lost that way in a single session, each
discarding hours of compute, because ``run_ensemble`` returns every member at
once and writes nothing per-member.

A run launched from a script survives anything — one in this session outlived
several API restarts and a long pause across a five-hour solve — but nothing
called ``db.create_run``, so no row existed, ``GET /runs`` could not list it, and
the dashboard could not load it. Two completed Khadakwasla drainage runs sat in
exactly that state: 50 export products and 60 keyframes each, unreachable from
the browser.

This module gives a script the same lifecycle ``tasks.run_dam_break_task``
performs, in about five lines::

    with registered_run(dam_id="khadakwasla", dam_config=cfg, solver="swe",
                        solver_params={"ensemble_size": 4, ...}) as run:
        result = run_dam_break_ensemble(cfg, dem, output_dir=run.export_dir,
                                        progress_cb=run.progress, ...)
        run.finish(result)

THREE THINGS HERE ARE LOAD-BEARING, AND EACH FAILS SILENTLY IF DROPPED.

``record_worker_pid`` — the API runs ``mark_stale_runs_failed()`` at startup,
which marks every ``running``/``queued`` row failed unless a LIVE process id is
recorded against it. Registering a long run at start without the pid means the
next API restart marks a still-solving run as failed. Since surviving restarts
is the entire reason scripts exist, omitting this would defeat the purpose.

``os.chdir(REPO_ROOT)`` — ``DATABASE_URL`` and ``DATA_DIR`` are both RELATIVE
paths resolved against the process CWD. A script started from anywhere else
silently creates a second, empty database and writes artifacts the API will
never find. ``scripts/backfill_xdmf.py`` does the same chdir for the same reason.

Artifacts must live in **run-id directories** — ``data/exports/<run_id>/`` and
``data/keyframes/<run_id>/``. ``_to_file_url`` in main.py serves a path only if
it resolves under ``DATA_DIR``, and the frontend resolves each keyframe's
``png_url`` as a SIBLING of the manifest, so the PNGs and the manifest cannot be
separated.

WHAT THIS MODULE DOES NOT DO. It does not make the solve itself restartable.
``run_dam_break_ensemble`` still returns every member at once, so a process
killed mid-solve loses the members it had finished — the run is simply marked
failed rather than left hanging. Per-member checkpointing is a separate problem.
"""

from __future__ import annotations

import json
import os
import traceback
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

#: Status strings the API recognises. ``done`` is compared EXACTLY by
#: ``GET /runs/{id}/result`` (409 otherwise) and by the picker's client-side
#: filter, so these are not free-form labels.
STATUS_RUNNING = "running"
STATUS_DONE = "done"
STATUS_FAILED = "failed"


def gauge_rows_from_result(result: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Turn a solver result's ``arrival_times`` into ``gauge_results`` rows.

    Extracted from ``tasks.run_dam_break_task`` so the API path and the script
    path cannot disagree about what a gauge row contains. Two copies would
    eventually diverge on ``_minority_arrival_note``, and that note is a
    correctness claim — it is what stops "1 of 4 members arrived" being read as
    a confident ensemble median.

    ``gauge_name`` and ``distance_km`` must both be non-null: ``GaugeResult`` in
    schemas.py declares them required, so a null there turns
    ``GET /runs/{id}/result`` into a 500 rather than a missing value.
    """
    from jalraksha_service.tasks import _gauge_max_depths, _minority_arrival_note

    gauge_depths = _gauge_max_depths(result)
    rows: List[Dict[str, Any]] = []
    for gname, g in (result.get("arrival_times") or {}).items():
        rows.append({
            "gauge_name": gname,
            "distance_km": g.get("distance_km"),
            "arrival_time_s": g.get("median"),
            "arrival_p05_s": g.get("p05"),
            "arrival_p95_s": g.get("p95"),
            "max_depth_m": gauge_depths.get(gname),
            "note": _minority_arrival_note(g) or g.get("note"),
            # Deliberately null, matching the API path: a domain-wide
            # population-at-risk figure cannot be divided among gauges without a
            # per-gauge catchment radius that no source defines.
            "par_estimate": None,
        })
    return rows


def write_run_summary(
    run_id: str,
    result: Dict[str, Any],
    dam_config: Dict[str, Any],
    solver_params: Dict[str, Any],
    dem_path: Optional[str] = None,
    dem_provenance: Any = None,
) -> Dict[str, str]:
    """
    Write ``exports/<run_id>/run_summary.json`` and return its export row.

    This one file is what the result endpoint reads back for the ``ensemble``,
    ``grid``, ``rapid_estimate``, ``dem_update`` and ``dem_used`` fields — five
    panels' worth of content from a single artifact. Without it they all render
    as empty states, which looks like a broken dashboard rather than a run that
    was registered by a different route.
    """
    from jalraksha_service.config import settings
    from jalraksha_service.tasks import _ensemble_summary, _grid_summary

    run_summary: Dict[str, Any] = {
        "ensemble": _ensemble_summary(result) if isinstance(result, dict) else None,
        "grid": _grid_summary(result) if isinstance(result, dict) else None,
        "solver_params": dict(solver_params),
        "dem": {
            "dem_used": dem_path,
            "dem_update": (
                dem_provenance.to_dict() if dem_provenance is not None else None
            ),
        },
    }
    if isinstance(result, dict) and result.get("rapid_estimate"):
        est = result["rapid_estimate"]
        run_summary["rapid_estimate"] = {
            k: est.get(k) for k in (
                "q_peak_median_m3s", "wave_celerity_ms", "inundation_area_km2",
                "affected_population", "economic_loss_crore_inr", "method", "note")
        }

    summary_dir = settings.DATA_DIR / "exports" / run_id
    summary_dir.mkdir(parents=True, exist_ok=True)
    summary_path = summary_dir / "run_summary.json"
    summary_path.write_text(
        json.dumps(run_summary, indent=2, default=str), encoding="utf-8"
    )
    return {"kind": "run_summary", "path_or_url": str(summary_path)}


class RegisteredRun:
    """
    A live database row for a script's simulation.

    Obtained from :func:`registered_run`; not constructed directly.
    """

    def __init__(self, run_id: str, dam_config: Dict[str, Any],
                 solver_params: Dict[str, Any]):
        from jalraksha_service.config import settings

        self.run_id = run_id
        self.dam_config = dict(dam_config)
        self.solver_params = dict(solver_params)
        self.export_dir = settings.DATA_DIR / "exports" / run_id
        self.keyframe_dir = settings.DATA_DIR / "keyframes" / run_id
        self.export_dir.mkdir(parents=True, exist_ok=True)
        self._extra_exports: List[Dict[str, str]] = []
        self._finished = False

    # ------------------------------------------------------------------

    def progress(self, pct: float, label: str = "") -> None:
        """
        Progress callback with the signature ``run_dam_break_ensemble`` expects.

        ``Callable[[float, str], None]`` — pass it straight as ``progress_cb``
        and the picker shows "Solving member 12/30" while the run is in flight
        instead of a frozen row. Failures here are swallowed: telemetry must
        never be able to kill a simulation that is otherwise fine.
        """
        from jalraksha_service import db

        try:
            db.update_run_status(
                self.run_id, STATUS_RUNNING, float(pct), phase=label or None
            )
        except Exception as exc:  # pragma: no cover - telemetry only
            print(f"[script-run] progress update failed: {exc}")

    def add_export(self, kind: str, path: Any) -> None:
        """
        Register an extra artifact this script produced.

        For anything the standard pipeline does not know about — the drainage
        check's ``hazard_series.json``, for instance. Rows whose file does not
        exist are dropped at finish, so a speculative call is harmless.
        """
        self._extra_exports.append({"kind": kind, "path_or_url": str(path)})

    # ------------------------------------------------------------------

    def finish(self, result: Dict[str, Any], n_keyframes: int = 30,
               dem_path: Optional[str] = None,
               keyframes_already_exported: bool = False) -> None:
        """
        Record the finished run: keyframes, summary, gauges, exports, status.

        Ordering matters and mirrors ``tasks.py``. ``update_run_status(done)``
        is LAST, because ``done`` is exactly what the picker filters on — a run
        flipped to done before its export rows exist is briefly listed as a
        complete run with nothing in it.
        """
        from jalraksha_service import db
        from jalraksha_service.tasks import _existing_exports

        exports: List[Dict[str, str]] = []

        for kind, path in (result.get("raster_paths") or {}).items():
            exports.append({"kind": kind, "path_or_url": path})

        # Keyframes: the difference between a run that lists and one that plays.
        # The manifest and its PNGs must stay in one directory — the frontend
        # resolves png_url relative to the manifest's own URL.
        if keyframes_already_exported and (self.keyframe_dir / "manifest.json").exists():
            # The caller needed the manifest itself (to derive its own summary
            # from the per-frame hazard counts, say) and exported it already.
            # Re-exporting would render every frame a second time for an
            # identical result.
            exports.append({
                "kind": "keyframe_manifest",
                "path_or_url": str(self.keyframe_dir / "manifest.json"),
            })
        elif result.get("depth_series"):
            from jalraksha.export.keyframes import export_keyframes
            from jalraksha.impact.hazard import HazardClassifier

            manifest = export_keyframes(
                {**result, "dam_name": self.dam_config.get("name", "Dam")},
                HazardClassifier(),
                n_keyframes=n_keyframes,
                out_dir=self.keyframe_dir,
            )
            exports.append({
                "kind": "keyframe_manifest",
                "path_or_url": str(self.keyframe_dir / "manifest.json"),
            })
            self._keyframe_manifest = manifest
        else:
            print("[script-run] no depth_series in result — the run will list "
                  "in the picker but will NOT play back.")

        exports.append(write_run_summary(
            self.run_id, result, self.dam_config, self.solver_params,
            dem_path=dem_path,
        ))
        exports.extend(self._extra_exports)

        db.insert_gauge_results(self.run_id, gauge_rows_from_result(result))
        db.insert_exports(self.run_id, _existing_exports(self.run_id, exports))
        db.update_run_status(self.run_id, STATUS_DONE, 100.0, phase="Complete")
        self._finished = True
        print(f"[script-run] registered {self.run_id} as {STATUS_DONE} "
              f"({len(exports)} export rows) — loadable in the dashboard")

    def fail(self, error: str) -> None:
        from jalraksha_service import db

        db.update_run_status(self.run_id, STATUS_FAILED, 0.0, error=error,
                             phase="Failed")
        print(f"[script-run] marked {self.run_id} {STATUS_FAILED}: {error}")


class registered_run:  # noqa: N801 - used as a context manager, reads as one
    """
    Context manager registering a script's run for the whole of its life.

    Args:
        dam_id: Preset id, stored in the ``runs.dam_id`` column. The ParaView
            endpoint looks its preset up by this.
        dam_config: The dam configuration. Stored in ``params_json``; its
            ``name`` becomes the label in the run picker, so make it say what
            the run IS — a plateau study listed as plain "Khadakwasla Dam" will
            be opened by somebody expecting the demo.
        solver: "swe" | "sph" | "delft3d" | "both".
        solver_params: Recorded under ``params_json["_solver_params"]``.
            ``scripts/backfill_xdmf.py`` REFUSES to re-run a run whose solver
            params were not persisted rather than guess them, so supplying
            ensemble_size / solver_duration_s / target_resolution here is what
            keeps the run reproducible later.

    On a clean exit the caller is expected to have called ``finish``; if it has
    not, the run is marked failed rather than left ``running`` forever, because
    a permanently-running row is indistinguishable from a live one to the
    stale-run sweep.
    """

    def __init__(self, dam_id: Optional[str], dam_config: Dict[str, Any],
                 solver: str, solver_params: Dict[str, Any]):
        self.dam_id = dam_id
        self.dam_config = dict(dam_config)
        self.solver = solver
        self.solver_params = dict(solver_params)
        self.run: Optional[RegisteredRun] = None

    def __enter__(self) -> RegisteredRun:
        from jalraksha_service import db

        db.init_db()
        run_id = db.create_run(
            self.dam_id,
            {**self.dam_config, "_solver_params": self.solver_params},
            self.solver,
        )
        # Before any status write: the stale-run sweep keys off this pid, and a
        # row that reaches "running" without one is reapable from the moment it
        # is written.
        db.record_worker_pid(run_id, os.getpid())
        db.update_run_status(run_id, STATUS_RUNNING, 0.0, phase="Starting")

        self.run = RegisteredRun(run_id, self.dam_config, self.solver_params)
        print(f"[script-run] run_id {run_id} — visible in the dashboard picker "
              f"as it progresses")
        return self.run

    def __exit__(self, exc_type, exc, tb) -> bool:
        if self.run is None:
            return False
        if exc is not None:
            detail = f"{type(exc).__name__}: {exc}"
            traceback.print_exception(exc_type, exc, tb)
            try:
                self.run.fail(detail)
            except Exception as inner:  # pragma: no cover
                print(f"[script-run] could not record failure: {inner}")
            return False
        if not self.run._finished:
            self.run.fail(
                "The script exited without calling finish(), so no exports or "
                "gauges were recorded. Marked failed rather than left running, "
                "which would look like a live run to the stale-run sweep."
            )
        return False


def bootstrap_repo_root(repo_root: Path) -> None:
    """
    Make ``jalraksha_service`` importable and the relative paths resolve.

    Both ``DATABASE_URL`` (``sqlite:///./data/jalraksha.db``) and ``DATA_DIR``
    (``./data``) are relative to the process CWD, so a script run from anywhere
    else silently creates a SECOND empty database and writes artifacts the API
    cannot see. Call this before importing anything from ``jalraksha_service``.
    """
    import sys

    os.chdir(repo_root)
    os.environ.setdefault("JALRAKSHA_DATA_DIR", "./data")
    services_api = str(repo_root / "services" / "api")
    if services_api not in sys.path:
        sys.path.insert(0, services_api)
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
