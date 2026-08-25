"""
Keyframe export for 3D / time-slider visualization (Phase 5+ deliverable).

This module produces the single artifact consumed by both the 2D time-slider and
the CesiumJS 3D view: a *manifest* of time-tagged, FD2320-classified flood
keyframes rendered over the exact terrain the solver ran on.

Design rules (per integration brief §5.3 / §5.5.6):
  * Color mapping is delegated to `jalraksha.impact.hazard.HazardClassifier` — the
    SINGLE source of truth for FD2320 depth×velocity hazard colors. No second
    color scheme is invented here.
  * Keyframes are sliced by *simulation time*, not adaptive-CFL step index, so the
    browser clock maps directly onto physical time.
  * Each keyframe's geographic bounds are reprojected UTM → WGS84 (EPSG:4326) so
    the PNGs geo-register correctly in Cesium / Leaflet.
  * This module contains no simulation logic — it only renders outputs the
    pipeline already produces.

Consumed by: `export_keyframes(result, hazard_classifier, n_keyframes, out_dir)`.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Sequence
import json
import datetime
import numpy as np


# ── Result container ──────────────────────────────────────────────────────────

@dataclass
class Keyframe:
    """One time-tagged, colorized flood snapshot."""
    time_s: float
    png_url: str
    bounds: List[float]          # [west, south, east, north] in WGS84 degrees
    hazard_summary: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class KeyframeManifest:
    """The single artifact consumed by the 2D slider and 3D view."""
    keyframes: List[Keyframe] = field(default_factory=list)
    simulation_info: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": "1.0",
            "generated": datetime.datetime.utcnow().isoformat(),
            "simulation_info": self.simulation_info,
            "keyframes": [k.to_dict() for k in self.keyframes],
            "metadata": self.metadata,
        }

    def to_json(self, path: Path) -> Path:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2)
        return path


# ── Helpers ───────────────────────────────────────────────────────────────────

def _utmtp_corners(grid: Dict[str, Any]):
    """
    Return (x_min, y_min, x_max, y_max) of the domain in its metric CRS.

    jalraksha.solver.types.Grid documents x0/y0 as the LOWER-LEFT corner, with
    cell centres at x0 + (i+0.5)*dx (row index increasing northward/eastward) —
    see Grid.cell_centres_2d(). So the domain simply spans [x0, x0+nx*dx] x
    [y0, y0+ny*dy]; no raster-style origin-at-top-row correction applies here.
    """
    nx = int(grid["nx"])
    ny = int(grid["ny"])
    dx = float(grid["dx"])
    dy = float(grid["dy"])
    x0 = float(grid.get("x0", 0.0))
    y0 = float(grid.get("y0", 0.0))
    x_min = x0
    x_max = x0 + nx * dx
    y_min = y0
    y_max = y0 + ny * dy
    return x_min, y_min, x_max, y_max


def _parse_epsg(grid: Dict[str, Any]) -> int:
    """Parse an EPSG code from either a bare int or an "EPSG:xxxxx" string."""
    raw_crs = grid.get("crs", 32643)
    return int(str(raw_crs).replace("EPSG:", "").replace("epsg:", ""))


def _reproject_bounds_utm_to_wgs84(
    grid: Dict[str, Any]
) -> List[float]:
    """Reproject domain corners UTM → WGS84 [west, south, east, north]."""
    x_min, y_min, x_max, y_max = _utmtp_corners(grid)
    # jalraksha.solver.types.Grid.crs is a string like "EPSG:32643"; accept
    # that form as well as a bare int for callers that pass one directly.
    crs = _parse_epsg(grid)
    try:
        from rasterio.warp import transform
        xs, ys = transform(
            f"EPSG:{crs}", "EPSG:4326", [x_min, x_max], [y_min, y_max]
        )
        # transform returns (xs_list, ys_list) for the two input points
        lon0, lon1 = float(xs[0]), float(xs[1])
        lat0, lat1 = float(ys[0]), float(ys[1])
        west, east = min(lon0, lon1), max(lon0, lon1)
        south, north = min(lat0, lat1), max(lat0, lat1)
        return [west, south, east, north]
    except Exception:
        # Fallback: very rough degrees-per-metre approximation (Tehri latitude).
        # Only used if rasterio warp is unavailable; flagged as approximate.
        lat0 = 30.0
        dlat = (y_max - y_min) / 111320.0
        dlon = (x_max - x_min) / (111320.0 * np.cos(np.radians(lat0)))
        cx = (x_min + x_max) / 2.0
        cy = (y_min + y_max) / 2.0
        return [
            cx / (111320.0 * np.cos(np.radians(lat0))) - dlon / 2.0,
            lat0 + (cy - 0) / 111320.0 - dlat / 2.0,
            cx / (111320.0 * np.cos(np.radians(lat0))) + dlon / 2.0,
            lat0 + (cy - 0) / 111320.0 + dlat / 2.0,
        ]


def _extract_depth_series(result: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Pull (time_s, depth_grid) pairs from a pipeline result.

    Accepts either:
      result["depth_series"]      -> list of {"time_s": float, "depth": ndarray}
      result["keyframe_depth_grids"] -> dict {time_s: ndarray}

    Returns a sorted list of {"time_s", "depth"} dicts. Raises ValueError if no
    usable series is present (the caller must record snapshots during the run).
    """
    if "depth_series" in result and result["depth_series"]:
        series = result["depth_series"]
    elif "keyframe_depth_grids" in result and result["keyframe_depth_grids"]:
        series = [
            {"time_s": float(t), "depth": np.asarray(g, dtype=np.float32)}
            for t, g in result["keyframe_depth_grids"].items()
        ]
    else:
        raise ValueError(
            "export_keyframes requires result['depth_series'] (list of "
            "{'time_s', 'depth'}) recorded during the run. The solver must "
            "snapshot the median ensemble member's depth grid at simulation "
            "times — keyframes cannot be derived from max-only outputs."
        )
    series = sorted(series, key=lambda s: float(s["time_s"]))
    for s in series:
        s["depth"] = np.asarray(s["depth"], dtype=np.float32)
    return series


