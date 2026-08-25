"""
Shapefile export for inundation polygons and arrival-time contours.

Phase 5: Export module for vector outputs.

Implements:
  - raster_to_inundation_polygon(): Convert h_max raster → inundation polygons
  - export_inundation_polygon(): Single maximum-envelope polygon
  - export_hazard_classification_polygons(): Per-class hazard polygons
  - export_arrival_time_contours(): Arrival-time isochrones as polylines

All outputs use EPSG:32643 (UTM 43N for India).

References:
  Spec §5: Export formats
  Spec §13.1: Vector export requirements
"""

import os
import numpy as np
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional, List, Tuple
import warnings


def raster_to_inundation_polygon(
    h_max: np.ndarray,
    grid_dict: Dict,
    depth_threshold: float = 0.1,
) -> Optional[Dict]:
    """
    Convert maximum-depth raster to a single inundation polygon (maximum envelope).

    Returns a polygon dict in Shapefile-compatible format:
        {
            "type": "Polygon",
            "coordinates": [[[x1, y1], [x2, y2], ...]],
            "properties": {
                "area_m2": ...,
                "max_depth_m": ...,
                "depth_threshold": ...,
            }
        }

    Args:
        h_max: 2D array [ny, nx] of maximum flood depth (m)
        grid_dict: Grid definition (nx, ny, dx, dy, x0, y0)
        depth_threshold: Depth threshold for "wet" cells (default 0.1 m)

    Returns:
        Polygon dict, or None if no cells exceed threshold.
    """
    ny = grid_dict["ny"]
    nx = grid_dict["nx"]
    dx = grid_dict["dx"]
    dy = grid_dict["dy"]
    x0 = grid_dict["x0"]
    y0 = grid_dict["y0"]

    # Find wet cells
    wet_mask = h_max >= depth_threshold

    if not np.any(wet_mask):
        return None

    # Compute max depth in wet area
    max_depth = float(np.max(h_max[wet_mask]))

    # Estimate area: count wet cells * cell area
    wet_count = int(np.sum(wet_mask))
    area_m2 = wet_count * dx * dy

    # Build convex hull-style envelope by walking wet cells (north->south)
    # For each row, get leftmost and rightmost wet cell indices.
    # For simplicity, use bounding-box approach with refined interior contour.
    # The result is a polygon approximating the wet area.

    # Get row ranges (north-to-south, so iterate from y=ny-1 to y=0)
    polygon_points: List[List[float]] = []
    seen_x_at_y: Dict[int, List[Tuple[float, float]]] = {}

    for iy in range(ny):
        # y coordinate of cell centre
        cy = y0 + iy * dy

        wet_cols = np.where(wet_mask[iy, :])[0]
        if len(wet_cols) == 0:
            continue

        # Cell centres in this row
        x_min = x0 + wet_cols[0] * dx - dx / 2
        x_max = x0 + wet_cols[-1] * dx + dx / 2
        yc_lower = cy - dy / 2
        yc_upper = cy + dy / 2

        # Append the leftmost edge bottom, rightmost edge bottom (for this row)
        if iy not in seen_x_at_y:
            seen_x_at_y[iy] = []
        seen_x_at_y[iy].append((x_min, yc_lower))
        seen_x_at_y[iy].append((x_max, yc_lower))

    # Construct polygon: trace leftmost edge south, then rightmost edge north
    # (a "ribbon" polygon: narrow corridors get a sensible shape)
    rows_with_wet = sorted(seen_x_at_y.keys())
    if not rows_with_wet:
        return None

    polygon_points: List[List[float]] = []
    # Top row: leftmost + rightmost
    top_y = rows_with_wet[-1]
    top_pts = seen_x_at_y[top_y]
    polygon_points.append([top_pts[0][0], top_pts[0][1]])  # left bottom of top row
    polygon_points.append([top_pts[1][0], top_pts[1][1]])  # right bottom of top row
    # Walk down: right edge
    for iy in reversed(rows_with_wet):
        pts = seen_x_at_y[iy]
        # right-bottom of this row -> right-top (next row)
        cy_top = pts[1][1] + dy
        polygon_points.append([pts[1][0], cy_top])
    # Walk back up: left edge
    for iy in rows_with_wet:
        pts = seen_x_at_y[iy]
        # left-top -> left-bottom
        polygon_points.append([pts[0][0], pts[0][1]])

    # Close polygon
    if polygon_points[0] != polygon_points[-1]:
        polygon_points.append(polygon_points[0])

    return {
        "type": "Polygon",
        "coordinates": [polygon_points],
        "properties": {
            "area_m2": float(area_m2),
            "max_depth_m": max_depth,
            "depth_threshold": depth_threshold,
            "creation_date": datetime.utcnow().isoformat(),
        },
    }


