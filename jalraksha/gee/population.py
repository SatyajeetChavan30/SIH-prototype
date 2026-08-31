"""
GHSL population exposure via Google Earth Engine (Phase 9).

Fetches the Global Human Settlement Layer population raster so that
population-at-risk figures rest on a published gridded census product rather
than on an assumed density.

WHY THIS WAS REWRITTEN. The previous version had a dead `ee` branch that
constructed a query and never evaluated it, wrapped in a bare `except: pass`,
followed unconditionally by an `np.random.uniform` "population" field labelled
`GHSL_Offline_Synthetic`. Any caller reading `population_grid` got random
numbers. The synthetic generator survives here only behind an explicit
`allow_synthetic=True` used by tests.

COUNTS AGGREGATE BY SUM, NOT MEAN. GHSL P2023A posts population COUNT per
100 m cell. The solver grid is coarser (200-400 m), so moving GHSL onto it must
SUM the contributing cells. Resampling counts with a mean — which is what every
default resampler does, because it assumes an intensive quantity — divides the
population by the cell-count ratio: at 400 m over a 100 m source that is a
sixteen-fold undercount, silently, in the number that says how many people are
at risk. `reduceResolution(ee.Reducer.sum())` is therefore not an optimisation
here, it is the difference between right and wrong.

References:
  - Schiavina, M., Freire, S., MacManus, K. (2023) "GHS-POP R2023A - GHS
    population grid multitemporal (1975-2030)", European Commission JRC.
  - Pesaresi, M. & Politis, P. (2023) "GHS-BUILT-S R2023A", European
    Commission JRC.
"""

from __future__ import annotations

import datetime as _dt
import json
import warnings
from pathlib import Path
from typing import Dict, Optional, Tuple

import numpy as np

from jalraksha.gee.auth import gee_status

#: Multitemporal GHSL population count collection (100 m posting).
GHSL_COLLECTION = "JRC/GHSL/P2023A/GHS_POP"
GHSL_BAND = "population_count"

#: Epoch to use. GHSL R2023A runs 1975-2030; anything past the present is a
#: projection, so the most recent OBSERVED epoch is the honest default.
DEFAULT_EPOCH = 2020


class PopulationUnavailableError(RuntimeError):
    """
    No population grid could be produced, live or from cache.

    Raised rather than falling back to a synthetic field. A fabricated
    population count feeding a "people at risk" headline is precisely the
    failure this module was rewritten to remove.
    """


def _cache_manifest(cache_dir: Path) -> Path:
    return Path(cache_dir) / "ghsl_manifest.json"


def _read_cache(cache_dir: Path) -> Optional[Dict]:
    manifest = _cache_manifest(cache_dir)
    if not manifest.exists():
        return None
    try:
        cached = json.loads(manifest.read_text(encoding="utf-8"))
    except Exception as exc:
        warnings.warn(f"Cached GHSL manifest is unreadable: {exc}")
        return None
    path = cached.get("geotiff_path")
    if not path or not Path(path).exists():
        return None
    return cached


