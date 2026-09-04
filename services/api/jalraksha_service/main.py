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

import json
import os
import sys
import threading
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
    EnsembleSummary, GridSummary, EngineInfo, RunListEntry,
    GeeStatus, ValidationCheck, ValidationResult, BlockageDetectionResponse,
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


@app.middleware("http")
async def _static_assets_always_cors(request, call_next):
    """
    Stamp Access-Control-Allow-Origin on /files and /tiles unconditionally.

    CORSMiddleware only adds the header when the REQUEST carries an Origin, and
    that is not enough here because the same asset is fetched two different ways:

      * Leaflet (2D) loads a keyframe PNG through a plain <img>, which sends no
        Origin — so the response comes back without CORS headers and the browser
        caches it that way.
      * Cesium (3D) loads the SAME url via XMLHttpRequest, which does send
        Origin. The browser serves the cached, header-less copy and blocks it:
        "No 'Access-Control-Allow-Origin' header is present".

    The failure is therefore order-dependent — it only appears once the 2D tab
    has cached the image first, which is why it can look intermittently fine.
    allow_origins is already ["*"] with no credentials, so the header value is
    "*" in every case and stamping it unconditionally is equivalent, minus the
    dependence on which consumer happened to ask first. Vary: Origin keeps any
    intermediate cache from making the same mistake.
    """
    response = await call_next(request)
    if request.url.path.startswith(("/files/", "/tiles/")):
        response.headers.setdefault("Access-Control-Allow-Origin", "*")
        response.headers.setdefault("Vary", "Origin")
    return response

# Exports/keyframes/comparison images are written to disk under DATA_DIR by
# the worker (paths only, no web server involved there) — serve them so the
# frontend can actually load them. See _to_file_url() below for the path→URL
# conversion applied when returning them from the endpoints.
app.mount("/files", StaticFiles(directory=str(settings.DATA_DIR)), name="files")

# Cesium terrain tiles (brief §5.5.1), built by tools/cesium/build_terrain_tiles.py
# from the same DEM the solver conditions. Docker Compose serves these through the
# dedicated nginx `tiles` service; mounting them here as well means local dev needs
# no second process, and inherits this app's CORS headers — Cesium fetches
# layer.json cross-origin from the Vite dev server and is blocked without them.
app.mount("/tiles", StaticFiles(directory=str(settings.DATA_DIR / "tiles")), name="tiles")


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
    # Tasks run in-process under CELERY_EAGER, so a restart kills any in-flight
    # run with no chance for it to update its own row. Left alone those rows
    # claim "running" forever and fill the run picker with entries that will
    # never finish - there were eight in the demo database.
    stale = db.mark_stale_runs_failed()
    if stale:
        print(f"[api] marked {stale} orphaned run(s) as failed")


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
    if req.scenario_type != "dam_break" and req.solver not in {"swe", "sph"}:
        raise HTTPException(
            422,
            "River blockage and overflow scenarios currently require the SWE "
            "pipeline (or SWE + near-field SPH). Delft3D comparison is only "
            "configured for dam-break hydrographs.",
        )
    try:
        dam_config = req.to_dam_config()
    except ValueError as e:
        raise HTTPException(422, str(e))

    # Domain-shape overrides. Threaded through dam_config, same convention as
    # the preset's own domain_radius_km (tasks.py reads both off dam_config,
    # not task_args) -- these are per-request, not part of any dam preset.
    if req.domain_margins_km is not None:
        dam_config["domain_margins_km"] = req.domain_margins_km
    dam_config["fill_max_depth_m"] = req.fill_max_depth_m
    dam_config["notch_breach"] = req.notch_breach

    # Detection needs Earth Engine, and a run that cannot detect and has no
    # manual barrier to fall back on has nothing to burn into the DEM. Checked
    # here because gee_status() is cached and answers in milliseconds: failing at
    # submission beats failing twenty minutes into a solve.
    if req.scenario_type == "river_blockage" and req.blockage_source == "detect":
        from jalraksha.gee.auth import gee_status

        available, reason = gee_status()
        has_manual_fallback = None not in (
            req.blockage_lat, req.blockage_lon,
            req.blockage_crest_height_m, req.blockage_width_m,
        )
        if not available and not has_manual_fallback:
            raise HTTPException(
                422,
                f"blockage_source='detect' needs Earth Engine, which is not "
                f"available: {reason}. Either configure it, or supply the "
                f"barrier manually (blockage_lat, blockage_lon, "
                f"blockage_crest_height_m, blockage_width_m) — the manual path "
                f"runs fully offline. The run is refused rather than falling "
                f"back to the pre-event DEM, which would simulate a valley the "
                f"landslide has already changed.",
            )

    dam_id = req.dam_id
    # Persist the solver parameters alongside the dam config, under a namespaced
    # key so they cannot collide with a dam field. create_run stores only what it
    # is given, and until now the run parameters existed solely in task_args —
    # meaning a finished run recorded WHICH dam it simulated but not at what
    # resolution, duration or ensemble size. scripts/backfill_xdmf.py has to
    # reproduce a run faithfully, and cannot do that from a dam config alone.
    #
    # Kept out of the dict handed to the task: that one is the dam config the
    # solver consumes, and it should not grow service bookkeeping.
    run_record = {
        **dam_config,
        "_solver_params": {
            "ensemble_size": req.ensemble_size,
            "solver_duration_s": req.solver_duration_s,
            "target_resolution": req.target_resolution,
            "scenario_type": req.scenario_type,
        },
    }
    run_id = db.create_run(dam_id, run_record, req.solver)
    task_args = [run_id, dam_config, req.ensemble_size, req.solver,
                 req.solver_duration_s, req.target_resolution]
    if celery_app.conf.task_always_eager:
        _spawn_run_subprocess(run_id, task_args)
    else:
        celery_app.send_task("jalraksha.run_dam_break", args=task_args)
    return RunStatus(run_id=run_id, status="queued", progress_pct=0.0,
                     solver=req.solver, phase="Queued")


