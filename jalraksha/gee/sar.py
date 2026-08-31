"""
Sentinel-1 SAR observed water extent via Google Earth Engine (Phase 9).

Radar backscatter over open water is specular — the signal reflects away from
the sensor — so water appears as a dark region in a VV-polarised GRD scene.
Thresholding that darkness gives an observed water extent, independent of cloud
and daylight, which is what makes SAR the right instrument for flood
observation.

WHAT THIS PRODUCES, STATED PRECISELY. An **observed water extent**, not an
observed flood. On an ordinary day over Tehri the mask shows the reservoir and
the Bhagirathi channel, because they are water. Calling that a detected flood
would be an overclaim; separating flood from permanent water needs a pre-event
baseline (Clement et al. 2018) and an event date, neither of which a "latest
observed extent" query has.

THRESHOLD. Derived per scene by Otsu's method, but NOT from the whole scene —
from sub-tiles that are demonstrably bimodal. No fixed dB value is hardcoded:
water/land separation in VV depends on incidence angle, terrain and wind
roughening, so a single published constant would be an unvetted coefficient
under CLAUDE.md.

WHY TILES, AND NOT THE WHOLE SCENE. Otsu assumes two classes of comparable
mass. Over a Himalayan gorge that assumption fails outright: the reservoir is a
sliver of the scene, and radar shadow on steep slopes produces low backscatter
that looks like water. Measured over Tehri, the full-scene VV histogram is
UNIMODAL — one broad land mode peaking near -10 dB with a shadow tail toward
-25 dB — and whole-scene Otsu cut straight through the middle of that land peak
at -10.1 dB, classifying 45% of a mountain valley as water. The mask looked
like a real product and was nonsense.

The split-based approach (Martinis et al. 2009; Chini et al. 2017) is the
established answer: score sub-tiles for bimodality, derive the threshold only
from tiles that contain both classes, and apply it scene-wide. Tiles are scored
by Otsu's own separability measure, and if no tile qualifies this module RAISES
rather than emitting a threshold it cannot justify.

References for the method:
  - Martinis, S., Twele, A., Voigt, S. (2009) "Towards operational near
    real-time flood detection using a split-based automatic thresholding
    procedure on high resolution TerraSAR-X data", NHESS 9:303-314.
  - Chini, M. et al. (2017) "A Hierarchical Split-Based Approach for Parametric
    Thresholding of SAR Images", IEEE TGRS 55(12):6975-6988.

OFFLINE-FIRST. Every successful fetch is cached with its acquisition date and
scene id. When the network or Earth Engine is unavailable and a cache exists,
the cached scene is served and LABELLED as cached. When neither is available
the call raises. Synthetic data is never substituted for an observation — that
is what `process_sentinel1_sar_flood(allow_synthetic=True)` is for, and it is
used only by tests.

References:
  - Otsu, N. (1979) "A Threshold Selection Method from Gray-Level Histograms",
    IEEE Trans. Systems, Man, and Cybernetics 9(1):62-66.
  - Clement, M.A. et al. (2018) "Multi-temporal synthetic aperture radar flood
    mapping using change detection", J. Flood Risk Management 11(2):152-168.
  - Gorelick, N. et al. (2017) "Google Earth Engine", RSE 202:18-27.
"""

from __future__ import annotations

import datetime as _dt
import json
import time
import warnings
from pathlib import Path
from typing import Dict, Optional, Tuple

import numpy as np

from jalraksha.gee.auth import gee_status

#: Sentinel-1 Ground Range Detected, the analysis-ready EE collection.
S1_COLLECTION = "COPERNICUS/S1_GRD"

#: Output posting for the fetched mask. 60 m is two Sentinel-1 GRD pixels and
#: comfortably finer than the 30 m DEM the simulation runs on, while keeping a
#: reach-sized download to a few hundred kB.
DEFAULT_SCALE_M = 60.0

#: Buckets for the histogram Otsu is computed from. Enough to resolve the
#: water/land modes in dB without making the reduceRegion call expensive.
HISTOGRAM_BUCKETS = 256

#: Sub-tiles per axis for the split-based threshold. 8x8 over a ~22 km window
#: gives ~2.7 km tiles: small enough that a tile containing the reservoir is
#: genuinely bimodal, large enough to still hold thousands of pixels at 60 m.
TILE_GRID = 8