def fetch_population_on_grid(
    grid_dict: Dict,
    crs_epsg: int,
    cache_dir,
    epoch: int = DEFAULT_EPOCH,
) -> Dict:
    """
    GHSL population counts resampled onto the solver's own grid.

    The raster comes back already in the solver's metric CRS and on its exact
    cell alignment, because Earth Engine is given the grid's affine transform
    directly. That removes a whole class of near-miss: a population grid that
    is half a cell — or a whole UTM zone — away from the depth grid it is about
    to be multiplied against.

    Args:
        grid_dict: {"nx","ny","dx","dy","x0","y0"} from the run's Grid.
        crs_epsg: The run's metric EPSG code.
        cache_dir: Directory for the cached GeoTIFF and manifest.
        epoch: GHSL epoch year.

    Returns:
        Dict with 'population_grid' [ny, nx] in solver row order (row 0 south),
        'total_population', 'source', 'epoch', 'geotiff_path'.

    Raises:
        PopulationUnavailableError: when neither Earth Engine nor a cache can
            supply the grid.
    """
    import rasterio

    from jalraksha.export.georef import grid_affine, to_north_up

    cache_dir = Path(cache_dir)
    available, reason = gee_status()

    if available:
        try:
            result = _fetch_ghsl_live(grid_dict, crs_epsg, cache_dir, epoch)
            _cache_manifest(cache_dir).write_text(
                json.dumps({k: v for k, v in result.items()
                            if k != "population_grid"}, indent=2),
                encoding="utf-8")
            return result
        except Exception as exc:
            live_failure = f"{type(exc).__name__}: {exc}"
            print(f"[gee] Live GHSL fetch failed - {live_failure}")
    else:
        live_failure = reason
        print(f"[gee] Earth Engine unavailable for GHSL - {reason}")

    cached = _read_cache(cache_dir)
    if cached is not None:
        with rasterio.open(cached["geotiff_path"]) as src:
            raster = src.read(1)
        # The GeoTIFF is north-up; the solver is south-up. to_north_up is its
        # own inverse for a vertical flip, so it converts either way.
        grid = to_north_up(raster).astype(np.float32)
        result = dict(cached)
        result["population_grid"] = grid
        result["source"] = "cached"
        result["reason"] = f"Served from cache: {live_failure}"
        print(f"[gee] Serving cached GHSL grid (epoch {cached.get('epoch')})")
        return result

    raise PopulationUnavailableError(
        f"No GHSL population grid available: the live Earth Engine query could "
        f"not run ({live_failure}), and nothing is cached under {cache_dir}. "
        f"No synthetic population is substituted."
    )


def _fetch_ghsl_live(grid_dict: Dict, crs_epsg: int, cache_dir: Path,
                     epoch: int) -> Dict:
    """Download GHSL aligned to the solver grid, aggregating counts by SUM."""
    import ee
    import rasterio
    import requests

    from jalraksha.export.georef import grid_affine, to_north_up

    nx, ny = int(grid_dict["nx"]), int(grid_dict["ny"])
    affine = grid_affine(grid_dict)
    # Earth Engine's crsTransform is [xScale, xShear, xTranslate,
    # yShear, yScale, yTranslate] — the same six numbers as a GDAL/Affine
    # transform in the same order.
    crs_transform = [affine.a, affine.b, affine.c, affine.d, affine.e, affine.f]

    collection = ee.ImageCollection(GHSL_COLLECTION)
    image = collection.filter(
        ee.Filter.eq("system:index", str(epoch))).first()
    if image.getInfo() is None:
        # Fall back to the most recent available epoch rather than guessing an
        # index name, and report which one was actually used.
        image = collection.sort("system:time_start", False).first()
    resolved_epoch = image.get("system:index").getInfo()

    # CLIP FIRST. reduceResolution on the unclipped global GHSL image makes
    # Earth Engine try to load the whole planet at 100 m to aggregate it, and
    # the request dies with "Number of pixels requested from Image.load exceeds
    # the maximum allowed (2^31)". Clipping to the run's own footprint before
    # aggregating is what keeps the work proportional to the domain.
    region = ee.Geometry.Rectangle(
        [affine.c, affine.f + affine.e * ny, affine.c + affine.a * nx, affine.f],
        proj=ee.Projection(f"EPSG:{crs_epsg}"), geodesic=False,
    )
    population = image.select(GHSL_BAND).clip(region)

    # SUM, not mean — see the module docstring. reduceResolution aggregates the
    # 100 m source cells that fall inside each solver cell before reprojection.
    aggregated = (
        population
        .reduceResolution(reducer=ee.Reducer.sum(), maxPixels=1024)
        .reproject(crs=f"EPSG:{crs_epsg}", crsTransform=crs_transform)
    )

    # crsTransform + dimensions, NOT region + scale. The latter returns a grid
    # one cell larger with its own origin (241x241 starting at 197500 rather
    # than 240x240 at 197736), which would put the population raster half a cell
    # off the depth raster it is about to be intersected with.
    url = aggregated.getDownloadURL({
        "format": "GEO_TIFF",
        "crsTransform": crs_transform,
        "dimensions": [nx, ny],
    })

    cache_dir.mkdir(parents=True, exist_ok=True)
    destination = cache_dir / f"ghsl_pop_{resolved_epoch}_epsg{crs_epsg}.tif"
    response = requests.get(url, timeout=300)
    response.raise_for_status()
    destination.write_bytes(response.content)

    with rasterio.open(destination) as src:
        raster = src.read(1)
        raster_crs = src.crs.to_epsg()

    if (raster.shape[0], raster.shape[1]) != (ny, nx):
        raise PopulationUnavailableError(
            f"GHSL download came back {raster.shape} but the solver grid is "
            f"({ny}, {nx}). Refusing to use a misaligned population grid."
        )

    grid = to_north_up(raster).astype(np.float32)   # north-up raster -> south-up solver
    grid = np.nan_to_num(grid, nan=0.0, posinf=0.0, neginf=0.0)

    return {
        "population_grid": grid,
        "total_population": float(grid.sum()),
        "source": "GHSL_P2023A",
        "collection": GHSL_COLLECTION,
        "epoch": resolved_epoch,
        "crs_epsg": raster_crs,
        "aggregation": "sum over contributing 100 m cells",
        "geotiff_path": str(destination),
        "fetched_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
    }


