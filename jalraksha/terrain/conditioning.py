"""
Terrain preprocessing for 2D SWE solver (Phase 2).

Responsibilities:
- Load DEM from cache (Phase 0)
- Resample to solver grid resolution (typically 100–500 m)
- Apply smoothing to reduce artifacts
- Interpolate to uniform Cartesian grid
- Assign Manning's n from land-cover data

Output: State(h, u, v, b) ready for solver.

References:
  - Copernicus GLO-30 DEM: https://cloud.sdsc.edu/v1/AUTH_ogc/Raster/COPDEM/
  - ESA WorldCover 2021: https://esa-worldcover.org/
"""

import numpy as np
import rasterio
from rasterio.transform import Affine
from scipy.ndimage import gaussian_filter
from scipy.interpolate import RegularGridInterpolator

from jalraksha.solver.types import Grid, State, create_state


def preprocess_dem(
    dem_path: str,
    target_resolution: float = 200.0,
    manning_table: dict = None,
    dam_lat: float = None,
    dam_lon: float = None,
    domain_radius_km: float = 60.0,
) -> tuple:
    """
    Load and preprocess DEM for solver domain.

    Args:
        dem_path: Path to GeoTIFF DEM (from Phase 0 cache)
        target_resolution: Target grid resolution in metres (default 200 m)
        manning_table: Manning's n lookup table (from roughness.py)
        dam_lat, dam_lon: Dam location for domain centering (optional)
        domain_radius_km: Domain extent from dam center (default 60 km)

    Returns:
        (grid, state): Grid object and initial State for solver
    """
    # Load DEM from cache
    with rasterio.open(dem_path) as dem_src:
        dem_data = dem_src.read(1)  # Band 1
        dem_transform = dem_src.transform
        dem_crs = dem_src.crs
        dem_bounds = dem_src.bounds
        dem_res_x = dem_src.res[0]
        dem_res_y = dem_src.res[1]

    # Resample DEM to target resolution
    dem_resampled = resample_dem(dem_data, dem_res_x, target_resolution)

    # Apply smoothing (Gaussian filter, σ=1 pixel)
    dem_smooth = gaussian_filter(dem_resampled.astype(np.float32), sigma=1.0)

    # Create uniform Cartesian grid in metric CRS
    # For now, use simple lat/lon bounds; later convert to UTM via dam location
    nx = int((dem_bounds.right - dem_bounds.left) / target_resolution)
    ny = int((dem_bounds.top - dem_bounds.bottom) / target_resolution)

    grid = Grid(
        nx=max(nx, 10),  # Minimum 10 cells
        ny=max(ny, 10),
        dx=target_resolution,
        dy=target_resolution,
        x0=dem_bounds.left,
        y0=dem_bounds.bottom,
        crs="EPSG:32643",  # UTM 43N for India (will be refined in domain.py)
    )

    # Interpolate DEM to grid
    bed_elevation = interpolate_dem_to_grid(dem_smooth, grid, dem_bounds)

    # Assign Manning's n (default uniform if no table provided)
    if manning_table is None:
        manning_n_field = np.ones((grid.ny, grid.nx)) * 0.03
    else:
        manning_n_field = np.ones((grid.ny, grid.nx)) * 0.03  # TODO: load worldcover

    # Initial conditions: still water
    h_init = np.ones((grid.ny, grid.nx), dtype=np.float32) * 1.0  # 1 m initial depth
    state = create_state(grid, h_init, b_init=bed_elevation.astype(np.float32))

    return grid, state, manning_n_field


def resample_dem(dem_data: np.ndarray, original_resolution: float, target_resolution: float) -> np.ndarray:
    """
    Resample DEM to target resolution using bilinear interpolation.

    Args:
        dem_data: 2D DEM array
        original_resolution: Original pixel size (metres)
        target_resolution: Target pixel size (metres)

    Returns:
        Resampled DEM array
    """
    if abs(original_resolution - target_resolution) < 0.1:
        return dem_data  # No resampling needed

    # Scaling factor
    scale = original_resolution / target_resolution

    # Bilinear interpolation using scipy.ndimage.zoom
    from scipy.ndimage import zoom

    dem_resampled = zoom(dem_data, scale, order=1)  # order=1 is bilinear

    return dem_resampled


def interpolate_dem_to_grid(
    dem_data: np.ndarray,
    grid: Grid,
    dem_bounds,
) -> np.ndarray:
    """
    Interpolate DEM raster to uniform Cartesian grid.

    Args:
        dem_data: 2D DEM array (already resampled)
        grid: Target grid
        dem_bounds: Rasterio bounds object

    Returns:
        Bed elevation at grid cell centres
    """
    # Create coordinate arrays for DEM (pixel centres)
    dem_x = np.linspace(dem_bounds.left, dem_bounds.right, dem_data.shape[1])
    dem_y = np.linspace(dem_bounds.bottom, dem_bounds.top, dem_data.shape[0])

    # Grid cell centres
    grid_x, grid_y = grid.cell_centres_2d()

    # Bilinear interpolation
    interpolator = RegularGridInterpolator(
        (dem_y, dem_x),
        dem_data,
        method="linear",
        bounds_error=False,
        fill_value=dem_data.mean(),  # Fill out-of-bounds with mean elevation
    )

    # Stack and flatten for interpolation
    points = np.column_stack([grid_y.ravel(), grid_x.ravel()])
    bed_elevation = interpolator(points).reshape(grid.ny, grid.nx)

    return bed_elevation.astype(np.float32)


def apply_edge_detection(dem_data: np.ndarray, threshold: float = 5.0) -> np.ndarray:
    """
    Detect edges (cliffs, water bodies) in DEM and mask artifacts.

    Args:
        dem_data: 2D DEM array
        threshold: Gradient threshold for edge detection (m)

    Returns:
        Edge mask (True where gradient > threshold)
    """
    # Compute gradients
    grad_x = np.gradient(dem_data, axis=1)
    grad_y = np.gradient(dem_data, axis=0)
    grad_mag = np.sqrt(grad_x**2 + grad_y**2)

    edge_mask = grad_mag > threshold

    return edge_mask


def build_domain_state(
    grid: Grid,
    dem_path: str,
    manning_table: dict = None,
) -> tuple:
    """
    High-level wrapper to build domain State from DEM.

    Args:
        grid: Target grid (from domain.py)
        dem_path: Path to DEM GeoTIFF (from cache)
        manning_table: Manning's n lookup table

    Returns:
        (state, manning_field): Initial state and Manning's n field for all cells
    """
    grid_out, state, manning_field = preprocess_dem(
        dem_path,
        target_resolution=grid.dx,
        manning_table=manning_table,
    )

    return state, manning_field
