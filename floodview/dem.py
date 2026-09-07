"""
DEM (Digital Elevation Model) fetch and processing for JalRaksha.

Phase 0 responsibility: Fetch Copernicus GLO-30 DEM from the public AWS S3
bucket (open, no auth). Clip to a bounding box around dam + 60 km domain and
return a GeoTIFF path.

Source: Copernicus DEM GLO-30 (1 arc-second, ~30 m, global, free)
- Endpoint: https://copernicus-dem-30m.s3.amazonaws.com/
- Tile layout: Copernicus_DSM_COG_10_N<lat>_00_E<lon>_00_DEM/<same>.tif
- Each tile is 1 deg x 1 deg, 3600 x 3600, float32 metres, EPSG:4326

Why this endpoint and not the previous one: the SDSC mirror this module
originally targeted (cloud.sdsc.edu/v1/AUTH_ogc/...) now answers 401
Unauthorized. An auth-gated source violates the project's own hard rule
against login-gated data, and every fetch was silently falling through to
synthetic terrain. The AWS bucket is the distribution channel Copernicus
itself documents and needs no credentials.

Why Copernicus at all:
- Free, open, no login required
- 30 m resolution adequate for Tier-1 screening
- Global coverage, actively maintained

Why NOT:
- FABDEM: CC BY-NC-SA (redistribution restricted)
- MERIT: CC BY-NC (restricted)
- CartoDEM / Bhuvan: geo-fenced and login-gated

Resolution caveat: 30 m is a Tier-1 screening resolution. Point depths from a
30 m DEM are indicative only; lead with arrival times and inundation
envelopes.

Implementation:
  - fetch_dem(lat, lon, domain_radius_km, cache_dir, offline_mode) -> dem_path
  - Compute bounding box from dam location + radius
  - Identify the 1-degree tiles that overlap it
  - Fetch each tile's overlapping window via /vsicurl (range requests, not a
    43 MB whole-tile download), then register it in the cache
  - Mosaic, clip, write GeoTIFF
"""

from pathlib import Path
from typing import Tuple, Optional, Dict
import math
import warnings

import os

os.environ.pop("PROJ_LIB", None)
os.environ.pop("PROJ_DATA", None)
# Stop GDAL listing the whole S3 prefix on every open; without this each
# /vsicurl open issues a bucket listing before the first range request.
os.environ.setdefault("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")

import numpy as np
import rasterio
from rasterio.mask import mask
from rasterio.merge import merge
from rasterio.io import MemoryFile
from shapely.geometry import box

from jalraksha.cache import check_cache, store_cache, CacheError


class DEMError(Exception):
    """Raised when DEM operations fail."""

    pass


def latlon_to_utm_zone(lat: float, lon: float) -> int:
    """
    Compute UTM zone from lat/lon.

    Args:
        lat: Latitude (degrees, -90 to 90)
        lon: Longitude (degrees, -180 to 180)

    Returns:
        UTM zone number (1–60)
    """
    # UTM zone: lon in [-180, -174] → zone 1, [-174, -168] → zone 2, ..., [174, 180] → zone 60
    zone = math.floor((lon + 180) / 6) + 1
    return max(1, min(60, zone))


def copdem_tile_name(lat: int, lon: int) -> str:
    """
    Build the Copernicus GLO-30 tile stem for a 1-degree cell.

    The AWS layout keys tiles by the integer degree of their south-west
    corner, zero-padded to 2 digits of latitude and 3 of longitude:

        Copernicus_DSM_COG_10_N30_00_E078_00_DEM

    The "10" is the 10 x 1-arc-second (i.e. GLO-30) product code, and the two
    "_00" fields are the arc-minute offsets, always zero for whole-degree
    tiles.

    Args:
        lat: Integer latitude of the tile's south edge
        lon: Integer longitude of the tile's west edge

    Returns:
        Tile stem without extension
    """
    lat_str = f"N{lat:02d}" if lat >= 0 else f"S{abs(lat):02d}"
    lon_str = f"E{lon:03d}" if lon >= 0 else f"W{abs(lon):03d}"
    return f"Copernicus_DSM_COG_10_{lat_str}_00_{lon_str}_00_DEM"


