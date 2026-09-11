"""
KML/KMZ export for inundation polygons and time-animated flood wave.

Phase 5: Export module for KML/KMZ outputs.

Implements:
  - export_inundation_kml(): Inundation envelope as KML Polygon
  - export_time_animated_kml(): Time-animated flood wave via TimeSpan
  - export_depth_ground_overlay(): Depth raster as coloured PNG ground overlay
  - export_kmz(): Bundle KML + assets into KMZ

COORDINATE SYSTEM. KML is WGS84-only; the solver runs in a metric UTM CRS
(CLAUDE.md). Every geometry written here is therefore reprojected through
export/georef.to_wgs84 first. This module previously emitted a warning and then
wrote raw UTM eastings into <coordinates>, which produces a file Google Earth
either rejects outright or silently places at absurd coordinates — a warning on
a console nobody reads is not a substitute for the transform.

References:
  Spec §13.2: KML/KMZ with time-animated flood wave
  Google Earth KML reference: https://developers.google.com/kml/documentation/kmlreference
"""

import os
import zipfile
import numpy as np
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, Optional, List, Tuple
import warnings

from jalraksha.export.georef import to_wgs84, wgs84_bounds
from jalraksha.export.shapefile import wet_mask_polygons


# KML template
KML_HEADER = '''<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2"
     xmlns:gx="http://www.google.com/kml/ext/2.2">
'''

KML_FOOTER = '</kml>\n'


def _ring_coords(ring) -> str:
    """Serialise one shapely ring to a KML <coordinates> body (lon,lat,alt)."""
    return " ".join(f"{x:.8f},{y:.8f},0" for x, y in ring.coords)


def _polygon_kml(polygon, indent: str = "      ") -> str:
    """Serialise one shapely Polygon, interior rings included, as KML."""
    parts = [f"{indent}<Polygon>\n"]
    parts.append(f"{indent}  <outerBoundaryIs><LinearRing><coordinates>\n")
    parts.append(f"{indent}    {_ring_coords(polygon.exterior)}\n")
    parts.append(f"{indent}  </coordinates></LinearRing></outerBoundaryIs>\n")
    # Holes matter: a dry knoll inside the flood is information a judge acts on,
    # and filling it in overstates the inundated area.
    for interior in polygon.interiors:
        parts.append(f"{indent}  <innerBoundaryIs><LinearRing><coordinates>\n")
        parts.append(f"{indent}    {_ring_coords(interior)}\n")
        parts.append(f"{indent}  </coordinates></LinearRing></innerBoundaryIs>\n")
    parts.append(f"{indent}</Polygon>\n")
    return "".join(parts)


def _geometry_kml(geometry, indent: str = "      ") -> str:
    """Serialise a shapely Polygon or MultiPolygon as KML geometry."""
    if geometry.geom_type == "Polygon":
        return _polygon_kml(geometry, indent)
    # Disjoint flood pockets stay disjoint (MultiGeometry), rather than being
    # merged into one envelope that covers ground which never wetted.
    parts = [f"{indent}<MultiGeometry>\n"]
    for part in geometry.geoms:
        parts.append(_polygon_kml(part, indent + "  "))
    parts.append(f"{indent}</MultiGeometry>\n")
    return "".join(parts)


def _wgs84_envelope(h_max: np.ndarray, grid_dict: Dict, depth_threshold: float,
                    crs_epsg: int):
    """Wet-cell geometry for one depth field, reprojected to WGS84 lon/lat."""
    geometry = wet_mask_polygons(np.asarray(h_max) >= depth_threshold, grid_dict)
    if geometry is None:
        return None
    return to_wgs84(geometry, crs_epsg)