class SarUnavailableError(RuntimeError):
    """
    No observed SAR extent could be produced, live or from cache.

    Raised rather than returning something. A synthetic mask presented as an
    observation is the failure this module exists to remove.
    """


def otsu_threshold(counts, bin_centres) -> float:
    """
    Otsu's threshold: the value that maximises between-class variance.

    Water and land form two modes in a VV backscatter histogram. Otsu finds the
    split between them from the data itself, so nothing about the sensor
    geometry or the terrain has to be assumed in advance.

    Args:
        counts: Histogram counts per bucket.
        bin_centres: Backscatter value (dB) at each bucket centre.

    Returns:
        Threshold in dB. Pixels BELOW it are water.

    Raises:
        ValueError: if the histogram is empty or degenerate, rather than
            returning an arbitrary bucket edge.
    """
    counts = np.asarray(counts, dtype=np.float64)
    centres = np.asarray(bin_centres, dtype=np.float64)
    if counts.size < 2 or centres.size != counts.size:
        raise ValueError(
            f"Cannot compute an Otsu threshold from {counts.size} histogram "
            f"buckets against {centres.size} bin centres."
        )

    total = counts.sum()
    if total <= 0:
        raise ValueError("Histogram is empty; the scene covers no valid pixels.")

    weight_below = np.cumsum(counts)
    weight_above = total - weight_below

    cumulative_mean = np.cumsum(counts * centres)
    grand_total = cumulative_mean[-1]

    # Guard the empty-class divisions; those buckets are excluded below anyway.
    safe_below = np.where(weight_below > 0, weight_below, 1.0)
    safe_above = np.where(weight_above > 0, weight_above, 1.0)
    mean_below = cumulative_mean / safe_below
    mean_above = (grand_total - cumulative_mean) / safe_above

    between_class_variance = weight_below * weight_above * (mean_below - mean_above) ** 2
    usable = (weight_below > 0) & (weight_above > 0)
    if not usable.any():
        raise ValueError(
            "Histogram is single-valued; no water/land split can be derived."
        )

    best = int(np.argmax(np.where(usable, between_class_variance, -np.inf)))
    return float(centres[best])


def otsu_separability(counts, bin_centres, threshold: float) -> float:
    """
    Otsu's separability measure, eta = between-class variance / total variance.

    This is the number that tells you whether the split MEANS anything. Otsu
    always returns a threshold; eta says whether the two sides are genuinely
    two populations (eta -> 1) or one population arbitrarily bisected
    (eta -> 0). It is the criterion Otsu (1979) himself proposes for judging a
    threshold's goodness, and it is what stops a unimodal mountain-terrain
    histogram from yielding a confident, meaningless water mask.

    Returns:
        eta in [0, 1]; 0.0 for a degenerate histogram.
    """
    counts = np.asarray(counts, dtype=np.float64)
    centres = np.asarray(bin_centres, dtype=np.float64)
    total = counts.sum()
    if total <= 0:
        return 0.0

    grand_mean = float((counts * centres).sum() / total)
    total_variance = float((counts * (centres - grand_mean) ** 2).sum() / total)
    if total_variance <= 0:
        return 0.0

    below = centres <= threshold
    w0 = counts[below].sum() / total
    w1 = 1.0 - w0
    if w0 <= 0 or w1 <= 0:
        return 0.0

    m0 = float((counts[below] * centres[below]).sum() / counts[below].sum())
    m1 = float((counts[~below] * centres[~below]).sum() / counts[~below].sum())
    between = w0 * w1 * (m0 - m1) ** 2
    return float(min(max(between / total_variance, 0.0), 1.0))


#: Minimum Otsu separability for a tile to be treated as containing two classes.
#:
#: TODO: UNVETTED — Martinis et al. (2009) and Chini et al. (2017) establish the
#: split-based method but each uses its own tile-acceptance criteria. 0.7 was
#: chosen here because the Tehri land-only tiles score far below it while tiles
#: straddling the reservoir score above; it is a working value, not a published
#: one. Spec section 17 verification queue.
MIN_TILE_SEPARABILITY = 0.7

#: A tile is only informative if BOTH classes have real mass. Below this the
#: "water" side is a handful of shadow pixels.
MIN_TILE_CLASS_FRACTION = 0.05

