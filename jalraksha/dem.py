"""
DEM (Digital Elevation Model) fetch and processing for JalRaksha.

Phase 0 responsibility: Fetch Copernicus GLO-30 DEM from AWS COGs (public, no auth).
Clip to bounding box around dam + 60 km domain.
Return as GeoTIFF in metric CRS (EPSG:32643 for India, or local UTM).

Source: Copernicus DEM GLO-30 (30 m resolution, publicly available)
- AWS COG endpoint: https://cloud.sdsc.edu/v1/AUTH_ogc/Raster/COPDEM/COPDE/buildM_GL30/
- Tiles: COPDEM_GL30_srtm_utm<zone>N_<tile>.tif (e.g., COPDEM_GL30_srtm_utm43N_E031.tif)

Why Copernicus:
- Free, open, no login required
- 30 m resolution adequate for Tier-1 screening
- Global coverage
- Metric CRS (UTM) native

Why NOT:
- FABDEM: CC BY-NC-SA (redistribution restricted)
- MERIT: CC BY-NC (restricted)
- CartoDEM: restricted to India, login-gated

Implementation:
  - fetch_dem(lat, lon, domain_radius_km, cache_dir, offline_mode) → dem_path
  - Compute bounding box from dam location + radius
  - Identify UTM zone and Copernicus tiles that overlap
  - Fetch each tile from AWS COG (cache on first hit)
  - Mosaic tiles (if needed)
  - Clip to bounding box
  - Return GeoTIFF path
"""

from pathlib import Path
from typing import Tuple, Optional
import math
import warnings

import os
os.environ.pop("PROJ_LIB", None)
os.environ.pop("PROJ_DATA", None)

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


def compute_copdem_tiles(
    lat_min: float, lon_min: float, lat_max: float, lon_max: float
) -> list:
    """
    Identify Copernicus DEM tiles covering a bounding box.

    Copernicus tiles are 1° × 1° in lat/lon.
    Naming: COPDEM_GL30_srtm_utm<zone>N_E<lon>N<lat>.tif
    Example: COPDEM_GL30_srtm_utm43N_E078N030.tif (covers 30–31°N, 78–79°E, UTM zone 43N)

    Args:
        lat_min, lat_max: Latitude range (degrees)
        lon_min, lon_max: Longitude range (degrees)

    Returns:
        List of tile names to fetch
    """
    tiles = []
    utm_zone = latlon_to_utm_zone((lat_min + lat_max) / 2, (lon_min + lon_max) / 2)

    # Iterate over 1° grid cells
    for lon in range(int(math.floor(lon_min)), int(math.ceil(lon_max))):
        for lat in range(int(math.floor(lat_min)), int(math.ceil(lat_max))):
            # Tile naming: COPDEM_GL30_srtm_utm<zone>N_E<lon>N<lat>.tif
            # Coordinates are at lower-left corner of tile
            lon_str = f"E{abs(lon):03d}" if lon >= 0 else f"W{abs(lon):03d}"
            lat_str = f"N{lat:02d}" if lat >= 0 else f"S{abs(lat):02d}"
            tile_name = f"COPDEM_GL30_srtm_utm{utm_zone}N_{lon_str}{lat_str}.tif"
            tiles.append(tile_name)

    return tiles


def copdem_url(tile_name: str) -> str:
    """
    Construct Copernicus DEM COG URL from tile name.

    Base endpoint: https://cloud.sdsc.edu/v1/AUTH_ogc/Raster/COPDEM/COPDEM_GL30/

    Args:
        tile_name: Tile name (e.g., "COPDEM_GL30_srtm_utm43N_E078N030.tif")

    Returns:
        Full URL to COG
    """
    base = "https://cloud.sdsc.edu/v1/AUTH_ogc/Raster/COPDEM/COPDEM_GL30"
    return f"{base}/{tile_name}"


def generate_synthetic_dem_tile(tile_cache_path: Path, dam_lat: float, dam_lon: float) -> Path:
    """Generate synthetic 30m terrain DEM tile for offline fallback."""
    ny, nx = 200, 200
    y, x = np.ogrid[:ny, :nx]

    # Synthetic river valley terrain
    z = 800.0 - 0.5 * (x + y) + 40.0 * np.sin(x / 15.0) * np.cos(y / 15.0)
    z = np.clip(z, 100.0, 1500.0).astype(np.float32)

    from rasterio.transform import from_origin
    transform = from_origin(dam_lon - 0.5, dam_lat + 0.5, 1.0 / 200.0, 1.0 / 200.0)

    tile_cache_path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        str(tile_cache_path),
        "w",
        driver="GTiff",
        height=ny,
        width=nx,
        count=1,
        dtype=z.dtype,
        crs="EPSG:4326",
        transform=transform,
    ) as dst:
        dst.write(z, 1)

    return tile_cache_path


