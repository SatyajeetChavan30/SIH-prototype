"""
Export a simulation to a MATLAB .mat file (spec section 21).

This is the seam between the two halves of the system: Python owns DEM I/O and
the validated shallow-water solver, MATLAB owns 3D visualization. Everything
MATLAB needs travels through the single struct written here, so the MATLAB side
needs no Mapping Toolbox, no GeoTIFF reader, and no solver.

Contract (all spatial values in a projected metric CRS, never degrees):

    sim.time              (1 x nt)        double, seconds, strictly increasing
    sim.x                 (1 x nx)        double, metres, easting, increasing
    sim.y                 (1 x ny)        double, metres, northing, increasing
    sim.terrainElevation  (ny x nx)       single, metres          <- stored ONCE
    sim.waterDepth        (ny x nx x nt)  single, metres
    sim.velocityX         (ny x nx x nt)  single, m/s
    sim.velocityY         (ny x nx x nt)  single, m/s
    sim.crs               char, e.g. 'EPSG:32644'
    sim.isSynthetic       logical         <- drives the SYNTHETIC banner
    sim.provenance        struct

ORIENTATION — the one thing that must not be got wrong. Row 0 is the
SOUTHERNMOST row, because jalraksha.solver.types.Grid.cell_centres_y() increases
northward. Image formats put row 0 at the top (north), and that exact mismatch
rendered this project's keyframe PNGs upside-down once already. MATLAB's
surf(X, Y, Z) wants Y increasing, which matches the solver's convention, so the
arrays cross the boundary unflipped and _assert_orientation() enforces it here
rather than leaving MATLAB to guess.

waterLevel is deliberately NOT stored: it is exactly terrainElevation +
waterDepth, and duplicating the largest array would violate the spec's own rule
against redundant copies (section 20).
"""

from __future__ import annotations

import datetime
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

# Visualization-only fields. float32 halves the file with no visible effect on a
# rendered surface; the solver itself remains float64 (types.py precision policy).
EXPORT_DTYPE = np.float32


class MatlabExportError(Exception):
    """Raised when a simulation cannot be expressed in the .mat contract."""


def _git_sha() -> str:
    """Short commit hash, so a .mat can be traced back to the code that made it."""
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except Exception:
        return "unknown"


def _axis_from_grid(grid: Dict[str, Any]) -> tuple:
    """
    Cell-centre coordinate vectors in metres, both strictly increasing.

    Mirrors Grid.cell_centres_x/y (origin + (i + 0.5) * spacing) rather than
    recomputing a different convention — a half-cell disagreement would offset
    the whole terrain against the water.
    """
    nx, ny = int(grid["nx"]), int(grid["ny"])
    dx, dy = float(grid["dx"]), float(grid["dy"])
    x0, y0 = float(grid.get("x0", 0.0)), float(grid.get("y0", 0.0))
    x = x0 + (np.arange(nx, dtype=np.float64) + 0.5) * dx
    y = y0 + (np.arange(ny, dtype=np.float64) + 0.5) * dy
    return x, y


def _assert_orientation(x: np.ndarray, y: np.ndarray) -> None:
    """Fail loudly if the axes are not increasing — see ORIENTATION above."""
    if not np.all(np.diff(x) > 0):
        raise MatlabExportError("x axis must be strictly increasing (metres, easting).")
    if not np.all(np.diff(y) > 0):
        raise MatlabExportError(
            "y axis must be strictly increasing (metres, northing). Row 0 must be "
            "the southernmost row; do not flip arrays before exporting."
        )


def _stack(series: List[Dict[str, Any]], key: str, shape: tuple) -> np.ndarray:
    """Stack a per-snapshot field into (ny, nx, nt), the layout MATLAB indexes."""
    if not series:
        return np.zeros(shape + (0,), dtype=EXPORT_DTYPE)
    frames = []
    for idx, snap in enumerate(series):
        if key not in snap:
            raise MatlabExportError(
                f"Snapshot {idx} has no '{key}'. Velocity capture was added to "
                f"jalraksha/solver/parallel.py::_snapshot — a simulation recorded "
                f"before that change cannot supply velocity fields; re-run it."
            )
        frame = np.asarray(snap[key], dtype=EXPORT_DTYPE)
        if frame.shape != shape:
            raise MatlabExportError(
                f"Snapshot {idx} '{key}' has shape {frame.shape}, expected {shape}."
            )
        frames.append(frame)
    return np.stack(frames, axis=-1)


