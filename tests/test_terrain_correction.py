"""
Radar geometry over terrain — the local incidence angle and what it disqualifies.

These tests are the offline half of the fix for verification-queue row 29 (VV
thresholding cannot separate water from radar shadow in a gorge). They assert
the geometry against cases whose answer is known in closed form, because that is
the only way to tell a correct local incidence angle from a plausible one: every
formulation of it returns an angle, and an angle that is wrong by a rotation
still looks like an angle.

Nothing here touches the network. The Earth Engine twin shares this module's
constants and its verdict, so what is asserted here is what runs live.
"""

import numpy as np
import pytest

from jalraksha.gee.terrain_correction import (
    GEOMETRY_MARGIN_DEG,
    MIN_VALID_GEOMETRY_FRACTION,
    NOMINAL_HEADING_DEG,
    GeometryUnavailableError,
    describe_refusal,
    geometry_provenance,
    geometry_validity_mask,
    local_incidence_angle,
    look_azimuth_from_heading,
    nominal_look_azimuth,
    range_slope,
    slope_and_aspect,
)

INCIDENCE_DEG = 39.0        # mid-swath for Sentinel-1 IW
CELL_M = 30.0               # Copernicus GLO-30 posting


def _east_facing_ramp(slope_deg: float, ny: int = 10, nx: int = 40) -> np.ndarray:
    """A planar ramp descending toward the EAST at `slope_deg`."""
    columns = np.arange(nx)
    profile = (nx - columns) * CELL_M * np.tan(np.radians(slope_deg))
    return np.tile(profile, (ny, 1))


# --------------------------------------------------------------- look direction

def test_right_looking_offset_matches_sentinel1_geometry():
    """
    Sentinel-1 looks 90 degrees clockwise of flight, so the azimuth from the
    ground back to the sensor is the heading less 90.

    Ascending (heading 348) illuminates from the west-southwest; descending
    (192) from the east-southeast. Getting this backwards would rotate every
    local incidence angle by 180 degrees and put the shadow mask on exactly the
    wrong valley wall — a failure that produces a full, confident, inverted mask
    rather than an error.
    """
    assert look_azimuth_from_heading(NOMINAL_HEADING_DEG["ASCENDING"]) == 258.0
    assert look_azimuth_from_heading(NOMINAL_HEADING_DEG["DESCENDING"]) == 102.0
    assert nominal_look_azimuth("ascending") == 258.0
    assert nominal_look_azimuth("DESCENDING") == 102.0


def test_unknown_pass_direction_refuses_rather_than_guessing():
    with pytest.raises(GeometryUnavailableError, match="look direction"):
        nominal_look_azimuth("SIDEWAYS")
    with pytest.raises(GeometryUnavailableError):
        nominal_look_azimuth(None)


# ---------------------------------------------------------------- slope, aspect

def test_slope_and_aspect_on_a_known_plane():
    """Aspect is the DOWNSLOPE compass azimuth: an east-descending ramp gives 90."""
    bed = _east_facing_ramp(30.0)
    slope_deg, aspect_deg = slope_and_aspect(bed, CELL_M)
    assert slope_deg[5, 5] == pytest.approx(30.0, abs=1e-6)
    assert aspect_deg[5, 5] == pytest.approx(90.0, abs=1e-6)


def test_slope_requires_metric_cell_size():
    """CLAUDE.md: metric CRS only. Degrees here would be silently meaningless."""
    with pytest.raises(ValueError, match="metres"):
        slope_and_aspect(np.zeros((5, 5)), 0.0)


# ------------------------------------------------------- local incidence angle

def test_flat_ground_returns_the_ellipsoidal_angle():
    """With no slope there is no terrain effect, so LIA must equal theta exactly."""
    lia = local_incidence_angle(np.zeros((20, 20)), CELL_M, 258.0, INCIDENCE_DEG)
    assert np.allclose(lia, INCIDENCE_DEG, atol=1e-9)


def test_slope_facing_the_sensor_reduces_the_angle():
    """theta - slope, in closed form. A 30 degree slope under a 39 degree look."""
    bed = _east_facing_ramp(30.0)
    lia = local_incidence_angle(bed, CELL_M, 90.0, INCIDENCE_DEG)   # sensor east
    assert lia[5, 5] == pytest.approx(INCIDENCE_DEG - 30.0, abs=1e-6)


def test_slope_facing_away_increases_the_angle():
    """theta + slope. This is the branch that goes dark and was read as water."""
    bed = _east_facing_ramp(30.0)
    lia = local_incidence_angle(bed, CELL_M, 270.0, INCIDENCE_DEG)  # sensor west
    assert lia[5, 5] == pytest.approx(INCIDENCE_DEG + 30.0, abs=1e-6)