def export_inundation_polygon(
    h_max: np.ndarray,
    grid_dict: Dict,
    output_path: str,
    depth_threshold: float = 0.1,
    crs_epsg: int = 32643,
    dam_name: str = "Dam",
) -> Optional[str]:
    """
    Export inundation envelope as Shapefile (.shp).

    Args:
        h_max: 2D array of maximum flood depth (m)
        grid_dict: Grid definition
        output_path: Output path (must end in .shp)
        depth_threshold: Wet-cell threshold (m)
        crs_epsg: EPSG code for CRS
        dam_name: Dam name for metadata

    Returns:
        Path to output shapefile, or None if no inundation.
    """
    output_path = str(output_path)
    polygon = raster_to_inundation_polygon(h_max, grid_dict, depth_threshold)

    if polygon is None:
        warnings.warn(f"No inundation cells above threshold {depth_threshold} m; "
                      f"no shapefile written")
        return None

    try:
        from shapely.geometry import Polygon, mapping
        from shapely.ops import transform as shapely_transform
    except ImportError:
        warnings.warn("shapely not installed; cannot write Shapefile. "
                      "Install with: pip install shapely")
        return None

    # Build Shapely polygon
    coords = polygon["coordinates"][0]
    poly = Polygon(coords)

    if not poly.is_valid:
        poly = poly.buffer(0)  # attempt fix

    # Build GeoDataFrame
    try:
        import geopandas as gpd

        gdf = gpd.GeoDataFrame(
            {
                "dam": [dam_name],
                "area_m2": [polygon["properties"]["area_m2"]],
                "max_d_m": [polygon["properties"]["max_depth_m"]],
                "depth_th": [depth_threshold],
                "created": [polygon["properties"]["creation_date"]],
            },
            geometry=[poly],
            crs=f"EPSG:{crs_epsg}",
        )

        # Ensure output directory exists
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        gdf.to_file(output_path, driver="ESRI Shapefile")
        return output_path

    except ImportError:
        warnings.warn("geopandas not installed; cannot write Shapefile. "
                      "Install with: pip install geopandas")
        return None


def export_hazard_classification_polygons(
    h_max: np.ndarray,
    v_max: np.ndarray,
    grid_dict: Dict,
    output_path: str,
    crs_epsg: int = 32643,
    dam_name: str = "Dam",
) -> Optional[Dict[str, str]]:
    """
    Export per-hazard-class polygons (low / medium / high / extreme).

    Hazard classes (FD2320 / DEFRA-style):
      - Low:       0.1 <= h < 0.5  AND v < 1.0
      - Medium:    0.5 <= h < 1.2  OR  (h >= 0.1 AND v >= 1.0 AND v < 2.0)
      - High:      1.2 <= h < 2.0  OR  (h >= 0.5 AND v >= 2.0 AND v < 4.0)
      - Extreme:   h >= 2.0        OR  v >= 4.0

    ⚠ Class thresholds are indicative (FD2320). Verify before operational use.
    See Spec §11.1 and §17 item 9 (FD2320 debris factors + category thresholds).

    Args:
        h_max: 2D array of maximum flood depth (m)
        v_max: 2D array of maximum velocity magnitude (m/s)
        grid_dict: Grid definition
        output_path: Output base path (will append _low/_medium/_high/_extreme)
        crs_epsg: EPSG code
        dam_name: Dam name

    Returns:
        Dict mapping hazard_class -> file path, or None if geopandas unavailable.
    """
    try:
        import geopandas as gpd
        from shapely.geometry import Polygon
    except ImportError:
        warnings.warn("geopandas/shapely not installed; cannot write hazard polygons")
        return None

    # Compute velocity magnitude
    if v_max.ndim == 2:
        v_mag = v_max  # already magnitude
    elif v_max.ndim == 3:
        # v_max is array of (u, v) pairs (last axis)
        v_mag = np.sqrt(v_max[..., 0] ** 2 + v_max[..., 1] ** 2)
    else:
        v_mag = np.zeros_like(h_max)

    # Classify
    h_low = h_max >= 0.1
    h_med = h_max >= 0.5
    h_high = h_max >= 1.2
    h_ext = h_max >= 2.0

    v1 = v_mag >= 1.0
    v2 = v_mag >= 2.0
    v4 = v_mag >= 4.0

    classes = {
        "low": h_low & ~h_med,
        "medium": (h_med & ~h_high) | (h_low & v1 & ~v2),
        "high": (h_high & ~h_ext) | (h_med & v2 & ~v4),
        "extreme": h_ext | v4,
    }

    ny = grid_dict["ny"]
    nx = grid_dict["nx"]
    dx = grid_dict["dx"]
    dy = grid_dict["dy"]
    x0 = grid_dict["x0"]
    y0 = grid_dict["y0"]

    output_paths: Dict[str, str] = {}

    for cls_name, mask in classes.items():
        if not np.any(mask):
            continue

        # Build polygon for this class
        polygon = raster_to_inundation_polygon(
            mask.astype(np.float32),  # treat mask as binary depth
            grid_dict,
            depth_threshold=0.5,  # any cell with mask == 1 counts
        )

        if polygon is None:
            continue

        coords = polygon["coordinates"][0]
        poly = Polygon(coords)

        if not poly.is_valid:
            poly = poly.buffer(0)

        area = float(np.sum(mask) * dx * dy)

        gdf = gpd.GeoDataFrame(
            {
                "dam": [dam_name],
                "hazard": [cls_name],
                "area_m2": [area],
            },
            geometry=[poly],
            crs=f"EPSG:{crs_epsg}",
        )

        # Output path
        out = output_path.replace(".shp", f"_{cls_name}.shp")
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        gdf.to_file(out, driver="ESRI Shapefile")
        output_paths[cls_name] = out

    return output_paths if output_paths else None