def _spawn_run_subprocess(run_id: str, task_args: List[Any]) -> None:
    """
    Run the simulation in a SEPARATE PROCESS, not a thread.

    This used to be `threading.Thread(...)`, which is the right shape for IO-
    bound work and the wrong one here. A dam-break run is CPU-bound throughout
    and holds the GIL: the flux kernels are `@njit` without `nogil=True`, and
    the delft3d/both path is pure Python plus PySPH plus matplotlib. Uvicorn
    runs single-process, single-loop, so the API was starved for the whole run.

    The measured symptom was `GET /validation` returning nothing after 120
    seconds while a run was in flight, and every dashboard request crawling. A
    demo where clicking a tab hangs for minutes is not usable.

    A child process has its own interpreter and its own GIL, so the API stays
    responsive regardless of what the solver is doing. It reports status through
    the same SQLite database, which is safe because db.py opens and closes a
    connection per call rather than sharing one across the fork.

    A real Celery broker remains the intended production answer and is still
    available via `scripts/run_api.py --broker`; it is not the default because
    it makes Redis a hard demo-day dependency.
    """
    import subprocess
    import tempfile

    payload = {
        "run_id": run_id,
        "dam_config": task_args[1],
        "ensemble_size": task_args[2],
        "solver": task_args[3],
        "solver_duration_s": task_args[4],
        "target_resolution": task_args[5],
    }
    # Passed as a file, not on argv: a dam config plus solver parameters can
    # exceed the Windows command-length limit, and quoting JSON through a shell
    # is a reliable way to corrupt it.
    scratch = settings.DATA_DIR / "runs"
    scratch.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", prefix=f"{run_id}_", dir=str(scratch),
        delete=False, encoding="utf-8")
    with handle as fh:
        json.dump(payload, fh)

    repo_root = Path(__file__).resolve().parents[3]
    env = dict(os.environ)
    # The child needs both the service package and the library on its path.
    env["PYTHONPATH"] = os.pathsep.join(
        filter(None, [str(repo_root / "services" / "api"), str(repo_root),
                      env.get("PYTHONPATH", "")]))

    # DETACHED, so a long run outlives the server that started it.
    #
    # This used to be a plain Popen with no detachment, which made the worker an
    # ordinary child of uvicorn. Three runs were lost that way in one session —
    # each discarding hours of compute — because restarting the API reaped the
    # solver with it, and `run_ensemble` returns every member at once and writes
    # nothing per-member, so a killed run leaves nothing at all.
    #
    # The consequence is that a dashboard-submitted run and a script-launched
    # one now have the same durability, which is what makes the dashboard usable
    # for anything longer than a demo.
    log_path = scratch / f"{run_id}.log"
    log_handle = open(log_path, "w", encoding="utf-8", buffering=1)

    popen_kwargs = {}
    if os.name == "nt":
        # DETACHED_PROCESS gives the child no console; CREATE_NEW_PROCESS_GROUP
        # keeps a Ctrl-C in the API's console from propagating to it.
        popen_kwargs["creationflags"] = (
            subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
        )
    else:
        popen_kwargs["start_new_session"] = True

    # Output goes to a per-run FILE rather than being inherited. It has to: a
    # detached process has no console to inherit, so inheriting would silently
    # discard the solver's progress. This is better than the old behaviour
    # anyway — the log survives the server and is attributable to one run,
    # instead of being interleaved with every other request in the API's stdout.
    subprocess.Popen(
        [sys.executable, "-m", "jalraksha_service.run_worker", handle.name],
        cwd=str(repo_root),
        env=env,
        stdout=log_handle, stderr=subprocess.STDOUT,
        **popen_kwargs,
    )
    # The parent's copy of the descriptor is closed immediately; the child holds
    # its own. Leaving it open would leak one handle per submitted run.
    log_handle.close()
    print(f"[api] run {run_id} dispatched to a detached subprocess "
          f"(log: {log_path})")


def _run_status(run_id: str) -> Dict[str, Any]:
    run = db.get_run(run_id)
    if run is None:
        raise HTTPException(404, "Unknown run_id")
    params = run.get("params") or {}
    return {**run,
            "progress_pct": float(params.get("progress_pct", 0.0)),
            "phase": params.get("phase")}


