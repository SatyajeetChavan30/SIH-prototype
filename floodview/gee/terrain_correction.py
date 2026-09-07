"""
Radar geometry over terrain — the local incidence angle, and what it disqualifies.

WHAT THIS FIXES, AND THE MEASUREMENT THAT MOTIVATED IT

``docs/validation_findings.md`` section 9 and verification-queue row 29 record
the blocking defect on the auto-detection path: VV backscatter cannot separate
water from radar shadow in a gorge. Over the Baige barrier lakes on the Jinsha,
``derive_threshold_from_tiles`` accepted 17 of 64 sub-tiles at median
separability 0.732, returned -8.29 dB, and classified **63% of the gorge as
water** (recall 0.92 against JRC, precision 0.0075). The same construction gave
46-68% across six event/window cases. Over the Tehri gorge the earlier
whole-scene form reached recall 0.945 and precision 0.010.

The literature remedy is to identify pixels whose brightness is an artifact of
the imaging geometry and exclude them BEFORE thresholding, which is what this
module does.

IT WAS MEASURED, AND IT DOES NOT RESCUE THE DETECTOR. Read this before quoting
the module as the fix for row 29. Over Baige it excludes 16.6% of the window and
moves Gate 1 precision from 0.0075 to 0.007 against a 0.5 requirement, while
recall falls 0.92 to 0.85; every case still refuses. The reason is in the
geometry itself: **radar shadow is 0.09% of that window**. Shadow was never
numerous enough to explain a 63%-water mask, so the original diagnosis was wrong
in its emphasis. What is being mis-classified is ground that images perfectly
well and is merely dark — dry, smooth, or unfavourably oriented surfaces whose
backscatter overlaps open water's. That is radiometric, and the half of Small
(2011) that addresses it is the flattening below, which is not built.

This module is kept because excluding layover is correct on its own terms — a
layover pixel is a superposition of several places and means nothing wherever it
occurs — and because any radiometric correction needs exactly this geometry
underneath it. It is a prerequisite that turned out not to be sufficient, which
is a different thing from a fix. Measurements: docs/validation_findings.md §9.

WHAT THIS IS AND IS NOT

This is the **geometric** half of Small (2011): the local incidence angle from
a DEM and the imaging geometry, and the shadow / layover / severe-foreshortening
classes that follow from it. It is NOT the full radiometric terrain flattening
of that paper, which replaces the ellipsoid reference area with the local
illuminated area to produce gamma-nought. Flattening changes the VALUE of every
retained pixel; this changes only WHICH pixels are retained.

That distinction turned out to BE the result, not a caveat on it. Discarding
pixels is only the right instrument when the bad pixels are geometrically
identifiable, and the measurement above says they are not: 0.09% shadow against
a 63%-water mask. The dark ground defeating the threshold is imageable ground
whose backscatter simply overlaps water's, which is the quantity flattening
normalises and masking cannot touch. Anything published from this module says
"geometry-masked", never "terrain-flattened".

    cos(LIA) = cos(slope) * cos(theta) + sin(slope) * sin(theta) * cos(phi_look - phi_aspect)

with ``theta`` the ellipsoidal incidence angle, ``slope`` the terrain slope,
``phi_aspect`` the downslope azimuth, and ``phi_look`` the ground azimuth FROM
the target TOWARD the sensor. A slope facing the sensor gives LIA = theta -
slope; a slope facing away gives LIA = theta + slope. Shadow is LIA >= 90
degrees (the ground turns away past grazing); layover is LIA <= 0 (the slope is
steeper than the look ray, so near and far ground arrive out of order).

BOTH HALVES ARE HERE, AND THEY SHARE THEIR THRESHOLDS

``local_incidence_angle`` and ``geometry_validity_mask`` are pure numpy: they
run offline, against a cached DEM, and are what the tests exercise.
``earth_engine_validity_mask`` is the server-side twin for a live query, built
from Copernicus GLO-30 inside the Earth Engine call. They read the same module
constants, so the two cannot drift apart in what they disqualify.

References:
  - Small, D. (2011) "Flattening Gamma: Radiometric Terrain Correction for SAR
    Imagery", IEEE Transactions on Geoscience and Remote Sensing 49(10):
    3081-3093.
  - Ulaby, F.T. & Long, D.G. (2014) "Microwave Radar and Radiometric Remote
    Sensing", University of Michigan Press, ch. 13 (imaging geometry, layover
    and shadow definitions).
  - ESA Sentinel-1 Product Definition (S1-RS-MDA-52-7440): right-looking
    geometry, IW swath incidence range 29.1-46.0 degrees, orbit inclination
    98.18 degrees.
"""

