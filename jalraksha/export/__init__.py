"""
Output modules for JalRaksha results.

Phase 5+: Export results in various formats (GeoTIFF, Shapefile, KML, keyframes).

Exports:
- GeoTIFF (Cloud-Optimized GeoTIFF)
- Shapefile (polygons)
- KML/KMZ (for visualization)
- Keyframe PNGs for 3D visualization
- Word (.docx) run report

The report module is safe to import without python-docx installed: the optional
dependency is imported inside its functions, so only building a document
raises.
"""

from jalraksha.export.geotiff import export_cog
from jalraksha.export.shapefile import export_shapefile
from jalraksha.export.kml import export_kml
from jalraksha.export.keyframes import export_keyframes
from jalraksha.export.docx_report import build_report

__all__ = [
    "export_cog",
    "export_shapefile",
    "export_kml",
    "export_keyframes",
    "build_report",
]