@app.get("/runs/{run_id}", response_model=RunStatus)
def run_status(run_id: str) -> RunStatus:
    run = _run_status(run_id)
    return RunStatus(
        run_id=run["run_id"], status=run["status"],
        progress_pct=run["progress_pct"], solver=run["solver"],
        phase=run.get("phase"),
        created_at=run.get("created_at"),
        error=run.get("error"),
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

    # Population at risk, written by the worker as its own artifact. Read the
    # same way hazard_summary is read above: from the file, so an absent or
    # unreadable artifact yields None rather than a fabricated figure.
    population_at_risk = None
    par_path = next((e["path_or_url"] for e in exports_rows
                     if e["kind"] == "population_at_risk"), None)
    if par_path and Path(par_path).exists():
        try:
            import json as _json
            population_at_risk = _json.loads(Path(par_path).read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"[api] run {run_id}: population_at_risk unreadable - "
                  f"{type(exc).__name__}: {exc}")

    # Run-level summary (ensemble statistics, grid geometry, engine identity),
    # written by the worker as run_summary.json. Read from disk for the same
    # reason hazard_summary and population_at_risk are: an absent or unreadable
    # artifact must yield None, never a placeholder number.
    summary = _read_export_json(exports_rows, "run_summary", run_id) or {}
    impact = _read_export_json(exports_rows, "impact", run_id)
    sph = _read_export_json(exports_rows, "sph_near_field", run_id)

    comparison_url = None
    if any(e["kind"] == "comparison_metrics" for e in exports_rows):
        comparison_url = f"/runs/{run_id}/comparison"

    # Which terrain this run was computed over, and whether it was modified.
    # Runs written before this existed have no "dem" block and report None,
    # which is the honest answer: nobody recorded it at the time.
    dem_block = summary.get("dem") or {}
    dem_update = dem_block.get("dem_update")
    if dem_update:
        # The updated raster and its sidecar are downloadable products; the
        # dashboard shows the provenance banner from these fields.
        for key in ("updated_dem", "provenance_json"):
            if dem_update.get(key):
                dem_update[key] = _to_file_url(dem_update[key])

    return RunResult(
        run_id=run_id,
        dam_name=run.get("params", {}).get("name", "Dam"),
        exports=[ExportRef(kind=e["kind"], path_or_url=_to_file_url(e["path_or_url"])) for e in exports_rows],
        keyframe_manifest_url=_to_file_url(manifest_url) if manifest_url else None,
        gauges=[GaugeResult(**g) for g in gauges_rows],
        hazard_summary=hazard_summary,
        population_at_risk=population_at_risk,
        ensemble=EnsembleSummary(**summary["ensemble"]) if summary.get("ensemble") else None,
        grid=GridSummary(**summary["grid"]) if summary.get("grid") else None,
        engine=EngineInfo(**summary["engine"]) if summary.get("engine") else None,
        rapid_estimate=summary.get("rapid_estimate"),
        impact=impact,
        sph=sph,
        solver=run.get("solver"),
        status=run.get("status"),
        error=run.get("error"),
        comparison_url=comparison_url,
        dem_update=dem_update,
        dem_used=_to_file_url(dem_block["dem_used"]) if dem_block.get("dem_used") else None,
    )


def _read_export_json(exports_rows: List[Dict[str, Any]], kind: str,
                      run_id: str) -> Dict[str, Any] | None:
    """
    Load one JSON export by kind, or None.

    Shared by every artifact the result endpoint stitches together. Failure is
    logged with the kind and reason rather than silently swallowed - the three
    inline copies of this that preceded it used a bare `except: pass`, so a
    corrupt file was indistinguishable from one that was never written.
    """
    import json as _json

    path = next((e["path_or_url"] for e in exports_rows if e["kind"] == kind), None)
    if not path or not Path(path).exists():
        return None
    try:
        return _json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"[api] run {run_id}: {kind} unreadable - {type(exc).__name__}: {exc}")
        return None


@app.get("/runs/{run_id}/comparison", response_model=ComparisonResult)
def run_comparison(run_id: str) -> ComparisonResult:
    run = _run_status(run_id)
    # The worker (tasks.py::_run_comparison) writes comparison_metrics.json for
    # solver="both" runs — brief §5.7.
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
                # Why there is no SPH half, when there is not one — so the tab
                # can distinguish "PySPH could not run" from "not requested".
                "sph_error": data.get("sph_error"),
                "sph_near_field": data.get("sph_near_field"),
                "delft3d_engine": data.get("delft3d_engine"),
                "delft3d_engine_label": data.get("delft3d_engine_label"),
                # Whether the official Delft3D FM binary ran, and why not if it
                # did not. The Comparison tab turns these into a banner; without
                # them a reader has to infer the engine from a label string.
                "delft3d_binary_used": data.get("delft3d_binary_used", False),
                "delft3d_fallback_reason": data.get("delft3d_fallback_reason"),
                "gauge_arrival_method": data.get("gauge_arrival_method"),
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


#: Fallbacks for a dam with no preset (bhakra/idukki/hirakud have entries in
#: DEMO_DAMS but no DamPreset). These are render_static.py's own defaults.
_PARAVIEW_FALLBACK = {"vertical_exaggeration": 1.5, "nominal_depth_m": 25.0}


def _run_preset(run: Dict[str, Any]) -> Dict[str, Any]:
    """
    This run's dam's visualization settings, or the generic fallback.

    Reads DEMO_DAMS rather than jalraksha.presets.get_preset() because the
    service's registry is the one that covers every selectable dam; the preset
    registry has entries only for tehri and khadakwasla and would raise for the
    others.
    """
    dam_id = run.get("dam_id")
    for dam in settings.DEMO_DAMS:
        if dam.get("id") == dam_id:
            return {
                "vertical_exaggeration": dam.get("vertical_exaggeration")
                or _PARAVIEW_FALLBACK["vertical_exaggeration"],
                "nominal_depth_m": dam.get("nominal_depth_m")
                or _PARAVIEW_FALLBACK["nominal_depth_m"],
            }
    return dict(_PARAVIEW_FALLBACK)


