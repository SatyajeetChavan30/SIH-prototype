"""
GHSL built-up surface via Google Earth Engine (Phase 9).

Supplies the ASSET layer that turns a depth-damage ratio into a rupee figure.
Before this existed, ``impact/damage.py`` multiplied its damage ratios by three
fixed constants — 125 / 85 / 45 crore for residential / infrastructure /
agricultural — that were the same number for Tehri, Khadakwasla and every other
site, and were derived from nothing. A damage figure whose exposure term does
not vary with the catchment is not an estimate of that catchment.

WHAT THIS PRODUCT IS, EXACTLY. GHS-BUILT-S R2023A posts built-up SURFACE AREA
in m2 per 100 m cell — the roofprint area inside the cell, not a building
count, not a floor area, and not a footprint polygon. Two bands are used:

  * ``built_surface``      — total built-up surface, m2 per cell.
  * ``built_surface_nres`` — the non-residential part of that total, m2 per
    cell. Residential is derived as ``total - nres``.

That derivation is why the sector split here is real: it comes from two
published bands, not from a residential/commercial ratio somebody picked. A
building COUNT is still unavailable — Google Open Buildings (CC BY 4.0) is the
licence-compatible source for that and is not wired into this build.

BUILT-UP SURFACE IS EXTENSIVE. Each 100 m cell holds an AREA in m2, so moving
it onto a coarser solver grid must preserve the total. Note that
``ee.Reducer.sum()`` inside ``reduceResolution`` does NOT do that — Earth
Engine's weights make it an average, which cost the population layer a factor
of 25 before it was measured. ``grid_fetch.fetch_image_on_grid(extensive=True)``
carries the correction, and the damage figure is directly proportional to this
term, so an undetected factor there is a factor on the rupees.

THE VALUE IS ALREADY PER CELL. ``built_surface`` is m2, not a fraction, so a
caller must NOT multiply it by the solver cell area. Doing so gives m2 x m2 and
inflates the damage by the cell area — 40,000x at 200 m. ``impact/damage.py``
takes built-up m2 per cell for exactly this reason.

THREE STATES AND NO FOURTH: live, cached, or ``BuiltUpUnavailableError``.
Nothing here synthesises an asset layer, and there is deliberately no
``allow_synthetic`` parameter to reach for — following ``blockage_detect``
rather than ``population.py``, whose synthetic generator survives only for
tests. A fabricated exposure grid behind a rupee headline is the same class of
failure as a fabricated headcount behind a "people at risk" one.

OFFLINE-FIRST. A fetched grid is cached under a directory named for the domain
and kept indefinitely. Built-up surface for a given epoch does not change, so
there is no TTL here, matching the rest of this repository.

References:
  - Pesaresi, M. & Politis, P. (2023) "GHS-BUILT-S R2023A - GHS built-up
    surface grid, derived from Sentinel-2 and Landsat, multitemporal
    (1975-2030)", European Commission JRC. doi:10.2905/9F06F36F-4B11-47EC-ABB0-4F8B7B1D72EA
  - Gorelick, N. et al. (2017) "Google Earth Engine", RSE 202:18-27.
"""

from __future__ import annotations

import datetime as _dt
import json
import warnings
from pathlib import Path
from typing import Dict, Optional

import numpy as np

from floodview.gee.auth import gee_status

#: Multitemporal GHSL built-up surface collection (100 m posting).
GHS_BUILT_COLLECTION = "JRC/GHSL/P2023A/GHS_BUILT_S"

#: Total built-up surface, m2 per cell.
BUILT_SURFACE_BAND = "built_surface"

#: Non-residential built-up surface, m2 per cell. Present on every epoch of
#: R2023A — verified live against the collection rather than assumed, because
#: the catalog entry describes the NRES layer as 2018-only in some vintages.
BUILT_SURFACE_NRES_BAND = "built_surface_nres"

#: Epoch to use. GHSL R2023A runs 1975-2030; anything past the present is a
#: projection, so the most recent OBSERVED epoch is the honest default. Kept
#: equal to the population default so the two exposure layers describe the same
#: year unless a caller deliberately says otherwise.
DEFAULT_EPOCH = 2020

#: Attribution that must travel with any redistributed product built from this.
ATTRIBUTION = (
    "Built-up surface: GHS-BUILT-S R2023A, European Commission JRC, "
    "doi:10.2905/9F06F36F-4B11-47EC-ABB0-4F8B7B1D72EA."
)


class BuiltUpUnavailableError(RuntimeError):
    """
    No built-up surface grid could be produced, live or from cache.

    Raised rather than falling back to an assumed asset density. The caller's
    contract is to publish no damage figure for the affected sector and to say
    why — see ``services/api/floodview_service/tasks.py::_damage_estimate``.
    """


def _cache_manifest(cache_dir: Path) -> Path:
    return Path(cache_dir) / "ghs_built_manifest.json"


def _read_cache(cache_dir: Path) -> Optional[Dict]:
    manifest = _cache_manifest(cache_dir)
    if not manifest.exists():
        return None
    try:
        cached = json.loads(manifest.read_text(encoding="utf-8"))
    except Exception as exc:
        warnings.warn(f"Cached GHS-BUILT-S manifest is unreadable: {exc}")
        return None
    path = cached.get("geotiff_path")
    if not path or not Path(path).exists():
        return None
    return cached