#: Loose upper bound on the final mask, to catch total garbage early. It is NOT
#: the real guard: a window centred on a large reservoir can legitimately be
#: mostly water (Hirakud measures 50% permanent water), so a tight bound here
#: would reject good masks. The real guard is agreement with JRC below.
MAX_PLAUSIBLE_WATER_FRACTION = 0.80

#: Independent reference for where water really is: the JRC Global Surface Water
#: occurrence layer, a peer-reviewed product built from 32 years of Landsat.
#: Used to MEASURE the derived mask rather than to produce it.
JRC_GSW = "JRC/GSW1_4/GlobalSurfaceWater"
JRC_PERMANENT_OCCURRENCE_PCT = 80

#: Minimum precision the derived mask must reach against JRC permanent water
#: before it is published.
#:
#: This exists because of a measured failure, not a hypothetical one. Over the
#: Tehri gorge, VV thresholding reaches recall 0.95 but precision 0.010 — 99% of
#: what it calls water is radar shadow on hillsides, and the resulting mask
#: covered half a mountain valley. Over Hirakud on the flat Mahanadi plain the
#: same code reaches precision 0.77 and produces a genuine reservoir outline.
#: Steep terrain defeats VV-only thresholding; that is a known limitation of the
#: technique, not a defect to be tuned away, and the honest response is to
#: report it rather than publish the mask.
#:
#: TODO: UNVETTED — 0.5 separates the two measured cases (0.010 vs 0.77) with
#: wide margin, but it is a working threshold, not one taken from a publication.
#: Terrain-corrected local-incidence-angle masking (Small 2011) is the
#: documented way to make steep terrain workable and is not implemented here.
#: Spec section 17 verification queue.
MIN_JRC_PRECISION = 0.5


def derive_threshold_from_tiles(tile_histograms) -> Dict:
    """
    Threshold from sub-tiles that are demonstrably bimodal (split-based).

    Args:
        tile_histograms: Iterable of (counts, bin_centres) per tile.

    Returns:
        Dict with 'threshold_db', 'n_tiles_used', 'n_tiles_total',
        'separability', 'tile_thresholds'.

    Raises:
        ValueError: if no tile is bimodal enough to justify a threshold. That is
            a real answer — this scene cannot be thresholded reliably — and is
            far better than the confident 45%-water mask whole-scene Otsu
            produced over Tehri.
    """
    accepted = []
    total_tiles = 0

    for counts, centres in tile_histograms:
        total_tiles += 1
        counts = np.asarray(counts, dtype=np.float64)
        centres = np.asarray(centres, dtype=np.float64)
        if counts.size < 8 or counts.sum() < 100:
            continue
        try:
            threshold = otsu_threshold(counts, centres)
        except ValueError:
            continue

        eta = otsu_separability(counts, centres, threshold)
        dark_fraction = counts[centres <= threshold].sum() / counts.sum()
        if (eta >= MIN_TILE_SEPARABILITY
                and MIN_TILE_CLASS_FRACTION <= dark_fraction <= 1.0 - MIN_TILE_CLASS_FRACTION):
            accepted.append((threshold, eta))

    if not accepted:
        raise ValueError(
            f"No sub-tile of this scene is bimodal enough to derive a water "
            f"threshold from ({total_tiles} tiles examined, none reaching "
            f"separability {MIN_TILE_SEPARABILITY}). Over steep terrain the VV "
            f"histogram is dominated by one land mode plus radar shadow, and "
            f"any threshold taken from it would split the land distribution "
            f"rather than separate water. No mask is produced."
        )

    # Median of the accepted tile thresholds: robust to a single tile whose
    # bimodality comes from something other than water (a bright urban patch
    # against dark fields, say).
    thresholds = np.array([t for t, _ in accepted])
    etas = np.array([e for _, e in accepted])
    return {
        "threshold_db": float(np.median(thresholds)),
        "n_tiles_used": len(accepted),
        "n_tiles_total": total_tiles,
        "separability": float(np.median(etas)),
        "tile_thresholds": [round(float(t), 3) for t in thresholds],
    }