@app.get("/runs", response_model=List[RunListEntry])
def list_runs(limit: int = 50) -> List[RunListEntry]:
    """
    All runs, newest first - the dashboard's run picker.

    There was no collection endpoint before this, so loading a previous run
    meant typing a 32-character hex id by hand. That is unusable in a live
    demo, and it is the whole mechanism behind "load a precomputed run".

    export_count is included so the UI can show which rows are actually
    loadable: a run with zero exports has nothing to display regardless of
    what its status says.
    """
    return [RunListEntry(**r) for r in db.list_runs(limit=limit)]


@app.get("/gee/status", response_model=GeeStatus)
def gee_status_endpoint() -> GeeStatus:
    """
    Whether Earth Engine is usable right now, and if not, why.

    Separate from /gee/latest because the dashboard needs to render an honest
    badge before any reach is chosen, and because /gee/latest conflates "not
    configured" with "no scene for this reach".

    The reason string is Earth Engine's own message, or this project's text
    naming the exact missing variable and the free registration URL. It is
    written for a person to read - render it verbatim.
    """
    from jalraksha.gee.auth import gee_project, gee_status

    available, reason = gee_status()
    return GeeStatus(available=available, reason=reason,
                     project=gee_project() or None)


#: On-disk cache for the validation gates.
#:
#: These checks are DETERMINISTIC — fixed seeds, fixed grids, fixed thresholds —
#: so a stored result stays valid until the solver itself changes. Persisting it
#: means the demo does not pay for them again after a restart.
_VALIDATION_CACHE_PATH = settings.DATA_DIR / "validation_cache.json"

#: In-flight guard. The gates run two 1000-step solves plus compare_ritter,
#: which launches its own Delft3D kernel, so a second concurrent request would
#: start a second kernel against the same scratch directory.
_VALIDATION_LOCK = threading.Lock()
_VALIDATION_RUNNING = {"active": False}


def _load_validation_cache() -> Dict[str, Any] | None:
    try:
        if _VALIDATION_CACHE_PATH.exists():
            return json.loads(_VALIDATION_CACHE_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"[validation] cache unreadable - {type(exc).__name__}: {exc}")
    return None


def _store_validation_cache(payload: Dict[str, Any]) -> None:
    try:
        _VALIDATION_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _VALIDATION_CACHE_PATH.write_text(json.dumps(payload, indent=2),
                                          encoding="utf-8")
    except Exception as exc:
        print(f"[validation] cache not written - {type(exc).__name__}: {exc}")


def _run_validation_checks() -> None:
    """Execute the gates and store the result. Runs on a background thread."""
    from datetime import datetime, timezone

    try:
        checks = [_check_lake_at_rest(), _check_mass_conservation(),
                  _check_ritter()]
        _store_validation_cache({
            "checks": [c.model_dump() for c in checks],
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "cached": False,
        })
    except Exception as exc:  # pragma: no cover - defensive
        print(f"[validation] run failed - {type(exc).__name__}: {exc}")
    finally:
        _VALIDATION_RUNNING["active"] = False


@app.get("/validation", response_model=ValidationResult)
def validation(refresh: bool = False) -> ValidationResult:
    """
    The analytical correctness gates, as pass/fail plus the curves to plot.

    This is the answer to "how do we know the animation is not decorative".
    Three independent kinds of evidence:

      * Ritter - the exact analytical dam-break solution, with JalRaksha and
        (where the kernel is present) Delft3D FM scored against it on a shared
        axis. Three curves that can be overlaid, plus per-engine RMSE.
      * Lake at rest - still water over irregular bathymetry must stay still.
        Catches an unbalanced pressure gradient, the classic well-balancing bug.
      * Mass conservation - total volume must not drift.

    Cached after the first call; pass refresh=true to re-run.
    """
    cached = _load_validation_cache()
    if cached and not refresh:
        cached["cached"] = True
        cached["status"] = "done"
        return ValidationResult(**cached)

    # Never run the gates inside the request. They perform real solver work —
    # two 1000-step solves plus compare_ritter, which starts the Delft3D
    # kernel — and holding a connection open for that returned nothing after
    # 120 seconds when a simulation was already competing for the machine.
    with _VALIDATION_LOCK:
        if not _VALIDATION_RUNNING["active"]:
            _VALIDATION_RUNNING["active"] = True
            threading.Thread(target=_run_validation_checks, daemon=True).start()

    return ValidationResult(checks=[], generated_at=None, cached=False,
                            status="running")


def _check_lake_at_rest() -> ValidationCheck:
    """
    Still water over irregular bathymetry must stay still.

    The C-property (Bermudez & Vazquez 1994), and the single most diagnostic
    test of a shallow-water code: a scheme that fails it manufactures currents
    out of terrain, which on a 30 m Himalayan DEM means manufacturing a flood.

    Mirrors tests/test_solver.py::TestLakeAtRest::
    test_lake_at_rest_random_bathymetry exactly - same seed, same grid, same
    1000 steps, same thresholds - so the badge on the dashboard and the
    blocking CI gate can never disagree about whether the solver is sound.
    """
    try:
        import numpy as np

        from jalraksha.solver.core import SWESolver
        from jalraksha.solver.types import Grid, create_state

        rng = np.random.default_rng(42)
        grid = Grid(nx=50, ny=50, dx=50.0, dy=50.0)

        # 5 m of bed relief, water surface flat at eta = 10 m. Every interior
        # face has a bed step, so the Audusse hydrostatic reconstruction and
        # the bed-slope source term must cancel at every single face.
        bed = rng.uniform(0.0, 5.0, (50, 50))
        state = create_state(grid, np.maximum(10.0 - bed, 0.1), b_init=bed)
        eta_init = state.eta.copy()

        solver = SWESolver(grid, manning_n=0.03, cfl=0.9)
        for _ in range(1000):
            state = solver.step(state)

        vel_max = float(np.max(state.speed))
        eta_error = float(np.max(np.abs(state.eta - eta_init)))
        passed = vel_max < 1e-8 and eta_error < 1e-6

        return ValidationCheck(
            name="Lake at rest",
            passed=passed,
            detail=(f"max spurious velocity {vel_max:.2e} m/s and surface error "
                    f"{eta_error:.2e} m after 1000 steps over random bathymetry "
                    f"(gates: < 1e-8 m/s, < 1e-6 m)"),
            metrics={"max_velocity_m_s": vel_max,
                     "max_surface_error_m": eta_error,
                     "threshold_velocity_m_s": 1e-8,
                     "threshold_surface_m": 1e-6,
                     "steps": 1000},
        )
    except Exception as exc:
        return ValidationCheck(name="Lake at rest",
                               error=f"{type(exc).__name__}: {exc}")


