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

import heapq

import numpy as np
import rasterio
from rasterio.transform import Affine, from_origin
from rasterio.warp import Resampling, reproject
from scipy.ndimage import gaussian_filter, distance_transform_edt
from scipy.interpolate import RegularGridInterpolator

from jalraksha.solver.types import Grid, State, create_state


def _fill_nodata(elevation: np.ndarray, invalid_mask: np.ndarray) -> np.ndarray:
    """
    Fill nodata cells with their nearest valid neighbour's elevation.

    Copernicus GLO-30 has genuine voids over steep terrain and water bodies, and
    reprojection leaves nodata in the corners where the rotated source footprint
    does not cover the metric grid. Either way an unfilled cell is a hole in the
    bed: the solver would drain the whole reservoir into it (CLAUDE.md "DEM
    artifacts"). Nearest-neighbour fill is crude but never invents a sink, which
    is the property that matters here.
    """
    if not invalid_mask.any():
        return elevation
    # distance_transform_edt returns, for each invalid cell, the index of the
    # nearest valid cell — exactly the lookup we need.
    nearest = distance_transform_edt(
        invalid_mask, return_distances=False, return_indices=True
    )
    return elevation[tuple(nearest)]


def fill_depressions(bed: np.ndarray, max_fill_depth_m: float) -> tuple:
    """
    Threshold-limited priority-flood depression fill (Barnes et al. 2014).

    Bilinear downsampling of a narrow river channel to a coarse grid (see
    load_dem_as_grid's docstring) manufactures spurious local minima along
    the flow corridor — cells that are pits only because their true channel
    neighbours got averaged with higher bank elevation. Left alone, the
    solver's own flood water permanently pools in them (CLAUDE.md "DEM
    artifacts"): confirmed on a Khadakwasla run where the hazard classification
    plateaued at ~46 stuck SEVERE cells for the last 7.5 simulated hours of a
    24 h run instead of receding.

    Computes the FULL hydrological fill (every interior cell reaches a
    monotone downhill path to the domain boundary — matching the solver's
    transmissive boundary, the only place water can actually exit), then caps
    the raise actually applied per cell at `max_fill_depth_m`. A shallow pit
    (a metre or two — resampling noise) is fully filled; a real basin needing
    a bigger raise keeps standing at very nearly its original depth, since
    only the top `max_fill_depth_m` of it gets touched. This is deliberately
    NOT "fill everything to guarantee drainage" — a genuine multi-metre
    reservoir bowl or lake is left as terrain, not erased.

    Args:
        bed: (ny, nx) elevation array, no NaN/nodata (call _fill_nodata first).
        max_fill_depth_m: cap on the raise applied to any one cell (metres).

    Returns:
        (filled_bed, stats) — stats has n_filled (cells raised at all),
        max_raise_m (largest raise actually applied), and n_unfilled_deep
        (cells whose full hydrological fill exceeded the threshold, i.e. a
        real depression that was left standing).
    """
    ny, nx = bed.shape
    filled = bed.astype(np.float64, copy=True)
    visited = np.zeros((ny, nx), dtype=bool)
    heap = []

    # Seed the flood from the domain boundary: water can only leave there
    # (solver/core.py's transmissive boundary), so the boundary is the only
    # valid "sea level" a fill can drain to.
    for i in range(nx):
        for j in (0, ny - 1):
            if not visited[j, i]:
                visited[j, i] = True
                heapq.heappush(heap, (filled[j, i], j, i))
    for j in range(1, ny - 1):
        for i in (0, nx - 1):
            if not visited[j, i]:
                visited[j, i] = True
                heapq.heappush(heap, (filled[j, i], j, i))

    epsilon = 1e-6
    while heap:
        elev, j, i = heapq.heappop(heap)
        for dj, di in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            nj, ni = j + dj, i + di
            if nj < 0 or nj >= ny or ni < 0 or ni >= nx or visited[nj, ni]:
                continue
            visited[nj, ni] = True
            new_elev = filled[nj, ni] if filled[nj, ni] > elev else elev + epsilon
            filled[nj, ni] = new_elev
            heapq.heappush(heap, (new_elev, nj, ni))

    raise_amount = np.clip(filled - bed, 0.0, None)
    capped_raise = np.minimum(raise_amount, max_fill_depth_m)
    result = bed + capped_raise

    n_filled = int((raise_amount > epsilon).sum())
    n_unfilled_deep = int((raise_amount > max_fill_depth_m).sum())
    max_raise_m = float(capped_raise.max()) if n_filled else 0.0

    return result, {
        "n_filled": n_filled,
        "max_raise_m": max_raise_m,
        "n_unfilled_deep": n_unfilled_deep,
    }


