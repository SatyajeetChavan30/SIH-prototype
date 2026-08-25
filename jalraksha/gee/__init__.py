"""
Phase 9: Google Earth Engine & Open Data Integration Package.

Implements Sentinel-1 SAR satellite flood detection, GHSL population density ingestion,
and Earth Engine integration with 100% offline fallback support.

Modules:
  - auth: GEE authentication & offline mode manager
  - sar: Sentinel-1 SAR VV/VH backscatter flood mapping
  - population: GHSL population density grid fetcher
"""

from jalraksha.gee.auth import init_gee, is_gee_available
from jalraksha.gee.sar import process_sentinel1_sar_flood
from jalraksha.gee.population import fetch_ghsl_population_grid

__all__ = [
    "init_gee",
    "is_gee_available",
    "process_sentinel1_sar_flood",
    "fetch_ghsl_population_grid",
]
