"""
Manning's roughness coefficient assignment (Phase 2).

Maps land-cover classes (ESA WorldCover 2021) to Manning's n values.

References:
  - ESA WorldCover 2021: https://esa-worldcover.org/
  - Manning's n lookup tables from literature (Chow 1959, USGS)
"""

import numpy as np

# ESA WorldCover 10 m land-cover classes → Manning's n
MANNING_TABLE_ESA = {
    10: 0.08,   # Shrubland
    20: 0.08,   # Grassland
    30: 0.05,   # Cropland
    40: 0.06,   # Built area / urban
    50: 0.01,   # Bare / rock / sand
    60: 0.08,   # Snow / ice
    70: 0.08,   # Trees / forest
    80: 0.08,   # Herbaceous wetland
    90: 0.08,   # Mangroves
    95: 0.08,   # Moss / lichen
}

# Fallback values (literature)
MANNING_TABLE_FALLBACK = {
    "concrete": 0.010,
    "asphalt": 0.012,
    "brick": 0.015,
    "grass": 0.035,
    "shrub": 0.08,
    "forest": 0.08,
    "urban": 0.06,
    "water": 0.03,
}


def assign_manning_from_worldcover(
    worldcover_path: str,
    grid_shape: tuple,
    manning_table: dict = None,
) -> np.ndarray:
    """
    Assign Manning's n field from ESA WorldCover raster.

    Args:
        worldcover_path: Path to WorldCover GeoTIFF (10 m resolution)
        grid_shape: Target grid shape (ny, nx)
        manning_table: Custom Manning table (default: ESA_WORLDCOVER)

    Returns:
        Manning's n field (ny, nx) at grid resolution
    """
    if manning_table is None:
        manning_table = MANNING_TABLE_ESA

    # TODO: Load WorldCover from GEE or local cache
    # For now, return uniform fallback
    manning_field = np.ones(grid_shape, dtype=np.float32) * 0.03

    return manning_field


def get_manning_value(
    land_cover_class: int,
    manning_table: dict = None,
) -> float:
    """
    Get Manning's n for a single land-cover class.

    Args:
        land_cover_class: ESA WorldCover class code (10–95)
        manning_table: Custom Manning table (default: ESA_WORLDCOVER)

    Returns:
        Manning's n coefficient
    """
    if manning_table is None:
        manning_table = MANNING_TABLE_ESA

    return manning_table.get(land_cover_class, 0.03)  # Default 0.03


def source_citation() -> str:
    """Return citation for Manning's n values."""
    return """
    Manning's n assignments:
    - Urban/built (ESA 40): 0.06 — USGS guidelines for developed areas
    - Grassland (ESA 20): 0.08 — Chow 1959 Table 5-6
    - Shrubland (ESA 10): 0.08 — Chow 1959 Table 5-6
    - Forest (ESA 70): 0.08 — Chow 1959, dense vegetation
    - Cropland (ESA 30): 0.05 — USGS, cultivated fields
    - Bare/rock (ESA 50): 0.01 — Minimum friction, smooth surface
    - Concrete/asphalt: 0.01–0.015 — Standard spillway values

    TODO: Verify against India-specific land-use data (if available from CWC)
    """
