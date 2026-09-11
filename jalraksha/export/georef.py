"""
Shared georeferencing for every export product (Phase 5).

One place decides three things that MUST agree across the raster, vector and
KML writers, because a judge will open them in the same GIS session and lay
them on top of one another:

  1. grid_affine()   — how a solver Grid maps to world coordinates.
  2. to_wgs84()      — how metric coordinates become the lat/lon KML requires.
  3. zip_shapefile() — how a Shapefile's five sidecar files travel as one file.

Previously (1) was written inline in geotiff.py and re-derived by hand in
shapefile.py, and (2) did not exist at all: kml.py emitted a warning and then
wrote UTM eastings into a <coordinates> element, producing a file Google Earth
cannot place. Both are the kind of near-miss this module exists to make
impossible.

References:
  Spec §5: Export formats
  CLAUDE.md: metric CRS inside the solver; degrees only at the export boundary.
"""

from __future__ import annotations

import os
import zipfile
from pathlib import Path
from typing import Dict, Optional

from rasterio.transform import Affine

# Sidecars written by an ESRI Shapefile. .shp alone is not openable — the
# geometry is in .shp, the attributes in .dbf, the index in .shx and the CRS in
# .prj — so a download link that serves only .shp gives the user nothing.
SHAPEFILE_SIDECARS = (".shp", ".shx", ".dbf", ".prj", ".cpg", ".sbn", ".sbx")


class GeoreferenceError(ValueError):
    """A coordinate operation could not be performed correctly.

    Raised rather than warned-and-continued: an export written in the wrong
    coordinate system looks entirely normal until someone opens it, which is
    the failure mode CLAUDE.md's no-silent-fallback rule targets.
    """


def grid_affine(grid_dict: Dict) -> Affine:
    """
    Build the world transform for a solver grid.

    Two conventions differ between the solver and every raster format, and
    getting either wrong produces a file that opens cleanly in the wrong place:

      * ORIGIN. Grid.x0/y0 are the domain's LOWER-LEFT CORNER, not the centre of
        cell 0 — solver/types.py computes centres as x0 + (i + 0.5)*dx, and
        terrain/domain.py:176 sets x0 = dam_easting - radius. GeoTIFF wants the
        top-left corner, so no half-cell shift is applied here; only the y
        origin moves, to the top of the domain.
      * ROW ORDER. The solver is SOUTH-UP: row 0 is the southernmost row
        (terrain/conditioning.py:157 flips the north-up DEM to get there).
        Rasters are NORTH-UP. Callers must therefore pass np.flipud(array),
        for which to_north_up() below is the single helper.

    The version of this transform that previously lived inline in geotiff.py
    assumed x0/y0 were cell centres and did not flip, which placed the exported
    raster an entire domain-height south of the terrain it described.

    Args:
        grid_dict: {"nx", "ny", "dx", "dy", "x0", "y0"} in metres.

    Returns:
        Affine mapping (column, row) -> (x, y) in the grid's own CRS.
    """
    dx = float(grid_dict["dx"])
    dy = float(grid_dict["dy"])
    ny = int(grid_dict["ny"])

    x_left = float(grid_dict["x0"])
    y_top = float(grid_dict["y0"]) + ny * dy

    return Affine.translation(x_left, y_top) * Affine.scale(dx, -dy)


def to_north_up(array):
    """
    Flip a solver array (row 0 = south) into raster order (row 0 = north).

    Every writer that hands an array to rasterio, or to rasterio.features,
    must pass it through here — paired with grid_affine(), which assumes it.
    """
    import numpy as np

    return np.flipud(np.asarray(array))


def _transformer(crs_epsg: int):
    """Metric-CRS -> WGS84 transformer, x/y ordered (lon, lat)."""
    try:
        from pyproj import CRS, Transformer
    except ImportError as exc:  # pragma: no cover - pyproj is a hard dependency
        raise GeoreferenceError(
            "pyproj is required to write KML (which is WGS84-only). "
            "Install with: pip install pyproj"
        ) from exc

    try:
        source = CRS.from_epsg(int(crs_epsg))
    except Exception as exc:
        raise GeoreferenceError(
            f"EPSG:{crs_epsg} is not a CRS pyproj recognises; cannot convert "
            f"to WGS84 for KML export."
        ) from exc

    if source.is_geographic:
        # Already lat/lon — the caller should not be transforming.
        raise GeoreferenceError(
            f"EPSG:{crs_epsg} is already geographic; expected the solver's "
            f"metric CRS. Passing geographic coordinates through a projected "
            f"transform would silently corrupt them."
        )

    # always_xy: pyproj's native axis order for EPSG:4326 is (lat, lon), while
    # KML's <coordinates> element is (lon, lat). Getting this backwards puts an
    # Indian dam in Somalia and raises no error at all.
    return Transformer.from_crs(source, CRS.from_epsg(4326), always_xy=True)


