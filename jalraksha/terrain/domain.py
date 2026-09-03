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
from typing import Tuple, Dict, Any, Optional
import warnings

import numpy as np
import rasterio
from scipy import ndimage

from jalraksha.solver.types import Grid, create_state
from jalraksha.terrain.conditioning import load_dem_as_grid


def latlon_to_utm(
    lat: float, lon: float, utm_zone: Optional[int] = None
) -> Tuple[int, float, float]:
    """
    Convert latitude/longitude to UTM coordinates via pyproj.

    Args:
        lat: Latitude (degrees)
        lon: Longitude (degrees)
        utm_zone: Force a specific zone. Needed when a domain straddles a zone
            boundary — every cell must share one CRS, so points outside the
            domain's zone have to be projected into it rather than into their
            own. Defaults to the zone containing (lat, lon).

    Returns:
        (zone, easting, northing) in metres, in the correct UTM zone/hemisphere
        (EPSG:326xx north / 327xx south) for (lat, lon).
    """
    if utm_zone is None:
        zone = int((lon + 180) / 6) + 1
        if zone < 1:
            zone = 60
        if zone > 60:
            zone = 1
    else:
        zone = int(utm_zone)
        if not 1 <= zone <= 60:
            raise ValueError(f"utm_zone must be in 1..60, got {utm_zone}")

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
    target_resolution: float = 200.0,
    domain_radius_km: float = 60.0,
    use_synthetic_terrain: bool = False,
    margins_km: Optional[Dict[str, float]] = None,
    fill_max_depth_m: float = 3.0,
) -> Tuple[Grid, Any, np.ndarray]:
    """
    Build computational domain from DEM for dam-break simulation.

    Bed elevation goes into State.b; State.h (water DEPTH) starts at zero.

    That distinction is the whole point of this function and was previously
    inverted: the old implementation assigned the elevation field to
    ``state_init.h``, leaving the bed flat at zero, so every run began with the
    entire domain under ~1500 m of standing water. Every gauge then "arrived"
    within a fraction of a second because the domain was already wet at t=0.

    Modelling note — the domain starts DRY rather than with an impounded
    reservoir. The flood volume enters through the breach hydrograph, which
    run.py injects at the breach cell each timestep and which is itself derived
    from the reservoir storage by the Phase 3 breach regressions. Impounding the
    reservoir here as well would double-count that water.

    Args:
        dam_config: Dam configuration (lat, lon, height_m, storage_mm3, ...)
        dem_path: Path to DEM GeoTIFF (from Phase 0 cache)
        target_resolution: Target grid resolution (metres)
        domain_radius_km: Half-width of the square domain (km). Ignored when
            `margins_km` is given.
        use_synthetic_terrain: Emergency fallback — build an analytic valley
            instead of reading the DEM. Off by default; results from a synthetic
            run are not real terrain and must not be presented as such.
        margins_km: Optional asymmetric extent
            {"west":.., "east":.., "south":.., "north":..} (km from the dam),
            for a domain deliberately biased in one direction (e.g. downstream,
            so the flood has runway to actually exit) rather than centred on
            the dam. Produces a rectangular grid.
        fill_max_depth_m: Passed through to load_dem_as_grid — threshold-limited
            depression fill; see that function's docstring. Pass 0 to disable.

    Returns:
        grid: Grid definition in a metric UTM CRS
        state_init: Initial state (dry bed, real topography in .b)
        manning_field: Manning's n coefficient field
    """
    dam_lat = dam_config["lat"]
    dam_lon = dam_config["lon"]

    if use_synthetic_terrain:
        grid, bed_elevation = _synthetic_domain(
            dam_lat, dam_lon, target_resolution, domain_radius_km
        )
        warnings.warn(
            "build_domain(use_synthetic_terrain=True): the bed is an analytic "
            "valley, NOT real topography. Arrival times and depths from this run "
            "are illustrative only and must not be reported as screening results."
        )
    else:
        print(f"\n[Terrain] Building domain from DEM: {dem_path}")
        grid, bed_elevation = load_dem_as_grid(
            dem_path,
            dam_lat,
            dam_lon,
            target_resolution=target_resolution,
            domain_radius_km=domain_radius_km,
            margins_km=margins_km,
            fill_max_depth_m=fill_max_depth_m,
        )

    print(f"  Grid: {grid.nx} x {grid.ny} cells @ {grid.dx:.0f} m resolution ({grid.crs})")
    print(f"  Domain: {grid.nx * grid.dx / 1000:.1f} x {grid.ny * grid.dy / 1000:.1f} km")
    print(
        f"  Bed elevation: {bed_elevation.min():.1f} to {bed_elevation.max():.1f} m "
        f"(mean {bed_elevation.mean():.1f} m)"
    )

    # Dry bed. Elevation belongs in b, NOT h — see the docstring; this was the
    # inverted assignment that made every previous run meaningless.
    state_init = create_state(
        grid,
        h_init=np.zeros((grid.ny, grid.nx), dtype=np.float64),
        b_init=bed_elevation,
    )

    # Manning's n. TODO: UNVETTED — a uniform 0.03 stands in for the ESA
    # WorldCover lookup in terrain/roughness.py, which is still a stub returning
    # this same constant. 0.03 is a conventional natural-channel value
    # (Chow 1959, Table 5-6); a real land-cover field is Phase 2 work.
    manning_field = np.full(
        (grid.ny, grid.nx), dam_config.get("manning_n", 0.03), dtype=np.float64
    )

    return grid, state_init, manning_field