def _tile_bounds(tile_path):
    """(lon_min, lat_min, lon_max, lat_max) of a cached tile, or None if unreadable."""
    try:
        import rasterio

        with rasterio.open(str(tile_path)) as src:
            bounds = src.bounds
        return (bounds.left, bounds.bottom, bounds.right, bounds.top)
    except Exception:
        return None


def _window_covers(
    tile_path, lon_min: float, lat_min: float, lon_max: float, lat_max: float
) -> bool:
    """
    Whether a cached tile actually contains the requested bounding box.

    Tiles are cached under the full tile's URL but hold only the window some
    earlier domain needed, so a cache hit says the FILE exists, not that it
    covers anything in particular. See the call site for the measured case.

    A half-cell tolerance is allowed on each edge: the clip that follows trims
    nodata edges anyway, and demanding exact containment would re-fetch on
    floating-point noise.
    """
    try:
        import rasterio

        with rasterio.open(str(tile_path)) as src:
            bounds = src.bounds
            tolerance = max(abs(src.res[0]), abs(src.res[1])) * 0.5
    except Exception:
        # Unreadable cached tile: treat it as not covering, so the caller
        # re-fetches rather than carrying a broken file into the mosaic.
        return False

    return (
        bounds.left <= lon_min + tolerance
        and bounds.right >= lon_max - tolerance
        and bounds.bottom <= lat_min + tolerance
        and bounds.top >= lat_max - tolerance
    )


def compute_copdem_tiles(
    lat_min: float, lon_min: float, lat_max: float, lon_max: float
) -> list:
    """
    Identify Copernicus DEM tiles covering a bounding box.

    Copernicus GLO-30 tiles are 1 deg x 1 deg in lat/lon, keyed by the integer
    degree of their south-west corner. floor(min) .. ceil(max) - 1 therefore
    enumerates every tile the box touches.

    Args:
        lat_min, lat_max: Latitude range (degrees)
        lon_min, lon_max: Longitude range (degrees)

    Returns:
        List of tile names (with .tif extension) to fetch
    """
    tiles = []

    for lon in range(int(math.floor(lon_min)), int(math.ceil(lon_max))):
        for lat in range(int(math.floor(lat_min)), int(math.ceil(lat_max))):
            tiles.append(f"{copdem_tile_name(lat, lon)}.tif")

    return tiles


def copdem_url(tile_name: str) -> str:
    """
    Construct the public Copernicus DEM COG URL from a tile name.

    On AWS each tile lives in a directory named after itself, so the stem
    appears twice in the path.

    Args:
        tile_name: Tile file name (e.g. "Copernicus_DSM_COG_10_N30_00_E078_00_DEM.tif")

    Returns:
        Full HTTPS URL to the COG
    """
    base = "https://copernicus-dem-30m.s3.amazonaws.com"
    stem = tile_name[:-4] if tile_name.endswith(".tif") else tile_name
    return f"{base}/{stem}/{stem}.tif"


def _tile_origin_from_name(tile_name: str) -> Tuple[int, int]:
    """
    Recover a tile's south-west corner from its name.

    Returns (lat, lon) as signed integer degrees. Raises DEMError if the name
    does not follow the Copernicus convention, rather than guessing — a
    mis-parsed origin silently georeferences terrain in the wrong place.
    """
    stem = tile_name[:-4] if tile_name.endswith(".tif") else tile_name
    parts = stem.split("_")
    lat_token = lon_token = None
    for part in parts:
        if part and part[0] in "NS" and part[1:].isdigit():
            lat_token = part
        elif part and part[0] in "EW" and part[1:].isdigit():
            lon_token = part

    if lat_token is None or lon_token is None:
        raise DEMError(f"Cannot parse tile origin from name: {tile_name!r}")

    lat = int(lat_token[1:]) * (1 if lat_token[0] == "N" else -1)
    lon = int(lon_token[1:]) * (1 if lon_token[0] == "E" else -1)
    return (lat, lon)