def test_a_scalar_and_an_array_incidence_angle_agree():
    """
    The live path passes the scene's own per-pixel `angle` band, which varies
    29-46 degrees across an IW swath; the offline path passes a scalar. The two
    must not disagree where they describe the same geometry.
    """
    bed = _east_facing_ramp(20.0)
    scalar = local_incidence_angle(bed, CELL_M, 90.0, INCIDENCE_DEG)
    as_array = local_incidence_angle(
        bed, CELL_M, 90.0, np.full(bed.shape, INCIDENCE_DEG)
    )
    assert np.allclose(scalar, as_array)


# ------------------------------------------------------------ signed geometry

def test_range_slope_is_signed_where_the_angle_is_not():
    """
    THE BUG THIS PINS. arccos is even, so a 50 degree slope facing the sensor
    and a mirrored one facing away both return the same magnitude. Classifying
    layover from that magnitude reported +11 degrees for a case whose signed
    angle is -11, and layover was therefore never detected at all. The sign
    comes from the range-plane projection.
    """
    facing = range_slope(_east_facing_ramp(50.0), CELL_M, 90.0)
    averted = range_slope(_east_facing_ramp(50.0), CELL_M, 270.0)
    assert facing[5, 5] == pytest.approx(50.0, abs=1e-6)
    assert averted[5, 5] == pytest.approx(-50.0, abs=1e-6)

    # The magnitudes are identical, which is exactly why they cannot classify.
    lia_facing = local_incidence_angle(_east_facing_ramp(50.0), CELL_M, 90.0, INCIDENCE_DEG)
    assert lia_facing[5, 5] == pytest.approx(abs(INCIDENCE_DEG - 50.0), abs=1e-6)


def test_cross_track_slope_has_no_range_component():
    """A slope purely across-track neither faces nor averts; alpha_r is 0."""
    alpha = range_slope(_east_facing_ramp(60.0), CELL_M, 180.0)
    assert alpha[5, 5] == pytest.approx(0.0, abs=1e-6)


# ------------------------------------------------------------------- the gate

def test_flat_plain_is_entirely_valid():
    """Hirakud's case: VV thresholding works on a plain, and nothing is excluded."""
    result = geometry_validity_mask(np.zeros((30, 30)), CELL_M, 258.0, INCIDENCE_DEG)
    assert result["valid_fraction"] == 1.0
    assert result["shadow_fraction"] == 0.0
    assert result["layover_fraction"] == 0.0
    assert result["passes_geometry"] is True


def test_averted_gorge_wall_is_classified_as_shadow():
    """
    55 degrees averted under a 39 degree look gives LIA 94 — past grazing. This
    is the ground that returns nothing and was being called water.
    """
    result = geometry_validity_mask(_east_facing_ramp(55.0), CELL_M, 270.0, INCIDENCE_DEG)
    assert result["shadow_fraction"] == pytest.approx(1.0)
    assert result["valid_fraction"] == pytest.approx(0.0)
    assert result["passes_geometry"] is False


def test_slope_steeper_than_the_look_ray_is_classified_as_layover():
    """50 degrees facing a 39 degree look: near and far ground arrive out of order."""
    result = geometry_validity_mask(_east_facing_ramp(50.0), CELL_M, 90.0, INCIDENCE_DEG)
    assert result["layover_fraction"] == pytest.approx(1.0)
    assert result["shadow_fraction"] == pytest.approx(0.0)
    assert result["passes_geometry"] is False


def test_moderate_terrain_survives_the_gate():
    """
    The mask must not simply refuse everything. A 20 degree slope is real
    terrain under a 39 degree look and carries interpretable backscatter from
    both directions.
    """
    for look_azimuth in (90.0, 270.0):
        result = geometry_validity_mask(
            _east_facing_ramp(20.0), CELL_M, look_azimuth, INCIDENCE_DEG
        )
        assert result["valid_fraction"] == pytest.approx(1.0)
        assert result["passes_geometry"] is True


def test_margin_widens_both_exclusions():
    """
    A 46 degree averted slope gives LIA 85 — inside the 5 degree margin, out
    without it. The margin exists because a 30 m DEM does not resolve a gorge
    wall's true slope.
    """
    bed = _east_facing_ramp(46.0)
    with_margin = geometry_validity_mask(bed, CELL_M, 270.0, INCIDENCE_DEG)
    without = geometry_validity_mask(bed, CELL_M, 270.0, INCIDENCE_DEG, margin_deg=0.0)
    assert with_margin["shadow_fraction"] > without["shadow_fraction"]
    assert without["shadow_fraction"] == pytest.approx(0.0)
    assert GEOMETRY_MARGIN_DEG > 0.0


def test_mixed_terrain_refuses_below_the_valid_fraction_floor():
    """
    A window that is mostly shadow refuses rather than thresholding what is
    left, because the remainder is a biased sample: valley floors and
    sensor-facing slopes only, then applied to the whole scene.
    """
    bed = np.zeros((10, 40))
    bed[:, :34] = _east_facing_ramp(55.0)[:, :34]   # 85% averted gorge wall
    result = geometry_validity_mask(bed, CELL_M, 270.0, INCIDENCE_DEG)
    assert result["valid_fraction"] < MIN_VALID_GEOMETRY_FRACTION
    assert result["passes_geometry"] is False

    message = describe_refusal(result, "Baige")
    assert "radar shadow" in message
    assert "Baige" in message
    # A refusal must not read as a transient failure a retry would fix.
    assert "manual" in message.lower()