def export_simulation_mat(
    result: Dict[str, Any],
    out_path: Path | str,
    *,
    is_synthetic: bool = False,
    dem_path: Optional[str] = None,
    dam_config: Optional[Dict[str, Any]] = None,
) -> Path:
    """
    Write a run from run_dam_break_ensemble() to a .mat for the MATLAB viewer.

    Args:
        result: Return value of run_dam_break_ensemble(record_depth_snapshots=True).
        out_path: Destination .mat path.
        is_synthetic: True if any part of this run used fallback/synthetic data.
            Travels inside the file so a mislabeled dataset cannot be produced by
            forgetting a UI flag (spec section 0).
        dem_path: Source DEM, recorded for provenance.
        dam_config: Dam parameters, recorded for provenance.

    Returns:
        The path written.
    """
    from scipy.io import savemat

    if "grid" not in result:
        raise MatlabExportError("result has no 'grid'; was this run_dam_break_ensemble()?")
    if "terrain_elevation" not in result:
        raise MatlabExportError(
            "result has no 'terrain_elevation'. run_dam_break_ensemble now returns "
            "the bed it solved over; a result from before that change cannot be "
            "exported without risking a terrain that differs from the flood."
        )

    grid = result["grid"]
    ny, nx = int(grid["ny"]), int(grid["nx"])
    x, y = _axis_from_grid(grid)
    _assert_orientation(x, y)

    terrain = np.asarray(result["terrain_elevation"], dtype=EXPORT_DTYPE)
    if terrain.shape != (ny, nx):
        raise MatlabExportError(
            f"terrain_elevation shape {terrain.shape} does not match grid {(ny, nx)}."
        )

    series = result.get("depth_series") or []
    if not series:
        # Terrain-only export is legitimate (phase 1 renders terrain before any
        # water exists), but it must be an explicit, visible state rather than a
        # silently empty water array.
        print(
            "[matlab_export] No depth_series in result — writing a TERRAIN-ONLY .mat. "
            "Re-run with record_depth_snapshots=True to include water."
        )

    times = np.array([float(s["time_s"]) for s in series], dtype=np.float64)
    if times.size and not np.all(np.diff(times) > 0):
        raise MatlabExportError(f"snapshot times are not strictly increasing: {times}")

    water_depth = _stack(series, "depth", (ny, nx))
    velocity_x = _stack(series, "velocity_x", (ny, nx))
    velocity_y = _stack(series, "velocity_y", (ny, nx))

    crs = str(grid.get("crs", "EPSG:32644"))
    if "EPSG" not in crs.upper():
        raise MatlabExportError(
            f"grid crs {crs!r} is not an EPSG code; the MATLAB side assumes a "
            f"projected metric CRS and does no reprojection."
        )

    sim = {
        "time": times.reshape(1, -1),
        "x": x.reshape(1, -1),
        "y": y.reshape(1, -1),
        "terrainElevation": terrain,
        "waterDepth": water_depth,
        "velocityX": velocity_x,
        "velocityY": velocity_y,
        "crs": crs,
        "isSynthetic": bool(is_synthetic),
        "provenance": {
            "dem_path": str(dem_path or ""),
            "solver": "jalraksha SWE (HLLC + Audusse, well-balanced)",
            "dam_name": str(result.get("dam_name", "")),
            "git_sha": _git_sha(),
            "created_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "num_ensemble": int(result.get("num_ensemble", 0)),
            "num_completed": int(result.get("num_completed", 0)),
            "dam_config": {k: str(v) for k, v in (dam_config or {}).items()},
        },
    }

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # do_compression keeps a 600x600x30 run comfortably small; oned_as='row' so
    # the coordinate vectors arrive in MATLAB as 1 x n rather than n x 1.
    savemat(str(out_path), {"sim": sim}, do_compression=True, oned_as="row")

    nt = int(times.size)
    size_mb = out_path.stat().st_size / 1e6
    label = "SYNTHETIC" if is_synthetic else "real solver"
    print(
        f"[matlab_export] {out_path}  ({size_mb:.1f} MB)\n"
        f"  grid {ny} x {nx} @ {grid['dx']:.0f} m   {crs}\n"
        f"  {nt} snapshot(s)"
        + (f", t = {times[0]:.0f}..{times[-1]:.0f} s" if nt else " (terrain only)")
        + f"\n  terrain {terrain.min():.1f}..{terrain.max():.1f} m   [{label}]"
    )
    return out_path