def _split_sectors(total: np.ndarray, nres: np.ndarray) -> Dict:
    """
    Residential = total - non-residential, clipped at zero, drift reported.

    The two bands are aggregated independently, so float32 rounding can leave a
    cell whose non-residential surface marginally exceeds its total. Clipping
    silently would hide a much worse case: if the two bands ever disagree
    structurally, the residential share is meaningless and the count of clipped
    cells is the only evidence of it. So the count travels with the result.
    """
    residential = total - nres
    exceeded = int(np.count_nonzero(residential < 0.0))
    residential = np.maximum(residential, 0.0)
    return {
        "built_surface_res_m2": residential,
        "nres_exceeded_total_cells": exceeded,
    }


def fetch_built_up_on_grid(
    grid_dict: Dict,
    crs_epsg: int,
    cache_dir,
    epoch: int = DEFAULT_EPOCH,
) -> Dict:
    """
    GHSL built-up surface resampled onto the solver's own grid.

    The raster comes back in the solver's metric CRS on its exact cell
    alignment, because Earth Engine is handed the grid's affine transform
    directly. Both bands are fetched in ONE request so they cannot land on
    different grids and one shape check covers both.

    Args:
        grid_dict: {"nx","ny","dx","dy","x0","y0"} from the run's Grid.
        crs_epsg: The run's metric EPSG code.
        cache_dir: Directory for the cached GeoTIFF and manifest.
        epoch: GHSL epoch year.

    Returns:
        Dict with 'built_surface_m2', 'built_surface_nres_m2' and
        'built_surface_res_m2' [ny, nx] in solver row order (row 0 south), all
        in m2 PER CELL; their domain totals; 'nres_exceeded_total_cells'; and
        provenance ('source', 'collection', 'epoch', 'crs_epsg', 'aggregation',
        'geotiff_path', 'fetched_at', 'attribution').

    Raises:
        BuiltUpUnavailableError: when neither Earth Engine nor a cache can
            supply the grid.
    """
    from floodview.gee.grid_fetch import read_cached_stack

    cache_dir = Path(cache_dir)
    available, reason = gee_status()

    if available:
        try:
            result = _fetch_built_up_live(grid_dict, crs_epsg, cache_dir, epoch)
            _cache_manifest(cache_dir).write_text(
                json.dumps({k: v for k, v in result.items()
                            if not isinstance(v, np.ndarray)}, indent=2),
                encoding="utf-8")
            return result
        except Exception as exc:
            live_failure = f"{type(exc).__name__}: {exc}"
            print(f"[gee] Live GHS-BUILT-S fetch failed - {live_failure}")
    else:
        live_failure = reason
        print(f"[gee] Earth Engine unavailable for GHS-BUILT-S - {reason}")

    cached = _read_cache(cache_dir)
    if cached is not None:
        stack = read_cached_stack(cached["geotiff_path"], 2)
        total, nres = stack[0], stack[1]
        result = dict(cached)
        result["built_surface_m2"] = total
        result["built_surface_nres_m2"] = nres
        result.update(_split_sectors(total, nres))
        result["source"] = "cached"
        result["reason"] = f"Served from cache: {live_failure}"
        print(f"[gee] Serving cached GHS-BUILT-S grid "
              f"(epoch {cached.get('epoch')})")
        return result

    raise BuiltUpUnavailableError(
        f"No GHS-BUILT-S built-up surface grid available: the live Earth "
        f"Engine query could not run ({live_failure}), and nothing is cached "
        f"under {cache_dir}. No synthetic asset layer is substituted."
    )


def _fetch_built_up_live(grid_dict: Dict, crs_epsg: int, cache_dir: Path,
                         epoch: int) -> Dict:
    """Download both GHS-BUILT-S bands aligned to the solver grid, summed."""
    import ee

    from floodview.gee.grid_fetch import fetch_image_on_grid

    collection = ee.ImageCollection(GHS_BUILT_COLLECTION)
    image = collection.filter(
        ee.Filter.eq("system:index", str(epoch))).first()
    if image.getInfo() is None:
        # Fall back to the most recent available epoch rather than guessing an
        # index name, and report which one was actually used.
        image = collection.sort("system:time_start", False).first()
    resolved_epoch = image.get("system:index").getInfo()

    cache_dir.mkdir(parents=True, exist_ok=True)
    destination = cache_dir / f"ghs_built_{resolved_epoch}_epsg{crs_epsg}.tif"

    # extensive=True — built-up SURFACE is an area per source cell, so it must
    # be rescaled by the cell-area ratio rather than averaged. grid_fetch's
    # docstring records what `ee.Reducer.sum()` actually does here and the 25x
    # undercount it produced in the population layer.
    stack, meta = fetch_image_on_grid(
        image=image,
        bands=[BUILT_SURFACE_BAND, BUILT_SURFACE_NRES_BAND],
        grid_dict=grid_dict,
        crs_epsg=crs_epsg,
        destination=destination,
        extensive=True,
    )
    total, nres = stack[0], stack[1]
    sectors = _split_sectors(total, nres)

    result = {
        "built_surface_m2": total,
        "built_surface_nres_m2": nres,
        "total_built_surface_m2": float(total.sum()),
        "total_built_surface_nres_m2": float(nres.sum()),
        "total_built_surface_res_m2": float(sectors["built_surface_res_m2"].sum()),
        "nres_exceeded_total_cells": sectors["nres_exceeded_total_cells"],
        "source": "GHSL_BUILT_S_P2023A",
        "collection": GHS_BUILT_COLLECTION,
        "epoch": resolved_epoch,
        "crs_epsg": meta["crs_epsg"],
        "aggregation": meta["aggregation"],
        "geotiff_path": meta["geotiff_path"],
        "fetched_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "attribution": ATTRIBUTION,
    }
    result["built_surface_res_m2"] = sectors["built_surface_res_m2"]
    return result