def _check_mass_conservation() -> ValidationCheck:
    """
    A dam-break inside a closed box conserves volume.

    Reflective walls are essential: with transmissive boundaries the front
    leaves the domain and volume SHOULD drop, so a transmissive run tells you
    nothing about the discretisation.

    Mirrors tests/test_solver.py::TestMassConservation::
    test_mass_conservation_dam_break_walls, including the negative x0 - with
    the default x0=0 every cell centre is positive, the `x < 0` initial
    condition is empty, and the check would divide by a zero initial volume
    and pass vacuously.
    """
    try:
        import numpy as np

        from jalraksha.solver.core import SWESolver
        from jalraksha.solver.types import Grid, create_state

        nx = 200
        grid = Grid(nx=nx, ny=1, dx=0.5, dy=1.0, x0=-50.0)
        h_init = np.where(grid.cell_centres_x() < 0.0, 1.0, 0.0).reshape(1, nx)

        state = create_state(grid, h_init)
        volume_init = state.volume * grid.area
        if volume_init <= 0.0:
            return ValidationCheck(
                name="Mass conservation",
                error="Initial condition is empty - the check would be vacuous.")

        solver = SWESolver(grid, manning_n=0.0, cfl=0.9, boundary="reflective")
        for _ in range(1000):
            state = solver.step(state)

        volume_final = state.volume * grid.area
        drift = abs(volume_final - volume_init) / volume_init
        passed = drift < 1e-3

        return ValidationCheck(
            name="Mass conservation",
            passed=passed,
            detail=(f"volume drift {drift * 100:.6f}% over 1000 steps of a "
                    f"closed-box dam-break (gate: < 0.1%)"),
            metrics={"volume_initial_m3": float(volume_init),
                     "volume_final_m3": float(volume_final),
                     "drift_pct": drift * 100.0,
                     "threshold_pct": 0.1,
                     "steps": 1000},
        )
    except Exception as exc:
        return ValidationCheck(name="Mass conservation",
                               error=f"{type(exc).__name__}: {exc}")


def _check_ritter() -> ValidationCheck:
    """
    Ritter dry-bed dam-break against the exact solution.

    Uses jalraksha.validation.delft3d_benchmark.compare_ritter, which scores
    BOTH JalRaksha and the real Delft3D FM kernel against the same analytical
    curve on a shared axis. When the kernel is absent it still returns the
    JalRaksha-vs-analytical half; the series dict simply has no delft3d entry,
    and the UI draws two curves instead of three.
    """
    try:
        import tempfile

        from jalraksha.validation.delft3d_benchmark import compare_ritter

        with tempfile.TemporaryDirectory(prefix="jalraksha_ritter_") as tmp:
            result = compare_ritter(tmp)

        jr = result.get("jalraksha_vs_analytical", {}) or {}
        d3d = result.get("delft3d_vs_analytical", {}) or {}
        rmse = jr.get("rmse_m")
        passed = rmse is not None and rmse < 0.10

        series = {
            "x_m": _as_list(result.get("x")),
            "analytical_m": _as_list(result.get("analytical")),
            "jalraksha_m": _as_list(result.get("jalraksha")),
        }
        if result.get("delft3d") is not None:
            series["delft3d_m"] = _as_list(result.get("delft3d"))

        detail = (f"JalRaksha RMSE {rmse:.4f} m vs the exact solution at "
                  f"t={result.get('t_end_s')} s (gate: < 0.10 m)")
        if d3d.get("rmse_m") is not None:
            detail += f"; Delft3D FM {d3d['rmse_m']:.4f} m on the same case"

        return ValidationCheck(
            name="Ritter dam-break (analytical)",
            passed=passed,
            detail=detail,
            metrics={
                "jalraksha_rmse_m": rmse,
                "jalraksha_depth_at_dam_m": jr.get("depth_at_dam_m"),
                "delft3d_rmse_m": d3d.get("rmse_m"),
                "delft3d_depth_at_dam_m": d3d.get("depth_at_dam_m"),
                "exact_depth_at_dam_m": result.get("exact_depth_at_dam_m"),
                "engine_agreement_rmse_m": (result.get("engine_agreement") or {}).get("rmse_m"),
                "delft3d_executable": result.get("delft3d_executable"),
                "threshold_rmse_m": 0.10,
            },
            series=series,
        )
    except Exception as exc:
        return ValidationCheck(name="Ritter dam-break (analytical)",
                               error=f"{type(exc).__name__}: {exc}")


