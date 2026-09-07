"""
ESA WorldCover land cover via Google Earth Engine (Phase 9).

Supplies the land-cover raster that turns ``terrain/roughness.py``'s Manning
table from a lookup nobody could use into a friction field. Before this existed
the whole domain ran on a single Manning's n of 0.03, which treats a forested
Himalayan hillside, the built-up bank of the Mutha and open reservoir water as
the same surface.

WHY WORLDCOVER AND NOT SOMETHING ELSE. It is 10 m, global, and CC BY 4.0 —
approved for redistribution under this project's licensing rules, unlike the
OSM-derived land-use layers (ODbL share-alike) and the non-commercial DEMs
CLAUDE.md forbids. Attribution travels in the manifest.

SAME CONTRACT AS THE REST OF floodview.gee. Three states and no fourth: live,
cached, or ``LandCoverUnavailableError``. Nothing here synthesises land cover.
A fabricated roughness field is worse than a uniform one, because a uniform
field is at least visibly a placeholder while a fabricated one has structure
that looks like evidence.

OFFLINE-FIRST. A fetched tile is content-addressed by its bounding box and
resolution and kept indefinitely. Land cover for a given epoch does not change,
so there is no TTL here, matching the rest of this repository.

References:
  - Zanaga, D. et al. (2022) "ESA WorldCover 10 m 2021 v200",
    doi:10.5281/zenodo.7254221. CC BY 4.0.
  - Gorelick, N. et al. (2017) "Google Earth Engine", RSE 202:18-27.
"""

from __future__ import annotations

import datetime as _dt
import json
import warnings
from pathlib import Path
from typing import Dict, Optional, Tuple

import numpy as np

from floodview.gee.auth import gee_status
from floodview.terrain.roughness import LandCoverUnavailableError

#: ESA WorldCover 2021 v200 in Earth Engine. v100 is the 2020 epoch; v200 is
#: the later one and is what the class legend in roughness.py describes.
WORLDCOVER_COLLECTION = "ESA/WorldCover/v200"

#: Posting for the fetched raster, metres.
#:
#: WorldCover is natively 10 m. The solver runs at 100-300 m, so fetching at
#: native resolution would download 100x the pixels the domain can use. 30 m
#: matches the DEM and keeps the class boundaries sharper than the grid they
#: are resampled onto — which is the only property that matters, since a
#: nearest-neighbour resample to the solver grid follows.
DEFAULT_SCALE_M = 30.0

#: Attribution that must travel with any redistributed product built from this.
ATTRIBUTION = (
    "Land cover: ESA WorldCover 10 m 2021 v200, "
    "doi:10.5281/zenodo.7254221, CC BY 4.0."
)


def _cache_paths(cache_dir: Path, bbox, scale_m: float) -> Tuple[Path, Path]:
    """Content-addressed by extent and posting, so two domains cannot collide."""
    min_lon, min_lat, max_lon, max_lat = bbox
    stem = (
        f"worldcover_{min_lon:.4f}_{min_lat:.4f}_"
        f"{max_lon:.4f}_{max_lat:.4f}_{scale_m:.0f}m"
    )
    cache_dir = Path(cache_dir)
    return cache_dir / f"{stem}.tif", cache_dir / f"{stem}.json"


def _read_cache(geotiff: Path, manifest: Path) -> Optional[Dict]:
    if not (geotiff.exists() and manifest.exists()):
        return None
    try:
        cached = json.loads(manifest.read_text(encoding="utf-8"))
    except Exception:
        return None
    cached = dict(cached)
    cached["source"] = "cached"
    return cached


