"""
Domain geometry builder (Phase 2).

Constructs spatial domain for 2D SWE solver:
- Bounding box around dam (±60 km)
- Uniform Cartesian grid in metric CRS (UTM)
- Computes breach location

References:
  - Spec §2.3: Domain extent 60 km downstream
  - EPSG:32643: UTM Zone 43N (covers India)
"""

import os
os.environ.pop("PROJ_LIB", None)
os.environ.pop("PROJ_DATA", None)

import numpy as np
from pyproj import Transformer

from jalraksha.solver.types import Grid, State
from .conditioning import preprocess_dem


def latlon_to_utm(lat: float, lon: float, utm_zone: int = 43) -> tuple:
    """
    Convert lat/lon to UTM coordinates.

    Args:
        lat, lon: Latitude, longitude (decimal degrees)
        utm_zone: UTM zone (default 43 for India)

    Returns:
        (x_utm, y_utm): UTM coordinates (metres)
    """
    transformer = Transformer.from_crs("EPSG:4326", f"EPSG:326{utm_zone}", always_xy=True)
    x_utm, y_utm = transformer.transform(lon, lat)
    return x_utm, y_utm


def compute_utm_zone(lat: float, lon: float) -> int:
    """
    Compute UTM zone from lat/lon.

    Args:
        lat, lon: Latitude, longitude (decimal degrees)

    Returns:
        UTM zone (1–60)
    """
    zone = int((lon + 180) / 6) + 1
    return zone


def build_domain(
    dam_config: dict,
    dem_path: str,
    target_resolution: float = 200.0,
    manning_table: dict = None,
) -> tuple:
    """
    Build domain State for solver.

    Args:
        dam_config: Dict with keys: name, lat, lon, height_m, storage_mm3
        dem_path: Path to DEM GeoTIFF (from Phase 0 cache)
        target_resolution: Grid cell size (default 200 m)
        manning_table: Manning's n lookup table (from roughness.py)

    Returns:
        (grid, state, manning_field): Grid, initial State, Manning's n field
    """
    dam_lat = dam_config["lat"]
    dam_lon = dam_config["lon"]
    dam_name = dam_config["name"]

    # Compute UTM zone and convert dam location
    utm_zone = compute_utm_zone(dam_lat, dam_lon)
    dam_x_utm, dam_y_utm = latlon_to_utm(dam_lat, dam_lon, utm_zone)

    print(f"[Domain] {dam_name}: UTM zone {utm_zone}, location ({dam_x_utm:.0f}, {dam_y_utm:.0f}) m")

    # Bounding box: dam ± 60 km
    domain_radius_km = 60.0
    x_min = dam_x_utm - domain_radius_km * 1000
    x_max = dam_x_utm + domain_radius_km * 1000
    y_min = dam_y_utm - domain_radius_km * 1000
    y_max = dam_y_utm + domain_radius_km * 1000

    # Compute grid dimensions
    nx = int((x_max - x_min) / target_resolution)
    ny = int((y_max - y_min) / target_resolution)

    # Ensure minimum grid size
    nx = max(nx, 50)
    ny = max(ny, 50)

    print(f"[Domain] Grid: {nx} x {ny} cells @ {target_resolution} m = {nx*target_resolution/1000:.0f} x {ny*target_resolution/1000:.0f} km")

    # Create grid
    crs_string = f"EPSG:326{utm_zone}"
    grid = Grid(
        nx=nx,
        ny=ny,
        dx=target_resolution,
        dy=target_resolution,
        x0=x_min,
        y0=y_min,
        crs=crs_string,
    )

    # Preprocess DEM to grid
    _, state, manning_field = preprocess_dem(
        dem_path,
        target_resolution=target_resolution,
        manning_table=manning_table,
        dam_lat=dam_lat,
        dam_lon=dam_lon,
        domain_radius_km=domain_radius_km,
    )

    # Ensure grid matches state dimensions
    if state.h.shape != (grid.ny, grid.nx):
        print(f"[WARNING] State shape {state.h.shape} doesn't match grid ({grid.ny}, {grid.nx})")
        # Adjust grid to match state
        grid.ny, grid.nx = state.h.shape

    print(f"[Domain] Bed elevation range: {state.b.min():.1f} to {state.b.max():.1f} m")
    print(f"[Domain] Initial water depth: {state.h.mean():.2f} m")

    return grid, state, manning_field


def compute_breach_location(
    state: State,
    grid: Grid,
    dam_lat: float,
    dam_lon: float,
    utm_zone: int = 43,
) -> tuple:
    """
    Find breach location (lowest point near dam).

    Args:
        state: Initial state with bed elevation
        grid: Grid definition
        dam_lat, dam_lon: Dam location (lat/lon)
        utm_zone: UTM zone

    Returns:
        (i_breach, j_breach, b_breach): Cell indices and elevation
    """
    dam_x_utm, dam_y_utm = latlon_to_utm(dam_lat, dam_lon, utm_zone)

    # Cell centres
    x_centres, y_centres = grid.cell_centres_2d()

    # Distance to dam
    dist_to_dam = np.sqrt((x_centres - dam_x_utm)**2 + (y_centres - dam_y_utm)**2)

    # Search within 1 km of dam
    within_breach_zone = dist_to_dam <= 1000  # 1 km

    # Find lowest point within breach zone
    bed_in_zone = state.b.copy()
    bed_in_zone[~within_breach_zone] = np.inf  # Ignore points outside zone

    j_breach, i_breach = np.unravel_index(np.argmin(bed_in_zone), bed_in_zone.shape)
    b_breach = state.b[j_breach, i_breach]

    print(f"[Breach] Located at grid ({i_breach}, {j_breach}), elevation {b_breach:.1f} m")

    return i_breach, j_breach, b_breach
