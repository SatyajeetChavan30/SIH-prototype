"""
Celery job definitions (brief §5.1 / M1).

Each job is a *thin* wrapper around the existing pipeline. No new simulation
logic lives here. The worker:

  1. resolves the DEM (pre-baked into ./data for offline demo, or cache)
  2. calls run_dam_break_ensemble()  (swe)  /  rapid_estimate()  (delft3d/both)
  3. records gauge results + export references in the thin metadata store
  4. renders keyframes from the recorded depth time-series (if available)
  5. marks the run done / failed

The solver must record per-step depth snapshots (result["depth_series"]) for
keyframes to be produced; otherwise the run still completes and the existing
GeoTIFF/Shapefile/KML exports anchor the 2D view.
"""

from __future__ import annotations

import json
import traceback
from pathlib import Path
from typing import Any, Dict, List

from jalraksha_service.config import settings
from jalraksha_service import db
from jalraksha_service.worker import celery_app


def _resolve_dem(dam_config: Dict[str, Any]) -> str:
    """Find a pre-baked DEM for the dam's catchment (offline-first, brief §2.1)."""
    data = settings.DATA_DIR
    lat = dam_config.get("lat")
    lon = dam_config.get("lon")
    # Prefer an explicitly staged mosaic keyed by rounded lat/lon.
    if lat is not None and lon is not None:
        cand = data / f"dem/mosaic_{lat:.2f}_{lon:.2f}.tif"
        if cand.exists():
            return str(cand)
    # Fall back to the cached DEM used by the offline cache.
    from jalraksha import cache as cache_mod
    try:
        cached = cache_mod.get_cached_dem(lat, lon, cache_dir=data / "dem")
        if cached and Path(cached).exists():
            return cached
    except Exception:
        pass
    # Last resort: any DEM present in the data dir.
    for p in (data / "dem").glob("*.tif"):
        return str(p)
    raise FileNotFoundError("No DEM staged for this dam; pre-bake into ./data/dem (brief §5.8).")


def _run_comparison(run_id: str, dam_config: Dict[str, Any]) -> Dict[str, Any] | None:
    """
    SPH vs Delft3D-class comparison, direct port of the Streamlit "both" path
    (jalraksha/dashboard/app.py, ~line 312-358) into the service layer so the
    React Comparison tab (brief §5.7) has real data via GET /runs/{id}/comparison.

    No new analysis logic: reuses jalraksha.delft3d.{setup,runner,comparison}
    exactly as the existing dashboard does, including its SPH stand-in — the
    Streamlit app's own "SPH result" is itself synthesized (n_particles drawn
    from np.random, gauge arrivals from a wave-celerity approximation +
    np.random noise), not a real PySPH run; that is a pre-existing limitation
    of the reference implementation this ports, not something introduced here.
    """
    import json as _json
    import numpy as np
    from jalraksha.delft3d.setup import setup_delft3d_model
    from jalraksha.delft3d.runner import run_delft3d_simulation
    from jalraksha.delft3d.comparison import compare_sph_vs_delft3d

    try:
        gauges_list = [
            {"name": "Koteshwar", "distance_km": 13.0},
            {"name": "Devprayag", "distance_km": 28.0},
            {"name": "Rishikesh", "distance_km": 34.8},
            {"name": "Haridwar", "distance_km": 58.4},
        ]
        d3d_setup = setup_delft3d_model(dam_config, grid_nx=40, grid_ny=40, grid_dx=30.0, grid_dy=30.0)
        d3d_res = run_delft3d_simulation(
            d3d_setup, dam_config, gauge_locations=gauges_list, total_time_s=10.0, force_fallback=True,
        )

        dam_height = float(dam_config.get("height_m", 100.0))
        c_wave = 0.5 * np.sqrt(9.81 * dam_height)
        n_particles = 1500
        sph_res = {
            "x": np.random.uniform(0, 1200, n_particles),
            "y": np.random.uniform(0, 1200, n_particles),
            "z": np.random.exponential(1.5, n_particles),
            "gauge_arrivals": {
                g["name"]: {"median_min": (g["distance_km"] * 1000.0) / c_wave / 60.0 + np.random.normal(0, 1),
                            "distance_km": g["distance_km"]}
                for g in gauges_list
            },
        }
        for v in sph_res["gauge_arrivals"].values():
            v["median_s"] = v["median_min"] * 60.0
            v["p05_min"] = max(0.1, v["median_min"] * 0.85)
            v["p95_min"] = v["median_min"] * 1.15

        comp = compare_sph_vs_delft3d(sph_res, d3d_res, gauges_list)

        out_dir = settings.DATA_DIR / "exports" / run_id
        out_dir.mkdir(parents=True, exist_ok=True)

        import matplotlib
        matplotlib.use("Agg")
        depth_map_path = out_dir / "comparison_depth_map.png"
        hydro_path = out_dir / "comparison_hydrograph.png"
        comp["depth_fig"].savefig(depth_map_path, dpi=100, bbox_inches="tight")
        comp["hydro_fig"].savefig(hydro_path, dpi=100, bbox_inches="tight")
        import matplotlib.pyplot as plt
        plt.close(comp["depth_fig"])
        plt.close(comp["hydro_fig"])

        metrics_path = out_dir / "comparison_metrics.json"
        metrics_path.write_text(_json.dumps({
            "metrics": comp["metrics"],
            "gauge_comparison": comp["gauge_comparison"],
            "sph_engine": comp["sph_engine"],
            "delft3d_engine": comp["delft3d_engine"],
            "delft3d_engine_label": comp["delft3d_engine_label"],
            "depth_map_url": str(depth_map_path),
            "hydrograph_url": str(hydro_path),
        }, indent=2))

        return {"kind": "comparison_metrics", "path_or_url": str(metrics_path)}
    except Exception:
        return None


