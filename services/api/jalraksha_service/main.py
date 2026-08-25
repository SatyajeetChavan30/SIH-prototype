"""
FastAPI application (integration brief §5.1).

REST surface:
  POST /runs                      → submit a simulation, enqueue a Celery job
  GET  /runs/{run_id}            → status + progress
  GET  /runs/{run_id}/result     → exports, keyframe manifest, gauge stats, hazard
  GET  /runs/{run_id}/comparison → Delft3D comparison output (brief §5.7)
  GET  /dams                     → demo dam presets (Tehri canonical)
  GET  /gauges/{run_id}          → per-gauge arrival/depth/PAR
  GET  /gee/latest?reach=        → near-real-time SAR extent (brief §5.6)
  GET  /health                   → liveness
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from jalraksha_service import db
from jalraksha_service.config import settings
from jalraksha_service.schemas import (
    RunRequest, RunStatus, RunResult, GaugeResult, ExportRef,
    ComparisonResult, DamPreset, GeoSarResponse,
)
from jalraksha_service.worker import celery_app

settings.ensure_dirs()
db.init_db()

app = FastAPI(title="JalRaksha API", version="1.0", description="Dam-break screening + 3D viz service")

# The React dev server (Vite, localhost:3000) and the API (localhost:8000) are
# different origins; the browser blocks the fetches in api.js without this.
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

# Exports/keyframes/comparison images are written to disk under DATA_DIR by
# the worker (paths only, no web server involved there) — serve them so the
# frontend can actually load them. See _to_file_url() below for the path→URL
# conversion applied when returning them from the endpoints.
app.mount("/files", StaticFiles(directory=str(settings.DATA_DIR)), name="files")


def _to_file_url(path_str: str) -> str:
    """Convert an absolute filesystem path under DATA_DIR into a /files/... URL."""
    try:
        rel = Path(path_str).resolve().relative_to(settings.DATA_DIR.resolve())
        return f"/files/{rel.as_posix()}"
    except ValueError:
        return path_str  # not under DATA_DIR (e.g. an already-external URL)


@app.on_event("startup")
def _startup() -> None:
    db.init_db()


@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok", "service": "JalRaksha API v1"}


@app.get("/dams", response_model=List[DamPreset])
def list_dams() -> List[Dict[str, Any]]:
    return settings.DEMO_DAMS


@app.post("/runs", response_model=RunStatus)
def submit_run(req: RunRequest):
    if req.solver not in settings.SOLVERS:
        raise HTTPException(422, f"Invalid solver {req.solver!r}; choose from {settings.SOLVERS}")
    try:
        dam_config = req.to_dam_config()
    except ValueError as e:
        raise HTTPException(422, str(e))

    dam_id = req.dam_id
    run_id = db.create_run(dam_id, dam_config, req.solver)
    task_args = [run_id, dam_config, req.ensemble_size, req.solver,
                 req.solver_duration_s, req.target_resolution]
    if celery_app.conf.task_always_eager:
        # CELERY_EAGER=1 dev path (worker.py): run the task in a background
        # thread so POST /runs still returns immediately and the frontend's
        # poll-until-done flow behaves the same as with a real Celery worker.
        # (.apply() rather than send_task(): send_task() registers the pending
        # result with the unreachable Redis backend even when eager.)
        import threading
        threading.Thread(
            target=lambda: celery_app.tasks["jalraksha.run_dam_break"].apply(args=task_args),
            daemon=True,
        ).start()
    else:
        celery_app.send_task("jalraksha.run_dam_break", args=task_args)
    return RunStatus(run_id=run_id, status="queued", progress_pct=0.0, solver=req.solver)


def _run_status(run_id: str) -> Dict[str, Any]:
    run = db.get_run(run_id)
    if run is None:
        raise HTTPException(404, "Unknown run_id")
    progress = float((run.get("params") or {}).get("progress_pct", 0.0))
    return {**run, "progress_pct": progress}


@app.get("/runs/{run_id}", response_model=RunStatus)
def run_status(run_id: str) -> RunStatus:
    run = _run_status(run_id)
    return RunStatus(
        run_id=run["run_id"], status=run["status"],
        progress_pct=run["progress_pct"], solver=run["solver"],
        created_at=run.get("created_at"),
    )


@app.get("/runs/{run_id}/result", response_model=RunResult)
def run_result(run_id: str) -> RunResult:
    run = _run_status(run_id)
    if run["status"] != "done":
        raise HTTPException(409, f"Run not done (status={run['status']})")

    exports_rows = db.get_exports(run_id)
    gauges_rows = db.get_gauge_results(run_id)
    manifest_url = next((e["path_or_url"] for e in exports_rows if e["kind"] == "keyframe_manifest"), None)
    hazard_summary = None
    if manifest_url and Path(manifest_url).exists():
        try:
            import json as _json
            hazard_summary = _json.loads(Path(manifest_url).read_text()).get("keyframes", [{}])[-1].get("hazard_summary")
        except Exception:
            pass

    return RunResult(
        run_id=run_id,
        dam_name=run.get("params", {}).get("name", "Dam"),
        exports=[ExportRef(kind=e["kind"], path_or_url=_to_file_url(e["path_or_url"])) for e in exports_rows],
        keyframe_manifest_url=_to_file_url(manifest_url) if manifest_url else None,
        gauges=[GaugeResult(**g) for g in gauges_rows],
        hazard_summary=hazard_summary,
    )


@app.get("/runs/{run_id}/comparison", response_model=ComparisonResult)
def run_comparison(run_id: str) -> ComparisonResult:
    run = _run_status(run_id)
    # The worker (tasks.py::_run_comparison) writes comparison_metrics.json for
    # solver="both" runs — brief §5.7, direct port of the Streamlit "both" tab.
    exports_rows = db.get_exports(run_id)
    metrics_path = next(
        (e["path_or_url"] for e in exports_rows if e["kind"] == "comparison_metrics"), None
    )
    metrics: Dict[str, Any] = {}
    maps: List[Dict[str, Any]] = []
    if metrics_path and Path(metrics_path).exists():
        try:
            import json as _json
            data = _json.loads(Path(metrics_path).read_text())
            metrics = {
                "metrics": data.get("metrics", {}),
                "gauge_comparison": data.get("gauge_comparison", []),
                "sph_engine": data.get("sph_engine"),
                "delft3d_engine": data.get("delft3d_engine"),
                "delft3d_engine_label": data.get("delft3d_engine_label"),
            }
            if data.get("depth_map_url"):
                maps.append({"kind": "comparison_depth_map", "path_or_url": _to_file_url(data["depth_map_url"])})
            if data.get("hydrograph_url"):
                maps.append({"kind": "comparison_hydrograph", "path_or_url": _to_file_url(data["hydrograph_url"])})
        except Exception:
            pass
    return ComparisonResult(run_id=run_id, metrics=metrics, maps=[ExportRef(**m) for m in maps])


@app.get("/gauges/{run_id}", response_model=List[GaugeResult])
def run_gauges(run_id: str) -> List[GaugeResult]:
    _run_status(run_id)  # 404 if unknown
    rows = db.get_gauge_results(run_id)
    return [GaugeResult(**g) for g in rows]


@app.get("/gee/latest", response_model=GeoSarResponse)
def gee_latest(reach: str = "bhagirathi") -> GeoSarResponse:
    # Brief §5.6: promote gee/sar.py from mock to live Sentinel-1 GRD. Currently
    # a stub returning the configured threshold; the plumbing is in place.
    from jalraksha.gee import sar
    try:
        observed = sar.latest_observed_extent(reach)
        return GeoSarResponse(
            reach=reach, observed_extent_url=observed.get("url"),
            threshold_db=observed.get("threshold_db", -17.0),
            acquired_at=observed.get("acquired_at"), note="Live SAR pending (brief §5.6).",
        )
    except Exception:
        return GeoSarResponse(reach=reach, threshold_db=-17.0,
                              note="Stub — promote gee/sar.py to live Sentinel-1 GRD.")
