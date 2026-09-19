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

# The one Phase 6 name this module needs at import time. HazardClassifier itself
# is still imported inside export_keyframes(), where it is used; this is the
# threshold the RGBA writer needs as a module constant, and importing it is the
# only way the overlay and the legend cannot drift apart.
from jalraksha.impact.hazard import WET_THRESHOLD_M


# ── Result container ──────────────────────────────────────────────────────────

@dataclass
class Keyframe:
    """One time-tagged, colorized flood snapshot."""
    time_s: float
    png_url: str
    bounds: List[float]          # [west, south, east, north] in WGS84 degrees
    hazard_summary: Dict[str, Any] = field(default_factory=dict)
    # Web-Mercator warp of the same frame, for Leaflet. Optional so manifests
    # written before the warp existed still load.
    png_url_mercator: Optional[str] = None
    bounds_mercator: Optional[List[float]] = None

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
    """
    WGS84 envelope [west, south, east, north] of the domain's FOUR corners.

    Reuses jalraksha.export.georef.wgs84_bounds, which reprojects all four
    corners of the metric grid to return the true bounding envelope in degrees.
    """
    from jalraksha.export.georef import wgs84_bounds
    crs = _parse_epsg(grid)
    w, s, e, n = wgs84_bounds(grid, crs)
    return [float(w), float(s), float(e), float(n)]


#: Projections the overlay PNGs are warped into, keyed by the manifest field
#: suffix. Cesium's SingleTileImageryProvider stretches an image linearly in
#: lat/lon; Leaflet's ImageOverlay stretches it linearly in Web Mercator.
OVERLAY_PROJECTIONS = {"geographic": "EPSG:4326", "mercator": "EPSG:3857"}


