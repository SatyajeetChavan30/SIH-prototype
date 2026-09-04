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

SAME CONTRACT AS THE REST OF jalraksha.gee. Three states and no fourth: live,
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
from pathlib import Path
from typing import Dict, Optional, Tuple

from jalraksha.gee.auth import gee_status
from jalraksha.terrain.roughness import LandCoverUnavailableError

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
            the caller — ``jalraksha.gee`` must not import the service layer,
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

        from jalraksha.gee.sar import _download

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