def generate_synthetic_dem_tile(
    tile_cache_path: Path,
    dam_lat: float,
    dam_lon: float,
    tile_lat: Optional[int] = None,
    tile_lon: Optional[int] = None,
) -> Path:
    """
    Generate a synthetic 1-degree terrain tile for offline fallback.

    Georeferenced to the tile's own south-west corner, not the dam. Passing
    the dam location for every tile — which this function used to do — stacks
    all tiles on the same footprint, so a 6-tile mosaic collapses to one
    tile's extent and the clip step then reads terrain from the wrong place.
    The tile origin is recovered from the file name when not supplied.

    The surface is a synthetic valley draining to the south-west. It exists so
    the pipeline is exercisable with no network; it is NOT terrain and must
    never be presented as a result. Callers warn on this path.

    Args:
        tile_cache_path: Where to write the tile
        dam_lat, dam_lon: Dam location, used only as a fallback origin
        tile_lat, tile_lon: Integer degrees of the tile's south-west corner

    Returns:
        The path written
    """
    if tile_lat is None or tile_lon is None:
        try:
            tile_lat, tile_lon = _tile_origin_from_name(tile_cache_path.name)
        except DEMError:
            tile_lat, tile_lon = int(math.floor(dam_lat)), int(math.floor(dam_lon))

    # 1 deg at 30 m is 3600 cells; 1200 keeps the fallback cheap while holding
    # the same footprint, so the mosaic geometry still matches the real tiles.
    ny, nx = 1200, 1200
    y, x = np.ogrid[:ny, :nx]

    # Valley floor falling to the south-west, with terraced side slopes.
    elevation = (
        800.0
        - 0.25 * (x + (ny - 1 - y))
        + 40.0 * np.sin(x / 90.0) * np.cos((ny - 1 - y) / 90.0)
    )
    elevation = np.clip(elevation, 100.0, 1500.0).astype(np.float32)

    from rasterio.transform import from_origin

    # from_origin takes the NORTH-west corner, so the tile's north edge is
    # tile_lat + 1.
    cell_size_deg = 1.0 / nx
    transform = from_origin(
        float(tile_lon), float(tile_lat) + 1.0, cell_size_deg, cell_size_deg
    )

    tile_cache_path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        str(tile_cache_path),
        "w",
        driver="GTiff",
        height=ny,
        width=nx,
        count=1,
        dtype=elevation.dtype,
        crs="EPSG:4326",
        transform=transform,
    ) as dst:
        dst.write(elevation, 1)

    return tile_cache_path


def _fetch_tile_window(
    tile_url: str,
    tile_cache_path: Path,
    lat_min: float,
    lon_min: float,
    lat_max: float,
    lon_max: float,
) -> Path:
    """
    Read only the requested window of a remote COG and write it locally.

    Copernicus GLO-30 tiles are ~43 MB each and a 60 km domain typically
    touches 4-6 of them, so downloading whole tiles costs a quarter-gigabyte
    for a domain that needs a fraction of it. Reading through /vsicurl issues
    HTTP range requests against the COG's internal tiling instead, which is
    both faster on first fetch and gentler on the endpoint.

    Raises DEMError on any failure so the caller can decide whether to fall
    back to synthetic terrain.
    """
    try:
        # These GDAL settings are load-bearing, not tuning. Without
        # GDAL_DISABLE_READDIR_ON_OPEN, /vsicurl lists the whole bucket prefix
        # before opening the object, which against copernicus-dem-30m hangs long
        # enough to look like a network failure — and would silently trip the
        # synthetic-terrain fallback below. The timeouts bound that failure mode
        # instead of letting a run stall indefinitely.
        with rasterio.Env(
            GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",
            CPL_VSIL_CURL_USE_HEAD="NO",
            GDAL_HTTP_TIMEOUT="30",
            GDAL_HTTP_CONNECTTIMEOUT="15",
            GDAL_HTTP_MAX_RETRY="3",
            GDAL_HTTP_RETRY_DELAY="2",
        ), rasterio.open(f"/vsicurl/{tile_url}") as src:
            window = src.window(lon_min, lat_min, lon_max, lat_max)
            # Round outward so the window fully covers the request, and clamp
            # to the tile: a domain straddling tiles asks each for a window
            # that runs off its edge.
            window = window.round_lengths(op="ceil").round_offsets(op="floor")
            window = window.intersection(
                rasterio.windows.Window(0, 0, src.width, src.height)
            )
            if window.width <= 0 or window.height <= 0:
                raise DEMError(f"Requested window does not intersect {tile_url}")

            data = src.read(1, window=window)
            profile = src.profile.copy()
            profile.update(
                {
                    "driver": "GTiff",
                    "height": data.shape[0],
                    "width": data.shape[1],
                    "transform": src.window_transform(window),
                    "count": 1,
                    "compress": "deflate",
                }
            )

        tile_cache_path.parent.mkdir(parents=True, exist_ok=True)
        with rasterio.open(str(tile_cache_path), "w", **profile) as dst:
            dst.write(data, 1)

    except DEMError:
        raise
    except Exception as e:
        raise DEMError(f"Windowed COG read failed for {tile_url}: {e}")

    return tile_cache_path