def fetch_worldcover(
    bbox: Tuple[float, float, float, float],
    cache_dir,
    scale_m: float = DEFAULT_SCALE_M,
) -> Dict:
    """
    ESA WorldCover class codes over a bounding box.

    Args:
        bbox: (min_lon, min_lat, max_lon, max_lat) in WGS84 degrees. Supplied by
            the caller — ``floodview.gee`` must not import the service layer,
            which is where the site registry lives.
        cache_dir: Directory for the cached raster and its manifest.
        scale_m: Output posting, metres.

    Returns:
        Dict with ``geotiff_path``, ``source`` ("esa_worldcover_v200" or
        "cached"), the collection, the attribution string and the bbox.

    Raises:
        LandCoverUnavailableError: whenever a real raster cannot be produced —
            Earth Engine unavailable with nothing cached, or the download
            failing. No synthetic land cover is ever returned.
    """
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    geotiff, manifest = _cache_paths(cache_dir, bbox, scale_m)

    cached = _read_cache(geotiff, manifest)
    if cached is not None:
        return cached

    available, reason = gee_status()
    if not available:
        raise LandCoverUnavailableError(
            f"ESA WorldCover is not cached for this domain and Earth Engine is "
            f"not available ({reason}). No land cover is synthesised. The run "
            f"can still proceed on the uniform Manning default — omit "
            f"manning_table and worldcover_path — but friction will not vary "
            f"with land cover."
        )

    try:
        import ee

        from floodview.gee.sar import _download

        region = ee.Geometry.BBox(*bbox)
        image = (
            ee.ImageCollection(WORLDCOVER_COLLECTION)
            .first()
            .select("Map")
            .clip(region)
        )
        _download(
            image.getDownloadURL({
                "region": region,
                "scale": scale_m,
                "format": "GEO_TIFF",
                "crs": "EPSG:4326",
            }),
            geotiff,
        )
    except Exception as exc:
        raise LandCoverUnavailableError(
            f"Could not fetch ESA WorldCover over {bbox}: "
            f"{type(exc).__name__}: {exc}. No land cover is synthesised."
        ) from exc

    detection = {
        "source": "esa_worldcover_v200",
        "collection": WORLDCOVER_COLLECTION,
        "bbox": list(bbox),
        "scale_m": scale_m,
        "geotiff_path": str(geotiff),
        "attribution": ATTRIBUTION,
        "licence": "CC BY 4.0",
        "fetched_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "note": (
            "ESA WorldCover class codes, resampled to the solver grid by "
            "NEAREST NEIGHBOUR in terrain/roughness.py — these are categories, "
            "and an interpolated class code is not a land cover."
        ),
    }
    manifest.write_text(json.dumps(detection, indent=2), encoding="utf-8")
    return detection


#: Intermediate posting for the two-stage aggregation onto a solver grid.
#: 100 m matches the GHSL products, so every raster in the impact pipeline
#: passes through the same middle scale.
STAGE_SCALE_M = 100.0

#: ESA WorldCover class code for Cropland. The full legend lives in
#: ``terrain/roughness.py``; only this one class is needed here, because it is
#: the only one an agricultural damage figure is computed over.
CROPLAND_CLASS = 40


def _grid_cache_paths(cache_dir: Path, epoch_tag: str) -> Tuple[Path, Path]:
    cache_dir = Path(cache_dir)
    return (cache_dir / f"worldcover_cropland_{epoch_tag}.tif",
            cache_dir / "worldcover_cropland_manifest.json")