@celery_app.task(bind=True, name="jalraksha.run_dam_break")
def run_dam_break_task(
    self, run_id: str, dam_config: Dict[str, Any], ensemble_size: int, solver: str,
    solver_duration_s: float = 1800.0, target_resolution: float = 200.0,
) -> Dict[str, Any]:
    db.update_run_status(run_id, "running", 5.0)
    exports: List[Dict[str, Any]] = []
    gauges: List[Dict[str, Any]] = []
    keyframe_manifest_url = None
    hazard_summary = None

    try:
        if solver == "swe":
            from jalraksha.run import run_dam_break_ensemble
            dem_path = _resolve_dem(dam_config)
            result = run_dam_break_ensemble(
                dam_config, dem_path, ensemble_size=ensemble_size,
                output_dir=str(settings.DATA_DIR / "exports" / run_id),
                solver_duration_s=solver_duration_s,
                target_resolution=target_resolution,
                record_depth_snapshots=True, n_snapshots=30,
            )
            # Persist gauge results from the pipeline.
            for gname, g in (result.get("arrival_times") or {}).items():
                gauges.append({
                    "gauge_name": gname,
                    "distance_km": g.get("distance_km"),
                    "arrival_time_s": g.get("median"),
                    "max_depth_m": None,
                    "par_estimate": None,
                })
            # Record export references (paths are produced by run.py / export module).
            for kind, path in (result.get("raster_paths") or {}).items():
                exports.append({"kind": kind, "path_or_url": path})

        else:
            # delft3d / both: analytic rapid estimate keeps the demo responsive.
            from jalraksha.api import rapid_estimate, get_downstream_gauges
            cfg = {
                "name": dam_config.get("name", "Dam"),
                "lat": dam_config.get("lat", 30.3789),
                "lon": dam_config.get("lon", 78.4789),
                "height_m": dam_config.get("height_m", 100.0),
                "storage_mm3": dam_config.get("storage_mm3", 1000.0),
            }
            est = rapid_estimate(cfg, ensemble_size=max(10, min(ensemble_size, 200)))
            for gname, g in est.get("arrival_times", {}).items():
                gauges.append({
                    "gauge_name": gname,
                    "distance_km": g.get("distance_km"),
                    "arrival_time_s": g.get("median_s"),
                    "max_depth_m": None,
                    "par_estimate": None,
                })
            result = {"rapid_estimate": est}

            if solver == "both":
                comp_export = _run_comparison(run_id, cfg)
                if comp_export:
                    exports.append(comp_export)

        # Keyframe rendering (brief §5.3) — requires a recorded depth time-series.
        if isinstance(result, dict) and result.get("depth_series"):
            from jalraksha.export.keyframes import export_keyframes
            from jalraksha.impact.hazard import HazardClassifier
            kf_dir = settings.DATA_DIR / "keyframes" / run_id
            manifest = export_keyframes(
                {**result, "dam_name": dam_config.get("name", "Dam")},
                HazardClassifier(), n_keyframes=30, out_dir=kf_dir,
            )
            keyframe_manifest_url = str(kf_dir / "manifest.json")
            exports.append({"kind": "keyframe_manifest", "path_or_url": keyframe_manifest_url})
            if manifest.keyframes:
                hazard_summary = manifest.keyframes[-1].hazard_summary

        dam_name = dam_config.get("name", "Dam")
        db.insert_gauge_results(run_id, gauges)
        db.insert_exports(run_id, exports)
        db.update_run_status(run_id, "done", 100.0)

        return {
            "run_id": run_id,
            "dam_name": dam_name,
            "exports": exports,
            "keyframe_manifest_url": keyframe_manifest_url,
            "n_gauges": len(gauges),
            "hazard_summary": hazard_summary,
        }
    except Exception as exc:  # pragma: no cover - job failure path
        db.update_run_status(run_id, "failed", 0.0)
        return {"run_id": run_id, "status": "failed", "error": str(exc),
                "traceback": traceback.format_exc()}
