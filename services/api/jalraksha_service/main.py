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
        },
    }
    run_id = db.create_run(dam_id, run_record, req.solver)
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

    return RunResult(
        run_id=run_id,
        dam_name=run.get("params", {}).get("name", "Dam"),
        exports=[ExportRef(kind=e["kind"], path_or_url=_to_file_url(e["path_or_url"])) for e in exports_rows],
        keyframe_manifest_url=_to_file_url(manifest_url) if manifest_url else None,
        gauges=[GaugeResult(**g) for g in gauges_rows],
        hazard_summary=hazard_summary,
        population_at_risk=population_at_risk,
    )


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
    generators = [render_script, render_script.parent / "camera_presets.py"]
    newest_input = max(
        [Path(xdmf_path).stat().st_mtime]
        + [g.stat().st_mtime for g in generators if g.exists()]
    )
    stale = state_path.exists() and state_path.stat().st_mtime < newest_input
    if not state_path.exists() or stale:
        # pvpython, not this interpreter: ParaView's bundled Python cannot import
        # jalraksha (rasterio is absent), and this process cannot import
        # paraview.simple. The two only ever meet through files on disk.
        cmd = [
            settings.PVPYTHON_EXE, str(render_script),
            "--xdmf", str(xdmf_path),
            "--with-water", "--glyphs", "--show-area",
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
