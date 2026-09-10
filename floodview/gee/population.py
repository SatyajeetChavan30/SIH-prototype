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

COUNTS ARE EXTENSIVE, AND `ee.Reducer.sum()` DOES NOT SUM THEM. GHSL P2023A
posts population COUNT per 100 m cell, so moving it onto a coarser solver grid
must preserve the total. This module used to do that with
`reduceResolution(ee.Reducer.sum())` and documented at length why a mean would
be wrong — while producing exactly the mean it warned about. Earth Engine
weights each contributing pixel by the fraction of the OUTPUT pixel it covers,
and those weights sum to one, so a weighted sum IS an average. Measured over a
480x376 domain at 500 m: 741,659 people where the native-resolution total is
18,543,954, short by 25.003x — precisely (500/100)^2. Every population-at-risk
figure this project published before that was found was low by the square of
the ratio between the solver grid and 100 m.

The correction lives in `grid_fetch.fetch_image_on_grid(extensive=True)`: the
count becomes a density per m2, is aggregated as the intensive quantity it then
is, and is multiplied back by the solver cell area. See that module's docstring
for the measurements. THE OLD CACHE IS NOT REUSABLE — every `ghsl_manifest.json`
written before this fix points at a raster that is low by the cell-area ratio,
so the manifest name is versioned and the old ones are simply never read again.

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

from floodview.gee.auth import gee_status

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


#: Cache manifest name. VERSIONED: v1 manifests point at rasters aggregated
#: with the weighted `sum()` that is really a mean, so they are low by the
#: cell-area ratio. Bumping the name retires them rather than leaving a
#: silently wrong raster reachable — there is no in-place migration that could
#: recover the lost counts.
_MANIFEST_NAME = "ghsl_manifest_v2.json"


def _cache_manifest(cache_dir: Path) -> Path:
    return Path(cache_dir) / _MANIFEST_NAME


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

    from floodview.export.georef import grid_affine, to_north_up

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

    from floodview.gee.grid_fetch import fetch_image_on_grid

    collection = ee.ImageCollection(GHSL_COLLECTION)
    image = collection.filter(
        ee.Filter.eq("system:index", str(epoch))).first()
    if image.getInfo() is None:
        # Fall back to the most recent available epoch rather than guessing an
        # index name, and report which one was actually used.
        image = collection.sort("system:time_start", False).first()
    resolved_epoch = image.get("system:index").getInfo()

    # extensive=True — a population COUNT per source cell, not a density. See
    # grid_fetch's module docstring for why `ee.Reducer.sum()` is the wrong
    # tool for that and what it cost here. Clipping, the crsTransform +
    # dimensions download and the shape refusal all live there too, so this
    # module and the built-up / land-cover fetches cannot drift apart on cell
    # alignment.
    cache_dir.mkdir(parents=True, exist_ok=True)
    destination = (cache_dir /
                   f"ghsl_pop_{resolved_epoch}_epsg{crs_epsg}_areacorrected.tif")

    stack, meta = fetch_image_on_grid(
        image=image,
        bands=[GHSL_BAND],
        grid_dict=grid_dict,
        crs_epsg=crs_epsg,
        destination=destination,
        extensive=True,
    )
    grid = stack[0]

    return {
        "population_grid": grid,
        "total_population": float(grid.sum()),
        "source": "GHSL_P2023A",
        "collection": GHSL_COLLECTION,
        "epoch": resolved_epoch,
        "crs_epsg": meta["crs_epsg"],
        "aggregation": meta["aggregation"],
        "geotiff_path": meta["geotiff_path"],
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