def _synthetic_domain(
    dam_lat: float,
    dam_lon: float,
    target_resolution: float,
    domain_radius_km: float,
) -> Tuple[Grid, np.ndarray]:
    """
    Analytic valley used only as an emergency fallback (see build_domain).

    Vectorised: the previous version ran a 250,000-iteration Python double loop.
    """
    zone, dam_easting, dam_northing = latlon_to_utm(dam_lat, dam_lon)
    epsg = (32600 if dam_lat >= 0 else 32700) + zone
    n_cells = int(round(2.0 * domain_radius_km * 1000.0 / target_resolution))

    grid = Grid(
        nx=n_cells, ny=n_cells,
        dx=target_resolution, dy=target_resolution,
        x0=dam_easting - domain_radius_km * 1000.0,
        y0=dam_northing - domain_radius_km * 1000.0,
        crs=f"EPSG:{epsg}",
    )

    rows = np.arange(n_cells)[:, None]
    cols = np.arange(n_cells)[None, :]
    centre = n_cells // 2

    # A valley that descends toward +y, so released water has somewhere to go.
    downstream_slope = 0.01 * (rows - centre) * target_resolution
    valley_floor = 200.0 * (1.0 - np.exp(-((cols - centre) ** 2) / (n_cells / 6.0) ** 2))
    bed_elevation = 800.0 - downstream_slope + valley_floor

    return grid, np.ascontiguousarray(bed_elevation, dtype=np.float64)


def compute_breach_location(
    state: Any,
    grid: Grid,
    dam_lat: float,
    dam_lon: float,
    utm_zone: int,
    inject_lat: Optional[float] = None,
    inject_lon: Optional[float] = None,
) -> Tuple[int, int, float]:
    """
    Compute the cell the release hydrograph is injected at.

    Args:
        state: Initial state with topography
        grid: Grid definition
        dam_lat, dam_lon: Dam location
        utm_zone: UTM zone
        inject_lat, inject_lon: Optional explicit injection point, for a release
            that does not happen at the dam — a landslide barrier partway down
            the reach, say. Both must be given together. When omitted the
            behaviour is exactly as before.

    Returns:
        i_breach: column index (x), j_breach: row index (y)
        b_breach: bed elevation at that cell (m above sea level)
    """
    if (inject_lat is None) != (inject_lon is None):
        raise ValueError(
            "inject_lat and inject_lon must be supplied together; one alone "
            "would silently fall back to the domain centre."
        )

    if inject_lat is not None:
        # Project into the DOMAIN's zone, not the point's own: every cell shares
        # one CRS, and a release point near a zone boundary must be expressed in
        # the grid's coordinates rather than its own.
        _, easting, northing = latlon_to_utm(inject_lat, inject_lon, utm_zone=utm_zone)
        i_breach = int(np.floor((easting - grid.x0) / grid.dx))
        j_breach = int(np.floor((northing - grid.y0) / grid.dy))

        if not (0 <= i_breach < grid.nx and 0 <= j_breach < grid.ny):
            # Raising, not clamping. A clamped injection point would put the
            # release on the domain boundary and produce a complete,
            # plausible-looking flood originating somewhere nobody asked for —
            # the same failure class the DEM resolver refuses rather than
            # papering over.
            raise ValueError(
                f"Injection point ({inject_lat:.5f}, {inject_lon:.5f}) maps to "
                f"cell (i={i_breach}, j={j_breach}), outside the "
                f"{grid.nx} x {grid.ny} domain. The release point is not in the "
                f"modelled area; widen domain_radius_km or re-centre the domain."
            )
        b_breach = float(state.b[j_breach, i_breach])
        print(
            f"  Injection point: cell (i={i_breach}, j={j_breach}) from "
            f"({inject_lat:.5f}, {inject_lon:.5f}), bed elevation {b_breach:.1f} m"
        )
        return i_breach, j_breach, b_breach

    # load_dem_as_grid centres the domain on the dam, so the dam sits at the
    # middle cell by construction. i indexes x (columns, nx), j indexes y (rows,
    # ny) — matching the state.b[j, i] access used by run.py.
    i_breach = grid.nx // 2
    j_breach = grid.ny // 2

    # Read the real bed elevation instead of the previously hardcoded 1300.0 m,
    # which bore no relation to the terrain the solver was given.
    b_breach = float(state.b[j_breach, i_breach])

    print(f"  Breach location: cell (i={i_breach}, j={j_breach}), bed elevation {b_breach:.1f} m")

    return i_breach, j_breach, b_breach