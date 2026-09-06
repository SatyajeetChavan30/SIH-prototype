"""
Land-cover-derived Manning's n — the field, and the no-op it replaces.

``preprocess_dem(manning_table=...)`` accepted a table, passed it one level
down, and dropped it; ``assign_manning_from_worldcover`` ignored every argument
and returned a uniform 0.03. A caller who built a careful roughness table got a
constant and nothing said so. These tests assert that the field now VARIES, and
that the combination which cannot vary refuses instead of pretending.

Nothing here touches the network. The WorldCover rasters are written locally.
"""

import numpy as np
import pytest

rasterio = pytest.importorskip("rasterio")

from rasterio.transform import from_origin

from jalraksha.solver.types import Grid
from jalraksha.terrain.conditioning import _finish_domain
from jalraksha.terrain.roughness import (
    DEFAULT_MANNING_N,
    MANNING_TABLE_ESA,
    LandCoverUnavailableError,
    assign_manning_from_worldcover,
    manning_field_summary,
)

CRS = "EPSG:32643"
CELL_M = 100.0
NX = NY = 20
X0 = 500_000.0
Y0 = 3_000_000.0


@pytest.fixture
def grid() -> Grid:
    return Grid(nx=NX, ny=NY, dx=CELL_M, dy=CELL_M, x0=X0, y0=Y0, crs=CRS)


@pytest.fixture
def worldcover_raster(tmp_path, grid):
    """
    A WorldCover raster over the grid: forest west, built-up east, water in a
    band across the middle. Three classes whose Manning values are far apart, so
    a field that fails to vary is unmistakable.
    """
    classes = np.full((NY, NX), 10, dtype=np.uint8)      # 10 = Tree cover
    classes[:, NX // 2:] = 50                            # 50 = Built-up
    classes[NY // 2 - 2: NY // 2 + 2, :] = 80            # 80 = Permanent water

    path = tmp_path / "worldcover.tif"
    with rasterio.open(
        path, "w", driver="GTiff", height=NY, width=NX, count=1,
        dtype="uint8", crs=CRS, nodata=0,
        # Written from the UPPER-left corner, north-up.
        transform=from_origin(X0, Y0 + NY * CELL_M, CELL_M, CELL_M),
    ) as dst:
        dst.write(classes, 1)
    return path


# ------------------------------------------------------------- the field itself

def test_field_varies_with_land_cover(worldcover_raster, grid):
    """The whole point: three classes in, three roughness values out."""
    field = assign_manning_from_worldcover(str(worldcover_raster), grid)

    assert field.shape == (NY, NX)
    summary = manning_field_summary(field)
    assert summary["is_uniform"] is False
    assert summary["distinct_values"] == 3
    assert summary["fraction_at_default"] < 0.5

    assert set(np.unique(np.round(field, 6))) == {
        MANNING_TABLE_ESA[10], MANNING_TABLE_ESA[50], MANNING_TABLE_ESA[80],
    }


def test_classes_land_in_the_right_place(worldcover_raster, grid):
    """
    Geolocation, not just variety. A field with the right values in the wrong
    cells is the failure mode a shape-only signature could not even detect —
    which is why this function takes a Grid.

    Row 0 of the returned field is the SOUTH edge (Grid.cell_centres_y), while
    the raster is written north-up, so the water band is mirrored about the
    centre. It sits symmetrically here, so both halves check out either way.
    """
    field = assign_manning_from_worldcover(str(worldcover_raster), grid)

    # West half is forest, east half built-up, outside the water band.
    assert field[0, 2] == pytest.approx(MANNING_TABLE_ESA[10])
    assert field[0, NX - 3] == pytest.approx(MANNING_TABLE_ESA[50])
    # The central band is water across the full width.
    assert field[NY // 2, 2] == pytest.approx(MANNING_TABLE_ESA[80])
    assert field[NY // 2, NX - 3] == pytest.approx(MANNING_TABLE_ESA[80])


def test_custom_table_is_actually_used(worldcover_raster, grid):
    """A supplied table must reach the field. It previously did not."""
    field = assign_manning_from_worldcover(
        str(worldcover_raster), grid, manning_table={10: 0.222, 50: 0.333}
    )
    assert field[0, 2] == pytest.approx(0.222)
    assert field[0, NX - 3] == pytest.approx(0.333)
    # Class 80 is absent from the custom table, so it takes the default.
    assert field[NY // 2, 2] == pytest.approx(DEFAULT_MANNING_N)


def test_no_overlap_refuses_rather_than_returning_a_default_field(tmp_path, grid):
    """
    A raster somewhere else would reproject to all-nodata and yield a field of
    pure default_n — indistinguishable from a real uniform result. That is the
    Bhakra-over-a-Pune-tile failure in a different module, so it raises.
    """
    elsewhere = tmp_path / "elsewhere.tif"
    with rasterio.open(
        elsewhere, "w", driver="GTiff", height=10, width=10, count=1,
        dtype="uint8", crs=CRS, nodata=0,
        transform=from_origin(X0 + 900_000.0, Y0 + 900_000.0, CELL_M, CELL_M),
    ) as dst:
        dst.write(np.full((10, 10), 10, dtype=np.uint8), 1)

    with pytest.raises(LandCoverUnavailableError, match="no valid class"):
        assign_manning_from_worldcover(str(elsewhere), grid)


def test_unreadable_raster_refuses(tmp_path, grid):
    missing = tmp_path / "not_here.tif"
    with pytest.raises(LandCoverUnavailableError, match="Cannot build"):
        assign_manning_from_worldcover(str(missing), grid)


# --------------------------------------------------------------- the no-op gone

def test_table_without_land_cover_now_raises(grid):
    """
    THE SILENT NO-OP. preprocess_dem(manning_table=...) used to accept a table
    and discard it. A class-code table with no classes to map cannot change
    anything, so the honest response is to say so.
    """
    bed = np.zeros((NY, NX))
    with pytest.raises(ValueError, match="worldcover_path"):
        _finish_domain(grid, bed, manning_table=MANNING_TABLE_ESA)


def test_no_table_and_no_raster_still_gives_the_uniform_default(grid):
    """The old behaviour stays available — it just has to be asked for."""
    _, _, field = _finish_domain(grid, np.zeros((NY, NX)))
    assert np.allclose(field, DEFAULT_MANNING_N)
    assert manning_field_summary(field)["is_uniform"] is True


def test_finish_domain_builds_a_varying_field_from_a_raster(worldcover_raster, grid):
    _, state, field = _finish_domain(
        grid, np.zeros((NY, NX)), worldcover_path=str(worldcover_raster)
    )
    assert manning_field_summary(field)["is_uniform"] is False
    assert field.shape == state.h.shape


# ----------------------------------------------------------------- provenance

def test_summary_exposes_a_uniform_field_as_uniform(grid):
    """
    The reason this function exists: a uniform field wearing a
    land-cover-derived name is the defect, and the summary makes it visible
    rather than plausible.
    """
    summary = manning_field_summary(np.full((NY, NX), DEFAULT_MANNING_N))
    assert summary["is_uniform"] is True
    assert summary["fraction_at_default"] == 1.0
    assert summary["distinct_values"] == 1