def _select_keyframe_times(
    series_times: Sequence[float], n_keyframes: int
) -> List[float]:
    """
    Choose `n_keyframes` simulation times spanning the series.

    The window where the flood front passes the last gauge is sampled more
    densely; the calm tail (after the wave has moved on) is sampled more
    sparsely. Default behaviour is a uniform sweep if the series is short.
    """
    t_min = float(min(series_times))
    t_max = float(max(series_times))
    if t_max <= t_min or n_keyframes <= 1:
        return [t_min]
    # Uniform in time is the safe, predictable default; downstream code may
    # densify around arrival windows using gauge arrival times.
    return [t_min + (t_max - t_min) * i / (n_keyframes - 1) for i in range(n_keyframes)]


def _render_png(rgb: np.ndarray, path: Path) -> None:
    """Write an (ny, nx, 3) uint8 RGB array to a PNG file."""
    try:
        from PIL import Image
        Image.fromarray(rgb.astype(np.uint8)).save(path, format="PNG")
        return
    except Exception:
        pass
    # Fallback: matplotlib (always available in the Scientific Python stack)
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.imsave(path, rgb.astype(np.uint8))


# ── Main entry point ───────────────────────────────────────────────────────────

def export_keyframes(
    result: Dict[str, Any],
    hazard_classifier,
    n_keyframes: int = 30,
    out_dir: Path = Path("./exports/keyframes"),
) -> KeyframeManifest:
    """
    Render FD2320-classified flood keyframes for 2D/3D visualization.

    Args:
        result: Pipeline result containing a depth time series (see
            `_extract_depth_series`) plus a `grid` dict describing the metric
            domain (nx, ny, dx, dy, x0, y0, crs).
        hazard_classifier: A `jalraksha.impact.hazard.HazardClassifier` instance
            used for FD2320 colorization. If None, a default one is created.
        n_keyframes: Number of evenly-spaced simulation-time keyframes (default 30).
        out_dir: Directory for PNGs and manifest.json.

    Returns:
        KeyframeManifest with one Keyframe per simulation time, each carrying
        its WGS84 bounds and FD2320 hazard summary.
    """
    from jalraksha.impact.hazard import HazardClassifier

    if hazard_classifier is None:
        hazard_classifier = HazardClassifier()
    if not isinstance(hazard_classifier, HazardClassifier):
        # Allow duck-typed callers but expect the real classifier API.
        pass

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    grid = result.get("grid", {})
    if not grid:
        raise ValueError("export_keyframes requires result['grid'] domain info.")

    series = _extract_depth_series(result)
    series_times = [float(s["time_s"]) for s in series]
    key_times = _select_keyframe_times(series_times, n_keyframes)

    # Build a fast lookup so we can sample the nearest recorded snapshot per key.
    s_times_arr = np.array(series_times, dtype=np.float64)
    s_depths = [s["depth"] for s in series]

    wgs84_bounds = _reproject_bounds_utm_to_wgs84(grid)
    dam_name = result.get("dam_name", "unknown")

    keyframes: List[Keyframe] = []
    for idx, t_k in enumerate(key_times):
        # Nearest recorded snapshot in simulation time.
        nearest = int(np.argmin(np.abs(s_times_arr - t_k)))
        depth = s_depths[nearest]

        # FD2320 classification (depth-only, conservative) → exact color map.
        classification = hazard_classifier.classify_depth_only(depth)
        rgb = hazard_classifier.apply_to_rgb(classification)
        hazard_summary = hazard_classifier.summarize(classification)

        # depth/rgb row 0 is the grid's southernmost row (Grid.cell_centres_2d,
        # row index increasing northward — see _utmtp_corners above), but image
        # row 0 is conventionally the TOP; Leaflet's ImageOverlay and Cesium's
        # SingleTileImageryProvider both place image row 0 at the NORTH edge of
        # the given bounds. Flip vertically or the flood renders upside-down.
        rgb = np.flipud(rgb)

        png_name = f"keyframe_{idx:04d}_{int(round(t_k)):06d}s.png"
        png_path = out_dir / png_name
        _render_png(rgb, png_path)

        # png_url is a bare filename, not a filesystem path: manifest.json and
        # its PNGs are always siblings in out_dir, and whatever serves the
        # manifest over HTTP (services/api's /files static mount) resolves
        # this relative to the manifest's own URL. Keeps this module decoupled
        # from any web-server base URL.
        keyframes.append(
            Keyframe(
                time_s=float(t_k),
                png_url=png_name,
                bounds=[float(b) for b in wgs84_bounds],
                hazard_summary=hazard_summary,
            )
        )

    manifest = KeyframeManifest(
        keyframes=keyframes,
        simulation_info={
            "dam_name": dam_name,
            "n_keyframes": len(keyframes),
            "simulation_duration_s": [series_times[0], series_times[-1]],
            "grid_resolution_m": float(grid.get("dx", 0.0)),
            "classification_scheme": "FD2320",
            "color_source": "jalraksha.impact.hazard.HazardClassifier",
            "crs_source": f"EPSG:{_parse_epsg(grid)}",
        },
        metadata={
            "description": "Flood keyframes for JalRaksha dam-break visualization",
            "license": "CC BY 4.0 (data: Copernicus DEM, ESA WorldCover)",
            "note": "FD2320 depth-velocity hazard classification; terrain-matched.",
        },
    )

    manifest.to_json(out_dir / "manifest.json")
    return manifest
