"""
KML/KMZ export for inundation polygons and time-animated flood wave.

Phase 5: Export module for KML/KMZ outputs.

Implements:
  - export_inundation_kml(): Inundation envelope as KML Polygon
  - export_time_animated_kml(): Time-animated flood wave via TimeSpan
  - export_depth_ground_overlay(): Depth raster as coloured PNG ground overlay
  - export_kmz(): Bundle KML + assets into KMZ

References:
  Spec §13.2: KML/KMZ with time-animated flood wave
  Google Earth KML reference: https://developers.google.com/kml/documentation/kmlreference
"""

import os
import io
import zipfile
import numpy as np
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, Optional, List
import warnings


# KML template
KML_HEADER = '''<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2"
     xmlns:gx="http://www.google.com/kml/ext/2.2">
'''

KML_FOOTER = '</kml>\n'


def _coord_to_kml(coords):
    """Convert coordinate list to KML coordinate string."""
    return " ".join(f"{c[0]:.6f},{c[1]:.6f},0" for c in coords)


def export_inundation_kml(
    h_max: np.ndarray,
    grid_dict: Dict,
    output_path: str,
    depth_threshold: float = 0.1,
    dam_name: str = "Dam",
    crs_epsg: int = 32643,
) -> Optional[str]:
    """
    Export inundation envelope as KML Polygon.

    Args:
        h_max: 2D array of maximum flood depth (m)
        grid_dict: Grid definition
        output_path: Output path (.kml)
        depth_threshold: Wet-cell threshold (m)
        dam_name: Dam name
        crs_epsg: EPSG code (note: KML uses WGS84 lat/lon, EPSG:4326;
                    if crs_epsg != 4326, transformation is skipped with warning)

    Returns:
        Path to output KML file, or None on failure.
    """
    output_path = str(output_path)

    # Reuse polygon generator from shapefile module
    from .shapefile import raster_to_inundation_polygon

    polygon = raster_to_inundation_polygon(h_max, grid_dict, depth_threshold)
    if polygon is None:
        warnings.warn("No inundation polygon; no KML written")
        return None

    if crs_epsg != 4326:
        warnings.warn(
            f"KML requires WGS84 (EPSG:4326); input is EPSG:{crs_epsg}. "
            "Writing coordinates as-is (UTM metres will appear in wrong location). "
            "TODO: add proper UTM->WGS84 transformation."
        )

    coords = polygon["coordinates"][0]
    area_m2 = polygon["properties"]["area_m2"]
    max_depth = polygon["properties"]["max_depth_m"]

    # Build KML
    coords_str = _coord_to_kml(coords)

    kml_content = KML_HEADER
    kml_content += '<Document>\n'
    kml_content += f'  <name>{dam_name} Inundation Envelope</name>\n'
    kml_content += f'  <description>Maximum inundation envelope for dam-break scenario. '
    kml_content += f'Area: {area_m2:.0f} m². Max depth: {max_depth:.2f} m. '
    kml_content += f'Threshold: {depth_threshold} m. '
    kml_content += f'Generated: {datetime.utcnow().isoformat()}Z</description>\n'

    # Style: red transparent fill
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
    kml_content += '    <Polygon>\n'
    kml_content += '      <outerBoundaryIs>\n'
    kml_content += '        <LinearRing>\n'
    kml_content += '          <coordinates>\n'
    kml_content += f'            {coords_str}\n'
    kml_content += '         </coordinates>\n'
    kml_content += '       </LinearRing>\n'
    kml_content += '     </outerBoundaryIs>\n'
    kml_content += '   </Polygon>\n'
    kml_content += ' </Placemark>\n'
    kml_content += '  </Document>\n'
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
    Export time-animated flood wave as KML with TimeSpan elements.

    Google Earth can scrub through the animation to watch the wave advance.

    Args:
        time_steps_s: List of simulation times (s from breach)
        h_max_per_step: List of 2D arrays [ny, nx] - flood depth at each time
        grid_dict: Grid definition
        output_path: Output path (.kml)
        depth_threshold: Wet-cell threshold (m)
        dam_name: Dam name
        breach_time: Absolute UTC time of breach (for TimeSpan begin)
        crs_epsg: EPSG code

    Returns:
        Path to output KML file, or None on failure.
    """
    output_path = str(output_path)

    if len(time_steps_s) != len(h_max_per_step):
        raise ValueError(
            f"time_steps_s ({len(time_steps_s)}) and h_max_per_step "
            f"({len(h_max_per_step)}) must have the same length"
        )

    if crs_epsg != 4326:
        warnings.warn(
            f"KML requires WGS84; input is EPSG:{crs_epsg}. "
            "TODO: add proper UTM->WGS84 transformation."
        )

    from .shapefile import raster_to_inundation_polygon

    if breach_time is None:
        breach_time = datetime(2026, 1, 1, 0, 0, 0)  # arbitrary anchor

    kml_content = KML_HEADER
    kml_content += '<Document>\n'
    kml_content += f'  <name>{dam_name} Dam-Break Animation</name>\n'
    kml_content += f'  <description>Time-animated flood wave. {len(time_steps_s)} frames. '
    kml_content += f'Breach time: {breach_time.isoformat()}Z. '
    kml_content += 'Open in Google Earth to scrub through the animation</description>\n'

    # Common style
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

    # Each time step is a Placemark with TimeSpan
    for t_s, h in zip(time_steps_s, h_max_per_step):
        polygon = raster_to_inundation_polygon(h, grid_dict, depth_threshold)
        if polygon is None:
            continue

        begin = breach_time + timedelta(seconds=float(t_s))
        # End time is one second before next frame (or +1h for last frame)
        # For simplicity, give each frame a 1-second span
        end = begin + timedelta(seconds=1)

        coords = polygon["coordinates"][0]
        coords_str = _coord_to_kml(coords)

        kml_content += '  <Placemark>\n'
        kml_content += f'    <name>t = {t_s:.0f} s</name>\n'
        kml_content += '    <styleUrl>#floodStyle</styleUrl>\n'
        kml_content += '    <TimeSpan>\n'
        kml_content += f'      <begin>{begin.isoformat()}Z</begin>\n'
        kml_content += f'      <end>{end.isoformat()}Z</end>\n'
        kml_content += '   </TimeSpan>\n'
        kml_content += '    <Polygon>\n'
        kml_content += '      <outerBoundaryIs>\n'
        kml_content += '        <LinearRing>\n'
        kml_content += '          <coordinates>\n'
        kml_content += f'            {coords_str}\n'
        kml_content += '         </coordinates>\n'
        kml_content += '       </LinearRing>\n'
        kml_content += '     </outerBoundaryIs>\n'
        kml_content += '   </Polygon>\n'
        kml_content += ' </Placemark>\n'

    kml_content += '  </Document>\n'
    kml_content += KML_FOOTER

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
      - PNG with depth-coloured cells (jet colormap)
      - KML referencing the PNG as a GroundOverlay

    Args:
        h_max: 2D array of maximum flood depth (m)
        grid_dict: Grid definition
        output_path: Output KML path (the PNG will be in same directory)
        png_path: PNG output path (default: <output_path base>.png)
        dam_name: Dam name
        crs_epsg: EPSG code

    Returns:
        Tuple of (kml_path, png_path), or None on failure.
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib import cm
    except ImportError:
        warnings.warn("matplotlib required for ground overlay export")
        return None

    output_path = str(output_path)
    if png_path is None:
        png_path = output_path.replace(".kml", ".png")

    ny = grid_dict["ny"]
    nx = grid_dict["nx"]
    dx = grid_dict["dx"]
    dy = grid_dict["dy"]
    x0 = grid_dict["x0"]
    y0 = grid_dict["y0"]

    # Render depth as colormap PNG (jet: blue shallow → red deep)
    fig, ax = plt.subplots(figsize=(10, 10 * ny / nx), dpi=100)
    im = ax.imshow(h_max, cmap="jet", origin="lower",
                   extent=[x0 - dx / 2, x0 + (nx - 0.5) * dx,
                           y0 - dy / 2, y0 + (ny - 0.5) * dy],
                   vmin=0, vmax=max(0.1, float(np.max(h_max))))
    plt.colorbar(im, ax=ax, label="Depth (m)")
    ax.set_title(f"{dam_name} Maximum Flood Depth")
    plt.tight_layout()
    plt.savefig(png_path, dpi=100, bbox_inches="tight")
    plt.close(fig)

    # Bounds for GroundOverlay
    west = x0 - dx / 2
    east = x0 + (nx - 0.5) * dx
    south = y0 - dy / 2
    north = y0 + (ny - 0.5) * dy

    png_filename = os.path.basename(png_path)

    kml_content = KML_HEADER
    kml_content += '<Document>\n'
    kml_content += f'  <name>{dam_name} Maximum Depth</name>\n'
    kml_content += f'  <GroundOverlay>\n'
    kml_content += f'    <name>Max Depth (m)</name>\n'
    kml_content += f'    <Icon>\n'
    kml_content += f'      <href>{png_filename}</href>\n'
    kml_content += f'   </Icon>\n'
    kml_content += f'    <LatLonBox>\n'
    kml_content += f'      <north>{north:.6f}</north>\n'
    kml_content += f'      <south>{south:.6f}</south>\n'
    kml_content += f'      <east>{east:.6f}</east>\n'
    kml_content += f'      <west>{west:.6f}</west>\n'
    kml_content += f'   </LatLonBox>\n'
    kml_content += f' </GroundOverlay>\n'
    kml_content += '  </Document>\n'
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
            # KML must be at root with .kml extension for Google Earth to find it
            kmz.write(kml_path, arcname=os.path.basename(kml_path))

            # Bundle assets
            for asset in asset_paths:
                if os.path.exists(asset):
                    # Place assets in 'files/' subdirectory to keep tidy
                    arcname = "files/" + os.path.basename(asset)
                    kmz.write(asset, arcname=arcname)
    except Exception as e:
        warnings.warn(f"Failed to write KMZ: {e}")
        return None

    return output_path


# Backwards-compatible alias expected by export/__init__.py.
export_kml = export_inundation_kml