def _overlay_warps(grid: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """
    Destination grids for warping a north-up solver raster into each viewer's projection.

    Why this exists: the PNG used to BE the solver's UTM grid, flipped, and the
    viewers placed it inside a lat/lon box. That box is not the shape of a UTM
    rectangle, so every pixel lands a little off, and the offset grows with the
    size of the domain. On the 500 x 400 km Khadakwasla run the flood band sat
    visibly beside the Bhima near Daund rather than on it. Warping the pixels
    themselves removes the approximation instead of shrinking it.

    Returns {name: {"crs", "transform", "width", "height", "bounds"}} with bounds
    as [west, south, east, north] in DEGREES for both projections, because both
    viewers take degrees and do their own projection.
    """
    from rasterio.warp import calculate_default_transform, transform as warp_points

    nx, ny = int(grid["nx"]), int(grid["ny"])
    x_min, y_min, x_max, y_max = _utmtp_corners(grid)
    src_crs = f"EPSG:{_parse_epsg(grid)}"
    warps = {}
    for name, dst_crs in OVERLAY_PROJECTIONS.items():
        dst_transform, width, height = calculate_default_transform(
            src_crs, dst_crs, nx, ny, left=x_min, bottom=y_min, right=x_max, top=y_max)
        left, top = dst_transform * (0, 0)
        right, bottom = dst_transform * (width, height)
        if dst_crs != "EPSG:4326":
            (left, right), (bottom, top) = warp_points(dst_crs, "EPSG:4326", [left, right], [bottom, top])
        warps[name] = {
            "crs": dst_crs, "transform": dst_transform, "width": int(width), "height": int(height),
            "bounds": [float(left), float(bottom), float(right), float(top)],
        }
    return warps


def _warp_rgba(rgba_north_up: np.ndarray, grid: Dict[str, Any], warp: Dict[str, Any]) -> np.ndarray:
    """
    Warp a north-up (ny, nx, 4) uint8 RGBA frame onto one destination grid.

    NEAREST neighbour on purpose: every pixel is a hazard class colour plus a
    binary alpha, and blending two classes produces a colour that means nothing
    and a half-transparent edge the legend does not describe. Pixels outside the
    source footprint stay fully transparent.
    """
    from rasterio.transform import from_origin
    from rasterio.warp import Resampling, reproject

    x_min, _y_min, _x_max, y_max = _utmtp_corners(grid)
    src_transform = from_origin(x_min, y_max, float(grid["dx"]), float(grid["dy"]))
    source = np.ascontiguousarray(np.moveaxis(rgba_north_up.astype(np.uint8), -1, 0))
    destination = np.zeros((4, warp["height"], warp["width"]), dtype=np.uint8)
    reproject(
        source=source, destination=destination,
        src_transform=src_transform, src_crs=f"EPSG:{_parse_epsg(grid)}",
        dst_transform=warp["transform"], dst_crs=warp["crs"],
        resampling=Resampling.nearest, src_nodata=None, dst_nodata=0,
    )
    return np.moveaxis(destination, 0, -1)


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


def _render_png(rgba: np.ndarray, path: Path) -> None:
    """
    Write an (ny, nx, 4) uint8 RGBA array to a PNG file.

    RGBA, not RGB. These PNGs are drawn OVER a basemap — Leaflet's ImageOverlay
    in the 2D panel and Cesium's SingleTileImageryProvider in the 3D one — and
    an opaque image covers the map wherever the flood is not.

    That is what happened: HazardClassifier paints dry cells [128, 128, 128],
    and a 3-channel PNG has no way to say "nothing here". Every keyframe was a
    solid grey rectangle the size of the whole domain, with a thin coloured
    flood line on it, hiding the terrain and roads the flood is supposed to be
    read against. Both panels set a layer opacity (0.7 / 0.75), which made the
    grey translucent rather than absent — the map looked washed out and nobody
    could tell it was a bug rather than a style.
    """
    try:
        from PIL import Image
        Image.fromarray(rgba.astype(np.uint8), mode="RGBA").save(path, format="PNG")
        return
    except Exception:
        pass
    # Fallback: matplotlib (always available in the Scientific Python stack).
    # imsave handles a 4-channel array as RGBA, so transparency survives here
    # too.
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.imsave(path, rgba.astype(np.uint8))


#: Depth below which a cell is drawn as nothing at all.
#:
#: Aliased from the classifier's own wet threshold (imported at the top of this
#: module) rather than restated, so the transparent area is exactly the area the
#: classifier calls DRY and the overlay can never disagree with the legend
#: beside it. It was a literal 0.1 m matching the old band table's LOW minimum;
#: the FD2320 rating uses a 0.05 m wet threshold, and a hardcoded copy would
#: have left the 0.05-0.1 m ring classified LOW and drawn as nothing.
DRY_DEPTH_M = WET_THRESHOLD_M


def _to_rgba(rgb: np.ndarray, depth: np.ndarray) -> np.ndarray:
    """
    Add an alpha channel: opaque where there is water, transparent where dry.

    Derived from DEPTH rather than from the rendered colour. Testing the pixel
    against the dry grey would also erase any genuinely grey-coloured hazard
    class if the palette ever changed, and would couple this to the palette
    rather than to the physics.
    """
    alpha = np.where(np.asarray(depth) >= DRY_DEPTH_M, 255, 0).astype(np.uint8)
    return np.dstack([rgb.astype(np.uint8), alpha])


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

    warps = _overlay_warps(grid)
    dam_name = result.get("dam_name", "unknown")

    keyframes: List[Keyframe] = []
    for idx, t_k in enumerate(key_times):
        # Nearest recorded snapshot in simulation time.
        nearest = int(np.argmin(np.abs(s_times_arr - t_k)))
        depth = s_depths[nearest]

        # FD2320 classification (depth-only, conservative) + exact color map.
        classification = hazard_classifier.classify_depth_only(depth)
        rgb = hazard_classifier.apply_to_rgb(classification)
        hazard_summary = hazard_classifier.summarize(classification)

        # depth/rgb row 0 is the grid's southernmost row (Grid.cell_centres_2d,
        # row index increasing northward -> see _utmtp_corners above), but image
        # row 0 is conventionally the TOP; Leaflet's ImageOverlay and Cesium's
        # SingleTileImageryProvider both place image row 0 at the NORTH edge of
        # the given bounds. Flip vertically or the flood renders upside-down.
        # Alpha comes from the SAME depth array, so it is flipped with the
        # image rather than after it -> a mismatch here would punch the
        # transparent holes in upside down.
        rgba = np.flipud(_to_rgba(rgb, depth))

        png_name = f"keyframe_{idx:04d}_{int(round(t_k)):06d}s.png"
        png_mercator = f"keyframe_{idx:04d}_{int(round(t_k)):06d}s_3857.png"
        _render_png(_warp_rgba(rgba, grid, warps["geographic"]), out_dir / png_name)
        _render_png(_warp_rgba(rgba, grid, warps["mercator"]), out_dir / png_mercator)

        # png_url is a bare filename, not a filesystem path: manifest.json and
        # its PNGs are always siblings in out_dir, and whatever serves the
        # manifest over HTTP (services/api's /files static mount) resolves
        # this relative to the manifest's own URL. Keeps this module decoupled
        # from any web-server base URL.
        keyframes.append(
            Keyframe(
                time_s=float(t_k),
                png_url=png_name,
                bounds=warps["geographic"]["bounds"],
                hazard_summary=hazard_summary,
                png_url_mercator=png_mercator,
                bounds_mercator=warps["mercator"]["bounds"],
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
            # png_url is warped to EPSG:4326 and png_url_mercator to EPSG:3857;
            # manifests without this key hold the raw UTM grid in a lat/lon box.
            "overlay_warped": True,
        },
        metadata={
            "description": "Flood keyframes for JalRaksha dam-break visualization",
            "license": "CC BY 4.0 (data: Copernicus DEM, ESA WorldCover)",
            "note": "FD2320 hazard classification, depth-only (|V| taken as 0, so fast water is under-stated); terrain-matched.",
        },
    )

    manifest.to_json(out_dir / "manifest.json")
    return manifest