def _as_list(values: Any) -> List[float] | None:
    """numpy array -> plain list for JSON, passing None through."""
    if values is None:
        return None
    return [float(v) for v in values]


#: Half-width of the SAR window around a dam, in degrees (~11 km at these
#: latitudes). Wide enough to show the reservoir and several km of downstream
#: channel; narrow enough that one Sentinel-1 scene covers it and the download
#: stays small.
SAR_WINDOW_DEG = 0.10


def _resolve_reach(reach: str) -> Dict[str, Any] | None:
    """
    Map a reach name to a dam and a bounding box.

    Accepts either a dam id ("tehri") or a river name ("bhagirathi"), so the
    long-standing `?reach=bhagirathi` default keeps working.

    This lives in the SERVICE, not in jalraksha.gee, because the dam registry
    is service configuration and the library must not import it — service
    depends on library, never the reverse (config.py's own rule).
    """
    key = (reach or "").strip().lower()
    for dam in settings.DEMO_DAMS:
        if key in {str(dam.get("id", "")).lower(),
                   str(dam.get("river", "")).lower(),
                   str(dam.get("name", "")).lower()}:
            lat, lon = dam["lat"], dam["lon"]
            return {
                "dam": dam,
                "bbox": (lon - SAR_WINDOW_DEG, lat - SAR_WINDOW_DEG,
                         lon + SAR_WINDOW_DEG, lat + SAR_WINDOW_DEG),
            }
    return None


@app.get("/gee/latest", response_model=GeoSarResponse)
def gee_latest(reach: str = "bhagirathi") -> GeoSarResponse:
    """
    Latest OBSERVED water extent over a reach, from Sentinel-1 (brief §5.6).

    Answers with `source` = sentinel1_grd | cached | unavailable, and a `reason`
    whenever it is unavailable. There is deliberately no fallback that returns
    something plausible: this endpoint used to call a function that did not
    exist, swallow the resulting AttributeError in a bare `except`, and reply
    with a hardcoded -17.0 dB threshold and a "stub" note — so it advertised a
    threshold for a scene it had never fetched, for every request ever made.

    This is observed WATER, not observed FLOOD. Over a dam on an ordinary day it
    shows the reservoir and the river, because those are water.
    """
    from jalraksha.gee.sar import SarUnavailableError, latest_observed_extent

    resolved = _resolve_reach(reach)
    if resolved is None:
        known = sorted({d["id"] for d in settings.DEMO_DAMS}
                       | {str(d.get("river", "")).lower() for d in settings.DEMO_DAMS})
        return GeoSarResponse(
            reach=reach, source="unavailable",
            reason=f"Unknown reach {reach!r}. Known reaches: {', '.join(known)}.",
        )

    try:
        observed = latest_observed_extent(
            reach=reach,
            bbox=resolved["bbox"],
            cache_dir=settings.DATA_DIR / "gee" / "sar" / reach.lower(),
        )
    except SarUnavailableError as exc:
        return GeoSarResponse(reach=reach, source="unavailable", reason=str(exc),
                              bbox=list(resolved["bbox"]))

    return GeoSarResponse(
        reach=reach,
        source=observed["source"],
        reason=observed.get("reason"),
        scene_id=observed.get("scene_id"),
        acquired_at=observed.get("acquired_at"),
        threshold_db=observed.get("threshold_db"),
        threshold_method=observed.get("threshold_method"),
        water_fraction=observed.get("water_fraction"),
        bbox=observed.get("bbox"),
        observed_extent_url=_to_file_url(observed["png_path"]),
        geotiff_url=_to_file_url(observed["geotiff_path"]),
        note=observed.get("note"),
    )


