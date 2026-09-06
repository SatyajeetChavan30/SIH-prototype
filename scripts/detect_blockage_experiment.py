"""
Does the landslide-lake auto-detector work anywhere? — a measured answer.

WHY THIS EXISTS

`jalraksha/gee/blockage_detect.py` has never produced a detection. The only
reach it has been run against is the Rishi Ganga (Chamoli 2021), where it
refuses at Gate 1: JRC Global Surface Water shows permanent water over 0.001% of
the window, so the pre-event mask has nothing to be verified against. That
refusal is real and is documented in docs/validation_findings.md section 6, but
it leaves the central question unanswered. The refusal happens *before* any
new-water logic runs, so the Rishi Ganga cannot tell us whether the rest of the
detector works at all.

Answering that needs a landslide dam on a DIFFERENT CLASS OF RIVER — a wide,
JRC-mapped channel where Gate 1 can pass and the later gates actually execute.
This harness runs the real detector, unmodified, against:

  * Baige (Bai Ge) barrier lakes, Jinsha River (upper Yangtze), Tibet —
    10 October 2018 and 3 November 2018. A major channel in a deep gorge.
  * Rishi Ganga, Chamoli 2021 — the known-refusal control, so any change in
    verdict can be attributed to the river rather than to this harness.

WHAT THIS IS NOT

It does not modify the detector, and it does not tune a threshold to make a
reach pass. CLAUDE.md is explicit that MIN_JRC_PRECISION must not be widened to
force a steep reach through; the same applies to every other gate here. The
output is a measurement. If the detector refuses everywhere, that is the finding.

WHY IT WRITES TO ITS OWN CACHE ROOT

`detect_new_water` writes `blockage_manifest.json` into whatever cache_dir it is
handed, and `_read_cache` will later serve that file back as a genuine
observation with source="cached". The API reads
`data/gee/blockage/<reach>` (services/api/jalraksha_service/main.py). This
harness therefore writes only to `data/gee/blockage_experiment/`, so no
experimental artefact can ever surface in the dashboard as a real detection.

USAGE

    python scripts/detect_blockage_experiment.py --stage preflight
    # ...look at the PNGs. Is the barrier lake actually in the window?
    python scripts/detect_blockage_experiment.py --stage detect

Plan: C:/Users/satya/.claude/plans/wise-beaming-moth.md
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Same pattern as scripts/run_api.py: setdefault, so a real environment
# variable still wins. jalraksha.gee.auth reads JALRAKSHA_GEE_PROJECT and has
# no default of its own.
os.environ.setdefault("JALRAKSHA_GEE_PROJECT", "sih-prototype-506812")
os.environ.setdefault("JALRAKSHA_DATA_DIR", str(ROOT / "data"))

OUTPUT_ROOT = ROOT / "data" / "gee" / "blockage_experiment"

#: Half-widths of the square window, in degrees.
#:
#: 0.10 is the app's own SAR_WINDOW_DEG (main.py:760), so results here sit
#: directly beside the already-measured JRC reference fractions: Rishi Ganga
#: 0.001%, Tehri 0.572%, Hirakud 44.520%.
#:
#: 0.20 is a sensitivity pass. Window size drives `reference_fraction` directly
#: — a bigger box catches more JRC-mapped river — and `reference_fraction` is
#: the number that decided the Rishi Ganga refusal. If a verdict flips on window
#: size alone, that is a finding about the gate, not about the river.
WINDOW_HALF_DEGREES: Tuple[float, ...] = (0.10, 0.20)

#: Sentinel-2 Level-1C, top-of-atmosphere. Deliberately NOT S2_SR_HARMONIZED:
#: the Level-2A surface-reflectance archive outside Europe does not reach back
#: to October 2018, so an L2A query for Baige returns nothing. L1C is complete
#: from 2015 globally, and true colour is all this is used for — a human check
#: that the barrier lake is genuinely inside the window.
S2_COLLECTION = "COPERNICUS/S2_HARMONIZED"

#: Longest half-window searched for a cloud-free optical scene, days. Sentinel-2
#: revisit is 5 days with both satellites; 20 days allows a few attempts at a
#: cloud gap without drifting so far from the event that the lake may have been
#: breached in between.
S2_SEARCH_DAYS = 20

#: Sentinel-1 VV display stretch, decibels. Water is a specular reflector and
#: reads very dark; -25 to 0 dB is the conventional range for a VV GRD scene.
S1_DISPLAY_DB = (-25.0, 0.0)

#: Sentinel-2 true-colour display stretch, TOA reflectance x 10000.
S2_DISPLAY_REFLECTANCE = (0.0, 3000.0)

THUMBNAIL_PIXELS = 768


@dataclass(frozen=True)
class Event:
    """One landslide-dam event to test the detector against."""

    key: str
    name: str
    lat: float
    lon: float
    date_pre_start: str
    date_pre_end: str
    date_post: str
    #: When the barrier formed and when the lake ceased to exist, ISO dates.
    #: Used only to report whether any Sentinel-1 acquisition fell inside the
    #: lake's lifetime; never used to filter or to adjust a gate.
    lake_from: str
    lake_until: Optional[str]
    provenance: str
    expectation: str


def _rishi_ganga_control() -> Event:
    """
    The control, built from the shipped preset rather than retyped.

    Reading lat/lon and the detection dates out of jalraksha.presets.RISHI_GANGA
    keeps the control identical to what the dashboard runs. A retyped copy would
    be free to drift, and then a changed verdict could be the coordinates rather
    than the detector.
    """
    from jalraksha.presets import RISHI_GANGA

    post = _dt.date.fromisoformat(RISHI_GANGA.detect_date_post)
    return Event(
        key="rishi_ganga",
        name=RISHI_GANGA.name,
        lat=RISHI_GANGA.lat,
        lon=RISHI_GANGA.lon,
        date_pre_start=RISHI_GANGA.detect_date_pre,
        # The API computes pre_end as date_post minus one day
        # (main.py:889). Mirrored here so the control is the same query.
        date_pre_end=(post - _dt.timedelta(days=1)).isoformat(),
        date_post=RISHI_GANGA.detect_date_post,
        lake_from=RISHI_GANGA.event_date,
        lake_until=None,
        provenance=(
            "jalraksha.presets.RISHI_GANGA — the coordinates and detection "
            "dates the dashboard itself uses."
        ),
        expectation=(
            "KNOWN REFUSAL. Gate 1, no usable reference: JRC permanent water "
            "covers 0.001% of the 0.2-degree window. Included as a control so a "
            "different verdict elsewhere can be attributed to the river."
        ),
    )


# Baige (Bai Ge) landslide dams, Jinsha River, on the Tibet/Sichuan border.
#
# TODO: UNVETTED COORDINATES. 31.08 N, 98.71 E and the event dates below are
# working values, not transcribed from a source held in this repository. They
# are exactly what the preflight stage exists to check: if the Sentinel-2
# after-image does not show the barrier lake, the box is wrong and every gate
# number downstream of it is meaningless. Confirm visually before quoting any
# result from this event.
_BAIGE_LAT, _BAIGE_LON = 31.08, 98.71

# One pre-window shared by BOTH Baige events, ending before the first barrier
# formed. The November case must not be differenced against a pre-state that
# already contains the October lake — that would suppress exactly the signal
# being looked for, since the pre-image is a median.
_BAIGE_PRE_START, _BAIGE_PRE_END = "2018-08-15", "2018-10-09"

EVENTS: Tuple[Event, ...] = (
    Event(
        key="baige_2018_10",
        name="Baige landslide dam (first), Jinsha River",
        lat=_BAIGE_LAT,
        lon=_BAIGE_LON,
        date_pre_start=_BAIGE_PRE_START,
        date_pre_end=_BAIGE_PRE_END,
        date_post="2018-10-11",
        lake_from="2018-10-10",
        lake_until="2018-10-13",
        provenance="TODO: UNVETTED — working coordinates, confirm in preflight imagery.",
        expectation=(
            "TIMING RISK. The lake existed roughly 10-13 October, about three "
            "days. Sentinel-1 revisit here in 2018 was 6-12 days and the "
            "detector caps its post window at MAX_POST_WINDOW_DAYS = 6 to keep "
            "a single named scene. If no acquisition caught the lake, that is a "
            "temporal-resolution limit of open SAR, not a gate failure, and the "
            "two are reported separately."
        ),
    ),
    Event(
        key="baige_2018_11",
        name="Baige landslide dam (second), Jinsha River",
        lat=_BAIGE_LAT,
        lon=_BAIGE_LON,
        date_pre_start=_BAIGE_PRE_START,
        date_pre_end=_BAIGE_PRE_END,
        date_post="2018-11-04",
        lake_from="2018-11-03",
        lake_until="2018-11-13",
        provenance="TODO: UNVETTED — working coordinates, confirm in preflight imagery.",
        expectation=(
            "THE PRIMARY TEST. The lake stood roughly 3-13 November, about ten "
            "days, comfortably longer than the Sentinel-1 revisit interval, on "
            "a major channel that JRC does map. This is the case where Gate 1 "
            "can pass and the later gates actually get exercised."
        ),
    ),
    _rishi_ganga_control(),
)


def get_events(keys: Optional[List[str]]) -> List[Event]:
    if not keys:
        return list(EVENTS)
    by_key = {event.key: event for event in EVENTS}
    missing = [key for key in keys if key not in by_key]
    if missing:
        raise SystemExit(
            f"Unknown event key(s): {', '.join(missing)}. "
            f"Known: {', '.join(by_key)}"
        )
    return [by_key[key] for key in keys]


def bbox_for(event: Event, half_deg: float) -> Tuple[float, float, float, float]:
    """
    (min_lon, min_lat, max_lon, max_lat) in WGS84 degrees.

    Same construction as the service layer's _resolve_reach (main.py:782): a
    square window centred on the site point. Order matches ee.Geometry.BBox,
    which takes (west, south, east, north).
    """
    return (
        event.lon - half_deg,
        event.lat - half_deg,
        event.lon + half_deg,
        event.lat + half_deg,
    )


def case_dir(event: Event, half_deg: float) -> Path:
    return OUTPUT_ROOT / f"{event.key}_w{half_deg:.2f}".replace(".", "p", 1)


def require_gee() -> None:
    from jalraksha.gee.auth import gee_project, gee_status

    available, reason = gee_status()
    if not available:
        raise SystemExit(
            f"Earth Engine is not available, so nothing can be measured: {reason}\n"
            f"Project resolved to {gee_project()!r}. If authentication has "
            f"lapsed, run `earthengine authenticate` and try again."
        )
    print(f"[gee] {reason}")


# ---------------------------------------------------------------------------
# Stage 1 — preflight
# ---------------------------------------------------------------------------


def _list_s1_scenes(bbox, start: str, end: str) -> List[Dict]:
    """Every Sentinel-1 IW/VV acquisition over the box in a date range."""
    import ee

    from jalraksha.gee.sar import S1_COLLECTION

    region = ee.Geometry.BBox(*bbox)
    collection = (
        ee.ImageCollection(S1_COLLECTION)
        .filterBounds(region)
        .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VV"))
        .filter(ee.Filter.eq("instrumentMode", "IW"))
        .filterDate(start, end)
        .sort("system:time_start", True)
    )
    listing = collection.toList(collection.size()).getInfo() or []

    scenes = []
    for item in listing:
        properties = item.get("properties", {})
        acquired = _dt.datetime.fromtimestamp(
            properties["system:time_start"] / 1000.0, tz=_dt.timezone.utc
        )
        scenes.append({
            "scene_id": item.get("id", "").split("/")[-1],
            "acquired_at": acquired.isoformat(),
            "date": acquired.date().isoformat(),
            "orbit_number": properties.get("relativeOrbitNumber_start"),
            "orbit_pass": properties.get("orbitProperties_pass"),
            "platform": properties.get("platform_number"),
        })
    return scenes


def _save_thumbnail(image, region, destination: Path, vis: Dict) -> Optional[str]:
    """Download one Earth Engine thumbnail, returning None rather than raising."""
    from jalraksha.gee.sar import _download

    try:
        params = {"region": region, "dimensions": THUMBNAIL_PIXELS, "format": "png"}
        params.update(vis)
        _download(image.getThumbURL(params), destination)
        return str(destination)
    except Exception as exc:  # noqa: BLE001 — a missing picture must not stop the run
        print(f"    ! thumbnail {destination.name} failed: {type(exc).__name__}: {exc}")
        return None


def _optical_pair(bbox, region, event: Event, out: Path) -> Dict:
    """
    Least-cloudy Sentinel-2 true-colour scene before and after the event.

    This is the human-readable half of the preflight. The detector never sees
    optical data; these images exist so a person can confirm the barrier lake is
    genuinely inside the window before any gate number is believed.
    """
    import ee

    results: Dict[str, object] = {"collection": S2_COLLECTION}
    anchor = _dt.date.fromisoformat(event.date_post)
    lake_from = _dt.date.fromisoformat(event.lake_from)

    windows = {
        # Before: ends the day the barrier formed.
        "pre": (
            (lake_from - _dt.timedelta(days=S2_SEARCH_DAYS)).isoformat(),
            lake_from.isoformat(),
        ),
        # After: starts at the barrier and runs forward. Bounded by the lake's
        # own end date where one is known, so the image shows the lake rather
        # than the drained valley after it breached.
        "post": (
            lake_from.isoformat(),
            (
                _dt.date.fromisoformat(event.lake_until)
                if event.lake_until
                else anchor + _dt.timedelta(days=S2_SEARCH_DAYS)
            ).isoformat(),
        ),
    }

    for label, (start, end) in windows.items():
        collection = (
            ee.ImageCollection(S2_COLLECTION)
            .filterBounds(region)
            .filterDate(start, end)
            .sort("CLOUDY_PIXEL_PERCENTAGE", True)
        )
        if collection.size().getInfo() == 0:
            results[label] = {
                "available": False,
                "window": [start, end],
                "reason": "No Sentinel-2 scene intersects this box in the window.",
            }
            print(f"    S2 {label}: no scene between {start} and {end}")
            continue

        scene = ee.Image(collection.first())
        properties = scene.getInfo()["properties"]
        acquired = _dt.datetime.fromtimestamp(
            properties["system:time_start"] / 1000.0, tz=_dt.timezone.utc
        )
        cloud = properties.get("CLOUDY_PIXEL_PERCENTAGE")
        path = _save_thumbnail(
            scene.select(["B4", "B3", "B2"]).clip(region),
            region,
            out / f"s2_{label}.png",
            {
                "min": S2_DISPLAY_REFLECTANCE[0],
                "max": S2_DISPLAY_REFLECTANCE[1],
                "gamma": 1.2,
            },
        )
        results[label] = {
            "available": True,
            "window": [start, end],
            "scene_id": properties.get("PRODUCT_ID") or scene.get("system:index").getInfo(),
            "acquired_at": acquired.isoformat(),
            "cloudy_pixel_percentage": cloud,
            "png": path,
        }
        print(f"    S2 {label}: {acquired.date()} cloud={cloud}% -> {path}")

    return results


def preflight(event: Event, half_deg: float) -> Dict:
    """
    Establish that the box and the dates are right, before trusting any gate.

    Four things, in order of how much they cost: the Sentinel-1 scene table
    (settles whether an acquisition even exists while the lake stood), the
    Sentinel-1 VV pair (what the detector actually consumes), the Sentinel-2
    true-colour pair (what a person can verify), and the JRC permanent-water
    fraction (which predicts the Gate 1 verdict for a fraction of the cost of
    running it).
    """
    import ee

    from jalraksha.gee.sar import (
        JRC_GSW,
        JRC_PERMANENT_OCCURRENCE_PCT,
        MIN_JRC_PRECISION,
    )
    from jalraksha.gee.blockage_detect import (
        DEFAULT_SCALE_M,
        MIN_JRC_REFERENCE_FRACTION,
    )

    bbox = bbox_for(event, half_deg)
    out = case_dir(event, half_deg)
    out.mkdir(parents=True, exist_ok=True)
    region = ee.Geometry.BBox(*bbox)

    print(f"\n=== PREFLIGHT {event.key} @ +/-{half_deg:.2f} deg ===")
    print(f"    bbox {bbox}")

    # 1. Scene table. Search from the pre-window start to a month past the post
    # date, so the report can say what WAS available as well as what was used.
    search_end = (
        _dt.date.fromisoformat(event.date_post) + _dt.timedelta(days=30)
    ).isoformat()
    scenes = _list_s1_scenes(bbox, event.date_pre_start, search_end)
    print(f"    Sentinel-1 IW/VV scenes in {event.date_pre_start}..{search_end}: {len(scenes)}")

    # Did any acquisition fall inside the lake's own lifetime? This is the
    # question the October Baige case turns on, and it is a different failure
    # from a gate refusal.
    lake_from = _dt.date.fromisoformat(event.lake_from)
    lake_until = (
        _dt.date.fromisoformat(event.lake_until)
        if event.lake_until
        else _dt.date.fromisoformat(event.date_post) + _dt.timedelta(days=30)
    )
    during_lake = [
        scene for scene in scenes
        if lake_from <= _dt.date.fromisoformat(scene["date"]) <= lake_until
    ]
    print(
        f"    ...of which inside the lake's lifetime "
        f"({lake_from} to {lake_until}): {len(during_lake)}"
    )
    for scene in during_lake:
        print(f"        {scene['date']}  orbit {scene['orbit_number']} {scene['orbit_pass']}")

    # 2. Sentinel-1 VV pre-median and post scene — exactly the two images the
    # detector differences.
    from jalraksha.gee.sar import S1_COLLECTION

    base = (
        ee.ImageCollection(S1_COLLECTION)
        .filterBounds(region)
        .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VV"))
        .filter(ee.Filter.eq("instrumentMode", "IW"))
    )
    sar_vis = {"min": S1_DISPLAY_DB[0], "max": S1_DISPLAY_DB[1]}
    sar_paths: Dict[str, Optional[str]] = {}

    pre_collection = base.filterDate(event.date_pre_start, event.date_pre_end)
    if pre_collection.size().getInfo() > 0:
        sar_paths["pre_median"] = _save_thumbnail(
            pre_collection.median().select("VV").clip(region),
            region, out / "s1_pre_median.png", sar_vis,
        )
    else:
        sar_paths["pre_median"] = None
        print("    ! no Sentinel-1 scene in the pre-window")

    post_start = _dt.date.fromisoformat(event.date_post)
    from jalraksha.gee.blockage_detect import MAX_POST_WINDOW_DAYS

    post_collection = base.filterDate(
        post_start.isoformat(),
        (post_start + _dt.timedelta(days=MAX_POST_WINDOW_DAYS)).isoformat(),
    ).sort("system:time_start", True)
    if post_collection.size().getInfo() > 0:
        sar_paths["post_scene"] = _save_thumbnail(
            ee.Image(post_collection.first()).select("VV").clip(region),
            region, out / "s1_post_scene.png", sar_vis,
        )
    else:
        sar_paths["post_scene"] = None
        print(
            f"    ! no Sentinel-1 scene within {MAX_POST_WINDOW_DAYS} days of "
            f"{event.date_post} — the detector will refuse on that alone"
        )

    # 3. Optical before/after.
    optical = _optical_pair(bbox, region, event, out)

    # 4. JRC permanent water: the fraction, and a picture of it.
    occurrence = ee.Image(JRC_GSW).select("occurrence").unmask(0).clip(region)
    permanent = occurrence.gt(JRC_PERMANENT_OCCURRENCE_PCT).rename("w")
    reference_fraction = float(
        (permanent.reduceRegion(
            reducer=ee.Reducer.mean(), geometry=region,
            scale=DEFAULT_SCALE_M, maxPixels=int(1e9), bestEffort=True,
        ).getInfo() or {}).get("w") or 0.0
    )
    jrc_png = _save_thumbnail(
        permanent.selfMask(), region, out / "jrc_permanent_water.png",
        {"min": 0, "max": 1, "palette": ["0000FF"]},
    )
    print(
        f"    JRC permanent water (occurrence > {JRC_PERMANENT_OCCURRENCE_PCT}%): "
        f"{reference_fraction:.4%}  "
        f"(gate needs >= {MIN_JRC_REFERENCE_FRACTION:.3%} for the precision "
        f"check to mean anything)"
    )

    record = {
        "event": event.key,
        "name": event.name,
        "expectation": event.expectation,
        "provenance": event.provenance,
        "bbox": list(bbox),
        "window_half_deg": half_deg,
        "date_pre_start": event.date_pre_start,
        "date_pre_end": event.date_pre_end,
        "date_post": event.date_post,
        "lake_from": event.lake_from,
        "lake_until": event.lake_until,
        "s1_scene_count": len(scenes),
        "s1_scenes": scenes,
        "s1_scenes_during_lake": during_lake,
        "s1_thumbnails": sar_paths,
        "sentinel2": optical,
        "jrc_reference_fraction": reference_fraction,
        "jrc_reference_fraction_threshold": MIN_JRC_REFERENCE_FRACTION,
        "jrc_permanent_water_png": jrc_png,
        "min_jrc_precision": MIN_JRC_PRECISION,
        "generated_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
    }
    (out / "preflight.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    return record


# ---------------------------------------------------------------------------
# Stage 2 — the detector itself
# ---------------------------------------------------------------------------

#: Maps a refusal to which gate produced it, by matching the distinctive stem of
#: each message already raised inside _fetch_live. The harness classifies; it
#: does not invent new failure modes. Ordered most specific first.
REFUSAL_SIGNATURES: Tuple[Tuple[str, str], ...] = (
    ("There is no pre-event state to difference against", "no_pre_scene"),
    ("Nothing has been observed since the event on this reach", "no_post_scene"),
    ("no usable histogram", "unthresholdable_scene"),
    ("Cannot threshold the", "unthresholdable_scene"),
    ("shows permanent water over only", "gate1_no_usable_reference"),
    ("the mask largely missed it", "gate1_mask_missed_real_reference"),
    ("there is simply no new water body", "no_new_water_found"),
    ("of a watercourse", "gate3_drainage_proximity"),
    ("No blockage detection available", "earth_engine_unavailable"),
)


def classify_refusal(message: str) -> str:
    for stem, label in REFUSAL_SIGNATURES:
        if stem in message:
            return label
    return "unclassified"


def measure_gate1(event: Event, bbox, scale_m: float) -> Dict:
    """
    Record Gate 1's four numbers whether the detector passes or refuses.

    On the refusal path `_agreement_with_jrc`'s output is lost inside the
    exception, so it is recomputed here — by IMPORTING AND CALLING the real
    `_scene_threshold` and `_agreement_with_jrc` rather than reimplementing
    them. A re-derived gate would be free to drift away from the one that ships,
    and then this harness would be measuring itself.
    """
    import ee

    from jalraksha.gee.blockage_detect import _scene_threshold
    from jalraksha.gee.sar import MIN_JRC_PRECISION, S1_COLLECTION, _agreement_with_jrc

    region = ee.Geometry.BBox(*bbox)
    pre_collection = (
        ee.ImageCollection(S1_COLLECTION)
        .filterBounds(region)
        .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VV"))
        .filter(ee.Filter.eq("instrumentMode", "IW"))
        .filterDate(event.date_pre_start, event.date_pre_end)
    )
    if pre_collection.size().getInfo() == 0:
        return {"measured": False, "reason": "no pre-event scene to threshold"}

    pre = pre_collection.median().select("VV").clip(region)
    try:
        derivation = _scene_threshold(pre, region, bbox, scale_m, "pre-event")
    except Exception as exc:  # noqa: BLE001
        return {"measured": False, "reason": f"{type(exc).__name__}: {exc}"}

    pre_water = pre.lt(derivation["threshold_db"]).rename("water").toByte()
    agreement = _agreement_with_jrc(pre, pre_water, region, scale_m)
    return {
        "measured": True,
        "threshold_db": derivation["threshold_db"],
        "n_tiles_used": derivation.get("n_tiles_used"),
        "n_tiles_total": derivation.get("n_tiles_total"),
        "separability": derivation.get("separability"),
        "precision": agreement["precision"],
        "recall": agreement["recall"],
        "reference_fraction": agreement["reference_fraction"],
        "mask_fraction": agreement["mask_fraction"],
        "min_jrc_precision": MIN_JRC_PRECISION,
        "passes": agreement["precision"] >= MIN_JRC_PRECISION,
    }


def measure_dead_gates(mask_geotiff: Path, event: Event, half_deg: float) -> Dict:
    """
    What the two documented-but-unwired gates WOULD have done.

    Both are declared in blockage_detect.py and then never applied inside
    _fetch_live:

      * MIN_NEW_WATER_AREA_M2 = 20 000 is never referenced. There is no area
        floor on a candidate.
      * score_candidate_flatness is called "the strongest filter and it is free"
        in the module docstring and is never invoked by the detector. The
        docstring says so itself.

    This function reports what they would have produced. It changes nothing.
    """
    import numpy as np
    import rasterio

    from jalraksha.gee.blockage_detect import (
        MAX_LAKE_ELEVATION_SPREAD_M,
        MAX_LAKE_MEAN_SLOPE_DEG,
        MIN_NEW_WATER_AREA_M2,
        score_candidate_flatness,
    )

    result: Dict[str, object] = {
        "min_new_water_area_m2": MIN_NEW_WATER_AREA_M2,
        "max_lake_elevation_spread_m": MAX_LAKE_ELEVATION_SPREAD_M,
        "max_lake_mean_slope_deg": MAX_LAKE_MEAN_SLOPE_DEG,
    }

    with rasterio.open(mask_geotiff) as source:
        mask = source.read(1) > 0
        # The mask is written in EPSG:4326 at `scale_m` posting, so a cell's
        # ground area varies with latitude. cos(lat) is accurate enough for an
        # area floor comparison and avoids a reprojection for a diagnostic.
        lat_rad = np.deg2rad(event.lat)
        deg_height = abs(source.transform.e)
        deg_width = abs(source.transform.a)
        cell_m2 = (deg_height * 110_574.0) * (deg_width * 111_320.0 * np.cos(lat_rad))

    candidate_cells = int(mask.sum())
    area_m2 = float(candidate_cells * cell_m2)
    result["candidate_cells"] = candidate_cells
    result["candidate_area_m2"] = area_m2
    result["passes_area_floor"] = bool(area_m2 >= MIN_NEW_WATER_AREA_M2)

    # Flatness needs the stale DEM. Best-effort: a failed DEM fetch must not
    # discard a detection that already succeeded.
    try:
        from jalraksha.dem import fetch_dem
        from jalraksha.terrain.conditioning import load_dem_as_grid

        # Radius in km covering the window's half-width. 111 km per degree is
        # the same rounding fetch_dem itself uses.
        radius_km = half_deg * 111.0 * 1.45  # sqrt(2) plus margin: a square UTM
        # domain's corners fall outside a same-sized box in degrees.
        dem_path = fetch_dem(
            dam_lat=event.lat, dam_lon=event.lon, domain_radius_km=radius_km,
        )
        # load_dem_as_grid returns (grid, bed_elevation); row 0 of the array is
        # the SOUTHERNMOST row.
        _grid, bed_elevation = load_dem_as_grid(
            dem_path=str(dem_path), dam_lat=event.lat, dam_lon=event.lon,
            target_resolution=60.0, domain_radius_km=half_deg * 111.0,
            fill_max_depth_m=0.0,
        )
        bed = np.asarray(bed_elevation, dtype=np.float64)

        # Nearest-neighbour resample of the lat/lon mask onto the metric grid.
        # Crude, and adequate: this is a diagnostic on a gate that does not run.
        rows = np.linspace(0, mask.shape[0] - 1, bed.shape[0]).round().astype(int)
        cols = np.linspace(0, mask.shape[1] - 1, bed.shape[1]).round().astype(int)
        # Row 0 of a Grid is the SOUTHERNMOST row; row 0 of a north-up GeoTIFF
        # is the northernmost, so the mask is flipped before sampling.
        aligned = np.flipud(mask)[np.ix_(rows, cols)]

        result["flatness"] = score_candidate_flatness(bed, aligned, 60.0)
        result["flatness_dem"] = str(dem_path)
    except Exception as exc:  # noqa: BLE001
        result["flatness"] = None
        result["flatness_error"] = f"{type(exc).__name__}: {exc}"

    return result


def diagnostic_bypass_gate1(event: Event, half_deg: float) -> Dict:
    """
    Rebuild the candidate mask with GATE 1 SKIPPED. NOT A DETECTION.

    Gate 1 refuses on every case tested, so Gates 2 and 3 — and the two gates
    the detector never applies at all — have never executed on real data. This
    reconstructs the candidate exactly as `_fetch_live` does but without the
    precision check, purely to answer one question: if Gate 1 were removed,
    would anything downstream catch the bad mask, or would the detector publish
    a confident false lake?

    Every artefact is written under a `diagnostic_` prefix and NO
    `blockage_manifest.json` is written, so nothing produced here can ever be
    read back by `_read_cache` and served as a real observation.
    """
    import ee

    from jalraksha.gee.blockage_detect import (
        CHANGE_THRESHOLD_DB,
        DEFAULT_SCALE_M,
        DRAINAGE_PROXIMITY_M,
        MIN_FRACTION_NEAR_DRAINAGE,
        _scene_threshold,
    )
    from jalraksha.gee.sar import (
        JRC_GSW,
        JRC_PERMANENT_OCCURRENCE_PCT,
        MAX_PLAUSIBLE_WATER_FRACTION,
        S1_COLLECTION,
        _download,
    )

    bbox = bbox_for(event, half_deg)
    out = case_dir(event, half_deg)
    out.mkdir(parents=True, exist_ok=True)
    region = ee.Geometry.BBox(*bbox)
    scale_m = DEFAULT_SCALE_M

    print(f"\n=== DIAGNOSTIC (GATE 1 BYPASSED) {event.key} @ +/-{half_deg:.2f} deg ===")
    print("    NOT A DETECTION. Measures what the downstream gates would do.")

    base = (
        ee.ImageCollection(S1_COLLECTION)
        .filterBounds(region)
        .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VV"))
        .filter(ee.Filter.eq("instrumentMode", "IW"))
    )
    pre = base.filterDate(event.date_pre_start, event.date_pre_end).median().select("VV").clip(region)

    post_start = _dt.date.fromisoformat(event.date_post)
    from jalraksha.gee.blockage_detect import MAX_POST_WINDOW_DAYS

    post_collection = base.filterDate(
        post_start.isoformat(),
        (post_start + _dt.timedelta(days=MAX_POST_WINDOW_DAYS)).isoformat(),
    ).sort("system:time_start", True)
    if post_collection.size().getInfo() == 0:
        return {
            "event": event.key,
            "window_half_deg": half_deg,
            "gate1_bypassed": True,
            "measured": False,
            "reason": "no post-event scene within the detector's 6-day window",
        }
    post_scene = ee.Image(post_collection.first())
    post = post_scene.select("VV").clip(region)

    pre_derivation = _scene_threshold(pre, region, bbox, scale_m, "pre-event")
    post_derivation = _scene_threshold(post, region, bbox, scale_m, "post-event")
    pre_water = pre.lt(pre_derivation["threshold_db"]).rename("water").toByte()
    post_water = post.lt(post_derivation["threshold_db"]).rename("water").toByte()

    # Everything below is _fetch_live's own construction, verbatim in intent.
    new_water = post_water.And(pre_water.Not()).rename("new_water").toByte()
    permanent = (
        ee.Image(JRC_GSW).select("occurrence").unmask(0).clip(region)
        .gt(JRC_PERMANENT_OCCURRENCE_PCT)
    )
    candidate = new_water.And(permanent.Not()).rename("candidate").toByte()
    drainage = ee.Image(JRC_GSW).select("occurrence").unmask(0).clip(region).gt(10)
    near_drainage = (
        drainage.fastDistanceTransform().sqrt()
        .multiply(ee.Image.pixelArea().sqrt())
        .lte(DRAINAGE_PROXIMITY_M)
    )
    candidate_near = candidate.And(near_drainage).rename("candidate").toByte()
    amplitude_new = (
        post.subtract(pre).lte(CHANGE_THRESHOLD_DB).And(permanent.Not()).toByte()
    )

    def fraction(image) -> float:
        value = image.rename("w").reduceRegion(
            reducer=ee.Reducer.mean(), geometry=region, scale=scale_m,
            maxPixels=int(1e9), bestEffort=True,
        ).getInfo()
        return float((value or {}).get("w") or 0.0)

    post_water_fraction = fraction(post_water)
    candidate_fraction = fraction(candidate)
    candidate_near_fraction = fraction(candidate_near)
    fraction_near_drainage = (
        candidate_near_fraction / candidate_fraction if candidate_fraction > 0 else 0.0
    )

    record: Dict[str, object] = {
        "event": event.key,
        "window_half_deg": half_deg,
        "gate1_bypassed": True,
        "measured": True,
        "WARNING": (
            "GATE 1 BYPASSED - NOT A DETECTION. The pre-event mask failed its "
            "agreement check against JRC; these numbers describe what the "
            "remaining gates would do with a mask already known to be wrong."
        ),
        "threshold_db_pre": pre_derivation["threshold_db"],
        "threshold_db_post": post_derivation["threshold_db"],
        "post_water_fraction": post_water_fraction,
        "max_plausible_water_fraction": MAX_PLAUSIBLE_WATER_FRACTION,
        "post_water_exceeds_plausibility_guard": post_water_fraction > MAX_PLAUSIBLE_WATER_FRACTION,
        "candidate_fraction": candidate_fraction,
        "candidate_near_drainage_fraction": candidate_near_fraction,
        "fraction_near_drainage": fraction_near_drainage,
        "min_fraction_near_drainage": MIN_FRACTION_NEAR_DRAINAGE,
        "passes_gate3_drainage": fraction_near_drainage >= MIN_FRACTION_NEAR_DRAINAGE,
        "amplitude_form_fraction": fraction(amplitude_new),
    }
    print(
        f"    post-event water mask covers {post_water_fraction:.1%} of the window "
        f"(sar.py's plausibility guard is {MAX_PLAUSIBLE_WATER_FRACTION:.0%}, and "
        f"blockage_detect never applies it)"
    )
    print(
        f"    candidate new water {candidate_fraction:.2%}, "
        f"{fraction_near_drainage:.0%} of it near drainage "
        f"(gate 3 needs >= {MIN_FRACTION_NEAR_DRAINAGE:.0%}) -> "
        f"{'WOULD PASS' if record['passes_gate3_drainage'] else 'would refuse'}"
    )

    if candidate_fraction > 0:
        mask_path = out / "diagnostic_gate1_bypassed_mask.tif"
        try:
            _download(
                candidate_near.getDownloadURL({
                    "region": region, "scale": scale_m,
                    "format": "GEO_TIFF", "crs": "EPSG:4326",
                }),
                mask_path,
            )
            _save_thumbnail(
                candidate_near.selfMask(), region,
                out / "diagnostic_gate1_bypassed_mask.png",
                {"min": 0, "max": 1, "palette": ["D81B60"]},
            )
            record["mask_geotiff_path"] = str(mask_path)
            record["unwired_gates"] = measure_dead_gates(mask_path, event, half_deg)
            unwired = record["unwired_gates"]
            print(
                f"    area {unwired['candidate_area_m2']:,.0f} m2 vs floor "
                f"{unwired['min_new_water_area_m2']:,.0f} m2 -> "
                f"{'WOULD PASS' if unwired['passes_area_floor'] else 'would refuse'}"
            )
            flatness = unwired.get("flatness")
            if flatness:
                print(
                    f"    flatness spread {flatness['elevation_spread_m']:.1f} m, "
                    f"mean slope {flatness['mean_slope_deg']:.2f} deg (limits "
                    f"{unwired['max_lake_elevation_spread_m']} m / "
                    f"{unwired['max_lake_mean_slope_deg']} deg) -> "
                    f"{'WOULD PASS' if flatness['passes_flatness'] else 'would refuse'}"
                )
            else:
                print(f"    flatness not measured: {unwired.get('flatness_error')}")
        except Exception as exc:  # noqa: BLE001
            record["mask_error"] = f"{type(exc).__name__}: {exc}"
            print(f"    ! mask download failed: {record['mask_error']}")

    # Deliberately NOT blockage_manifest.json: _read_cache must never find this.
    (out / "diagnostic_gate1_bypassed.json").write_text(
        json.dumps(record, indent=2), encoding="utf-8"
    )
    return record


def detect(event: Event, half_deg: float) -> Dict:
    """Run the real detector, catching a refusal instead of dying on it."""
    from jalraksha.gee.blockage_detect import (
        DEFAULT_SCALE_M,
        detect_new_water,
        reset_refusals,
    )
    from jalraksha.gee.sar import SarUnavailableError

    bbox = bbox_for(event, half_deg)
    out = case_dir(event, half_deg)
    out.mkdir(parents=True, exist_ok=True)

    print(f"\n=== DETECT {event.key} @ +/-{half_deg:.2f} deg ===")

    # A refusal is remembered per reach for an hour. Cleared so a deliberate
    # re-run actually re-queries rather than replaying the last verdict.
    reset_refusals()

    record: Dict[str, object] = {
        "event": event.key,
        "name": event.name,
        "bbox": list(bbox),
        "window_half_deg": half_deg,
        "date_pre_start": event.date_pre_start,
        "date_pre_end": event.date_pre_end,
        "date_post": event.date_post,
        "expectation": event.expectation,
        "run_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
    }

    # Gate 1's numbers first, so they exist whichever way the verdict goes.
    print("    measuring Gate 1 (pre-event mask vs JRC)...")
    record["gate1"] = measure_gate1(event, bbox, DEFAULT_SCALE_M)
    gate1 = record["gate1"]
    if gate1.get("measured"):
        print(
            f"      precision {gate1['precision']:.4f} "
            f"(needs >= {gate1['min_jrc_precision']}), "
            f"recall {gate1['recall']:.3f}, "
            f"JRC reference {gate1['reference_fraction']:.4%}, "
            f"threshold {gate1['threshold_db']:.2f} dB "
            f"-> {'PASS' if gate1['passes'] else 'FAIL'}"
        )
    else:
        print(f"      not measurable: {gate1.get('reason')}")

    try:
        detection = detect_new_water(
            reach=f"{event.key}_w{half_deg:.2f}",
            bbox=bbox,
            cache_dir=out,
            date_pre_start=event.date_pre_start,
            date_pre_end=event.date_pre_end,
            date_post=event.date_post,
        )
    except SarUnavailableError as exc:
        message = str(exc)
        record["verdict"] = "refused"
        record["refusal_class"] = classify_refusal(message)
        record["refusal_message"] = message
        print(f"    REFUSED [{record['refusal_class']}]")
        print(f"      {message}")
        (out / "detection.json").write_text(
            json.dumps(record, indent=2), encoding="utf-8"
        )
        return record
    except Exception as exc:  # noqa: BLE001
        record["verdict"] = "error"
        record["error"] = f"{type(exc).__name__}: {exc}"
        record["traceback"] = traceback.format_exc()
        print(f"    ERROR {record['error']}")
        (out / "detection.json").write_text(
            json.dumps(record, indent=2), encoding="utf-8"
        )
        return record

    record["verdict"] = "detected"
    record["detection"] = detection
    print(
        f"    DETECTED  new water {detection['new_water_fraction']:.5%} of window, "
        f"{detection['fraction_near_drainage']:.0%} near drainage, "
        f"scene {detection['scene_id_post']}"
    )

    geotiff = Path(detection["mask_geotiff_path"])
    if geotiff.exists():
        print("    measuring the two gates the detector never applies...")
        record["unwired_gates"] = measure_dead_gates(geotiff, event, half_deg)
        unwired = record["unwired_gates"]
        print(
            f"      area {unwired['candidate_area_m2']:,.0f} m2 vs floor "
            f"{unwired['min_new_water_area_m2']:,.0f} m2 -> "
            f"{'PASS' if unwired['passes_area_floor'] else 'FAIL'}"
        )
        flatness = unwired.get("flatness")
        if flatness:
            print(
                f"      flatness spread {flatness['elevation_spread_m']:.2f} m, "
                f"mean slope {flatness['mean_slope_deg']:.2f} deg -> "
                f"{'PASS' if flatness['passes_flatness'] else 'FAIL'}"
            )
        else:
            print(f"      flatness not measured: {unwired.get('flatness_error')}")

    (out / "detection.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    return record


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------


def write_summary(
    preflights: List[Dict],
    detections: List[Dict],
    diagnostics: Optional[List[Dict]] = None,
) -> Path:
    """A single JSON holding every case, for the findings write-up to quote."""
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_ROOT / "summary.json"
    existing: Dict[str, object] = {}
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            existing = {}

    if preflights:
        existing["preflight"] = preflights
    if detections:
        existing["detection"] = detections
    if diagnostics:
        existing["diagnostic_gate1_bypassed"] = diagnostics
    existing["written_at"] = _dt.datetime.now(_dt.timezone.utc).isoformat()
    path.write_text(json.dumps(existing, indent=2), encoding="utf-8")
    return path


def print_table(detections: List[Dict]) -> None:
    if not detections:
        return
    print("\n" + "=" * 78)
    print("RESULT")
    print("=" * 78)
    header = f"{'case':<26} {'verdict':<10} {'precision':>10} {'JRC ref':>9}  class"
    print(header)
    print("-" * 78)
    for record in detections:
        gate1 = record.get("gate1") or {}
        precision = (
            f"{gate1['precision']:.4f}" if gate1.get("measured") else "n/a"
        )
        reference = (
            f"{gate1['reference_fraction']:.4%}" if gate1.get("measured") else "n/a"
        )
        case = f"{record['event']}@{record['window_half_deg']:.2f}"
        detail = record.get("refusal_class") or record.get("error") or "-"
        print(
            f"{case:<26} {record['verdict']:<10} {precision:>10} "
            f"{reference:>9}  {detail}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run the landslide-lake auto-detector against real before/after "
            "satellite imagery for events where a barrier lake is known to "
            "have formed."
        )
    )
    parser.add_argument(
        "--stage", choices=("preflight", "detect", "diagnostic", "all"), default="preflight",
        help=(
            "preflight: fetch imagery and the scene table, confirm the box is "
            "right. detect: run the detector. diagnostic: rebuild the candidate "
            "with GATE 1 BYPASSED to see what the downstream gates would do — "
            "never a detection, and it writes no manifest. Default preflight, "
            "because detecting over a wrong box measures nothing."
        ),
    )
    parser.add_argument(
        "--event", action="append", default=None,
        help="Event key; repeatable. Default: all of them.",
    )
    parser.add_argument(
        "--window", type=float, action="append", default=None,
        help=f"Window half-width in degrees; repeatable. Default: {WINDOW_HALF_DEGREES}.",
    )
    args = parser.parse_args()

    events = get_events(args.event)
    windows = tuple(args.window) if args.window else WINDOW_HALF_DEGREES

    require_gee()
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    print(f"[out] {OUTPUT_ROOT}")
    print(
        "[note] This harness writes only under blockage_experiment/. The app's "
        "own cache at data/gee/blockage/ is never touched."
    )

    preflights: List[Dict] = []
    detections: List[Dict] = []
    diagnostics: List[Dict] = []

    for event in events:
        for half_deg in windows:
            try:
                if args.stage in ("preflight", "all"):
                    preflights.append(preflight(event, half_deg))
                if args.stage in ("detect", "all"):
                    detections.append(detect(event, half_deg))
                if args.stage in ("diagnostic", "all"):
                    diagnostics.append(diagnostic_bypass_gate1(event, half_deg))
            except Exception as exc:  # noqa: BLE001 — one bad case must not end the run
                print(f"    !! {event.key} @ {half_deg}: {type(exc).__name__}: {exc}")
                traceback.print_exc()

    summary = write_summary(preflights, detections, diagnostics)
    print_table(detections)
    print(f"\n[out] summary written to {summary}")

    if args.stage == "preflight":
        print(
            "\nNEXT: open the s2_pre.png / s2_post.png in each case directory. "
            "The barrier lake must be visible in the after-image. If it is not, "
            "the coordinates are wrong and the detect stage would only measure "
            "that mistake."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