def fetch_ghsl_population_grid(
    bbox: Tuple[float, float, float, float],
    grid_shape: Tuple[int, int] = (50, 50),
    mean_density_per_cell: float = 25.0,
    allow_synthetic: bool = False,
    epoch: int = DEFAULT_EPOCH,
) -> Dict[str, np.ndarray]:
    """
    GHSL population counts over a lat/lon bounding box.

    The simple, bbox-shaped entry point. Use fetch_population_on_grid() when the
    result has to line up cell-for-cell with a simulation grid.

    Args:
        bbox: (min_lon, min_lat, max_lon, max_lat) in WGS84 degrees.
        grid_shape: Output array shape (ny, nx).
        mean_density_per_cell: Only used by the synthetic generator.
        allow_synthetic: Return a FABRICATED field instead of querying Earth
            Engine. Tests only; the returned `source` says so plainly.
        epoch: GHSL epoch year.

    Returns:
        Dict with 'population_grid', 'total_population', 'source'.

    Raises:
        PopulationUnavailableError: if Earth Engine is unavailable and
            allow_synthetic is False.
    """
    ny, nx = grid_shape

    if allow_synthetic:
        return _synthetic_population(ny, nx, mean_density_per_cell)

    available, reason = gee_status()
    if not available:
        raise PopulationUnavailableError(
            f"Cannot fetch GHSL population: {reason}. Pass allow_synthetic=True "
            f"only in tests - this function will not return fabricated "
            f"population counts as though they were census-derived."
        )

    import ee

    region = ee.Geometry.BBox(*bbox)
    collection = ee.ImageCollection(GHSL_COLLECTION)
    image = collection.filter(ee.Filter.eq("system:index", str(epoch))).first()
    if image.getInfo() is None:
        image = collection.sort("system:time_start", False).first()
    resolved_epoch = image.get("system:index").getInfo()

    sampled = image.select(GHSL_BAND).clip(region).sampleRectangle(
        region=region, defaultValue=0)
    grid = np.asarray(sampled.get(GHSL_BAND).getInfo(), dtype=np.float32)

    return {
        "population_grid": grid,
        "total_population": float(np.nansum(grid)),
        "source": "GHSL_P2023A",
        "collection": GHSL_COLLECTION,
        "epoch": resolved_epoch,
    }


def _synthetic_population(ny: int, nx: int, mean_density_per_cell: float) -> Dict:
    """
    A fabricated settlement field, for exercising array plumbing in tests.

    Reachable only through `allow_synthetic=True`. It used to be the silent
    result of every call, including calls that had asked for real GHSL data.
    """
    rng = np.random.default_rng(0)
    grid = rng.uniform(5.0, mean_density_per_cell * 1.5,
                       size=(ny, nx)).astype(np.float32)

    y, x = np.ogrid[:ny, :nx]
    urban = (x - nx // 2) ** 2 + (y - ny // 2) ** 2 <= (min(ny, nx) // 6) ** 2
    grid[urban] += rng.uniform(50.0, 150.0, size=int(urban.sum())).astype(np.float32)

    return {
        "population_grid": grid,
        "total_population": float(grid.sum()),
        "source": "SYNTHETIC_not_census_derived",
    }