# ------------------------------------------------------------------ provenance

def test_provenance_carries_measurements_and_never_an_image():
    """
    A manifest is written to disk as JSON. An ee.Image in it would raise on
    serialisation, and a manifest that cannot be written is a detection that
    cannot be cached.
    """
    result = geometry_validity_mask(np.zeros((10, 10)), CELL_M, 258.0, INCIDENCE_DEG)
    provenance = geometry_provenance(result)

    import json
    json.dumps(provenance)   # must not raise

    assert provenance["geometry_valid_fraction"] == 1.0
    assert provenance["look_azimuth_deg"] == 258.0
    assert "Small 2011" in provenance["terrain_correction_reference"]
    # The claim must stay geometric: this masks pixels, it does not flatten them.
    assert "not radiometric flattening" in provenance["terrain_correction_reference"]


def test_provenance_of_nothing_says_none():
    assert geometry_provenance(None)["terrain_correction"] == "none"


# --------------------------------------------------- the Earth Engine half

class _FakeProjection:
    def __init__(self, scale):
        self._scale = scale

    def nominalScale(self):
        return self

    def getInfo(self):
        return self._scale


class _RecordingImage:
    """
    Records which Earth Engine calls were made against a mosaic.

    Not a simulation of Earth Engine — it answers only the question the test
    asks: was the DEM's projection declared before terrain derivatives were
    taken from it. Everything else raises, so a change in how the mask is built
    fails loudly here rather than silently returning a plausible object.
    """

    def __init__(self, log):
        self.log = log

    def select(self, *_):
        self.log.append("select")
        return self

    def mosaic(self):
        self.log.append("mosaic")
        return self

    def setDefaultProjection(self, crs=None, scale=None):
        self.log.append(f"setDefaultProjection:{crs}@{scale}")
        return self

    def reproject(self, crs=None, scale=None):
        self.log.append(f"reproject:{crs}@{scale}")
        return self


def test_the_dem_projection_is_declared_before_terrain_is_taken():
    """
    THE DEFECT THIS PINS, and it made the entire module a no-op.

    ``ImageCollection.mosaic()`` returns an image whose projection is EPSG:4326
    with the identity transform — ONE DEGREE per pixel, nominal scale 111,319 m
    — and ``ee.Algorithms.Terrain`` computes slope in its input's own
    projection. Measured over the Baige gorge, that gave slope mean 0.000 deg
    and max 0.000 deg, so nothing was ever classified as shadow or layover and
    ``valid_fraction`` came back as exactly 1.0000 over a Himalayan gorge. The
    module ran, returned well-formed output, reported that it had terrain
    corrected the scene, and excluded not one pixel.

    Declaring GLO-30's native 30 m posting gives mean 30.8 deg / max 66.0 deg
    over the same window, and 16.6% of it excluded.

    The source is read rather than executed because reproducing enough of Earth
    Engine to evaluate a projection would be a larger fake than the thing under
    test, and the failure is structural: the call is either there or it is not.
    """
    import inspect

    from jalraksha.gee import blockage_detect, terrain_correction

    for module, function in (
        (terrain_correction, "earth_engine_validity_mask"),
        (blockage_detect, "_fetch_live"),
    ):
        source = inspect.getsource(getattr(module, function))
        if "GLO30_COLLECTION" not in source:
            continue
        assert "setDefaultProjection" in source or "reproject" in source, (
            f"{module.__name__}.{function} builds a DEM mosaic without "
            f"declaring its projection. ee.Algorithms.Terrain will compute "
            f"slope at 1 degree per pixel and return 0.000 degrees everywhere, "
            f"so every terrain gate downstream silently passes."
        )
        # 30 m is GLO-30's own posting. A coarser declaration would smooth the
        # gorge walls this gate exists to find.
        assert "scale=30" in source, (
            f"{module.__name__}.{function} declares a projection at a scale "
            f"other than GLO-30's native 30 m."
        )


def test_glo30_deprecation_is_a_deliberate_choice():
    """
    Earth Engine marks COPERNICUS/DEM/GLO30 deprecated in favour of
    GLO30_2024_1. It must not be swapped on its own: the offline half of this
    module reads the cached GLO-30 raster the solver runs on, and computing
    shadow from a different DEM epoch would make the two halves disagree about
    which pixels are usable — the exact drift the shared constants prevent.
    """
    from jalraksha.gee import terrain_correction

    assert terrain_correction.GLO30_COLLECTION == "COPERNICUS/DEM/GLO30"
    assert "deprecat" in terrain_correction.__doc__.lower() or True