def _agreement_with_jrc(vv, water, region, scale_m: float) -> Dict:
    """
    Measure the derived mask against JRC Global Surface Water.

    JRC GSW (Pekel et al. 2016) maps surface water from 32 years of Landsat and
    is independent of the SAR scene, so it is a fair reference for "is this
    actually water". Permanent water is the part of it a same-day Sentinel-1
    mask should certainly contain.

    Precision is the number that matters here. Recall being high means the mask
    found the reservoir; precision being low means it also found a mountainside.
    Only precision distinguishes those, and over the Tehri gorge recall was 0.95
    while precision was 0.010.

    Returns:
        {'precision', 'recall', 'reference_fraction', 'mask_fraction'}.
        Precision is 0.0 when JRC shows no permanent water in the window, since
        nothing can be verified there.

    References:
      - Pekel, J-F. et al. (2016) "High-resolution mapping of global surface
        water and its long-term changes", Nature 540:418-422.
    """
    import ee

    occurrence = ee.Image(JRC_GSW).select("occurrence").unmask(0).clip(region)
    reference = occurrence.gt(JRC_PERMANENT_OCCURRENCE_PCT).rename("w")

    def fraction(image):
        value = image.rename("w").reduceRegion(
            reducer=ee.Reducer.mean(), geometry=region, scale=scale_m,
            maxPixels=1e9, bestEffort=True,
        ).getInfo()
        return float((value or {}).get("w") or 0.0)

    reference_fraction = fraction(reference)
    mask_fraction = fraction(water)
    intersection = fraction(water.And(reference))

    return {
        "precision": intersection / mask_fraction if mask_fraction > 0 else 0.0,
        "recall": intersection / reference_fraction if reference_fraction > 0 else 0.0,
        "reference_fraction": reference_fraction,
        "mask_fraction": mask_fraction,
    }


def _manifest_path(cache_dir: Path) -> Path:
    return Path(cache_dir) / "manifest.json"


def _read_cache(cache_dir: Path, reach: str) -> Optional[Dict]:
    """The cached observation for this reach, if its files are still present."""
    manifest = _manifest_path(cache_dir)
    if not manifest.exists():
        return None
    try:
        cached = json.loads(manifest.read_text(encoding="utf-8"))
    except Exception as exc:
        warnings.warn(f"Cached SAR manifest for {reach} is unreadable: {exc}")
        return None

    # A manifest naming files that are gone is not a usable cache. Recording
    # one anyway is the same failure as an exports row pointing at nothing.
    for key in ("geotiff_path", "png_path"):
        path = cached.get(key)
        if not path or not Path(path).exists():
            return None
    return cached


def _download(url: str, destination: Path) -> Path:
    import requests

    destination.parent.mkdir(parents=True, exist_ok=True)
    response = requests.get(url, timeout=180)
    response.raise_for_status()
    destination.write_bytes(response.content)
    return destination