def to_wgs84_xy(x, y, crs_epsg: int):
    """
    Convert metric (x, y) arrays or scalars to (lon, lat) degrees.

    Args:
        x, y: eastings/northings in EPSG:<crs_epsg> (scalars or sequences).
        crs_epsg: the projected EPSG code the solver ran in (e.g. 32644).

    Returns:
        (lon, lat) in the same shape as the input.

    Raises:
        GeoreferenceError: if crs_epsg is unknown or already geographic.
    """
    return _transformer(crs_epsg).transform(x, y)


def to_wgs84(geometry, crs_epsg: int):
    """
    Reproject a shapely geometry from a metric CRS to WGS84 lon/lat.

    Args:
        geometry: any shapely geometry.
        crs_epsg: the projected EPSG code the geometry is expressed in.

    Returns:
        The same geometry type, in degrees.
    """
    from shapely.ops import transform as shapely_transform

    transformer = _transformer(crs_epsg)
    return shapely_transform(
        lambda xs, ys, z=None: transformer.transform(xs, ys), geometry
    )


def wgs84_bounds(grid_dict: Dict, crs_epsg: int):
    """
    WGS84 (west, south, east, north) envelope of a metric grid's extent.

    Used for KML <LatLonBox>, which is axis-aligned in lat/lon. A rectangle in
    UTM is NOT a rectangle in WGS84, so this returns the bounding envelope of
    the four reprojected corners — an approximation inherent to the KML element,
    not a shortcut. Over a 60 km domain in mid-latitudes the edge discrepancy is
    of order a hundred metres, inside the 30 m DEM's own Tier-1 tolerance.
    """
    dx = float(grid_dict["dx"])
    dy = float(grid_dict["dy"])
    nx = int(grid_dict["nx"])
    ny = int(grid_dict["ny"])
    x0 = float(grid_dict["x0"])
    y0 = float(grid_dict["y0"])

    # x0/y0 are the lower-left CORNER (see grid_affine), so the extent is
    # simply the corner plus the cell count — no half-cell adjustment.
    x_min, x_max = x0, x0 + nx * dx
    y_min, y_max = y0, y0 + ny * dy

    corners_x = [x_min, x_max, x_max, x_min]
    corners_y = [y_min, y_min, y_max, y_max]
    lons, lats = to_wgs84_xy(corners_x, corners_y, crs_epsg)

    return (min(lons), min(lats), max(lons), max(lats))


def epsg_from_crs(crs) -> int:
    """
    Extract an integer EPSG code from a Grid.crs value such as "EPSG:32644".

    Raises:
        GeoreferenceError: if no EPSG code can be read. Guessing a default here
        would place every export in the wrong hemisphere without complaint.
    """
    if isinstance(crs, int):
        return crs
    text = str(crs).strip()
    if ":" in text:
        text = text.rsplit(":", 1)[-1]
    try:
        return int(text)
    except ValueError as exc:
        raise GeoreferenceError(
            f"Cannot read an EPSG code from grid CRS {crs!r}. The solver grid "
            f"must carry a metric CRS (CLAUDE.md); exports cannot be written "
            f"without knowing it."
        ) from exc


def zip_shapefile(shp_path: str, output_path: Optional[str] = None) -> str:
    """
    Bundle a Shapefile and its sidecars into a single .zip.

    Args:
        shp_path: path to the .shp component.
        output_path: destination .zip (default: alongside, same stem).

    Returns:
        Path to the written .zip.

    Raises:
        FileNotFoundError: if the .shp or any of .shx/.dbf/.prj is missing — an
        incomplete bundle is worse than none, since it fails only once the
        recipient tries to open it.
    """
    shp_path = str(shp_path)
    stem = os.path.splitext(shp_path)[0]
    if output_path is None:
        output_path = stem + ".zip"
    output_path = str(output_path)

    required = (".shp", ".shx", ".dbf", ".prj")
    missing = [ext for ext in required if not os.path.exists(stem + ext)]
    if missing:
        raise FileNotFoundError(
            f"Shapefile {shp_path} is incomplete: missing {', '.join(missing)}. "
            f"Refusing to publish a bundle that cannot be opened."
        )

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as bundle:
        for ext in SHAPEFILE_SIDECARS:
            part = stem + ext
            if os.path.exists(part):
                bundle.write(part, arcname=os.path.basename(part))

    return output_path
