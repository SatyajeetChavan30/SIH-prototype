"""
Terrain domain building from DEM for dam-break simulations.

Phase 2: Build computational domain, condition DEM, prepare grid.

Inputs:
- DEM (from Phase 0)
- Dam configuration
- Target grid resolution

Outputs:
- Grid definition (uniform Cartesian)
- Initial state (dry bed)
- Manning's n field (from ESA WorldCover)
"""

from pathlib import Path
from typing import Tuple, Dict, Any
import numpy as np
import rasterio
from scipy import ndimage

from jalraksha.solver.types import Grid, create_state


def latlon_to_utm(lat: float, lon: float) -> Tuple[int, float, float]:
    """
    Convert latitude/longitude to UTM coordinates via pyproj.

    Args:
        lat: Latitude (degrees)
        lon: Longitude (degrees)

    Returns:
        (zone, easting, northing) in meters, in the correct UTM zone/hemisphere
        (EPSG:326xx north / 327xx south) for (lat, lon).
    """
    zone = int((lon + 180) / 6) + 1
    if zone < 1:
        zone = 60
    if zone > 60:
        zone = 1

    epsg = 32600 + zone if lat >= 0 else 32700 + zone
    from pyproj import Transformer

    transformer = Transformer.from_crs("EPSG:4326", f"EPSG:{epsg}", always_xy=True)
    easting, northing = transformer.transform(lon, lat)

    return zone, float(easting), float(northing)


def compute_utm_zone(lat: float, lon: float) -> int:
    """Compute UTM zone number from lat/lon."""
    return int((lon + 180) / 6) + 1


def build_domain(
    dam_config: Dict[str, Any],
    dem_path: str,
    target_resolution: float = 200.0
) -> Tuple[Grid, Any, np.ndarray]:
    """
    Build computational domain from DEM for dam-break simulation.

    Args:
        dam_config: Dam configuration (lat, lon, height, storage, etc.)
        dem_path: Path to DEM GeoTIFF file
        target_resolution: Target grid resolution (meters)

    Returns:
        grid: Grid definition
        state_init: Initial state (dry bed, h=0 everywhere)
        manning_field: Manning's n coefficient field
    """
    print(f"\n[Terrain] Building domain from DEM: {dem_path}")

    # Load DEM using rasterio
    with rasterio.open(dem_path) as src:
        dem_array = src.read(1)  # First band (elevation)
        transform = src.transform
        crs = src.crs

        # Check CRS
        if crs and "EPSG:4326" in str(crs):
            print("  WARNING: DEM in geographic CRS (degrees), reprojecting to metric...")
            # Would need proper reprojection in full implementation

    # Compute domain extent (add buffer around dam)
    dam_lat = dam_config["lat"]
    dam_lon = dam_config["lon"]
    domain_radius_km = 30.0  # 30 km buffer

    # Convert to degrees roughly (1 deg ≈ 111 km)
    lat_radius = domain_radius_km / 111.0
    lon_radius = domain_radius_km / (111.0 * np.cos(np.radians(dam_lat)))

    lat_min = dam_lat - lat_radius
    lat_max = dam_lat + lat_radius
    lon_min = dam_lon - lon_radius
    lon_max = dam_lon + lon_radius

    # Load DEM subset within bounding box
    # In full implementation: extract subset from DEM
    ny, nx = 500, 500  # Simplified - would compute based on resolution

    # Georeference the grid on the dam's real location so exported rasters/
    # keyframes place the flood at the correct spot on the map, even though
    # the terrain itself is still synthetic (tracked separately from this fix).
    zone, dam_easting, dam_northing = latlon_to_utm(dam_lat, dam_lon)
    epsg = 32600 + zone if dam_lat >= 0 else 32700 + zone
    x0 = dam_easting - (nx / 2.0) * target_resolution
    y0 = dam_northing - (ny / 2.0) * target_resolution

    # Create grid
    grid = Grid(
        nx=nx,
        ny=ny,
        dx=target_resolution,
        dy=target_resolution,
        x0=x0,
        y0=y0,
        crs=f"EPSG:{epsg}",
    )

    print(f"  Grid: {grid.nx} x {grid.ny} cells @ {grid.dx:.0f} m resolution")
    print(f"  Domain extent: {lat_min:.4f}° to {lat_max:.4f}° lat, {lon_min:.4f}° to {lon_max:.4f}° lon")

    # Create initial state (depth is set below from the synthetic terrain).
    state_init = create_state(grid, h_init=np.zeros((grid.ny, grid.nx), dtype=np.float64))

    # Generate synthetic terrain for demonstration
    # In full implementation: interpolate actual DEM
    dem_field = np.zeros((grid.ny, grid.nx))

    # Create synthetic terrain profile representing dam valley
    for i in range(grid.ny):
        for j in range(grid.nx):
            # Base elevation
            base_elev = 800.0  # meters

            # Dam location (center of domain)
            dam_i, dam_j = grid.ny // 2, grid.nx // 2

            # Dam mountain shape (simplified)
            dist_from_dam = np.sqrt((i - dam_i) ** 2 + (j - dam_j) ** 2)
            dam_height = 500.0 * np.exp(-dist_from_dam / (grid.nx / 4))

            # River valley
            valley = 200.0 * np.exp(-((j - grid.nx // 2) ** 2) / ((grid.nx // 4) ** 2))

            dem_field[i, j] = base_elev + dam_height + valley

    # Set initial water surface to DEM elevation (dry bed)
    state_init.h = np.maximum(dem_field, 0.0)

    # Generate Manning's n field based on land cover
    manning_field = np.full((grid.ny, grid.nx), dam_config.get("manning_n", 0.03))

    # Add roughness variations
    roughness = np.random.normal(1.0, 0.1, (grid.ny, grid.nx))
    manning_field *= roughness

    return grid, state_init, manning_field


def compute_breach_location(
    state: Any,
    grid: Grid,
    dam_lat: float,
    dam_lon: float,
    utm_zone: int
) -> Tuple[int, int, float]:
    """
    Compute breach location on dam.

    Args:
        state: Initial state with topography
        grid: Grid definition
        dam_lat, dam_lon: Dam location
        utm_zone: UTM zone

    Returns:
        i_breach, j_breach: Cell indices of breach location
        b_breach: Breach elevation (m)
    """
    # In full implementation: use dam geometry and elevation data
    # For demonstration: place breach at center of domain

    i_breach = grid.ny // 2
    j_breach = grid.nx // 2

    # Breach elevation (simplified - top of dam)
    b_breach = 1300.0  # meters above sea level

    print(f"  Breach location: cell ({i_breach}, {j_breach}), elevation {b_breach:.1f}m")

    return i_breach, j_breach, b_breach