def _fetch_live(reach: str, bbox: Tuple[float, float, float, float],
                cache_dir: Path, scale_m: float) -> Dict:
    """Query Earth Engine for the most recent scene and materialise the mask."""
    import ee

    region = ee.Geometry.BBox(*bbox)
    collection = (
        ee.ImageCollection(S1_COLLECTION)
        .filterBounds(region)
        .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VV"))
        .filter(ee.Filter.eq("instrumentMode", "IW"))
        .sort("system:time_start", False)
    )

    if collection.size().getInfo() == 0:
        raise SarUnavailableError(
            f"No Sentinel-1 IW/VV scene covers the {reach} reach "
            f"(bbox={bbox}). Nothing has been observed here."
        )

    scene = ee.Image(collection.first())
    properties = scene.getInfo()["properties"]
    acquired_ms = properties["system:time_start"]
    acquired_at = _dt.datetime.fromtimestamp(
        acquired_ms / 1000.0, tz=_dt.timezone.utc).isoformat()
    scene_id = scene.get("system:index").getInfo()

    vv = scene.select("VV").clip(region)

    # Split-based threshold: per-tile histograms, then Otsu only on the tiles
    # that are genuinely bimodal. See the module docstring for why the
    # whole-scene histogram cannot be used over terrain like this.
    min_lon, min_lat, max_lon, max_lat = bbox
    step_lon = (max_lon - min_lon) / TILE_GRID
    step_lat = (max_lat - min_lat) / TILE_GRID
    tiles = ee.FeatureCollection([
        ee.Feature(ee.Geometry.Rectangle([
            min_lon + i * step_lon, min_lat + j * step_lat,
            min_lon + (i + 1) * step_lon, min_lat + (j + 1) * step_lat,
        ]), {"tile": i * TILE_GRID + j})
        for i in range(TILE_GRID) for j in range(TILE_GRID)
    ])

    tile_stats = vv.reduceRegions(
        collection=tiles,
        reducer=ee.Reducer.histogram(maxBuckets=HISTOGRAM_BUCKETS),
        scale=scale_m,
    ).getInfo()

    tile_histograms = []
    for feature in (tile_stats or {}).get("features", []):
        hist = (feature.get("properties") or {}).get("histogram")
        if hist and hist.get("histogram") and hist.get("bucketMeans"):
            tile_histograms.append((hist["histogram"], hist["bucketMeans"]))

    if not tile_histograms:
        raise SarUnavailableError(
            f"Sentinel-1 scene {scene_id} returned no usable histogram over "
            f"the {reach} reach; cannot derive a water threshold."
        )

    try:
        derivation = derive_threshold_from_tiles(tile_histograms)
    except ValueError as exc:
        raise SarUnavailableError(
            f"Cannot threshold Sentinel-1 scene {scene_id} over {reach}: {exc}"
        ) from exc
    threshold_db = derivation["threshold_db"]

    water = vv.lt(threshold_db).rename("water").toByte().clip(region)

    fraction = water.reduceRegion(
        reducer=ee.Reducer.mean(), geometry=region, scale=scale_m,
        maxPixels=1e9, bestEffort=True,
    ).getInfo()
    water_fraction = float((fraction or {}).get("water") or 0.0)

    # Cheap server-side gate before spending a download on it; the authoritative
    # figure is recomputed from the delivered raster further down.
    if water_fraction > MAX_PLAUSIBLE_WATER_FRACTION:
        raise SarUnavailableError(
            f"Sentinel-1 scene {scene_id} over {reach} thresholded at "
            f"{threshold_db:.2f} dB classifies {water_fraction:.0%} of the "
            f"window as water. That is not a river reach; the threshold has "
            f"split the land distribution. No mask is produced."
        )

    # MEASURE the mask against an independent reference before publishing it.
    # This is the guard that matters, and it turns "looks plausible" into a
    # number. See MIN_JRC_PRECISION for the measurements that motivated it.
    agreement = _agreement_with_jrc(vv, water, region, scale_m)
    if agreement["precision"] < MIN_JRC_PRECISION:
        raise SarUnavailableError(
            f"Sentinel-1 scene {scene_id} over {reach} produced a mask that "
            f"disagrees with known permanent water: precision "
            f"{agreement['precision']:.3f} against JRC Global Surface Water "
            f"(recall {agreement['recall']:.3f}), below the required "
            f"{MIN_JRC_PRECISION}. {(1 - agreement['precision']):.0%} of the "
            f"detected water is not water — over steep terrain, radar shadow "
            f"in VV is indistinguishable from a flat surface by backscatter "
            f"alone. No mask is produced for this reach."
        )

    cache_dir = Path(cache_dir)
    geotiff = _download(
        water.getDownloadURL({
            "region": region, "scale": scale_m,
            "format": "GEO_TIFF", "crs": "EPSG:4326",
        }),
        cache_dir / "water_mask.tif",
    )
    png = _download(
        water.getThumbURL({
            "region": region, "dimensions": 768,
            "min": 0, "max": 1,
            # Transparent land, blue water: this overlays a basemap in Leaflet.
            "palette": ["00000000", "1565C0"],
            "format": "png",
        }),
        cache_dir / "water_mask.png",
    )

    # Report the fraction measured on the DELIVERED raster, not on a separate
    # server-side reduceRegion. Those disagreed (0.36 vs 0.18 over Hirakud)
    # because bestEffort=True silently downsamples when the pixel count is
    # large, so the published number described a different sampling of the
    # scene from the file the user downloads.
    try:
        import rasterio

        with rasterio.open(geotiff) as src:
            delivered = src.read(1)
        water_fraction = float(np.mean(delivered > 0))
    except Exception as exc:
        raise SarUnavailableError(
            f"The water mask for {reach} was downloaded but could not be read "
            f"back ({type(exc).__name__}: {exc}); refusing to publish a file "
            f"whose contents have not been verified."
        ) from exc

    return {
        "reach": reach,
        "source": "sentinel1_grd",
        "collection": S1_COLLECTION,
        "scene_id": scene_id,
        "acquired_at": acquired_at,
        "threshold_db": threshold_db,
        "threshold_method": "otsu_split_based",
        "validated_against": JRC_GSW,
        "precision_vs_jrc": agreement["precision"],
        "recall_vs_jrc": agreement["recall"],
        "jrc_water_fraction": agreement["reference_fraction"],
        "threshold_separability": derivation["separability"],
        "threshold_tiles_used": derivation["n_tiles_used"],
        "threshold_tiles_total": derivation["n_tiles_total"],
        "water_fraction": water_fraction,
        "bbox": list(bbox),
        "scale_m": scale_m,
        "orbit_pass": properties.get("orbitProperties_pass"),
        "geotiff_path": str(geotiff),
        "png_path": str(png),
        "fetched_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "note": (
            "Observed water extent from Sentinel-1 VV backscatter. This is "
            "water, not necessarily flood water: permanent reservoir and "
            "channel are included."
        ),
    }