def export_arrival_time_contours(
    t_arrival: np.ndarray,
    grid_dict: Dict,
    output_path: str,
    iso_times_s: Optional[List[float]] = None,
    crs_epsg: int = 32643,
) -> Optional[str]:
    """
    Export arrival-time contours as polylines in Shapefile format.

    Args:
        t_arrival: 2D array of arrival times (s from breach)
        grid_dict: Grid definition
        output_path: Output path (.shp)
        iso_times_s: List of times at which to draw contours (s).
            Default: [300, 900, 1800, 3600, 7200] (5, 15, 30, 60, 120 min)
        crs_epsg: EPSG code

    Returns:
        Path to output shapefile, or None on failure.
    """
    try:
        import geopandas as gpd
        from shapely.geometry import LineString
    except ImportError:
        warnings.warn("geopandas/shapely not installed; cannot write contours")
        return None

    if iso_times_s is None:
        iso_times_s = [300.0, 900.0, 1800.0, 3600.0, 7200.0]

    ny = grid_dict["ny"]
    nx = grid_dict["nx"]
    dx = grid_dict["dx"]
    dy = grid_dict["dy"]
    x0 = grid_dict["x0"]
    y0 = grid_dict["y0"]

    # Build cell-centre coordinate arrays
    xs = x0 + np.arange(nx) * dx
    ys = y0 + np.arange(ny) * dy
    XX, YY = np.meshgrid(xs, ys)

    # Replace inf with NaN for contour computation
    t_clean = t_arrival.copy()
    t_clean[np.isinf(t_clean)] = np.nan

    rows = []
    geometries = []

    for iso_t in iso_times_s:
        # Find cells where arrival time is <= iso_t (flooded by iso_t)
        # Contour line = boundary of {t_arrival <= iso_t}
        try:
            import matplotlib
            matplotlib.use("Agg")  # non-interactive backend
            import matplotlib.pyplot as plt
            cs = plt.contour(XX, YY, t_clean, levels=[iso_t])
            plt.close()
        except (ImportError, ValueError):
            warnings.warn("matplotlib required for arrival-time contours")
            return None

        # Extract contour path vertices portably across matplotlib versions
        paths_vertices = []
        if hasattr(cs, "allsegs"):
            for level_segs in cs.allsegs:
                for seg in level_segs:
                    paths_vertices.append(seg)
        elif hasattr(cs, "collections") and cs.collections:
            for collection in cs.collections:
                for path in collection.get_paths():
                    paths_vertices.append(path.vertices)

        # Each contour path is a list of (x, y) points
        for vertices in paths_vertices:
            if len(vertices) < 2:
                continue

            # Convert to LineString
            line = LineString([(float(v[0]), float(v[1])) for v in vertices])
            if not line.is_valid:
                line = line.buffer(0).boundary

            if line.is_empty:
                continue

            rows.append({"iso_time_s": float(iso_t), "iso_time_min": float(iso_t) / 60.0})
            geometries.append(line)

    if not rows:
        warnings.warn("No arrival-time contours generated (no flooded cells?)")
        return None

    gdf = gpd.GeoDataFrame(rows, geometry=geometries, crs=f"EPSG:{crs_epsg}")

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    gdf.to_file(output_path, driver="ESRI Shapefile")
    return output_path
