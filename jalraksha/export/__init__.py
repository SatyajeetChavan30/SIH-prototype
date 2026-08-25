"""
Export module for dam-break simulation results.

Phase 5: Export formats — Cloud-Optimized GeoTIFF, Shapefile, KML.

Provides:
  - export_raster_to_cog() - single raster → COG
  - export_ensemble_to_cogs() - ensemble results → multiple COGs
  - validate_cog() - verify COG integrity

Exports are used by Phase 4 (end-to-end pipeline) to write final rasters.
"""

from .geotiff import (
    export_raster_to_cog,
    export_ensemble_to_cogs,
    validate_cog,
)

__all__ = [
    "export_raster_to_cog",
    "export_ensemble_to_cogs",
    "validate_cog",
]