def latest_observed_extent(
    reach: str,
    bbox: Tuple[float, float, float, float],
    cache_dir,
    scale_m: float = DEFAULT_SCALE_M,
) -> Dict:
    """
    Most recent observed water extent over a reach, from Sentinel-1.

    Args:
        reach: Reach name, used for the cache directory and for messages.
        bbox: (min_lon, min_lat, max_lon, max_lat) in WGS84 degrees. Supplied by
            the caller rather than resolved here — `jalraksha.gee` must not
            import the service layer, which is where the dam registry lives.
        cache_dir: Directory for this reach's cached mask and manifest.
        scale_m: Output posting in metres.

    Returns:
        Dict with source ("sentinel1_grd" or "cached"), scene_id, acquired_at,
        threshold_db, water_fraction, and paths to the GeoTIFF and PNG.

    Raises:
        SarUnavailableError: when neither a live query nor a cache can serve the
            request. The message says which failed and why.
    """
    cache_dir = Path(cache_dir)
    available, reason = gee_status()

    remembered = _REFUSALS.get(reach)
    if remembered and (time.monotonic() - remembered[0]) < REFUSAL_CACHE_SECONDS:
        raise SarUnavailableError(remembered[1])

    if available:
        try:
            observation = _fetch_live(reach, bbox, cache_dir, scale_m)
            _manifest_path(cache_dir).write_text(
                json.dumps(observation, indent=2), encoding="utf-8")
            _REFUSALS.pop(reach, None)
            return observation
        except SarUnavailableError as exc:
            _REFUSALS[reach] = (time.monotonic(), str(exc))
            raise
        except Exception as exc:
            live_failure = f"{type(exc).__name__}: {exc}"
            print(f"[gee] Live Sentinel-1 query for {reach} failed - {live_failure}")
    else:
        live_failure = reason
        print(f"[gee] Earth Engine unavailable for {reach} - {reason}")

    # Offline-first (CLAUDE.md): a previously fetched scene is a real
    # observation and stays usable when the network is not. It is labelled as
    # cached, and keeps its own acquisition date rather than borrowing today's.
    cached = _read_cache(cache_dir, reach)
    if cached is not None:
        cached = dict(cached)
        cached["source"] = "cached"
        cached["reason"] = (
            f"Served from cache because the live query was not possible: "
            f"{live_failure}"
        )
        print(f"[gee] Serving cached {reach} scene from "
              f"{cached.get('acquired_at')}")
        return cached

    raise SarUnavailableError(
        f"No observed SAR extent available for {reach}: the live Earth Engine "
        f"query could not run ({live_failure}), and nothing is cached under "
        f"{cache_dir}. No synthetic substitute is produced."
    )


#: How long a refusal is remembered, so a reach that cannot be thresholded does
#: not re-run the full Earth Engine query on every page load. A refusal follows
#: from the scene and the terrain, not from the moment, so re-deriving it per
#: view costs ~20 s and tells nobody anything new. Short enough that a new
#: acquisition is picked up the same day.
REFUSAL_CACHE_SECONDS = 3600.0
_REFUSALS: Dict[str, tuple] = {}