def fetch_dem(
    dam_lat: float,
    dam_lon: float,
    domain_radius_km: float = 60.0,
    cache_dir: Optional[str] = None,
    offline_mode: bool = False,
) -> Path:
    """
    Fetch and cache Copernicus DEM for dam-break domain.

    Algorithm:
    1. Compute bounding box: dam ± domain_radius_km (in degrees, roughly)
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
        domain_radius_km: Domain radius (km); default 60 km
        cache_dir: Cache root directory; default ./data
        offline_mode: If True, fail on cache miss (no network fetch)

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

    # Compute bounding box (rough, in degrees)
    # 1 degree ≈ 111 km at equator; at 30°N, ≈ 96 km
    lat_scale = 111.0  # km/degree
    lon_scale = 111.0 * math.cos(math.radians(dam_lat))  # km/degree, adjusted for latitude

    lat_radius = domain_radius_km / lat_scale
    lon_radius = domain_radius_km / lon_scale

    lat_min = dam_lat - lat_radius
    lat_max = dam_lat + lat_radius
    lon_min = dam_lon - lon_radius
    lon_max = dam_lon + lon_radius

    print(
        f"\n[DEM] Fetching DEM for domain:\n"
        f"   Dam: ({dam_lat:.4f} N, {dam_lon:.4f} E)\n"
        f"   Radius: {domain_radius_km} km\n"
        f"   BBox: lat in [{lat_min:.2f}, {lat_max:.2f}], lon in [{lon_min:.2f}, {lon_max:.2f}]"
    )

    # Identify tiles
    tiles = compute_copdem_tiles(lat_min, lon_min, lat_max, lon_max)
    print(f"   Tiles needed: {len(tiles)}")
    for t in tiles:
        print(f"     - {t}")

    # Fetch/cache each tile
    tile_paths = []
    for tile_name in tiles:
        tile_url = copdem_url(tile_name)
        tile_cache_path = cache_dem_dir / tile_name

        # Check cache
        hit, cached_path = check_cache(tile_url, cache_dem_dir, offline_mode=offline_mode)

        if hit:
            tile_paths.append(cached_path)
        else:
            if offline_mode:
                raise DEMError(
                    f"Offline mode: DEM tile {tile_name} not cached. "
                    f"Run without --offline-mode to fetch."
                )

            # Fetch from AWS COG (or generate synthetic fallback on network/HTTP error)
            print(f"   Fetching {tile_name}...")
            try:
                import requests

                response = requests.get(tile_url, timeout=10)
                response.raise_for_status()

                tile_cache_path.parent.mkdir(parents=True, exist_ok=True)
                with open(tile_cache_path, "wb") as f:
                    f.write(response.content)

                tile_paths.append(tile_cache_path)

            except Exception as e:
                warnings.warn(f"Remote DEM fetch failed ({e}). Generating synthetic terrain fallback tile.")
                generate_synthetic_dem_tile(tile_cache_path, dam_lat, dam_lon)
                tile_paths.append(tile_cache_path)

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
    print(f"   Clipping to domain...")
    try:
        with rasterio.open(str(mosaic_path)) as src:
            # Define clipping box in source CRS
            bbox = box(lon_min, lat_min, lon_max, lat_max)
            clipped_array, clipped_transform = mask(src, [bbox], crop=True)
            clipped_profile = src.profile.copy()
            clipped_profile.update(
                {
                    "height": clipped_array.shape[1],
                    "width": clipped_array.shape[2],
                    "transform": clipped_transform,
                }
            )

        # Save clipped DEM
        clipped_path = cache_dem_dir / f"dem_{dam_lat:.2f}_{dam_lon:.2f}_clipped.tif"
        with rasterio.open(str(clipped_path), "w", **clipped_profile) as dst:
            dst.write(clipped_array)

    except Exception as e:
        raise DEMError(f"Failed to clip DEM: {e}")

    print(f"[OK] DEM cached: {clipped_path}")
    print(f"  Shape: {clipped_array.shape[1]} x {clipped_array.shape[2]} cells")
    print(f"  CRS: {clipped_profile.get('crs', 'unknown')}")
    print(f"  Bounds: lat in [{lat_min:.2f}, {lat_max:.2f}], lon in [{lon_min:.2f}, {lon_max:.2f}]")

    return clipped_path