from __future__ import annotations

from typing import Dict, Optional, Tuple

import numpy as np

#: Local incidence angle at or above which the ground is in radar shadow.
#:
#: NOT a tunable threshold: 90 degrees is the definition. Past grazing incidence
#: the surface has turned away from the ray and returns nothing, so the pixel
#: carries no information about what is on the ground. This is the class that
#: was being read as water.
SHADOW_LIA_DEG = 90.0

#: Local incidence angle at or below which the ground is in layover.
#:
#: Also a definition, not a threshold: at LIA <= 0 the slope is steeper than the
#: look ray and returns from near and far ground arrive in the wrong order, so
#: the pixel is a superposition of several places at once.
LAYOVER_LIA_DEG = 0.0

#: Margin in degrees held back from both geometric limits.
#:
#: A 30 m DEM does not resolve the true slope of a gorge wall, so a pixel
#: computed at LIA = 88 degrees may genuinely be in shadow. The margin widens
#: both exclusions rather than sitting exactly on the definition.
#:
#: TODO: UNVETTED — 5 degrees is chosen against Copernicus GLO-30's stated ~4 m
#: vertical accuracy, which at 30 m posting is several degrees of slope error on
#: rough terrain. Small (2011) does not prescribe a margin, because it works
#: from the illuminated-area integral rather than from a per-pixel angle test.
#: docs/VERIFICATION_LOG.md row 30.
GEOMETRY_MARGIN_DEG = 5.0

#: Below this fraction of geometrically valid pixels, a window is refused
#: outright rather than thresholded on what survives.
#:
#: The point of the mask is to remove pixels whose darkness is geometric. If it
#: removes most of the window, the remainder is a biased sample of the terrain —
#: valley floors and sensor-facing slopes only — and a threshold derived from it
#: does not describe the scene it will be applied to.
#:
#: TODO: UNVETTED — 0.35 is a working value chosen so that a gorge whose walls
#: are mostly disqualified refuses, while a plain (essentially all valid) and a
#: moderately incised valley both pass. Not from a publication.
#: docs/VERIFICATION_LOG.md row 30.
MIN_VALID_GEOMETRY_FRACTION = 0.35

#: Nominal platform heading in compass degrees, used only when a scene does not
#: carry ``platform_heading``.
#:
#: Sentinel-1 flies a near-polar sun-synchronous orbit at 98.18 degrees
#: inclination, which puts the ground-track heading within a couple of degrees
#: of these values everywhere outside the polar circles. ESA Sentinel-1 Product
#: Definition; orbit inclination is a published mission parameter, not a fit.
NOMINAL_HEADING_DEG = {"ASCENDING": 348.0, "DESCENDING": 192.0}

#: Sentinel-1 is right-looking: the antenna points 90 degrees clockwise of the
#: flight direction. The azimuth FROM a target TOWARD the sensor is therefore
#: the heading minus 90 degrees. Mission geometry, not a coefficient.
RIGHT_LOOKING_OFFSET_DEG = -90.0

#: Copernicus GLO-30 inside Earth Engine. Same product as the offline DEM cache,
#: so the two halves of this module see the same terrain.
#:
#: EARTH ENGINE MARKS THIS DEPRECATED in favour of COPERNICUS/DEM/GLO30_2024_1,
#: and it is deliberately NOT changed. This project's DEM provenance is GLO-30
#: throughout — `jalraksha/dem.py` fetches it from the public AWS COGs, the
#: solver runs on that raster, and `terrain/dem_update.py` writes deltas back
#: onto it. Pointing the geometry mask at the 2024 release would compute shadow
#: and layover from a different DEM epoch than the terrain being modelled, and
#: the offline half of this module (which reads the cached raster) would then
#: disagree with the live half about which pixels are usable. That is precisely
#: the drift the shared constants exist to prevent.
#:
#: Migrating means migrating the whole DEM path together, cache included, not
#: this one string. Until then the deprecation warning is expected output.
GLO30_COLLECTION = "COPERNICUS/DEM/GLO30"


class GeometryUnavailableError(RuntimeError):
    """The imaging geometry needed to compute a local incidence angle is absent."""


