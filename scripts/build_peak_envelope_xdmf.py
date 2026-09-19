"""
Give a finished run a ParaView 3D view WITHOUT re-running the solver.

WHY THIS EXISTS

The ParaView button needs an XDMF dataset. Runs launched from scripts (the
500 x 400 km Khadakwasla GPU runs, for instance) never got one: the script
registration path wrote keyframes and rasters but not the XDMF, and the depth
time series it would have been built from was discarded after the keyframes
were drawn. Re-solving costs hours per run (~8 h each for those two).

WHAT IT BUILDS, AND WHAT IT DOES NOT

Two things on disk are exact and sufficient for a 3D picture:

* the TERRAIN the solver ran on. ``build_domain`` -> ``compute_breach_location``
  -> ``_notch_breach_into_bed`` is deterministic, so it is rebuilt from the same
  DEM, margins and resolution, and then CHECKED: the rebuilt grid must equal the
  run's recorded grid exactly (nx, ny, dx, dy, x0, y0, crs) or nothing is
  written;
* the ensemble-median MAXIMUM depth, ``h_max_median_cog.tif``.

The result is a PEAK-DEPTH ENVELOPE: one state holding each cell's maximum
depth over the whole run. It is not an animation and carries no velocity (none
was stored; zeros would render as still water). The file says so
(``dataset_kind="peak_envelope"``, ``is_peak_envelope=1``), the ParaView scene
labels it, and the dashboard's ParaView hint says it.

A run whose ``run_summary.json`` recorded no DEM needs ``--dem``; the path is
asserted, not guessed, and the grid check is what catches a wrong one.

Dry run by default; ``--apply`` writes the dataset and replaces the run's
``xdmf`` export row.

    python scripts/build_peak_envelope_xdmf.py bf0839d4... 81e0578b... \\
        --dem data/dem_wide/dem/dem_18.44_73.77_clipped.tif --apply
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]

#: Grid keys that must match the run's record exactly for the rebuilt terrain
#: to be the terrain the run was solved on.
GRID_KEYS = ("nx", "ny", "dx", "dy", "x0", "y0", "crs")

#: The drainage-check script's fixed terrain settings (it does not record them
#: because they are not arguments). Anything that differs is caught by the grid
#: check only if it changes the grid; these two change the BED, so they are
#: stated here with their source.
FILL_MAX_DEPTH_M = 3.0      # run_khadakwasla_drainage_check.py passes 3.0
NOTCH_BREACH = True         # run_khadakwasla_drainage_check.py passes True

#: params_json keys that are bookkeeping, not dam configuration.
_NOT_DAM_CONFIG = ("_solver_params", "progress_pct", "worker_pid", "phase")


class EnvelopeError(RuntimeError):
    """The run cannot be given an honest envelope; the message says why."""


def _bootstrap() -> None:
    sys.path.insert(0, str(REPO_ROOT / "services" / "api"))
    from jalraksha_service.script_runs import bootstrap_repo_root

    bootstrap_repo_root(REPO_ROOT)


def grids_match(rebuilt: Dict[str, Any], recorded: Dict[str, Any]) -> Optional[str]:
    """None when the grids agree on every GRID_KEYS field, else the first mismatch."""
    for key in GRID_KEYS:
        a, b = rebuilt.get(key), recorded.get(key)
        if isinstance(a, float) or isinstance(b, float):
            if a is None or b is None or abs(float(a) - float(b)) > 1e-6:
                return f"{key}: rebuilt {a!r} vs recorded {b!r}"
        elif a != b:
            return f"{key}: rebuilt {a!r} vs recorded {b!r}"
    return None


def read_cog_south_up(path: Path, grid: Dict[str, Any]):
    """
    Read a single-band solver COG back onto the solver's (ny, nx) array.

    COGs are written north-up (``geotiff.to_north_up`` flips); the solver and
    ``write_xdmf_series`` want row 0 = SOUTH. The transform and shape are
    asserted against the grid first, so a raster from a different domain can
    never be flipped into place and look right.
    """
    import numpy as np
    import rasterio

    from jalraksha.export.georef import grid_affine

    with rasterio.open(path) as src:
        if (src.height, src.width) != (int(grid["ny"]), int(grid["nx"])):
            raise EnvelopeError(
                f"{path.name} is {src.height}x{src.width}, grid is "
                f"{grid['ny']}x{grid['nx']}")
        expected = grid_affine(grid)
        if not src.transform.almost_equals(expected, precision=1e-6):
            raise EnvelopeError(
                f"{path.name} transform {tuple(src.transform)[:6]} does not match "
                f"the grid's {tuple(expected)[:6]}")
        data = src.read(1).astype("float32")
    data = np.flipud(data)
    return np.where(np.isfinite(data), data, 0.0)


def _rebuild_terrain(dam_config, dem_path, solver_params):
    from jalraksha.run import _notch_breach_into_bed
    from jalraksha.terrain.domain import (
        build_domain, compute_breach_location, compute_utm_zone,
    )

    grid, state, _manning = build_domain(
        dam_config,
        str(dem_path),
        target_resolution=float(solver_params["target_resolution"]),
        margins_km=solver_params.get("domain_margins_km"),
        fill_max_depth_m=FILL_MAX_DEPTH_M,
        condition_corridor_m=float(solver_params.get("condition_corridor_m") or 0.0),
    )
    lat, lon = dam_config["lat"], dam_config["lon"]
    i, j, b = compute_breach_location(
        state, grid, lat, lon, compute_utm_zone(lat, lon),
        inject_lat=dam_config.get("inject_lat", lat),
        inject_lon=dam_config.get("inject_lon", lon),
    )
    if NOTCH_BREACH:
        _notch_breach_into_bed(state, grid, i, j, b, dam_config)
    grid_dict = {"nx": grid.nx, "ny": grid.ny, "dx": grid.dx, "dy": grid.dy,
                 "x0": grid.x0, "y0": grid.y0, "crs": grid.crs}
    return grid_dict, state.b


def build_envelope(run_id: str, dem_override: Optional[Path], apply: bool) -> Path:
    from jalraksha.export.xdmf_export import write_xdmf_series
    from jalraksha_service import db
    from jalraksha_service.config import settings

    run = db.get_run(run_id)
    if run is None:
        raise EnvelopeError("no such run")
    if run["status"] != "done":
        raise EnvelopeError(f"status is {run['status']!r}, not 'done'")

    exports = {e["kind"]: Path(e["path_or_url"]) for e in db.get_exports(run_id)}
    summary_path = exports.get("run_summary")
    h_max_path = exports.get("cog_h_max_median")
    if not summary_path or not summary_path.exists():
        raise EnvelopeError("no run_summary.json; the recorded grid is unknown")
    if not h_max_path or not h_max_path.exists():
        raise EnvelopeError("no h_max_median COG; there is no depth to show")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    recorded_grid = summary.get("grid") or {}
    if recorded_grid.get("x0") is None or recorded_grid.get("y0") is None:
        raise EnvelopeError("the run's grid origin was never recorded")

    params = run.get("params") or {}
    solver_params = params.get("_solver_params") or {}
    if solver_params.get("target_resolution") is None:
        raise EnvelopeError("no recorded target_resolution; cannot rebuild the domain")
    dam_config = {k: v for k, v in params.items() if k not in _NOT_DAM_CONFIG}

    recorded_dem = (summary.get("dem") or {}).get("dem_used")
    dem_path = Path(recorded_dem) if recorded_dem else dem_override
    if dem_path is None:
        raise EnvelopeError(
            "run_summary.json recorded no DEM; pass --dem with the file the run "
            "used (the grid check will refuse a wrong one)")
    if not dem_path.exists():
        raise EnvelopeError(f"DEM {dem_path} does not exist")

    print(f"{run_id[:8]}  rebuilding terrain from {dem_path} "
          f"({recorded_grid['nx']}x{recorded_grid['ny']} @ {recorded_grid['dx']:.0f} m)…",
          flush=True)
    grid, terrain = _rebuild_terrain(dam_config, dem_path, solver_params)
    mismatch = grids_match(grid, recorded_grid)
    if mismatch:
        raise EnvelopeError(f"rebuilt domain is not the run's domain ({mismatch})")

    h_max = read_cog_south_up(h_max_path, grid)
    wet = int((h_max > 0.01).sum())
    print(f"{run_id[:8]}  grid matches; peak envelope has {wet:,} wet cells, "
          f"max {float(h_max.max()):.2f} m", flush=True)
    if wet == 0:
        raise EnvelopeError("the median maximum depth is dry everywhere")

    out_stem = settings.DATA_DIR / "simulation" / run_id
    if not apply:
        print(f"{run_id[:8]}  dry run: would write {out_stem}.xdmf/.h5")
        return out_stem.with_suffix(".xdmf")

    xdmf_path = write_xdmf_series(
        out_stem, grid, terrain,
        [{"time_s": float(solver_params.get("solver_duration_s") or 0.0),
          "depth": h_max}],
        is_synthetic=False,
        include_velocity=False,
        dataset_kind="peak_envelope",
        provenance={
            "run_id": run_id,
            "dam_name": dam_config.get("name", "Dam"),
            "dam_lat": dam_config.get("lat"),
            "dam_lon": dam_config.get("lon"),
            "solver": "peak-depth envelope (ensemble-median maximum depth)",
            "source": ("scripts/build_peak_envelope_xdmf.py: rebuilt terrain + "
                       "stored h_max_median COG; solver not re-run"),
            "dem": str(dem_path),
        },
    )
    db.replace_export(run_id, "xdmf", str(xdmf_path))
    print(f"{run_id[:8]}  wrote {xdmf_path} and set the run's xdmf export")
    return xdmf_path


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("run_ids", nargs="+")
    parser.add_argument("--dem", type=Path, default=None,
                        help="DEM the run used, when run_summary.json recorded none")
    parser.add_argument("--apply", action="store_true", help="write; default is a dry run")
    args = parser.parse_args(argv)

    _bootstrap()
    dem = args.dem.resolve() if args.dem else None
    failures = 0
    for run_id in args.run_ids:
        try:
            build_envelope(run_id, dem, args.apply)
        except EnvelopeError as exc:
            print(f"{run_id[:8]}  REFUSED: {exc}")
            failures += 1
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