def export_inundation_kml(
    h_max: np.ndarray,
    grid_dict: Dict,
    output_path: str,
    depth_threshold: float = 0.1,
    dam_name: str = "Dam",
    crs_epsg: int = 32643,
) -> Optional[str]:
    """
    Export inundation envelope as KML Polygon, in WGS84.

    Args:
        h_max: 2D array of maximum flood depth (m), solver row order.
        grid_dict: Grid definition
        output_path: Output path (.kml)
        depth_threshold: Wet-cell threshold (m)
        dam_name: Dam name
        crs_epsg: EPSG code the grid is expressed in (a metric CRS). Coordinates
            are reprojected to EPSG:4326 as KML requires.

    Returns:
        Path to output KML file, or None if nothing was above threshold.

    Raises:
        GeoreferenceError: if crs_epsg is not a usable projected CRS. Writing
        unreprojected coordinates instead is not an option — see module docstring.
    """
    output_path = str(output_path)

    geometry = _wgs84_envelope(h_max, grid_dict, depth_threshold, crs_epsg)
    if geometry is None:
        warnings.warn("No inundation polygon; no KML written")
        return None

    wet = np.asarray(h_max)[np.asarray(h_max) >= depth_threshold]
    max_depth = float(np.max(wet))
    # Area is measured in the METRIC CRS, before reprojection — computing it on
    # degree coordinates would return square degrees.
    metric = wet_mask_polygons(np.asarray(h_max) >= depth_threshold, grid_dict)
    area_m2 = float(metric.area)

    kml_content = KML_HEADER
    kml_content += '<Document>\n'
    kml_content += f'  <name>{dam_name} Inundation Envelope</name>\n'
    kml_content += '  <description>Maximum inundation envelope for dam-break scenario. '
    kml_content += f'Area: {area_m2:.0f} m2. Max depth: {max_depth:.2f} m. '
    kml_content += f'Threshold: {depth_threshold} m. '
    kml_content += 'Tier-1 screening product from 30 m Copernicus GLO-30 — arrival '
    kml_content += 'times and inundation extent are the intended readings; point '
    kml_content += 'depths are indicative only. '
    kml_content += f'Generated: {datetime.utcnow().isoformat()}Z</description>\n'

    kml_content += '''  <Style id="inundationStyle">
    <LineStyle>
      <color>ff0000ff</color>
      <width>2</width>
    </LineStyle>
    <PolyStyle>
      <color>4d0000ff</color>
      <fill>1</fill>
      <outline>1</outline>
    </PolyStyle>
  </Style>
'''

    kml_content += '  <Placemark>\n'
    kml_content += '    <name>Inundation Envelope</name>\n'
    kml_content += '    <styleUrl>#inundationStyle</styleUrl>\n'
    kml_content += _geometry_kml(geometry, indent="    ")
    kml_content += '  </Placemark>\n'
    kml_content += '</Document>\n'
    kml_content += KML_FOOTER

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(kml_content)

    return output_path


def export_time_animated_kml(
    time_steps_s: List[float],
    h_max_per_step: List[np.ndarray],
    grid_dict: Dict,
    output_path: str,
    depth_threshold: float = 0.1,
    dam_name: str = "Dam",
    breach_time: Optional[datetime] = None,
    crs_epsg: int = 32643,
) -> Optional[str]:
    """
    Export time-animated flood wave as KML with TimeSpan elements, in WGS84.

    Google Earth can scrub through the animation to watch the wave advance.

    Args:
        time_steps_s: List of simulation times (s from breach)
        h_max_per_step: List of 2D arrays [ny, nx] - flood depth at each time
        grid_dict: Grid definition
        output_path: Output path (.kml)
        depth_threshold: Wet-cell threshold (m)
        dam_name: Dam name
        breach_time: Absolute UTC time of breach (for TimeSpan begin)
        crs_epsg: metric EPSG code of the grid; reprojected to 4326 on write.

    Returns:
        Path to output KML file, or None if no frame had any wet cells.
    """
    output_path = str(output_path)

    if len(time_steps_s) != len(h_max_per_step):
        raise ValueError(
            f"time_steps_s ({len(time_steps_s)}) and h_max_per_step "
            f"({len(h_max_per_step)}) must have the same length"
        )

    if breach_time is None:
        breach_time = datetime(2026, 1, 1, 0, 0, 0)  # arbitrary anchor

    kml_content = KML_HEADER
    kml_content += '<Document>\n'
    kml_content += f'  <name>{dam_name} Dam-Break Animation</name>\n'
    kml_content += f'  <description>Time-animated flood wave. {len(time_steps_s)} frames. '
    kml_content += f'Breach time: {breach_time.isoformat()}Z. '
    kml_content += 'Open in Google Earth and use the time slider to watch the wave '
    kml_content += 'advance.</description>\n'

    kml_content += '''  <Style id="floodStyle">
    <LineStyle>
      <color>ff0000ff</color>
      <width>1</width>
    </LineStyle>
    <PolyStyle>
      <color>660000ff</color>
      <fill>1</fill>
    </PolyStyle>
  </Style>
'''

    # Each frame spans until the NEXT frame starts, so the animation is
    # continuous. Giving every frame a fixed 1-second span (as this once did)
    # makes the wave invisible at any realistic playback speed: the frames are
    # minutes apart in simulation time, so Google Earth shows nothing between them.
    frames_written = 0
    for idx, (t_s, h) in enumerate(zip(time_steps_s, h_max_per_step)):
        geometry = _wgs84_envelope(h, grid_dict, depth_threshold, crs_epsg)
        if geometry is None:
            continue

        begin = breach_time + timedelta(seconds=float(t_s))
        if idx + 1 < len(time_steps_s):
            end = breach_time + timedelta(seconds=float(time_steps_s[idx + 1]))
        else:
            span = float(t_s) - float(time_steps_s[idx - 1]) if idx > 0 else 60.0
            end = begin + timedelta(seconds=max(span, 1.0))

        kml_content += '  <Placemark>\n'
        kml_content += f'    <name>t = {t_s:.0f} s ({t_s / 60.0:.1f} min)</name>\n'
        kml_content += '    <styleUrl>#floodStyle</styleUrl>\n'
        kml_content += '    <TimeSpan>\n'
        kml_content += f'      <begin>{begin.isoformat()}Z</begin>\n'
        kml_content += f'      <end>{end.isoformat()}Z</end>\n'
        kml_content += '    </TimeSpan>\n'
        kml_content += _geometry_kml(geometry, indent="    ")
        kml_content += '  </Placemark>\n'
        frames_written += 1

    kml_content += '</Document>\n'
    kml_content += KML_FOOTER

    if frames_written == 0:
        warnings.warn("No frame had cells above threshold; no animated KML written")
        return None

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(kml_content)

    return output_path