def look_azimuth_from_heading(platform_heading_deg: float) -> float:
    """
    Ground azimuth from a target toward the sensor, compass degrees.

    Args:
        platform_heading_deg: Ground-track heading of the platform, compass
            degrees clockwise from north.

    Returns:
        Azimuth in [0, 360) pointing from the illuminated ground back toward the
        sensor. For Sentinel-1's right-looking geometry this is the heading less
        90 degrees: ascending (348) gives 258 (WSW), descending (192) gives 102
        (ESE).
    """
    return float((platform_heading_deg + RIGHT_LOOKING_OFFSET_DEG) % 360.0)


def nominal_look_azimuth(pass_direction: str) -> float:
    """
    Look azimuth from an orbit pass direction, when the scene carries no heading.

    Args:
        pass_direction: "ASCENDING" or "DESCENDING", case-insensitive.

    Raises:
        GeometryUnavailableError: on anything else. Guessing a heading would put
            a systematic error into every local incidence angle downstream, and
            the shadow mask derived from it would exclude the wrong slopes.
    """
    key = str(pass_direction or "").strip().upper()
    if key not in NOMINAL_HEADING_DEG:
        raise GeometryUnavailableError(
            f"Cannot determine the radar look direction: the scene reports pass "
            f"direction {pass_direction!r}, which is neither ASCENDING nor "
            f"DESCENDING, and carries no platform_heading. Without the look "
            f"azimuth every local incidence angle would be wrong by a fixed "
            f"rotation and the shadow mask would exclude the wrong slopes."
        )
    return look_azimuth_from_heading(NOMINAL_HEADING_DEG[key])