@app.get("/gee/blockage", response_model=BlockageDetectionResponse)
def gee_blockage(
    reach: str = "rishi_ganga",
    date_pre: str | None = None,
    date_post: str | None = None,
) -> BlockageDetectionResponse:
    """
    Has a new water body — a forming landslide-dammed lake — appeared here?

    The front half of the HADR workflow: detect, screen, and if needed simulate.
    A Sentinel-1 pre-event median is differenced against a SINGLE post-event
    scene, JRC permanent water is subtracted, and what is left must sit on a
    watercourse to be reported.

    THREE STATES, NO FOURTH — the same rule as /gee/latest. A refusal here is an
    ordinary outcome and not a failure of the demo: the manual barrier path runs
    fully offline, needs no Earth Engine, and is where a refusal sends you.

    The dates default to the reach's own event window when it has one (Rishi
    Ganga carries 2021-01-15 / 2021-02-08, the Chamoli event), because the
    scene that matters for a past event is not the latest one.
    """
    from jalraksha.gee.blockage_detect import detect_new_water
    from jalraksha.gee.sar import SarUnavailableError

    resolved = _resolve_reach(reach)
    if resolved is None:
        known = sorted({d["id"] for d in settings.DEMO_DAMS})
        return BlockageDetectionResponse(
            reach=reach, source="unavailable",
            reason=f"Unknown reach {reach!r}. Known reaches: {', '.join(known)}.",
        )

    record = resolved["dam"]
    pre_start = date_pre or record.get("blockage_date_pre")
    post = date_post or record.get("blockage_date_post")
    if not pre_start or not post:
        return BlockageDetectionResponse(
            reach=reach, source="unavailable", bbox=list(resolved["bbox"]),
            reason=(
                f"No event window is known for {reach!r} and none was supplied. "
                f"Change detection needs a before and an after; pass date_pre "
                f"and date_post, or place the barrier manually."
            ),
        )
    # Pre-event window ends the day before the post acquisition, so a scene from
    # after the event cannot leak into the "before" median.
    import datetime as _date

    pre_end = (_date.date.fromisoformat(post) - _date.timedelta(days=1)).isoformat()

    try:
        detection = detect_new_water(
            reach=reach,
            bbox=resolved["bbox"],
            cache_dir=settings.DATA_DIR / "gee" / "blockage" / reach.lower(),
            date_pre_start=pre_start,
            date_pre_end=pre_end,
            date_post=post,
        )
    except SarUnavailableError as exc:
        return BlockageDetectionResponse(
            reach=reach, source="unavailable", reason=str(exc),
            bbox=list(resolved["bbox"]),
        )

    return BlockageDetectionResponse(
        reach=reach,
        source=detection["source"],
        reason=detection.get("reason"),
        scene_id_post=detection.get("scene_id_post"),
        acquired_at_post=detection.get("acquired_at_post"),
        date_pre_start=detection.get("date_pre_start"),
        date_pre_end=detection.get("date_pre_end"),
        threshold_db_pre=detection.get("threshold_db_pre"),
        threshold_db_post=detection.get("threshold_db_post"),
        threshold_method=detection.get("threshold_method"),
        precision_of_pre_mask_vs_jrc=detection.get("precision_of_pre_mask_vs_jrc"),
        recall_of_pre_mask_vs_jrc=detection.get("recall_of_pre_mask_vs_jrc"),
        new_water_fraction=detection.get("new_water_fraction"),
        fraction_near_drainage=detection.get("fraction_near_drainage"),
        pre_water_fraction=detection.get("pre_water_fraction"),
        # Radar geometry, size and flatness. These are forwarded rather than
        # summarised: a detection that survived a 63%-shadow window and one over
        # open ground are different claims, and collapsing them to a boolean
        # would hide exactly the distinction the terrain correction exists for.
        terrain_correction=detection.get("terrain_correction"),
        terrain_correction_reference=detection.get("terrain_correction_reference"),
        geometry_valid_fraction=detection.get("geometry_valid_fraction"),
        geometry_shadow_fraction=detection.get("geometry_shadow_fraction"),
        geometry_layover_fraction=detection.get("geometry_layover_fraction"),
        look_azimuth_deg=detection.get("look_azimuth_deg"),
        look_azimuth_source=detection.get("look_azimuth_source"),
        dem_for_geometry=detection.get("dem_for_geometry"),
        orbit_pass=detection.get("orbit_pass"),
        relative_orbit=detection.get("relative_orbit"),
        pre_scenes_on_track=detection.get("pre_scenes_on_track"),
        largest_component_m2=detection.get("largest_component_m2"),
        min_component_m2=detection.get("min_component_m2"),
        lake_elevation_spread_m=detection.get("lake_elevation_spread_m"),
        lake_mean_slope_deg=detection.get("lake_mean_slope_deg"),
        lake_mean_elevation_m=detection.get("lake_mean_elevation_m"),
        passes_flatness=detection.get("passes_flatness"),
        flatness_dem=detection.get("flatness_dem"),
        amplitude_form_fraction=detection.get("amplitude_form_fraction"),
        amplitude_threshold_db=detection.get("amplitude_threshold_db"),
        bbox=detection.get("bbox"),
        mask_geotiff_url=(
            _to_file_url(detection["mask_geotiff_path"])
            if detection.get("mask_geotiff_path") else None
        ),
        mask_png_url=(
            _to_file_url(detection["mask_png_path"])
            if detection.get("mask_png_path") else None
        ),
        note=detection.get("note"),
    )