def fetch_cropland_fraction_on_grid(
    grid_dict: Dict,
    crs_epsg: int,
    cache_dir,
) -> Dict:
    """
    Per-cell CROPLAND FRACTION on the solver's own grid.

    WHY THIS EXISTS ALONGSIDE ``fetch_worldcover``. That function returns a
    4326, bbox-shaped, 30 m raster of class CODES, which ``roughness.py``
    resamples to the solver grid by nearest neighbour. Nearest neighbour is
    right for a friction lookup — an interpolated class code is not a land
    cover — but it is wrong for an AREA: it reports the class at the cell
    centre, so a 200 m cell that is 40% cropland comes back as either fully
    cropland or not cropland at all. An agricultural damage figure built on
    that is a coin flip per cell.

    It is also the only form that scales. WorldCover is 10 m; a 240 x 188 km
    domain fetched at 30 m is about 50 megapixels, past what
    ``getDownloadURL`` will return. Reducing to the solver grid server-side
    keeps the download proportional to the domain the solver actually has.

    So: ``Map.eq(40)`` gives a 0/1 cropland mask at native posting, and MEAN —
    not sum — aggregates it into the fraction of each solver cell that is
    cropland. Mean is correct here precisely because a fraction is INTENSIVE,
    which is the opposite of the population and built-up cases in this package.
    Multiply by the solver cell area to get cropland m2 per cell.

    Three states and no fourth, same as ``fetch_worldcover``: live, cached, or
    ``LandCoverUnavailableError``. No land cover is synthesised.

    Args:
        grid_dict: {"nx","ny","dx","dy","x0","y0"} from the run's Grid.
        crs_epsg: The run's metric EPSG code.
        cache_dir: Directory for the cached GeoTIFF and manifest.

    Returns:
        Dict with 'cropland_fraction' [ny, nx] in solver row order (row 0
        south), values in [0, 1], plus provenance.

    Raises:
        LandCoverUnavailableError: when neither Earth Engine nor a cache can
            supply the grid.
    """
    from floodview.gee.grid_fetch import read_cached_stack

    cache_dir = Path(cache_dir)
    geotiff, manifest = _grid_cache_paths(cache_dir, "v200")

    available, reason = gee_status()
    live_failure = reason

    if available:
        try:
            import ee

            from floodview.gee.grid_fetch import fetch_image_on_grid

            mask = (
                ee.ImageCollection(WORLDCOVER_COLLECTION)
                .first()
                .select("Map")
                .eq(CROPLAND_CLASS)
                .rename("cropland")
            )
            stack, meta = fetch_image_on_grid(
                image=mask,
                bands=["cropland"],
                grid_dict=grid_dict,
                crs_epsg=crs_epsg,
                destination=geotiff,
                # A FRACTION is intensive: the area-weighted mean of the 0/1
                # mask already is the cropland share of each solver cell, and
                # no cell-area rescaling belongs here. This is the opposite
                # case from population and built-up surface in this package.
                extensive=False,
                # WorldCover is 10 m and the solver runs at 100-500 m, which is
                # too far to cross in one reduceResolution: at 500 m Earth
                # Engine wants 3,081 source pixels per output pixel against a
                # 1,024 default, and lifting the cap instead asks it to
                # materialise the whole domain at 10 m ("Reprojection output
                # too large (27412x20470 pixels)"). Staging at 100 m makes both
                # ratios small, and both hops are means over the same fraction,
                # so nothing is approximated by splitting them.
                stage_scale_m=STAGE_SCALE_M,
            )
            fraction = np.clip(stack[0], 0.0, 1.0)
            detection = {
                "source": "esa_worldcover_v200",
                "collection": WORLDCOVER_COLLECTION,
                "class_code": CROPLAND_CLASS,
                "crs_epsg": meta["crs_epsg"],
                "aggregation":
                    f"{meta['aggregation']} — the 0/1 cropland mask, so an area fraction",
                "geotiff_path": meta["geotiff_path"],
                "attribution": ATTRIBUTION,
                "licence": "CC BY 4.0",
                "fetched_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
            }
            manifest.write_text(json.dumps(detection, indent=2), encoding="utf-8")
            detection["cropland_fraction"] = fraction
            return detection
        except Exception as exc:
            live_failure = f"{type(exc).__name__}: {exc}"
            print(f"[gee] Live WorldCover cropland fetch failed - {live_failure}")
    else:
        print(f"[gee] Earth Engine unavailable for WorldCover - {reason}")

    if geotiff.exists() and manifest.exists():
        try:
            cached = json.loads(manifest.read_text(encoding="utf-8"))
        except Exception as exc:
            warnings.warn(f"Cached cropland manifest is unreadable: {exc}")
            cached = None
        if cached is not None:
            cached = dict(cached)
            cached["cropland_fraction"] = np.clip(
                read_cached_stack(cached["geotiff_path"], 1)[0], 0.0, 1.0)
            cached["source"] = "cached"
            cached["reason"] = f"Served from cache: {live_failure}"
            return cached

    raise LandCoverUnavailableError(
        f"No ESA WorldCover cropland fraction available on this grid: the live "
        f"Earth Engine query could not run ({live_failure}), and nothing is "
        f"cached under {cache_dir}. No land cover is synthesised."
    )