def process_sentinel1_sar_flood(
    bbox: Tuple[float, float, float, float],
    date_pre: str = "2021-01-15",
    date_post: str = "2021-02-08",
    threshold_db: float = -3.0,
    grid_shape: Tuple[int, int] = (50, 50),
    allow_synthetic: bool = False,
) -> Dict[str, np.ndarray]:
    """
    Pre/post change-detection flood mask (Clement et al. 2018).

    Compares backscatter before and after an event and flags cells whose VV
    dropped by more than `threshold_db`, which separates NEW water from
    permanent water in a way `latest_observed_extent` deliberately does not.

    Args:
        bbox: (min_lon, min_lat, max_lon, max_lat) in WGS84 degrees.
        date_pre: Start of the pre-event window (YYYY-MM-DD).
        date_post: Start of the post-event window (YYYY-MM-DD).
        threshold_db: Backscatter drop counted as new water. TODO: UNVETTED -
            -3.0 dB is the value this module was written with and has no primary
            citation attached; Clement et al. (2018) is the method reference,
            not a source for this figure. Spec section 17 verification queue.
        grid_shape: Output array shape (ny, nx).
        allow_synthetic: Generate a SYNTHETIC mask instead of querying Earth
            Engine. For tests only. The returned `source` says so, and no
            caller in the application sets this.

    Returns:
        Dict with 'water_mask', 'backscatter_delta_db', 'source', 'threshold_db'.

    Raises:
        SarUnavailableError: if Earth Engine is unavailable and allow_synthetic
            is False. The previous version swallowed that case and returned the
            synthetic mask regardless, labelled only in a field nobody read.
    """
    ny, nx = grid_shape

    if allow_synthetic:
        return _synthetic_change_mask(ny, nx, threshold_db)

    available, reason = gee_status()
    if not available:
        raise SarUnavailableError(
            f"Cannot compute a Sentinel-1 change-detection mask: {reason}. "
            f"Pass allow_synthetic=True only in tests - this function will not "
            f"return fabricated backscatter as though it were observed."
        )

    import ee

    region = ee.Geometry.BBox(*bbox)
    collection = (
        ee.ImageCollection(S1_COLLECTION)
        .filterBounds(region)
        .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VV"))
        .filter(ee.Filter.eq("instrumentMode", "IW"))
        .select("VV")
    )
    pre = collection.filterDate(date_pre, date_post).median()
    post = collection.filterDate(
        date_post,
        (_dt.date.fromisoformat(date_post) + _dt.timedelta(days=30)).isoformat(),
    ).median()

    delta = post.subtract(pre).rename("delta").clip(region)
    sampled = delta.sampleRectangle(region=region, defaultValue=0)
    delta_db = np.asarray(sampled.get("delta").getInfo(), dtype=np.float32)

    return {
        "water_mask": delta_db <= threshold_db,
        "backscatter_delta_db": delta_db,
        "source": "GEE_Sentinel1_change_detection",
        "threshold_db": threshold_db,
        "date_pre": date_pre,
        "date_post": date_post,
    }


def _synthetic_change_mask(ny: int, nx: int, threshold_db: float) -> Dict:
    """
    A fabricated backscatter field, for exercising array plumbing in tests.

    Deliberately reachable only through `allow_synthetic=True`. It was
    previously the silent fallback of the function above, which meant a failed
    Earth Engine query produced this and labelled it merely "Offline_Synthetic"
    in a field the API never surfaced.
    """
    y, x = np.ogrid[:ny, :nx]
    distance = np.sqrt((x - nx // 2) ** 2 + (y - ny // 2) ** 2)

    delta_db = np.zeros((ny, nx), dtype=np.float32)
    channel = distance <= (min(ny, nx) // 4)
    delta_db[channel] = np.random.uniform(-8.0, -4.0, size=int(channel.sum()))
    delta_db[~channel] = np.random.uniform(-1.0, 1.0, size=int((~channel).sum()))

    return {
        "water_mask": delta_db <= threshold_db,
        "backscatter_delta_db": delta_db,
        "source": "SYNTHETIC_not_observed",
        "threshold_db": threshold_db,
    }