@app.post("/runs/{run_id}/open-paraview")
def open_in_paraview(run_id: str) -> Dict[str, Any]:
    """
    Launch the ParaView DESKTOP GUI on the API host, showing this run in 3D.

    LOCAL-ONLY BY CONSTRUCTION. This starts a windowed application on whatever
    machine runs this process. That is the point for the demo, where the browser
    and the API share a laptop — but it means the button does nothing useful for
    a remote user of a deployed API, and under docker-compose the api container
    is headless Linux with no ParaView installed. Those cases are reported, not
    hidden: see the `reason` values below.

    Returns a structured result rather than raising, because the ways this can
    fail are genuinely different and a bare 500 would collapse them into one
    opaque error:

      launched            ok — a new ParaView window is opening
      not_done            the run has not finished
      no_dataset          no XDMF for this run (see below)
      paraview_not_found  the executable is not where settings say it is
      state_build_failed  pvpython could not build the .pvsm (stderr included)

    `no_dataset` is expected for two legitimate reasons: the run used
    solver="delft3d"/"both", which produce an analytic estimate with no depth
    series to visualize; or the run predates the XDMF wiring in tasks.py, since
    the solver output is discarded when the task returns and cannot be recovered
    afterwards. scripts/backfill_xdmf.py re-runs the solver for the latter.

    Clicking twice opens a second window. That is Popen doing exactly what it
    says, and is more useful than an error — a second view of the same run at a
    different camera angle is a reasonable thing to want.
    """
    import os
    import subprocess

    run = _run_status(run_id)
    if run["status"] != "done":
        return {"launched": False, "reason": "not_done",
                "detail": f"Run status is {run['status']!r}; nothing to visualize yet."}

    xdmf_path = next(
        (e["path_or_url"] for e in db.get_exports(run_id) if e["kind"] == "xdmf"), None)
    if not xdmf_path or not Path(xdmf_path).exists():
        return {
            "launched": False, "reason": "no_dataset",
            "detail": (
                "No 3D dataset for this run. Runs using solver='delft3d' or "
                "'both' produce an analytic estimate with no depth series to "
                "render. Runs created before the XDMF export was added cannot "
                "be given one retroactively — the solver output is not kept — "
                "so re-create the run, or run "
                f"`python scripts/backfill_xdmf.py --run-id {run_id}`."
            ),
        }

    paraview_exe = settings.PARAVIEW_EXE
    if not os.path.exists(paraview_exe):
        return {
            "launched": False, "reason": "paraview_not_found",
            "detail": (
                f"ParaView is not at {paraview_exe!r}. Set JALRAKSHA_PARAVIEW_EXE "
                f"to the full path of paraview.exe (the GUI — not pvpython.exe, "
                f"which is headless). If the API is running in a container or on "
                f"a remote host, this endpoint cannot work at all: it opens a "
                f"desktop window on the API's own machine."
            ),
        }

    # A .pvsm bakes in the dataset path, so it is per-run and cannot be a shared
    # template. Build it once and reuse it on subsequent clicks.
    #
    # (This comment used to claim the path baked in was absolute. It was not, and
    # that wrong assumption is exactly why nothing guarded against the relative
    # path that made every restored state render blank.)
    # Absolute, always. DATA_DIR defaults to Path("./data"), so without this both
    # the dataset handed to pvpython and the --state given to paraview.exe are
    # relative and only work because those processes inherit the API's CWD. The
    # dataset path is the load-bearing one: ParaView writes it into the .pvsm
    # verbatim and resolves it on restore against the opening process's CWD, so a
    # relative value produced a state that rendered blank for anyone who opened it
    # any other way. render_static.py now resolves it too; this keeps the service
    # from emitting CWD-dependent paths in the first place.
    xdmf_path = str(Path(xdmf_path).resolve())
    state_path = (settings.DATA_DIR / "simulation" / f"{run_id}.pvsm").resolve()

    render_script = Path(__file__).resolve().parents[3] / "paraview" / "render_static.py"
    # Rebuild when the state is missing, older than the dataset, OR older than the
    # code that generates it. A .pvsm bakes in the dataset's timestep values and
    # animation frame count, so re-running scripts/backfill_xdmf.py with different
    # parameters leaves a state that scrubs the wrong range while silently reading
    # the new file.
    #
    # The generator check is what makes a bad-state bug self-correcting. States
    # written before paths were resolved to absolute are unopenable, and comparing
    # only against the .xdmf would have left every one of them cached forever —
    # the fix would have looked like it did nothing.
    # This module is a generator too: it decides --exaggeration, --depth-max and
    # --focus-water. Omitting it meant that when those switched from hardcoded
    # literals to per-dam preset values, every already-cached .pvsm kept its old
    # 1.5x terrain warp forever — the fix would have looked like it did nothing.
    generators = [render_script, render_script.parent / "camera_presets.py",
                  Path(__file__).resolve()]
    newest_input = max(
        [Path(xdmf_path).stat().st_mtime]
        + [g.stat().st_mtime for g in generators if g.exists()]
    )
    stale = state_path.exists() and state_path.stat().st_mtime < newest_input
    if not state_path.exists() or stale:
        # pvpython, not this interpreter: ParaView's bundled Python cannot import
        # jalraksha (rasterio is absent), and this process cannot import
        # paraview.simple. The two only ever meet through files on disk.
        # The visual arguments come from THIS DAM's preset, not from
        # render_static.py's defaults. They used to be a fixed literal list, so
        # every dam rendered at --exaggeration 1.5 and --depth-max 25.0
        # regardless of its own preset — confirmed in the generated .pvsm files,
        # where both dams' WarpByScalar.ScaleFactor read 1.5.
        #
        # That is not cosmetic for a dam like Khadakwasla. Its terrain has
        # 1,170 m of relief across 54 km (Tehri: 6,495 m across 120 km), so at
        # 1.5x it renders as a near-flat plate — its preset asks for 2.0. And a
        # colour ramp scaled to 25 m leaves a 13.4 m flood at 53% saturation,
        # washing the water out to pale blue; its preset asks for 18.5 m.
        preset = _run_preset(run)
        cmd = [
            settings.PVPYTHON_EXE, str(render_script),
            "--xdmf", str(xdmf_path),
            "--with-water", "--glyphs", "--show-area",
            "--exaggeration", str(preset["vertical_exaggeration"]),
            "--depth-max", str(preset["nominal_depth_m"]),
            # Frame the flood, not the whole domain. A 6 km2 inundation inside a
            # 54 km box is a hairline at whole-domain framing.
            "--focus-water",
            "--save-state", str(state_path),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if proc.returncode != 0 or not state_path.exists():
            return {
                "launched": False, "reason": "state_build_failed",
                "detail": (proc.stderr or proc.stdout or "pvpython produced no output"
                           ).strip()[-1200:],
            }

    # Popen, not run: return as soon as the GUI is handed off. Waiting here would
    # block a threadpool worker for as long as the user leaves ParaView open.
    subprocess.Popen([paraview_exe, f"--state={state_path}"])
    return {
        "launched": True, "reason": "launched",
        "detail": "ParaView is opening in a new window on the machine running this API.",
        "state_path": str(state_path),
        "xdmf_path": str(xdmf_path),
    }