def load_dem_as_grid(
    dem_path: str,
    dam_lat: float,
    dam_lon: float,
    target_resolution: float = 200.0,
    domain_radius_km: float = 60.0,
    smooth_sigma: float = 0.0,
    margins_km: dict = None,
    fill_max_depth_m: float = 3.0,
) -> tuple:
    """
    Load a DEM and reproject it onto a uniform metric grid centred on the dam.

    This is the single honest DEM -> Grid path. It replaces two broken ones: the
    old preprocess_dem() never reprojected (it divided a span in *degrees* by a
    resolution in *metres*, yielding nx=0 clamped to a 10x10 floor, and hardcoded
    EPSG:32643 regardless of location), and terrain/domain.py::build_domain()
    ignored the DEM entirely in favour of a synthetic cone.

    CLAUDE.md requires a metric CRS for every solver operation — never degrees.

    Args:
        dem_path: GeoTIFF DEM, typically geographic (EPSG:4326) from Phase 0.
        dam_lat, dam_lon: Dam location (degrees), used to centre the domain and
            to select the UTM zone.
        target_resolution: Grid spacing (m).
        domain_radius_km: Half-width of the square domain (km). Ignored when
            `margins_km` is given.
        margins_km: Optional asymmetric extent as
            {"west": ..., "east": ..., "south": ..., "north": ...} (km from
            the dam), for a domain deliberately biased in one direction
            (e.g. downstream) rather than centred on the dam. Produces a
            rectangular grid (nx may differ from ny).
        fill_max_depth_m: Depressions shallower than this are filled with a
            threshold-limited priority-flood pass (see `fill_depressions`
            below) so they don't trap flood water as permanent artefacts of
            bilinear resampling. Pass 0 to disable. Genuine basins deeper than
            the threshold are left untouched — this fills resampling noise,
            not real terrain.
        smooth_sigma: Gaussian smoothing in cells. DEFAULTS TO 0 (disabled).

            Measured against the 30 m source at two Bhagirathi landmarks, an
            isotropic Gaussian roughly DOUBLES the valley-floor error, because it
            blends the channel with the canyon walls that tower over it:

                                    sigma=0   sigma=1
                Tehri    @ 400 m     +31.5 m   +39.5 m
                Devprayag@ 400 m     +61.8 m  +140.3 m
                Tehri    @ 200 m     +17.7 m   +25.0 m
                Devprayag@ 200 m     +31.8 m   +82.3 m

            A river bed raised 140 m is not a cosmetic defect: it is the surface
            the flood routes over. The residual bias at sigma=0 is irreducible
            sub-grid averaging (a gorge narrower than one cell must average floor
            and wall), and halves with resolution as expected.

            CLAUDE.md's warning about GLO-30 cliff/water-body artifacts still
            stands, but a low-pass filter is the wrong instrument for it — it
            attacks the channel hardest. Use the edge-aware path
            (apply_edge_detection) for artifact suppression instead.

    Returns:
        (grid, bed_elevation): a Grid in metric CRS, and the float64 bed
        elevation array of shape (grid.ny, grid.nx). Row 0 is the SOUTHERNMOST
        row, matching Grid.cell_centres_y() which increases northward.
    """
    # Local import: terrain.domain imports this module's siblings, and importing
    # it at module scope would create a cycle.
    from jalraksha.terrain.domain import latlon_to_utm

    zone, dam_easting, dam_northing = latlon_to_utm(dam_lat, dam_lon)
    epsg = (32600 if dam_lat >= 0 else 32700) + zone
    dst_crs = f"EPSG:{epsg}"

    if margins_km is not None:
        west_m = margins_km["west"] * 1000.0
        east_m = margins_km["east"] * 1000.0
        south_m = margins_km["south"] * 1000.0
        north_m = margins_km["north"] * 1000.0
        nx = int(round((west_m + east_m) / target_resolution))
        ny = int(round((south_m + north_m) / target_resolution))
        if nx < 10 or ny < 10:
            raise ValueError(
                f"Domain margins {margins_km} at {target_resolution} m resolution "
                f"give only {nx}x{ny} cells; widen the margins or refine the grid."
            )
        x0 = dam_easting - west_m
        y0 = dam_northing - south_m
    else:
        half_span_m = domain_radius_km * 1000.0
        nx = ny = int(round(2.0 * half_span_m / target_resolution))
        if nx < 10:
            raise ValueError(
                f"Domain of {domain_radius_km} km at {target_resolution} m resolution "
                f"gives only {nx} cells; increase the radius or refine the grid."
            )
        x0 = dam_easting - half_span_m
        y0 = dam_northing - half_span_m

    # Destination transform is north-up (row 0 = north), which is the raster
    # convention rasterio.warp expects. We flip to south-up at the end to match
    # the Grid's y-increasing-northward convention.
    dst_transform = from_origin(x0, y0 + ny * target_resolution,
                                target_resolution, target_resolution)
    destination = np.full((ny, nx), np.nan, dtype=np.float64)

    with rasterio.open(dem_path) as src:
        src_nodata = src.nodata
        reproject(
            source=rasterio.band(src, 1),
            destination=destination,
            src_transform=src.transform,
            src_crs=src.crs,
            src_nodata=src_nodata,
            dst_transform=dst_transform,
            dst_crs=dst_crs,
            dst_nodata=np.nan,
            resampling=Resampling.bilinear,
        )

    invalid = ~np.isfinite(destination)
    if src_nodata is not None:
        invalid |= destination == src_nodata
    n_invalid = int(invalid.sum())
    if n_invalid:
        if n_invalid == destination.size:
            extent_desc = margins_km if margins_km is not None else f"{domain_radius_km} km radius"
            raise ValueError(
                f"DEM {dem_path} does not cover the {extent_desc} domain "
                f"around ({dam_lat}, {dam_lon}) — every cell is nodata."
            )
        print(f"  Filling {n_invalid} nodata cell(s) ({n_invalid / destination.size * 100:.2f}%)")
        destination = _fill_nodata(destination, invalid)

    if fill_max_depth_m and fill_max_depth_m > 0:
        destination, fill_stats = fill_depressions(destination, fill_max_depth_m)
        if fill_stats["n_filled"]:
            print(
                f"  Depression fill: raised {fill_stats['n_filled']} cell(s) "
                f"({fill_stats['n_filled'] / destination.size * 100:.3f}%), "
                f"max raise {fill_stats['max_raise_m']:.2f} m, "
                f"{fill_stats['n_unfilled_deep']} deeper pit(s) left untouched "
                f"(above the {fill_max_depth_m:.1f} m threshold)"
            )

    if smooth_sigma and smooth_sigma > 0:
        destination = gaussian_filter(destination, sigma=smooth_sigma)

    # Flip north-up raster rows to south-up, so row 0 is the southernmost row and
    # indexing agrees with Grid.cell_centres_y() / the keyframe bounds in
    # jalraksha/export/keyframes.py.
    bed_elevation = np.ascontiguousarray(np.flipud(destination), dtype=np.float64)

    grid = Grid(
        nx=nx, ny=ny,
        dx=target_resolution, dy=target_resolution,
        x0=x0, y0=y0, crs=dst_crs,
    )
    return grid, bed_elevation


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
        (grid, state, manning_n_field): Grid in metric CRS, initial State with a
        DRY bed and real topography in .b, and the Manning's n field.

    Note:
        This is now a thin wrapper over load_dem_as_grid(). The previous body
        divided a span in degrees by a resolution in metres (nx = 1.0 / 200 -> 0,
        clamped to a 10x10 floor), mixed degree origins with metre spacing, and
        hardcoded EPSG:32643 for every location. It also started the domain with
        a uniform 1 m of water everywhere, which is not a physical initial
        condition for a dam-break run.
    """
    with rasterio.open(dem_path) as dem_src:
        src_crs = dem_src.crs
        bounds = dem_src.bounds

    # A CRS tag can lie. Only treat a DEM as geographic if its bounds are also
    # plausible degrees — mislabelled rasters (EPSG:4326 declared over a metre
    # transform) are common enough in the wild that trusting the tag alone
    # produces a domain centred at, say, (450 N, -27450 E).
    looks_geographic = (
        src_crs is not None
        and src_crs.is_geographic
        and -180.0 <= bounds.left < bounds.right <= 180.0
        and -90.0 <= bounds.bottom < bounds.top <= 90.0
    )

    if dam_lat is None or dam_lon is None:
        if looks_geographic:
            # Geographic DEM, no dam given: centre the metric domain on the DEM.
            dam_lon = (bounds.left + bounds.right) / 2.0
            dam_lat = (bounds.bottom + bounds.top) / 2.0
        else:
            # Already-metric DEM (or no CRS at all): its own extent IS the
            # domain, so resample in place. Reprojecting it onto a dam-centred
            # UTM grid would be wrong twice over — there is no dam location to
            # centre on, and the coordinates are metres already.
            grid, bed_elevation = _grid_from_projected_dem(dem_path, target_resolution)
            return _finish_domain(grid, bed_elevation)

    grid, bed_elevation = load_dem_as_grid(
        dem_path,
        dam_lat,
        dam_lon,
        target_resolution=target_resolution,
        domain_radius_km=domain_radius_km,
    )
    return _finish_domain(grid, bed_elevation)


def _grid_from_projected_dem(dem_path: str, target_resolution: float) -> tuple:
    """Resample an already-metric DEM onto a uniform grid over its own extent."""
    with rasterio.open(dem_path) as src:
        bounds = src.bounds
        crs = src.crs
        nx = max(10, int(round((bounds.right - bounds.left) / target_resolution)))
        ny = max(10, int(round((bounds.top - bounds.bottom) / target_resolution)))

        dst_transform = from_origin(
            bounds.left, bounds.bottom + ny * target_resolution,
            target_resolution, target_resolution,
        )
        destination = np.full((ny, nx), np.nan, dtype=np.float64)
        reproject(
            source=rasterio.band(src, 1),
            destination=destination,
            src_transform=src.transform,
            src_crs=crs,
            src_nodata=src.nodata,
            dst_transform=dst_transform,
            dst_crs=crs,
            dst_nodata=np.nan,
            resampling=Resampling.bilinear,
        )

    invalid = ~np.isfinite(destination)
    if invalid.any():
        if invalid.all():
            raise ValueError(f"DEM {dem_path} has no valid cells.")
        destination = _fill_nodata(destination, invalid)

    grid = Grid(
        nx=nx, ny=ny, dx=target_resolution, dy=target_resolution,
        x0=bounds.left, y0=bounds.bottom,
        crs=str(crs) if crs is not None else "EPSG:32643",
    )
    # Flip to south-up rows, matching Grid.cell_centres_y().
    return grid, np.ascontiguousarray(np.flipud(destination), dtype=np.float64)


def _finish_domain(grid: Grid, bed_elevation: np.ndarray) -> tuple:
    """Wrap a (grid, bed) pair into the (grid, state, manning) triple."""

    # TODO: UNVETTED — uniform 0.03 until terrain/roughness.py returns a real
    # ESA WorldCover field; 0.03 is a conventional natural-channel value
    # (Chow 1959, Table 5-6).
    manning_n_field = np.full((grid.ny, grid.nx), 0.03, dtype=np.float64)

    # Dry bed: depth in h, elevation in b.
    state = create_state(
        grid,
        h_init=np.zeros((grid.ny, grid.nx), dtype=np.float64),
        b_init=bed_elevation,
    )

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
    # Create coordinate arrays for DEM (pixel centres, strictly ascending)
    y_min, y_max = min(dem_bounds.bottom, dem_bounds.top), max(dem_bounds.bottom, dem_bounds.top)
    x_min, x_max = min(dem_bounds.left, dem_bounds.right), max(dem_bounds.left, dem_bounds.right)

    dem_x = np.linspace(x_min, x_max, dem_data.shape[1])
    dem_y = np.linspace(y_min, y_max, dem_data.shape[0])

    # Grid cell centres
    grid_x, grid_y = grid.cell_centres_2d()
    mean_val = float(np.nanmean(dem_data)) if dem_data.size > 0 else 100.0

    try:
        interpolator = RegularGridInterpolator(
            (dem_y, dem_x),
            np.flipud(dem_data) if dem_bounds.top > dem_bounds.bottom else dem_data,
            method="linear",
            bounds_error=False,
            fill_value=mean_val,
        )

        points = np.column_stack([grid_y.ravel(), grid_x.ravel()])
        bed_elevation = interpolator(points).reshape(grid.ny, grid.nx)
    except Exception:
        bed_elevation = np.full((grid.ny, grid.nx), mean_val, dtype=np.float32)

    return np.nan_to_num(bed_elevation, nan=mean_val).astype(np.float32)


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