def fetch_dem(
    dam_lat: float,
    dam_lon: float,
    domain_radius_km: float = 60.0,
    cache_dir: Optional[str] = None,
    offline_mode: bool = False,
    margins_km: Optional[Dict[str, float]] = None,
) -> Path:
    """
    Fetch and cache Copernicus DEM for dam-break domain.

    Algorithm:
    1. Compute bounding box: dam ± domain_radius_km (in degrees, roughly), or
       an asymmetric box from `margins_km` when the domain is offset from the
       dam (e.g. biased downstream rather than dam-centred)
    2. Identify Copernicus tiles covering bbox
    3. For each tile:
       - Check cache; if hit, load from cache
       - If miss and offline_mode=False: fetch from AWS COG, cache, load
       - If miss and offline_mode=True: raise error
    4. Mosaic tiles (if >1)
    5. Clip to exact bounding box (metric CRS)
    6. Save as GeoTIFF to cache/dem/
    7. Return path

    Args:
        dam_lat: Dam latitude (degrees)
        dam_lon: Dam longitude (degrees)
        domain_radius_km: Domain radius (km); default 60 km. Ignored when
            `margins_km` is given.
        cache_dir: Cache root directory; default ./data
        offline_mode: If True, fail on cache miss (no network fetch)
        margins_km: Optional asymmetric extent as
            {"west": ..., "east": ..., "south": ..., "north": ...} (all km
            from the dam). When given, this replaces the symmetric
            `domain_radius_km` box entirely — used for a domain deliberately
            biased downstream rather than centred on the dam. The clipped
            product still saves to the SAME filename convention
            (dem_{lat:.2f}_{lon:.2f}_clipped.tif) as the symmetric case, so
            callers that resolve the DEM by lat/lon alone
            (services/api/jalraksha_service/tasks.py::_resolve_dem) need no
            change — the wider file simply replaces the narrower one at that
            path. Only one extent per (lat, lon) can be staged at a time.

    Returns:
        Path to cached DEM GeoTIFF in metric CRS

    Raises:
        DEMError: If fetch or processing fails
    """
    if cache_dir is None:
        cache_dir = Path("./data")
    else:
        cache_dir = Path(cache_dir)

    cache_dem_dir = cache_dir / "dem"
    cache_dem_dir.mkdir(parents=True, exist_ok=True)

    # Identity of the finished, clipped domain product. Both the short-circuit
    # check below and the registration at the end key off this.
    clipped_path = cache_dem_dir / f"dem_{dam_lat:.2f}_{dam_lon:.2f}_clipped.tif"
    if margins_km is not None:
        extent_tag = (
            f"w{margins_km['west']:g}_e{margins_km['east']:g}_"
            f"s{margins_km['south']:g}_n{margins_km['north']:g}km"
        )
    else:
        extent_tag = f"r{domain_radius_km:g}km"
    product_key = f"jalraksha://dem/clipped/{dam_lat:.4f}_{dam_lon:.4f}/{extent_tag}"

    # A repeat call should skip the whole fetch-mosaic-clip pipeline. Probe with
    # offline_mode=False even when offline: a miss here is not fatal, because the
    # per-tile cache below may still satisfy the request. Only that tile lookup
    # enforces the offline contract.
    try:
        product_hit, product_path = check_cache(product_key, cache_dem_dir, offline_mode=False)
    except CacheError:
        product_hit, product_path = False, None
    if product_hit and product_path is not None:
        print(f"[OK] DEM domain already cached: {product_path}")
        return Path(product_path)

    # Compute bounding box (rough, in degrees)
    # 1 degree ≈ 111 km at equator; at 30°N, ≈ 96 km
    lat_scale = 111.0  # km/degree
    lon_scale = 111.0 * math.cos(math.radians(dam_lat))  # km/degree, adjusted for latitude

    if margins_km is not None:
        lat_min = dam_lat - margins_km["south"] / lat_scale
        lat_max = dam_lat + margins_km["north"] / lat_scale
        lon_min = dam_lon - margins_km["west"] / lon_scale
        lon_max = dam_lon + margins_km["east"] / lon_scale
    else:
        lat_radius = domain_radius_km / lat_scale
        lon_radius = domain_radius_km / lon_scale

        lat_min = dam_lat - lat_radius
        lat_max = dam_lat + lat_radius
        lon_min = dam_lon - lon_radius
        lon_max = dam_lon + lon_radius

    print(
        f"\n[DEM] Fetching DEM for domain:\n"
        f"   Dam: ({dam_lat:.4f} N, {dam_lon:.4f} E)\n"
        f"   Extent: {margins_km if margins_km is not None else f'radius {domain_radius_km} km'}\n"
        f"   BBox: lat in [{lat_min:.2f}, {lat_max:.2f}], lon in [{lon_min:.2f}, {lon_max:.2f}]"
    )

    # Identify tiles
    tiles = compute_copdem_tiles(lat_min, lon_min, lat_max, lon_max)
    print(f"   Tiles needed: {len(tiles)}")
    for t in tiles:
        print(f"     - {t}")

    # Fetch/cache each tile
    tile_paths = []
    synthetic_tiles = []
    for tile_name in tiles:
        tile_url = copdem_url(tile_name)
        tile_cache_path = cache_dem_dir / tile_name

        # Check cache
        hit, cached_path = check_cache(tile_url, cache_dem_dir, offline_mode=offline_mode)

        # Window this tile is fetched for. Widened below to the union with
        # whatever a previous domain already cached, so a tile only ever grows.
        tile_lon_min, tile_lat_min = lon_min, lat_min
        tile_lon_max, tile_lat_max = lon_max, lat_max

        if hit and not _window_covers(cached_path, lon_min, lat_min, lon_max, lat_max):
            # A CACHE HIT IS NOT COVERAGE.
            #
            # _fetch_tile_window stores only the sub-window a previous domain
            # asked for, under the FULL TILE's URL as its cache key. So a tile
            # fetched for one dam is a hit for every other dam in the same
            # 1-degree square, however far away — and the file it returns may not
            # contain the requested area at all.
            #
            # Measured: the cached Copernicus_DSM_COG_10_N30_00_E079_00_DEM.tif
            # spans lon 79.000-79.105, the eastern sliver of Tehri's 60 km
            # window. A Rishi Ganga domain at lon 79.70 gets a confident "[OK]
            # Cache hit" for that file and then dies inside rasterio.mask with
            # "Input shapes do not overlap raster" — an error that says nothing
            # about the actual cause.
            #
            # Re-fetching the wider window is the fix. The alternative, keying
            # the cache on the window, would leave the same tile stored many
            # times over.
            #
            # The replacement window is the UNION of what is already cached and
            # what this domain needs. Fetching only the new window would silently
            # DESTROY the earlier domain's coverage — Tehri's own tile would stop
            # containing Tehri — turning a cache miss into a regression for a dam
            # nobody was running.
            existing = _tile_bounds(cached_path)
            if existing is not None:
                tile_lon_min = min(tile_lon_min, existing[0])
                tile_lat_min = min(tile_lat_min, existing[1])
                tile_lon_max = max(tile_lon_max, existing[2])
                tile_lat_max = max(tile_lat_max, existing[3])
            print(
                f"   Cached {tile_name} covers lon "
                f"{existing[0]:.3f}..{existing[2]:.3f} and does not reach this "
                f"domain; re-fetching the union, lon {tile_lon_min:.3f}.."
                f"{tile_lon_max:.3f} lat {tile_lat_min:.3f}..{tile_lat_max:.3f}."
                if existing
                else f"   Cached {tile_name} is unreadable; re-fetching."
            )
            hit = False

        if hit:
            tile_paths.append(cached_path)
            continue

        if offline_mode:
            raise DEMError(
                f"Offline mode: DEM tile {tile_name} not cached. "
                f"Run without --offline-mode to fetch."
            )

        # Fetch the overlapping window from the public COG, falling back to
        # synthetic terrain only if the network or endpoint fails.
        print(f"   Fetching {tile_name}...")
        try:
            _fetch_tile_window(
                tile_url,
                tile_cache_path,
                tile_lat_min,
                tile_lon_min,
                tile_lat_max,
                tile_lon_max,
            )
        except Exception as e:
            warnings.warn(
                f"Remote DEM fetch failed ({e}). Generating synthetic terrain "
                f"fallback tile — results from this run are NOT real terrain."
            )
            tile_lat, tile_lon = _tile_origin_from_name(tile_name)
            generate_synthetic_dem_tile(
                tile_cache_path, dam_lat, dam_lon, tile_lat, tile_lon
            )
            synthetic_tiles.append(tile_name)

        tile_paths.append(tile_cache_path)

        # Register in the cache so the next call is a hit. Without this the
        # offline-first contract is unmet: check_cache reads
        # CACHE_METADATA.json, and nothing was ever writing to it, so every
        # run re-fetched every tile and --offline-mode could never succeed.
        try:
            store_cache(
                tile_url,
                tile_cache_path,
                cache_dem_dir,
                metadata={
                    "format": "GeoTIFF",
                    "product": "Copernicus DEM GLO-30",
                    "synthetic": tile_name in synthetic_tiles,
                    "window_bbox": [
                        tile_lon_min, tile_lat_min, tile_lon_max, tile_lat_max
                    ],
                },
            )
        except CacheError as e:
            # A registration failure costs performance, not correctness.
            warnings.warn(f"Could not register {tile_name} in cache: {e}")

    if synthetic_tiles:
        warnings.warn(
            f"{len(synthetic_tiles)} of {len(tiles)} DEM tiles are synthetic "
            f"fallbacks. This DEM is for pipeline testing only."
        )

    # Mosaic tiles (if >1)
    if len(tile_paths) == 1:
        mosaic_path = tile_paths[0]
    else:
        print(f"   Mosaicking {len(tile_paths)} tiles...")
        try:
            mosaics = [rasterio.open(str(p)) for p in tile_paths]
            mosaic_array, mosaic_transform = merge(mosaics)
            mosaic_profile = mosaics[0].profile.copy()
            mosaic_profile.update(
                {
                    "height": mosaic_array.shape[1],
                    "width": mosaic_array.shape[2],
                    "transform": mosaic_transform,
                }
            )

            mosaic_path = cache_dem_dir / f"mosaic_{dam_lat:.2f}_{dam_lon:.2f}.tif"
            with rasterio.open(str(mosaic_path), "w", **mosaic_profile) as dst:
                dst.write(mosaic_array)

            for m in mosaics:
                m.close()

        except Exception as e:
            raise DEMError(f"Failed to mosaic tiles: {e}")

    # Clip to bounding box
    print("   Clipping to domain...")
    try:
        with rasterio.open(str(mosaic_path)) as src:
            bbox = box(lon_min, lat_min, lon_max, lat_max)
            # Declare an explicit nodata sentinel. Without one, mask() fills
            # any part of the crop window that the mosaic does not cover with
            # 0, and the crop window rounds outward by up to a cell — which
            # left a one-cell ring of 0 m elevation around the domain. Against
            # 3200 m Himalayan terrain that ring is a boundary-wide sink: the
            # solver would pour the entire reservoir into it.
            nodata_value = src.nodata if src.nodata is not None else -9999.0
            clipped_array, clipped_transform = mask(
                src, [bbox], crop=True, nodata=nodata_value, filled=True
            )

            band = clipped_array[0]

            # Trim any fully-nodata edge rows/columns rather than leaving them
            # for downstream code to trip over.
            valid = band != nodata_value
            if not valid.any():
                raise DEMError(
                    f"Clip produced no valid cells for ({dam_lat}, {dam_lon}). "
                    f"Check that the domain intersects the fetched tiles."
                )

            valid_rows = np.where(valid.any(axis=1))[0]
            valid_cols = np.where(valid.any(axis=0))[0]
            row_start, row_stop = int(valid_rows[0]), int(valid_rows[-1]) + 1
            col_start, col_stop = int(valid_cols[0]), int(valid_cols[-1]) + 1

            trimmed_rows = band.shape[0] - (row_stop - row_start)
            trimmed_cols = band.shape[1] - (col_stop - col_start)
            if trimmed_rows or trimmed_cols:
                print(
                    f"   Trimmed {trimmed_rows} nodata row(s) and "
                    f"{trimmed_cols} nodata column(s) from the clip edge"
                )

            band = band[row_start:row_stop, col_start:col_stop]
            clipped_transform = clipped_transform * rasterio.Affine.translation(
                col_start, row_start
            )
            clipped_array = band[np.newaxis, :, :]

            interior_gaps = int((band == nodata_value).sum())
            if interior_gaps:
                # Real Copernicus voids (steep terrain, water) can survive the
                # trim. Report them; Phase 2 conditioning is what fills them.
                warnings.warn(
                    f"DEM has {interior_gaps} interior nodata cells "
                    f"({interior_gaps / band.size * 100:.3f}%). Phase 2 terrain "
                    f"conditioning must fill these before the solver runs."
                )

            clipped_profile = src.profile.copy()
            clipped_profile.update(
                {
                    "driver": "GTiff",
                    "height": clipped_array.shape[1],
                    "width": clipped_array.shape[2],
                    "transform": clipped_transform,
                    "count": 1,
                    "nodata": nodata_value,
                    "compress": "deflate",
                }
            )

        with rasterio.open(str(clipped_path), "w", **clipped_profile) as dst:
            dst.write(clipped_array)

    except DEMError:
        raise
    except Exception as e:
        raise DEMError(f"Failed to clip DEM: {e}")

    # Register the finished product so a repeat call short-circuits the whole
    # mosaic-and-clip pipeline instead of redoing ~8 s of raster work.
    try:
        store_cache(
            product_key,
            clipped_path,
            cache_dem_dir,
            metadata={
                "format": "GeoTIFF",
                "product": "Copernicus DEM GLO-30 (clipped domain)",
                "synthetic": bool(synthetic_tiles),
                "domain_bbox": [lon_min, lat_min, lon_max, lat_max],
                "domain_radius_km": domain_radius_km,
            },
        )
    except CacheError as e:
        warnings.warn(f"Could not register clipped DEM in cache: {e}")

    print(f"[OK] DEM cached: {clipped_path}")
    print(f"  Shape: {clipped_array.shape[1]} x {clipped_array.shape[2]} cells")
    print(f"  CRS: {clipped_profile.get('crs', 'unknown')}")
    print(f"  Bounds: lat in [{lat_min:.2f}, {lat_max:.2f}], lon in [{lon_min:.2f}, {lon_max:.2f}]")

    return clipped_path
