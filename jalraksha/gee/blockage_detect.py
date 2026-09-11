"""
Detect a newly formed landslide-dammed lake from Sentinel-1 — Phase 9/10.

Answers one question: has a NEW water body appeared on this reach since the
event, and if so where is its outlet. That is the archived specification's
section 12.5 — "detect a new water body by differencing current surface water
against JRC GSW permanent water, filtering by size and by proximity to the
drainage network" — and it is the front half of the HADR workflow: detect,
screen, and if needed simulate.

THREE STATES, NO FOURTH. Live (``sentinel1_change_detection``), cached
(``cached``), or ``SarUnavailableError``. Nothing here synthesizes a lake. The
same contract ``sar.latest_observed_extent`` holds, for the same reason: a
labelled synthetic flood layer survives a screenshot badly.

WHY THE EXISTING PRECISION GATE IS NOT REUSED ON THE DIFFERENCE

``sar.MIN_JRC_PRECISION`` requires a derived water mask to agree with JRC
permanent water. Applied to a NEW-water mask that gate would reject exactly the
true positives, because a lake that formed last week is definitionally not in a
32-year permanent-water product. Precision against permanent water is near zero
BY CONSTRUCTION for a correct detection.

So the gate is transplanted rather than reused: it is applied to the PRE-event
scene's total-water mask, which should be the known river and should agree with
JRC. If the pre scene cannot find the river that is already there, the
difference between the two scenes means nothing. Three further gates then act on
the difference itself: JRC permanent water is subtracted outright, candidates must
sit within ``DRAINAGE_PROXIMITY_M`` of a watercourse, and the ground beneath them
must be flat (``score_candidate_flatness``).

WHAT IS NOT BUILT HERE. This returns a MASK, not a list of individually scored
candidate lakes. Vectorising the mask and reporting each patch separately is not
done, and there is deliberately no half-populated candidate list in the response
pretending otherwise.

The two gates that were declared and never executed now run. The size floor is
applied PER CONNECTED COMPONENT rather than to the window total — measured over
Baige, a garbage mask cleared a window-total floor by 900x precisely because its
mis-classified pixels were scattered everywhere, whereas a lake is one patch.
The flatness gate reads Copernicus GLO-30 from inside the Earth Engine call,
which is not a layering violation: an EE asset is another EE image, not a call
into ``jalraksha.terrain``. ``score_candidate_flatness`` remains the offline
twin, and both decide through the same ``flatness_verdict``.

Do NOT widen MIN_JRC_PRECISION to make a steep reach pass. That threshold
records a measured limitation (precision 0.010 over the Tehri gorge, 0.77 over
Hirakud); the fix for a different question is a different gate, not a looser one.

WHAT THIS MEASURES OVER THE RISHI GANGA, AND WHY THAT IS A RESULT

Run live against the Raini window on 2 September 2026, this refuses, and the
refusal is worth reading rather than working around. JRC's permanent-water band
covers 0.001% of that window — about one cell at 60 m — against 0.57% at Tehri
and 44.5% at Hirakud. A 30 m Landsat-derived product does not resolve a narrow
braided Himalayan headwater, so there is nothing to verify a same-day radar mask
against. An unverifiable mask is not a verified mask.

That is a documented limit of open-data change detection over exactly the
terrain the problem statement cares about, and it is a more useful thing to
report than a confident mask nobody checked. The manual barrier path runs fully
offline, needs no scene, and is where the demo goes from here.

THE FLATNESS GATE IS THE STRONGEST FILTER AND IT IS FREE. A lake surface is
flat; a radar-shadow patch on a hillside is not. The stale DEM is already in
hand, so the candidate is scored on the elevation spread and slope of the ground
beneath it. Measured with the earlier gates bypassed, it refuses every case
tested by 186x on elevation spread (933-3,258 m against a 5 m limit) and 16x on
mean slope (31-36 degrees against 2).

GEOMETRICALLY UNUSABLE PIXELS ARE EXCLUDED FIRST, AND THAT IS NOT THE FIX.
``terrain_correction.earth_engine_validity_mask`` computes the local incidence
angle from Copernicus GLO-30 and the scene geometry and drops shadow and layover
before any histogram is derived (Small 2011, geometric half only — this masks
pixels, it does not radiometrically flatten them).

Measured, it does not rescue this detector: over Baige it excludes 16.6% of the
window and moves Gate 1 precision from 0.0075 to 0.007 against a 0.5
requirement. Radar shadow turns out to be 0.09% of that window, so the darkness
being mis-read as water is on slopes that image perfectly well — a radiometric
problem, not a geometric one. Keep the masking (layover is meaningless wherever
it occurs, and any radiometric correction needs this geometry underneath it),
but do not describe it as making auto-detection work. docs/validation_findings.md
§9 carries the table.

WHY THIS DOES NOT BUILD ON process_sentinel1_sar_flood

That function's post-event image is a 30-DAY MEDIAN, so "rebuilt from the
2021-02-08 scene" would not be a true sentence about it; it calls
sampleRectangle with no scale, sampling S1 GRD at its native 10 m over a 0.2
degree window; and its grid_shape argument is ignored on the live path. The
detector here takes a SINGLE post scene and carries its own id and acquisition
time, because that is what makes the DEM provenance honest.
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
from jalraksha.gee.sar import (
    JRC_GSW,
    JRC_PERMANENT_OCCURRENCE_PCT,
    MAX_PLAUSIBLE_WATER_FRACTION,
    MIN_JRC_PRECISION,
    S1_COLLECTION,
    SarUnavailableError,
    TILE_GRID,
    _agreement_with_jrc,
    _download,
    derive_threshold_from_tiles,
)
from jalraksha.gee.terrain_correction import (
    GLO30_COLLECTION,
    describe_refusal as describe_geometry_refusal,
    earth_engine_validity_mask,
    geometry_provenance,
)

#: Output posting, metres. Coarser than S1's native 10 m on purpose: a
#: landslide-dammed lake is hundreds of metres across, and 60 m keeps an Earth
#: Engine request over a 0.2-degree window inside its limits.
DEFAULT_SCALE_M = 60.0

#: Longest post-event window that still yields a SINGLE scene rather than a
#: composite. Sentinel-1's repeat cycle is 6 days (12 for a single satellite),
#: so anything longer risks two acquisitions and a provenance claim that names
#: only one of them.
MAX_POST_WINDOW_DAYS = 6

#: Smallest new water body reported, square metres.
#:
#: TODO: UNVETTED — 20,000 m2 is about six 60 m pixels, chosen so a handful of
#: mis-thresholded cells cannot become a "lake". For scale, the published
#: inundation extent of the 7 February 2021 Chamoli flow is 0.66 km2
#: (literature.md 11.2) — 33 times this floor — so the floor is not close to
#: excluding an event of that class. It is a working value, not a published one.
#: docs/VERIFICATION_LOG.md row 25.
MIN_NEW_WATER_AREA_M2 = 20_000.0

#: How close to a known watercourse a candidate must sit, metres.
#:
#: A new lake forms ON a river. Radar shadow generally does not. JRC's
#: occurrence > 10% band ("water seen at least sometimes") is used as the
#: drainage network, which avoids needing flow accumulation or any dataset the
#: project's licensing rules forbid.
#:
#: TODO: UNVETTED — 500 m is roughly two valley widths in a Himalayan gorge at
#: this posting. Not taken from a publication. docs/VERIFICATION_LOG.md row 25.
DRAINAGE_PROXIMITY_M = 500.0

#: Least JRC permanent water a window must contain for the pre-scene precision
#: check to mean anything. Below this there is nothing to verify against and a
#: precision of 0 is arithmetic rather than evidence of a bad mask.
#:
#: MEASURED, JRC occurrence > 80% as a fraction of a 0.2-degree window:
#:
#:     Rishi Ganga (Raini)   0.001%   ~1 cell at 60 m — no usable reference
#:     Tehri (Bhagirathi)    0.572%   the reservoir
#:     Hirakud (Mahanadi)   44.520%   a large flat reservoir
#:
#: JRC is derived from 30 m Landsat and its permanent-water band simply does not
#: resolve a narrow braided Himalayan headwater. 0.1% of the window is about 135
#: cells at 60 m — enough to compare against, and two orders of magnitude above
#: the Rishi Ganga measurement.
#:
#: TODO: UNVETTED — a working threshold separating the three measured cases, not
#: one taken from a publication. docs/VERIFICATION_LOG.md row 25.
MIN_JRC_REFERENCE_FRACTION = 0.001

#: Fraction of a candidate that must lie within DRAINAGE_PROXIMITY_M of a
#: watercourse.
MIN_FRACTION_NEAR_DRAINAGE = 0.8

#: Flatness gates on the ground beneath a candidate, from the stale DEM.
#: A lake surface is flat; a hillside in radar shadow is not.
#:
#: TODO: UNVETTED — 5 m of elevation spread and 2 degrees of mean slope are
#: chosen against GLO-30's own ~4 m vertical accuracy over rough terrain, so a
#: genuinely flat pool should clear them and a valley wall should not. Not
#: published values. docs/VERIFICATION_LOG.md row 25.
MAX_LAKE_ELEVATION_SPREAD_M = 5.0
MAX_LAKE_MEAN_SLOPE_DEG = 2.0

#: Amplitude-change form of the new-water test, decibels. Reported alongside the
#: threshold form as a cheap robustness check: two independent constructions
#: that disagree wildly mean the scene pair should not be trusted.
#:
#: TODO: UNVETTED — the -3.0 dB in sar.process_sentinel1_sar_flood carries the
#: same flag. docs/VERIFICATION_LOG.md row 24.
CHANGE_THRESHOLD_DB = -3.0

#: How long a refusal is remembered. A refusal follows from the scene pair and
#: the terrain, not from the moment, so re-deriving it per page load costs ~30 s
#: of Earth Engine time and tells nobody anything new.
REFUSAL_CACHE_SECONDS = 3600.0
_REFUSALS: Dict[str, tuple] = {}


def _manifest_path(cache_dir: Path) -> Path:
    return Path(cache_dir) / "blockage_manifest.json"


def _read_cache(cache_dir: Path) -> Optional[Dict]:
    """The cached detection, if the files it names are still on disk."""
    manifest = _manifest_path(Path(cache_dir))
    if not manifest.exists():
        return None
    try:
        cached = json.loads(manifest.read_text(encoding="utf-8"))
    except Exception as exc:
        warnings.warn(f"Cached blockage manifest is unreadable: {exc}")
        return None
    for key in ("mask_geotiff_path", "mask_png_path"):
        path = cached.get(key)
        if path and not Path(path).exists():
            return None
    return cached


def _scene_threshold(image, region, bbox, scale_m: float, label: str) -> Dict:
    """
    Split-based Otsu threshold for one image.

    Derived PER SCENE, not once for the pair. The pre and post acquisitions can
    differ in orbit, incidence angle and soil moisture, and a threshold that
    separates water in one may cut through land in the other. A single fixed
    -3.0 dB is not defensible over Himalayan terrain — that is the measurement
    behind sar.py's whole split-based apparatus.
    """
    import ee

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

    stats = image.reduceRegions(
        collection=tiles,
        reducer=ee.Reducer.histogram(maxBuckets=256),
        scale=scale_m,
    ).getInfo()

    histograms = []
    for feature in (stats or {}).get("features", []):
        hist = (feature.get("properties") or {}).get("histogram")
        if hist and hist.get("histogram") and hist.get("bucketMeans"):
            histograms.append((hist["histogram"], hist["bucketMeans"]))

    if not histograms:
        raise SarUnavailableError(
            f"The {label} Sentinel-1 image returned no usable histogram over "
            f"this reach; no threshold can be derived."
        )
    try:
        return derive_threshold_from_tiles(histograms)
    except ValueError as exc:
        raise SarUnavailableError(
            f"Cannot threshold the {label} Sentinel-1 image over this reach: "
            f"{exc}"
        ) from exc


#: Largest component Earth Engine will count, in pixels. This is EE's own cap
#: on connectedPixelCount, not a choice: a component larger than this saturates
#: at the cap. Saturation can only UNDER-state a component's size, so it can
#: only make the area floor stricter, never looser — a lake big enough to
#: saturate is far past a 20,000 m2 floor either way.
MAX_COMPONENT_PIXELS = 1024


def flatness_verdict(elevation_spread_m: float, mean_slope_deg: float) -> bool:
    """
    The flatness gate itself, in one place.

    Both halves of this gate — the offline ``score_candidate_flatness`` and the
    Earth Engine reduction inside ``_fetch_live`` — call this, so the thresholds
    cannot drift apart between the path that is tested and the path that runs.
    """
    if not (np.isfinite(elevation_spread_m) and np.isfinite(mean_slope_deg)):
        return False
    return bool(
        elevation_spread_m <= MAX_LAKE_ELEVATION_SPREAD_M
        and mean_slope_deg <= MAX_LAKE_MEAN_SLOPE_DEG
    )


def score_candidate_flatness(
    bed_elevation: np.ndarray, candidate_mask: np.ndarray, cell_m: float
) -> Dict[str, float]:
    """
    How flat the ground beneath a candidate is, from the pre-event DEM.

    Pure numpy, no Earth Engine — so this gate is testable, and runs offline
    against a cached mask.

    Returns elevation spread, mean slope in degrees, and whether both clear
    their thresholds. A lake surface is flat; a radar-shadow patch on a valley
    wall is not, and no amount of backscatter analysis distinguishes the two.

    This is the offline twin of the gate ``_fetch_live`` applies server-side
    over Copernicus GLO-30. Both decide through ``flatness_verdict``.
    """
    mask = np.asarray(candidate_mask, dtype=bool)
    bed = np.asarray(bed_elevation, dtype=np.float64)
    if not mask.any():
        return {
            "elevation_spread_m": float("inf"),
            "mean_slope_deg": float("inf"),
            "mean_elevation_m": float("nan"),
            "passes_flatness": False,
        }

    samples = bed[mask]
    # 5th-to-95th rather than min-to-max: one mis-classified cliff cell inside a
    # genuinely flat lake should not condemn it.
    spread = float(np.percentile(samples, 95) - np.percentile(samples, 5))

    gradient_y, gradient_x = np.gradient(bed, cell_m)
    slope_deg = np.degrees(np.arctan(np.hypot(gradient_x, gradient_y)))
    mean_slope = float(slope_deg[mask].mean())

    return {
        "elevation_spread_m": spread,
        "mean_slope_deg": mean_slope,
        "mean_elevation_m": float(samples.mean()),
        "passes_flatness": flatness_verdict(spread, mean_slope),
    }


def _fetch_live(
    reach: str,
    bbox: Tuple[float, float, float, float],
    cache_dir: Path,
    date_pre_start: str,
    date_pre_end: str,
    date_post: str,
    scale_m: float,
) -> Dict:
    """Query Earth Engine for a pre/post scene pair and derive the new water."""
    import ee

    region = ee.Geometry.BBox(*bbox)
    base = (
        ee.ImageCollection(S1_COLLECTION)
        .filterBounds(region)
        .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VV"))
        .filter(ee.Filter.eq("instrumentMode", "IW"))
    )

    # POST IS RESOLVED FIRST, because its orbit decides which pre-event scenes
    # may be differenced against it. A SINGLE scene inside one repeat cycle, so
    # the provenance can name the acquisition it is built from — a median here
    # would make "rebuilt from the 2021-02-08 scene" false.
    post_start = _dt.date.fromisoformat(date_post)
    post_end = post_start + _dt.timedelta(days=MAX_POST_WINDOW_DAYS)
    post_collection = (
        base.filterDate(post_start.isoformat(), post_end.isoformat())
        .sort("system:time_start", True)
    )
    if post_collection.size().getInfo() == 0:
        raise SarUnavailableError(
            f"No Sentinel-1 IW/VV scene covers {reach} in the "
            f"{MAX_POST_WINDOW_DAYS} days from {date_post}. Nothing has been "
            f"observed since the event on this reach."
        )
    post_scene = ee.Image(post_collection.first())
    post_properties = post_scene.getInfo()["properties"]
    post_scene_id = post_scene.get("system:index").getInfo()
    post_acquired_at = _dt.datetime.fromtimestamp(
        post_properties["system:time_start"] / 1000.0, tz=_dt.timezone.utc
    ).isoformat()
    post_pass = post_properties.get("orbitProperties_pass")
    post_orbit = post_properties.get("relativeOrbitNumber_start")

    # PRE: a median over a stable window, restricted to the POST scene's own
    # track. Averaging is right here — the pre-event state is not changing and a
    # median suppresses speckle — but averaging across ORBITS is not: an
    # ascending and a descending pass illuminate opposite walls of a valley, so
    # differencing them puts a shadow-to-lit transition in the "new water" band
    # on every slope in the scene. The geometry mask derived below belongs to
    # ONE imaging geometry and is only valid for both images if both share it.
    pre_collection = base.filterDate(date_pre_start, date_pre_end)
    if post_pass is not None:
        pre_collection = pre_collection.filter(
            ee.Filter.eq("orbitProperties_pass", post_pass)
        )
    if post_orbit is not None:
        pre_collection = pre_collection.filter(
            ee.Filter.eq("relativeOrbitNumber_start", post_orbit)
        )
    n_pre_scenes = pre_collection.size().getInfo()
    if n_pre_scenes == 0:
        raise SarUnavailableError(
            f"No Sentinel-1 IW/VV scene covers {reach} between "
            f"{date_pre_start} and {date_pre_end} on the same track as the "
            f"post-event acquisition (pass {post_pass}, relative orbit "
            f"{post_orbit}). There is no pre-event state that can be "
            f"differenced against it: a scene from a different track "
            f"illuminates the opposite valley wall, so the difference would be "
            f"a change in geometry rather than a change in water. Widen the "
            f"pre-event window, or place the barrier manually."
        )
    pre = pre_collection.median().select("VV").clip(region)
    post = post_scene.select("VV").clip(region)

    # GATE 0: RADAR GEOMETRY, before any histogram is derived.
    #
    # This is the fix for verification-queue row 29. A slope facing away from
    # the sensor is dark for a geometric reason, and thresholding cannot tell
    # that darkness from water: measured at 63% of the Baige gorge classified as
    # water at precision 0.0075, and 46-68% across six event/window cases. The
    # local incidence angle identifies those pixels from the DEM and the imaging
    # geometry, so they are excluded rather than thresholded.
    geometry = earth_engine_validity_mask(post_scene, region, scale_m)
    if not geometry["passes_geometry"]:
        raise SarUnavailableError(describe_geometry_refusal(geometry, reach))

    valid_geometry = geometry["valid"]
    pre = pre.updateMask(valid_geometry)
    post = post.updateMask(valid_geometry)

    pre_derivation = _scene_threshold(pre, region, bbox, scale_m, "pre-event")
    post_derivation = _scene_threshold(post, region, bbox, scale_m, "post-event")

    # updateMask again after toByte(): a masked image byte-casts to 0 outside
    # the mask, and an unmasked 0 reads as "observed dry" over ground that was
    # never observed at all.
    pre_water = (
        pre.lt(pre_derivation["threshold_db"])
        .updateMask(valid_geometry).rename("water").toByte()
    )
    post_water = (
        post.lt(post_derivation["threshold_db"])
        .updateMask(valid_geometry).rename("water").toByte()
    )

    def _fraction(image, band: str = "w") -> float:
        value = image.rename(band).reduceRegion(
            reducer=ee.Reducer.mean(), geometry=region, scale=scale_m,
            maxPixels=1e9, bestEffort=True,
        ).getInfo()
        return float((value or {}).get(band) or 0.0)

    # GATE 0b: the loose sanity bound sar.py already applies to its own masks
    # and this module previously never did (verification-queue row 29). It is
    # not the real guard — a window centred on a large reservoir can legitimately
    # be mostly water — but a pre-event mask past it has had its threshold cut
    # through the land distribution, and nothing downstream would catch that.
    pre_water_fraction = _fraction(pre_water)
    if pre_water_fraction > MAX_PLAUSIBLE_WATER_FRACTION:
        raise SarUnavailableError(
            f"The pre-event Sentinel-1 mask for {reach}, thresholded at "
            f"{pre_derivation['threshold_db']:.2f} dB, classifies "
            f"{pre_water_fraction:.0%} of the geometrically valid window as "
            f"water, above the {MAX_PLAUSIBLE_WATER_FRACTION:.0%} bound. The "
            f"threshold has split the land distribution rather than separating "
            f"water from it, so a difference against it is meaningless. No "
            f"detection is produced."
        )

    # GATE 1: the transplanted precision gate, on the PRE scene's total water.
    # If the pre-event mask cannot find the river that is already there, the
    # difference between the two scenes is not evidence of anything.
    pre_agreement = _agreement_with_jrc(pre, pre_water, region, scale_m)
    if pre_agreement["precision"] < MIN_JRC_PRECISION:
        # TWO DIFFERENT FAILURES LOOK THE SAME IN THE PRECISION NUMBER, and
        # collapsing them into one message would misdiagnose the commoner one.
        #
        #   no usable reference — JRC shows essentially no permanent water in
        #     this window, so there is nothing to verify against and precision is
        #     0 by arithmetic rather than by error. Measured over the Rishi
        #     Ganga: 0.001% of the window, about one cell at 60 m. JRC's
        #     80%-occurrence band comes from 30 m Landsat and does not resolve a
        #     narrow braided Himalayan headwater at all. The gate is right to
        #     refuse — an unverifiable mask is not a verified one — but the
        #     reason is an absent reference, not radar shadow.
        #
        #   a real reference the mask missed — over steep terrain that means VV
        #     backscatter is picking up radar shadow on hillsides, which is the
        #     case MIN_JRC_PRECISION was originally measured against.
        if pre_agreement["reference_fraction"] < MIN_JRC_REFERENCE_FRACTION:
            detail = (
                f"JRC Global Surface Water shows permanent water over only "
                f"{pre_agreement['reference_fraction']:.4%} of this window, so "
                f"the mask cannot be verified against anything. That is expected "
                f"for a narrow braided Himalayan headwater: JRC comes from 30 m "
                f"Landsat and its permanent-water band does not resolve one "
                f"(measured 0.001% here against 0.57% at Tehri and 44.5% at "
                f"Hirakud). An unverifiable mask is not a verified mask, so no "
                f"detection is published."
            )
        else:
            detail = (
                f"JRC shows permanent water over "
                f"{pre_agreement['reference_fraction']:.1%} of this window and "
                f"the mask largely missed it. Over steep terrain radar shadow in "
                f"VV is indistinguishable from a flat surface by backscatter "
                f"alone."
            )
        raise SarUnavailableError(
            f"The pre-event Sentinel-1 mask for {reach} reaches precision "
            f"{pre_agreement['precision']:.3f} against JRC Global Surface Water "
            f"(recall {pre_agreement['recall']:.2f}), below the required "
            f"{MIN_JRC_PRECISION}. It cannot reliably find the river that was "
            f"already there, so a difference against it would not be evidence "
            f"of a new lake. {detail} Place the barrier manually — that path "
            f"runs fully offline and needs no scene."
        )

    # New water: dark now, not dark before.
    new_water = post_water.And(pre_water.Not()).rename("new_water").toByte()

    # GATE 2: minus JRC permanent water. A candidate must be genuinely new, not
    # the known reservoir re-detected.
    permanent = (
        ee.Image(JRC_GSW).select("occurrence").unmask(0).clip(region)
        .gt(JRC_PERMANENT_OCCURRENCE_PCT)
    )
    candidate = new_water.And(permanent.Not()).rename("candidate").toByte()

    # GATE 3: proximity to the drainage network. "Water seen at least
    # sometimes" stands in for the watercourse; a new lake forms on a river.
    drainage = (
        ee.Image(JRC_GSW).select("occurrence").unmask(0).clip(region).gt(10)
    )
    near_drainage = (
        drainage.fastDistanceTransform().sqrt()
        .multiply(ee.Image.pixelArea().sqrt())
        .lte(DRAINAGE_PROXIMITY_M)
    )
    candidate_near = candidate.And(near_drainage).rename("candidate").toByte()

    # The amplitude-change form, computed as an independent construction of the
    # same quantity. Reported, not enforced: agreement is reassurance, and
    # disagreement is a reason for a human to look.
    amplitude_new = (
        post.subtract(pre).lte(CHANGE_THRESHOLD_DB).And(permanent.Not()).toByte()
    )

    candidate_fraction = _fraction(candidate)
    candidate_near_fraction = _fraction(candidate_near)
    fraction_near_drainage = (
        candidate_near_fraction / candidate_fraction if candidate_fraction > 0 else 0.0
    )

    if candidate_fraction <= 0.0:
        raise SarUnavailableError(
            f"No new water was detected on {reach} between {date_pre_start} and "
            f"{post_acquired_at}. The scenes are usable and the pre-event mask "
            f"passed its agreement check; there is simply no new water body. "
            f"That is a result, not a failure."
        )

    if fraction_near_drainage < MIN_FRACTION_NEAR_DRAINAGE:
        raise SarUnavailableError(
            f"Only {fraction_near_drainage:.0%} of the new-water candidates on "
            f"{reach} lie within {DRAINAGE_PROXIMITY_M:.0f} m of a watercourse, "
            f"below the required {MIN_FRACTION_NEAR_DRAINAGE:.0%}. A landslide "
            f"lake forms on a river; a scatter of dark pixels across hillsides "
            f"is radar shadow. No detection is produced."
        )

    # GATE 4: A MINIMUM SIZE PER CANDIDATE, NOT PER WINDOW.
    #
    # MIN_NEW_WATER_AREA_M2 has existed since this module was written and was
    # never referenced (verification-queue row 28). Applying it to the window
    # total would have been worse than useless: over Baige a garbage mask
    # exceeded it by 900x precisely because the mis-classified pixels were
    # scattered everywhere. The floor is only meaningful per CONNECTED
    # component, which is what the constant's own docstring describes — a lake
    # is one patch, radar speckle is a thousand small ones.
    candidate_pixels = (
        candidate_near.selfMask().reproject(crs="EPSG:4326", scale=scale_m)
    )
    component_pixels = candidate_pixels.connectedPixelCount(
        maxSize=MAX_COMPONENT_PIXELS, eightConnected=True
    )
    cell_area = ee.Image.pixelArea().reproject(crs="EPSG:4326", scale=scale_m)
    component_area = component_pixels.multiply(cell_area).rename("area")

    largest_component_m2 = float(
        (component_area.reduceRegion(
            reducer=ee.Reducer.max(), geometry=region, scale=scale_m,
            maxPixels=1e9, bestEffort=True,
        ).getInfo() or {}).get("area") or 0.0
    )

    lake = candidate_near.updateMask(
        component_area.gte(MIN_NEW_WATER_AREA_M2)
    ).rename("candidate").toByte()

    if largest_component_m2 < MIN_NEW_WATER_AREA_M2:
        raise SarUnavailableError(
            f"The largest connected new-water patch on {reach} covers "
            f"{largest_component_m2:,.0f} m2, below the "
            f"{MIN_NEW_WATER_AREA_M2:,.0f} m2 floor for a reportable lake "
            f"(about six cells at {scale_m:.0f} m). Scattered pixels that do "
            f"not join up are speckle and residual thresholding error, not an "
            f"impoundment. For scale, the published extent of the 7 February "
            f"2021 Chamoli flow is 0.66 km2. No detection is produced."
        )

    # GATE 5: FLATNESS OF THE GROUND BENEATH THE CANDIDATE.
    #
    # Also declared and never invoked until now (row 28), despite the module
    # docstring calling it "the strongest filter and it is free". Measured with
    # the earlier gates bypassed, it would have refused every case tested by
    # 186x on elevation spread (933-3,258 m against 5 m) and 16x on mean slope
    # (31-36 degrees against 2). A lake surface is flat; a hillside is not.
    #
    # The DEM comes from Copernicus GLO-30 INSIDE the Earth Engine call, which
    # is why this can now run at all: importing an EE asset is not a call into
    # jalraksha.terrain, so the package's layering boundary is intact. The
    # verdict itself is flatness_verdict(), shared with the offline half.
    # setDefaultProjection for the same reason terrain_correction.py needs it:
    # a bare mosaic() is EPSG:4326 at ONE DEGREE per pixel, and Terrain computes
    # slope in the input's projection, so the slope half of this gate would read
    # 0.000 degrees everywhere and pass any candidate on any hillside. Declaring
    # GLO-30's native 30 m posting is what makes the measurement real.
    flat_dem = (
        ee.ImageCollection(GLO30_COLLECTION).select("DEM").mosaic()
        .setDefaultProjection(crs="EPSG:4326", scale=30)
    )
    flat_terrain = ee.Algorithms.Terrain(flat_dem)
    flatness_stats = (
        ee.Image.cat([
            flat_dem.rename("elevation"),
            flat_terrain.select("slope").rename("slope"),
        ])
        .updateMask(lake)
        .reduceRegion(
            # 5th-to-95th rather than min-to-max, matching the offline half: one
            # mis-classified cliff cell inside a genuinely flat lake should not
            # condemn it.
            reducer=ee.Reducer.percentile([5, 95]).combine(
                ee.Reducer.mean(), sharedInputs=True
            ),
            geometry=region, scale=scale_m, maxPixels=1e9, bestEffort=True,
        )
        .getInfo()
    ) or {}

    elevation_p5 = flatness_stats.get("elevation_p5")
    elevation_p95 = flatness_stats.get("elevation_p95")
    mean_slope_deg = flatness_stats.get("slope_mean")

    if elevation_p5 is None or elevation_p95 is None or mean_slope_deg is None:
        raise SarUnavailableError(
            f"The new-water candidate on {reach} could not be scored against "
            f"the terrain: Copernicus GLO-30 returned no elevation or slope "
            f"under the candidate mask. An unscored candidate is not a "
            f"detection, so none is produced."
        )

    elevation_spread_m = float(elevation_p95) - float(elevation_p5)
    mean_slope_deg = float(mean_slope_deg)
    passes_flatness = flatness_verdict(elevation_spread_m, mean_slope_deg)

    if not passes_flatness:
        raise SarUnavailableError(
            f"The new-water candidate on {reach} sits on ground that is not "
            f"flat: {elevation_spread_m:,.0f} m of elevation spread across it "
            f"(limit {MAX_LAKE_ELEVATION_SPREAD_M:.0f} m) at a mean slope of "
            f"{mean_slope_deg:.0f} degrees (limit "
            f"{MAX_LAKE_MEAN_SLOPE_DEG:.0f}). Standing water has a level "
            f"surface, so this is not an impoundment — it is residual dark "
            f"backscatter on a valley wall that survived the geometry mask. No "
            f"detection is produced. The barrier can still be placed manually, "
            f"which runs fully offline."
        )

    cache_dir = Path(cache_dir)
    geotiff = _download(
        lake.getDownloadURL({
            "region": region, "scale": scale_m,
            "format": "GEO_TIFF", "crs": "EPSG:4326",
        }),
        cache_dir / "new_water_mask.tif",
    )
    png = _download(
        lake.getThumbURL({
            "region": region, "dimensions": 768, "min": 0, "max": 1,
            "palette": ["00000000", "D81B60"],
            "format": "png",
        }),
        cache_dir / "new_water_mask.png",
    )

    return {
        "reach": reach,
        "source": "sentinel1_change_detection",
        "collection": S1_COLLECTION,
        "scene_id_post": post_scene_id,
        "acquired_at_post": post_acquired_at,
        "date_pre_start": date_pre_start,
        "date_pre_end": date_pre_end,
        "threshold_db_pre": pre_derivation["threshold_db"],
        "threshold_db_post": post_derivation["threshold_db"],
        "threshold_method": "otsu_split_based_per_scene",
        "precision_of_pre_mask_vs_jrc": pre_agreement["precision"],
        "recall_of_pre_mask_vs_jrc": pre_agreement["recall"],
        "new_water_fraction": candidate_near_fraction,
        "fraction_near_drainage": fraction_near_drainage,
        "pre_water_fraction": pre_water_fraction,
        "pre_scenes_on_track": n_pre_scenes,
        "orbit_pass": post_pass,
        "relative_orbit": post_orbit,
        "largest_component_m2": largest_component_m2,
        "min_component_m2": MIN_NEW_WATER_AREA_M2,
        "lake_elevation_spread_m": elevation_spread_m,
        "lake_mean_slope_deg": mean_slope_deg,
        "lake_mean_elevation_m": flatness_stats.get("elevation_mean"),
        "passes_flatness": passes_flatness,
        "flatness_dem": GLO30_COLLECTION,
        **geometry_provenance(geometry),
        "amplitude_form_fraction": _fraction(amplitude_new),
        "amplitude_threshold_db": CHANGE_THRESHOLD_DB,
        "bbox": list(bbox),
        "scale_m": scale_m,
        "mask_geotiff_path": str(geotiff),
        "mask_png_path": str(png),
        "fetched_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "note": (
            "New water observed between the pre-event median and a single "
            "post-event Sentinel-1 scene on the same track, after excluding "
            "radar shadow and layover from the local incidence angle, minus JRC "
            "permanent water, filtered to within "
            f"{DRAINAGE_PROXIMITY_M:.0f} m of a watercourse, to connected "
            f"patches of at least {MIN_NEW_WATER_AREA_M2:,.0f} m2, and to "
            "ground flat enough to hold standing water. Geometry-masked, NOT "
            "radiometrically terrain-flattened. This is a change in observed "
            "water extent, NOT a surveyed lake: its depth, volume and barrier "
            "geometry are not observable from backscatter and must come from "
            "the DEM and an operator."
        ),
    }


def detect_new_water(
    reach: str,
    bbox: Tuple[float, float, float, float],
    cache_dir,
    date_pre_start: str,
    date_pre_end: str,
    date_post: str,
    scale_m: float = DEFAULT_SCALE_M,
) -> Dict:
    """
    New water on a reach between a pre-event window and a post-event scene.

    Args:
        reach: Reach name, for messages and the cache directory.
        bbox: (min_lon, min_lat, max_lon, max_lat) WGS84. Supplied by the
            caller — jalraksha.gee must not import the service layer, which is
            where the site registry lives.
        cache_dir: Directory for this reach's cached mask and manifest.
        date_pre_start, date_pre_end: Stable pre-event window, ISO dates.
        date_post: First post-event acquisition date, ISO.
        scale_m: Output posting, metres.

    Returns:
        A detection dict with ``source`` of ``sentinel1_change_detection`` or
        ``cached``, the post scene's own id and acquisition time, both derived
        thresholds, the gate measurements, and paths to the mask.

    Raises:
        SarUnavailableError: whenever a mask cannot be produced honestly —
            Earth Engine unavailable, no scene, an unthresholdable scene, the
            pre-event mask failing its agreement check, or the candidates
            failing the drainage gate. The message says which and why. No
            synthetic substitute is ever produced.
    """
    cache_dir = Path(cache_dir)
    available, reason = gee_status()

    remembered = _REFUSALS.get(reach)
    if remembered and (time.monotonic() - remembered[0]) < REFUSAL_CACHE_SECONDS:
        raise SarUnavailableError(remembered[1])

    live_failure = reason
    if available:
        try:
            detection = _fetch_live(
                reach, bbox, cache_dir, date_pre_start, date_pre_end,
                date_post, scale_m,
            )
            _manifest_path(cache_dir).write_text(
                json.dumps(detection, indent=2), encoding="utf-8"
            )
            _REFUSALS.pop(reach, None)
            return detection
        except SarUnavailableError as exc:
            _REFUSALS[reach] = (time.monotonic(), str(exc))
            raise
        except Exception as exc:
            live_failure = f"{type(exc).__name__}: {exc}"
            print(f"[gee] Live blockage detection for {reach} failed - {live_failure}")
    else:
        print(f"[gee] Earth Engine unavailable for {reach} - {reason}")

    # Offline-first: a previously fetched detection is a real observation and
    # stays usable when the network is not. Relabelled, keeping its own dates.
    cached = _read_cache(cache_dir)
    if cached is not None:
        cached = dict(cached)
        cached["source"] = "cached"
        cached["reason"] = (
            f"Served from cache because the live query was not possible: "
            f"{live_failure}"
        )
        return cached

    raise SarUnavailableError(
        f"No blockage detection available for {reach}: the live Earth Engine "
        f"query could not run ({live_failure}), and nothing is cached under "
        f"{cache_dir}. No synthetic substitute is produced. The barrier can "
        f"still be placed manually, which runs fully offline."
    )


def reset_refusals() -> None:
    """Forget remembered refusals. For tests and for a deliberate retry."""
    _REFUSALS.clear()