def export_depth_ground_overlay(
    h_max: np.ndarray,
    grid_dict: Dict,
    output_path: str,
    png_path: Optional[str] = None,
    dam_name: str = "Dam",
    crs_epsg: int = 32643,
) -> Optional[Tuple[str, str]]:
    """
    Export maximum-depth raster as a coloured PNG ground overlay (KMZ-ready).

    Generates:
      - PNG with depth-coloured cells, transparent where dry
      - KML referencing the PNG as a GroundOverlay, in WGS84 lat/lon

    Args:
        h_max: 2D array of maximum flood depth (m), solver row order.
        grid_dict: Grid definition
        output_path: Output KML path (the PNG goes in the same directory)
        png_path: PNG output path (default: <output_path base>.png)
        dam_name: Dam name
        crs_epsg: metric EPSG code of the grid.

    Returns:
        Tuple of (kml_path, png_path), or None on failure.
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        warnings.warn("matplotlib required for ground overlay export")
        return None

    output_path = str(output_path)
    if png_path is None:
        png_path = output_path.replace(".kml", ".png")

    depth = np.asarray(h_max, dtype=np.float64)
    # Dry ground must be transparent, not dark blue: a GroundOverlay covers the
    # whole domain rectangle, and painting the dry majority opaque hides the
    # satellite imagery the overlay exists to be read against.
    masked = np.ma.masked_where(depth < 0.1, depth)

    Path(png_path).parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(10, 10 * grid_dict["ny"] / grid_dict["nx"]), dpi=100)
    # origin="lower" renders solver row 0 (south) at the bottom, matching the
    # LatLonBox below. No axes/margins — Google Earth stretches the image itself.
    ax.imshow(masked, cmap="jet", origin="lower",
              vmin=0, vmax=max(0.1, float(np.nanmax(depth))))
    ax.set_axis_off()
    fig.subplots_adjust(left=0, right=1, top=1, bottom=0)
    fig.savefig(png_path, dpi=100, transparent=True, pad_inches=0,
                bbox_inches="tight")
    plt.close(fig)

    west, south, east, north = wgs84_bounds(grid_dict, crs_epsg)

    png_filename = os.path.basename(png_path)

    kml_content = KML_HEADER
    kml_content += '<Document>\n'
    kml_content += f'  <name>{dam_name} Maximum Depth</name>\n'
    kml_content += '  <GroundOverlay>\n'
    kml_content += '    <name>Max Depth (m)</name>\n'
    kml_content += '    <Icon>\n'
    kml_content += f'      <href>{png_filename}</href>\n'
    kml_content += '    </Icon>\n'
    # LatLonBox is axis-aligned in lat/lon, while the domain is axis-aligned in
    # UTM. wgs84_bounds returns the envelope of the four reprojected corners;
    # the residual edge mismatch is well inside the 30 m DEM's own tolerance.
    kml_content += '    <LatLonBox>\n'
    kml_content += f'      <north>{north:.8f}</north>\n'
    kml_content += f'      <south>{south:.8f}</south>\n'
    kml_content += f'      <east>{east:.8f}</east>\n'
    kml_content += f'      <west>{west:.8f}</west>\n'
    kml_content += '    </LatLonBox>\n'
    kml_content += '  </GroundOverlay>\n'
    kml_content += '</Document>\n'
    kml_content += KML_FOOTER

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(kml_content)

    return (output_path, png_path)


def export_kmz(
    kml_path: str,
    asset_paths: Optional[List[str]] = None,
    output_path: Optional[str] = None,
) -> Optional[str]:
    """
    Bundle KML + asset files into a KMZ archive.

    Args:
        kml_path: Path to .kml file
        asset_paths: Optional list of paths to PNG/other asset files to bundle
        output_path: Output .kmz path (default: same dir, .kmz extension)

    Returns:
        Path to output KMZ file, or None on failure.
    """
    if output_path is None:
        output_path = kml_path.replace(".kml", ".kmz")

    output_path = str(output_path)
    kml_path = str(kml_path)

    if asset_paths is None:
        asset_paths = []

    try:
        with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as kmz:
            # KML at the archive root: Google Earth opens the first root-level
            # .kml it finds. Assets sit beside it rather than in a subdirectory,
            # because the <href> written by export_depth_ground_overlay is a
            # bare filename — a "files/" prefix here would break the reference
            # and the overlay would render as an empty box.
            kmz.write(kml_path, arcname=os.path.basename(kml_path))

            for asset in asset_paths:
                if os.path.exists(asset):
                    kmz.write(asset, arcname=os.path.basename(asset))
    except Exception as e:
        warnings.warn(f"Failed to write KMZ: {e}")
        return None

    return output_path


# Backwards-compatible alias expected by export/__init__.py.
export_kml = export_inundation_kml