def slope_and_aspect(
    bed_elevation: np.ndarray, cell_m: float
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Terrain slope and downslope azimuth from a north-up elevation grid.

    Args:
        bed_elevation: 2D elevation array, metres, rows increasing NORTHWARD
            (the solver's south-up convention, matching Grid.cell_centres_y).
        cell_m: Cell size in metres. Metric CRS only — this is meaningless on
            degrees (CLAUDE.md).

    Returns:
        (slope_deg, aspect_deg). Aspect is the compass azimuth the slope faces,
        i.e. the direction of steepest DESCENT, in [0, 360).
    """
    bed = np.asarray(bed_elevation, dtype=np.float64)
    if bed.ndim != 2:
        raise ValueError(f"bed_elevation must be 2D, got shape {bed.shape}")
    if not np.isfinite(cell_m) or cell_m <= 0:
        raise ValueError(f"cell_m must be a positive length in metres, got {cell_m}")

    # Rows increase northward, so d/drow is the northward derivative directly.
    d_north, d_east = np.gradient(bed, cell_m)

    slope_deg = np.degrees(np.arctan(np.hypot(d_east, d_north)))

    # Downslope azimuth: the direction water would run, compass-clockwise from
    # north. The descent vector is -(d_east, d_north), and atan2(east, north)
    # gives compass rather than mathematical convention.
    aspect_deg = np.degrees(np.arctan2(-d_east, -d_north)) % 360.0

    return slope_deg, aspect_deg


def local_incidence_angle(
    bed_elevation: np.ndarray,
    cell_m: float,
    look_azimuth_deg: float,
    incidence_deg,
) -> np.ndarray:
    """
    Local incidence angle over terrain, degrees.

    The angle between the radar ray and the local surface normal, as opposed to
    the ellipsoidal incidence angle the product reports, which assumes a flat
    Earth. On a slope facing the sensor it is smaller than the ellipsoidal
    angle; on a slope facing away it is larger, reaching 90 degrees at shadow.

    Args:
        bed_elevation: 2D elevation array in metres, rows increasing northward.
        cell_m: Cell size in metres.
        look_azimuth_deg: Ground azimuth from target toward sensor, compass
            degrees. See ``look_azimuth_from_heading``.
        incidence_deg: Ellipsoidal incidence angle, degrees. Scalar, or a 2D
            array matching ``bed_elevation`` when the scene's own ``angle`` band
            is available (it varies ~29-46 degrees across an IW swath).

    Returns:
        2D array of local incidence angles in degrees, in [0, 180]. This is the
        UNSIGNED angle between the ray and the surface normal, which is what
        arccos gives and what the radiometric literature means by LIA. It cannot
        by itself distinguish a slope facing the sensor from one facing away —
        both give the same magnitude — so shadow and layover are classified from
        ``range_slope`` instead. See ``geometry_validity_mask``.
    """
    slope_deg, aspect_deg = slope_and_aspect(bed_elevation, cell_m)

    theta_deg = np.broadcast_to(
        np.asarray(incidence_deg, dtype=np.float64), slope_deg.shape
    ).astype(np.float64)

    theta = np.radians(theta_deg)
    slope = np.radians(slope_deg)
    # Angle between the look direction and the downslope direction. cos() makes
    # the sign of the difference irrelevant, so no wrapping is needed.
    delta = np.radians(look_azimuth_deg - aspect_deg)

    cos_lia = np.cos(slope) * np.cos(theta) + np.sin(slope) * np.sin(theta) * np.cos(delta)

    return np.degrees(np.arccos(np.clip(cos_lia, -1.0, 1.0)))


def range_slope(
    bed_elevation: np.ndarray, cell_m: float, look_azimuth_deg: float
) -> np.ndarray:
    """
    Terrain slope projected into the range plane, SIGNED, degrees.

    Positive where the ground tilts toward the sensor, negative where it tilts
    away, zero for a slope purely across-track. This is the quantity that
    decides shadow and layover, and the reason ``local_incidence_angle`` cannot:
    arccos is even, so a 50-degree slope facing the sensor at a 39-degree
    incidence angle and one facing away at the mirrored geometry both come back
    as the same magnitude. The sign is exactly the information being asked for.

        alpha_r = atan( tan(slope) * cos(phi_look - phi_aspect) )

    With it, the signed local incidence angle in the range plane is
    ``theta - alpha_r``: layover at or below 0 (the slope has out-run the look
    ray), shadow at or above 90 (the ground has turned past grazing).
    """
    slope_deg, aspect_deg = slope_and_aspect(bed_elevation, cell_m)
    delta = np.radians(look_azimuth_deg - aspect_deg)
    return np.degrees(
        np.arctan(np.tan(np.radians(slope_deg)) * np.cos(delta))
    )


def geometry_validity_mask(
    bed_elevation: np.ndarray,
    cell_m: float,
    look_azimuth_deg: float,
    incidence_deg,
    margin_deg: float = GEOMETRY_MARGIN_DEG,
) -> Dict[str, object]:
    """
    Which pixels carry usable backscatter, and which are shadow or layover.

    This is the gate row 29 asks for. A pixel excluded here is dark (or bright)
    for a geometric reason, and including it in a histogram is what produced a
    63%-water mask over the Baige gorge.

    Args:
        bed_elevation: 2D elevation array, metres, rows increasing northward.
        cell_m: Cell size, metres.
        look_azimuth_deg: Ground azimuth from target toward sensor.
        incidence_deg: Ellipsoidal incidence angle, scalar or 2D array.
        margin_deg: Degrees held back from both geometric limits.

    Returns:
        Dict with ``valid`` (2D bool, True where backscatter is interpretable),
        ``shadow``, ``layover``, the ``local_incidence_deg`` field itself, the
        ``signed_incidence_deg`` the classes are decided from, the three
        fractions, and ``passes_geometry`` — whether enough of the window
        survives to derive a threshold from.
    """
    lia = local_incidence_angle(bed_elevation, cell_m, look_azimuth_deg, incidence_deg)
    alpha_r = range_slope(bed_elevation, cell_m, look_azimuth_deg)
    theta_deg = np.broadcast_to(
        np.asarray(incidence_deg, dtype=np.float64), alpha_r.shape
    ).astype(np.float64)

    # The SIGNED angle in the range plane. Shadow and layover are read from this
    # rather than from the arccos magnitude, which cannot tell a sensor-facing
    # slope from an averted one.
    signed = theta_deg - alpha_r

    # Two shadow conditions, both real. The range-plane one catches ground that
    # has turned away past grazing; the 3D one catches a face lying edge-on to
    # the look direction, which returns nothing either and has a range slope
    # near zero.
    shadow = (signed >= (SHADOW_LIA_DEG - margin_deg)) | (
        lia >= (SHADOW_LIA_DEG - margin_deg)
    )
    layover = signed <= (LAYOVER_LIA_DEG + margin_deg)
    valid = ~(shadow | layover)

    total = float(lia.size)
    valid_fraction = float(valid.sum()) / total if total else 0.0

    return {
        "valid": valid,
        "shadow": shadow,
        "layover": layover,
        "local_incidence_deg": lia,
        "signed_incidence_deg": signed,
        "range_slope_deg": alpha_r,
        "valid_fraction": valid_fraction,
        "shadow_fraction": float(shadow.sum()) / total if total else 0.0,
        "layover_fraction": float(layover.sum()) / total if total else 0.0,
        "look_azimuth_deg": float(look_azimuth_deg),
        "margin_deg": float(margin_deg),
        "passes_geometry": bool(valid_fraction >= MIN_VALID_GEOMETRY_FRACTION),
        "method": "local_incidence_angle_geometry_mask",
    }


def describe_refusal(geometry: Dict[str, object], reach: str) -> str:
    """The sentence to raise with when a window fails ``passes_geometry``."""
    return (
        f"Only {geometry['valid_fraction']:.0%} of the {reach} window has "
        f"interpretable radar geometry — {geometry['shadow_fraction']:.0%} is in "
        f"radar shadow and {geometry['layover_fraction']:.0%} in layover at a "
        f"look azimuth of {geometry['look_azimuth_deg']:.0f} degrees — below the "
        f"{MIN_VALID_GEOMETRY_FRACTION:.0%} required. A threshold derived from "
        f"the remainder would describe valley floors and sensor-facing slopes "
        f"only, then be applied to the whole scene. This is the terrain limit "
        f"recorded in docs/VERIFICATION_LOG.md row 29, not a transient failure: "
        f"a different orbit pass over the same reach may have usable geometry, "
        f"and the manual barrier path needs no scene at all."
    )


def scene_look_azimuth(scene) -> Tuple[float, str]:
    """
    Look azimuth for an Earth Engine Sentinel-1 image, and where it came from.

    Prefers the scene's own ``platform_heading`` and falls back to the nominal
    heading for its pass direction. Which one was used is returned alongside,
    because a nominal heading is good to a couple of degrees and a measured one
    is exact, and a reader of the provenance should be able to tell them apart.

    Raises:
        GeometryUnavailableError: if neither is available.
    """
    properties = scene.getInfo().get("properties", {}) if hasattr(scene, "getInfo") else {}

    heading = properties.get("platform_heading")
    if heading is not None and np.isfinite(float(heading)):
        # Sentinel-1 reports heading in (-180, 180]; compass wants [0, 360).
        return look_azimuth_from_heading(float(heading) % 360.0), "platform_heading"

    pass_direction = properties.get("orbitProperties_pass")
    return nominal_look_azimuth(pass_direction), "nominal_from_orbit_pass"


def earth_engine_validity_mask(
    scene,
    region,
    scale_m: float,
    margin_deg: float = GEOMETRY_MARGIN_DEG,
) -> Dict[str, object]:
    """
    The server-side twin of ``geometry_validity_mask``, over Copernicus GLO-30.

    Same formula and the same module constants as the offline half, evaluated
    inside Earth Engine so the DEM never has to be downloaded. Importing an
    Earth Engine asset does not cross the package's layering boundary — this is
    another EE image, not a call into ``jalraksha.terrain``.

    Args:
        scene: An ``ee.Image`` from COPERNICUS/S1_GRD, carrying the ``angle``
            band and its orbit metadata.
        region: An ``ee.Geometry`` bounding the window.
        scale_m: Posting for the fraction reductions, metres.
        margin_deg: Degrees held back from both geometric limits.

    Returns:
        Dict with ``valid`` (an ``ee.Image`` mask, 1 where interpretable), the
        measured fractions, the look azimuth and its source, and
        ``passes_geometry``.
    """
    import ee

    look_azimuth_deg, azimuth_source = scene_look_azimuth(scene)

    # GLO30 is an ImageCollection of tiles; mosaic before deriving terrain, or
    # the slope of a tile edge is computed against nothing.
    #
    # setDefaultProjection IS LOAD-BEARING, and omitting it makes this whole
    # module a silent no-op. `mosaic()` returns an image whose projection is
    # EPSG:4326 with the identity transform — ONE DEGREE per pixel, nominal
    # scale 111,319 m — and `ee.Algorithms.Terrain` computes slope in the
    # input's own projection. Over the Baige gorge that measured slope
    # mean 0.000 deg, max 0.000 deg, so nothing was ever classified as shadow or
    # layover and `valid_fraction` came back as exactly 1.0000. Declaring
    # GLO-30's native 30 m posting gives mean 30.8 deg, max 66.0 deg over the
    # same window, which is what a Himalayan gorge actually is.
    #
    # setDefaultProjection rather than reproject: it declares the projection the
    # terrain derivatives are computed in without forcing a resample of every
    # downstream operation onto a fixed grid. Both give the same slopes here
    # (30.8 vs 31.1 deg mean); this one is cheaper.
    dem = (
        ee.ImageCollection(GLO30_COLLECTION).select("DEM").mosaic()
        .setDefaultProjection(crs="EPSG:4326", scale=30)
    )
    terrain = ee.Algorithms.Terrain(dem)
    slope = terrain.select("slope")           # degrees
    aspect = terrain.select("aspect")         # degrees, downslope, compass

    # The scene's own per-pixel ellipsoidal incidence angle, which varies from
    # about 29 to 46 degrees across an IW swath. Using the swath mean instead
    # would misplace shadow by several degrees at both edges.
    theta = scene.select("angle")

    to_rad = np.pi / 180.0
    slope_rad = slope.multiply(to_rad)
    theta_rad = theta.multiply(to_rad)
    # cos() of the azimuth difference, so its sign does not matter and no
    # wrapping into (-180, 180] is needed.
    cos_delta = aspect.subtract(look_azimuth_deg).multiply(to_rad).cos()

    cos_lia = (
        slope_rad.cos().multiply(theta_rad.cos())
        .add(slope_rad.sin().multiply(theta_rad.sin()).multiply(cos_delta))
    )
    lia = cos_lia.clamp(-1.0, 1.0).acos().multiply(180.0 / np.pi).rename("lia")

    # SIGNED range-plane geometry, the same as the offline half. acos is even,
    # so the magnitude above cannot tell a sensor-facing slope from an averted
    # one, and that sign is precisely what separates layover from shadow.
    alpha_r = slope_rad.tan().multiply(cos_delta).atan().multiply(180.0 / np.pi)
    signed = theta.subtract(alpha_r)

    shadow = signed.gte(SHADOW_LIA_DEG - margin_deg).Or(
        lia.gte(SHADOW_LIA_DEG - margin_deg)
    )
    layover = signed.lte(LAYOVER_LIA_DEG + margin_deg)
    valid = shadow.Or(layover).Not().rename("valid_geometry")

    fractions = (
        ee.Image.cat([
            valid.rename("valid"),
            shadow.rename("shadow"),
            layover.rename("layover"),
        ])
        .toFloat()
        .reduceRegion(
            reducer=ee.Reducer.mean(), geometry=region, scale=scale_m,
            maxPixels=1e9, bestEffort=True,
        )
        .getInfo()
    ) or {}

    valid_fraction = float(fractions.get("valid") or 0.0)

    return {
        "valid": valid,
        "local_incidence_deg": lia,
        "valid_fraction": valid_fraction,
        "shadow_fraction": float(fractions.get("shadow") or 0.0),
        "layover_fraction": float(fractions.get("layover") or 0.0),
        "look_azimuth_deg": look_azimuth_deg,
        "look_azimuth_source": azimuth_source,
        "margin_deg": float(margin_deg),
        "dem_for_geometry": GLO30_COLLECTION,
        "passes_geometry": bool(valid_fraction >= MIN_VALID_GEOMETRY_FRACTION),
        "method": "local_incidence_angle_geometry_mask",
    }


def geometry_provenance(geometry: Optional[Dict[str, object]]) -> Dict[str, object]:
    """
    The reportable subset of a geometry result — no images, only measurements.

    Kept separate so a manifest written to disk cannot accidentally carry an
    ``ee.Image``, and so the same keys appear whether the geometry came from the
    offline or the Earth Engine half.
    """
    if not geometry:
        return {"terrain_correction": "none"}
    return {
        "terrain_correction": geometry.get("method"),
        "terrain_correction_reference": "Small 2011, IEEE TGRS 49(10):3081-3093 (geometric half only; not radiometric flattening)",
        "geometry_valid_fraction": geometry.get("valid_fraction"),
        "geometry_shadow_fraction": geometry.get("shadow_fraction"),
        "geometry_layover_fraction": geometry.get("layover_fraction"),
        "look_azimuth_deg": geometry.get("look_azimuth_deg"),
        "look_azimuth_source": geometry.get("look_azimuth_source", "offline_caller_supplied"),
        "geometry_margin_deg": geometry.get("margin_deg"),
        "dem_for_geometry": geometry.get("dem_for_geometry"),
    }
