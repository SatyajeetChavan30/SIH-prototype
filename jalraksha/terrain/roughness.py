"""
Manning's roughness coefficient assignment (Phase 2).

Maps ESA WorldCover land-cover classes onto the solver grid, so friction varies
with what is actually on the ground instead of a single number standing in for a
whole basin.

TWO DEFECTS THIS MODULE USED TO CARRY

**The class legend was shifted by one.** Every comment in the old
``MANNING_TABLE_ESA`` named the wrong class: 10 was labelled "Shrubland" (it is
Tree cover), 40 "Built area" (it is Cropland), and 50 "Bare / rock / sand" (it
is Built-up). The consequence was not cosmetic — built-up land, the most
hydraulically consequential class in a dam-break inundation and the one where
roughness is highest, was being assigned n = 0.01, the value for a smooth
concrete surface, while cropland got the urban value. The legend below is ESA's
published one and each entry names it.

**And nothing read the table anyway.** ``assign_manning_from_worldcover``
ignored its arguments and returned a uniform 0.03 field, and
``preprocess_dem(manning_table=...)`` accepted a table it never passed on. A
caller supplying a carefully built table got a constant, silently. Both are
fixed: the function below does the reprojection for real, and a table supplied
without the land-cover raster it needs now raises rather than being dropped.

WHY THIS TAKES A GRID AND NOT A SHAPE. The old signature asked for
``grid_shape``, which is exactly why it could not work: a shape says how many
cells there are and nothing about where they are, and land cover cannot be
placed on a domain without its transform and CRS. Resampling is NEAREST
NEIGHBOUR, always — these are class codes, and interpolating between "cropland"
(40) and "built-up" (50) yields 45, which is not a land cover.

References:
  - ESA WorldCover 10 m 2021 v200 Product User Manual, table 3 (class legend).
    Zanaga, D. et al. (2022), doi:10.5281/zenodo.7254221. CC BY 4.0 — approved
    for redistribution under this project's licensing rules.
  - Chow, V.T. (1959) "Open-Channel Hydraulics", McGraw-Hill, Table 5-6.
  - Arcement, G.J. & Schneider, V.R. (1989) "Guide for Selecting Manning's
    Roughness Coefficients for Natural Channels and Flood Plains",
    USGS Water-Supply Paper 2339.
"""

from __future__ import annotations

from typing import Dict, Optional

import numpy as np

#: Default Manning's n where a cell has no land-cover class.
#:
#: 0.03 is the conventional natural-channel value (Chow 1959, Table 5-6) and is
#: what the whole domain used before this module did anything.
DEFAULT_MANNING_N = 0.03

#: ESA WorldCover v200 class code -> Manning's n.
#:
#: The class names are ESA's published legend (Product User Manual table 3), not
#: a paraphrase: the previous version of this table named every class as the one
#: below it and assigned built-up land the roughness of bare rock.
#:
#: TODO: UNVETTED — the class codes are published and exact, but the n values
#: are working transcriptions of the Chow (1959) Table 5-6 and Arcement &
#: Schneider (1989) ranges onto a land-cover legend those sources predate. They
#: have not been checked against the primary tables, and no published crosswalk
#: from WorldCover classes to Manning's n is cited here. Every value below is a
#: mid-range pick. docs/VERIFICATION_LOG.md row 31.
MANNING_TABLE_ESA: Dict[int, float] = {
    10: 0.100,   # Tree cover — heavy stand of timber (Chow 5-6: 0.08-0.12)
    20: 0.070,   # Shrubland — medium to dense brush (Chow 5-6: 0.045-0.11)
    30: 0.035,   # Grassland — high grass (Chow 5-6: 0.030-0.050)
    40: 0.040,   # Cropland — mature field crops (Chow 5-6: 0.030-0.050)
    50: 0.080,   # Built-up — obstructed urban flow, NOT a smooth surface
    60: 0.028,   # Bare / sparse vegetation — bare soil (Chow 5-6: 0.025-0.035)
    70: 0.020,   # Snow and ice — smooth
    80: 0.030,   # Permanent water bodies — open channel (Chow 5-6: 0.025-0.033)
    90: 0.050,   # Herbaceous wetland — scattered brush, heavy weeds
    95: 0.120,   # Mangroves — dense brush and trees, submerged root structure
    100: 0.030,  # Moss and lichen
}

#: Named surfaces for callers that have a material rather than a class code.
#:
#: TODO: UNVETTED — same status as the table above. Concrete and asphalt are the
#: firmest of these (Chow 5-6 gives 0.011-0.013 for finished concrete).
MANNING_TABLE_FALLBACK: Dict[str, float] = {
    "concrete": 0.012,
    "asphalt": 0.013,
    "brick": 0.015,
    "grass": 0.035,
    "shrub": 0.070,
    "forest": 0.100,
    "urban": 0.080,
    "water": 0.030,
}


class LandCoverUnavailableError(RuntimeError):
    """
    A spatially varying Manning field was asked for and cannot be produced.

    Raised rather than falling back to a uniform field. A uniform 0.03 returned
    from a function whose name promises land-cover-derived roughness is the
    defect this module was carrying: the caller believes friction varies and it
    does not, and nothing in the output says so.
    """


def assign_manning_from_worldcover(
    worldcover_path: str,
    grid,
    manning_table: Optional[Dict[int, float]] = None,
    default_n: float = DEFAULT_MANNING_N,
) -> np.ndarray:
    """
    Manning's n field on the solver grid, from an ESA WorldCover raster.

    Args:
        worldcover_path: Path to a WorldCover GeoTIFF holding class codes.
        grid: Solver ``Grid`` — its ``nx``, ``ny``, ``dx``, ``dy``, ``x0``,
            ``y0`` and ``crs`` place the domain. A shape alone is not enough to
            put land cover anywhere.
        manning_table: Class code -> n. Defaults to ``MANNING_TABLE_ESA``.
        default_n: Value for cells whose class is absent from the table or has
            no data. Counted and reported through ``manning_field_summary``.

    Returns:
        (ny, nx) float64 array of Manning's n, south-up to match
        ``Grid.cell_centres_y``.

    Raises:
        LandCoverUnavailableError: if the raster cannot be read or does not
            overlap the domain. Both cases would otherwise produce a field of
            pure ``default_n`` that is indistinguishable from a real one.
    """
    import rasterio
    from rasterio.transform import from_origin
    from rasterio.warp import Resampling, reproject

    table = MANNING_TABLE_ESA if manning_table is None else manning_table

    # Grid.y0 is the LOWER-left corner; a raster transform is written from the
    # upper-left, hence the + ny * dy.
    destination_transform = from_origin(
        grid.x0, grid.y0 + grid.ny * grid.dy, grid.dx, grid.dy
    )
    classes = np.zeros((grid.ny, grid.nx), dtype=np.int16)

    try:
        with rasterio.open(worldcover_path) as source:
            reproject(
                source=rasterio.band(source, 1),
                destination=classes,
                src_transform=source.transform,
                src_crs=source.crs,
                src_nodata=source.nodata,
                dst_transform=destination_transform,
                dst_crs=grid.crs,
                dst_nodata=0,
                # NEAREST, not bilinear: these are class codes. Interpolating
                # between cropland (40) and built-up (50) gives 45, which is not
                # a land cover and would fall through to default_n.
                resampling=Resampling.nearest,
            )
    except LandCoverUnavailableError:
        raise
    except Exception as exc:
        raise LandCoverUnavailableError(
            f"Cannot build a Manning field from land cover at "
            f"{worldcover_path}: {type(exc).__name__}: {exc}. No uniform field "
            f"is substituted — a constant returned from this function would be "
            f"indistinguishable from a land-cover-derived one."
        ) from exc

    if not (classes > 0).any():
        raise LandCoverUnavailableError(
            f"The land cover at {worldcover_path} has no valid class over this "
            f"domain (grid origin {grid.x0:.0f}, {grid.y0:.0f} in {grid.crs}). "
            f"It most likely covers a different area. No Manning field is "
            f"produced."
        )

    # Flip to south-up rows, matching Grid.cell_centres_y() and the bed array.
    classes = np.flipud(classes)

    manning_field = np.full((grid.ny, grid.nx), float(default_n), dtype=np.float64)
    for class_code, n_value in table.items():
        manning_field[classes == int(class_code)] = float(n_value)

    return manning_field


def manning_field_summary(
    manning_field: np.ndarray, default_n: float = DEFAULT_MANNING_N
) -> Dict[str, float]:
    """
    What a Manning field actually contains, for provenance.

    A field that is 100% ``default_n`` is a uniform field wearing a
    land-cover-derived name, which is the exact failure this module used to
    ship. Reporting the fraction makes that visible instead of plausible.
    """
    field = np.asarray(manning_field, dtype=np.float64)
    at_default = np.isclose(field, default_n)
    return {
        "min_n": float(field.min()),
        "max_n": float(field.max()),
        "mean_n": float(field.mean()),
        "distinct_values": int(np.unique(np.round(field, 6)).size),
        "fraction_at_default": float(at_default.mean()),
        "is_uniform": bool(np.allclose(field, field.flat[0])),
    }


def get_manning_value(
    land_cover_class: int,
    manning_table: Optional[Dict[int, float]] = None,
) -> float:
    """
    Manning's n for a single ESA WorldCover class code.

    Args:
        land_cover_class: WorldCover v200 class code (10-100).
        manning_table: Custom table. Defaults to ``MANNING_TABLE_ESA``.

    Returns:
        Manning's n, or ``DEFAULT_MANNING_N`` for an unrecognised class.
    """
    table = MANNING_TABLE_ESA if manning_table is None else manning_table
    return table.get(land_cover_class, DEFAULT_MANNING_N)


def source_citation() -> str:
    """Citation and verification status for the values in MANNING_TABLE_ESA."""
    return """
    Manning's n by ESA WorldCover v200 class (Zanaga et al. 2022,
    doi:10.5281/zenodo.7254221, CC BY 4.0). Class codes are ESA's published
    legend; the n values are transcriptions onto it and are UNVETTED
    (docs/VERIFICATION_LOG.md row 31):

      10  Tree cover                 0.100  Chow 1959 Table 5-6, heavy timber
      20  Shrubland                  0.070  Chow 1959 Table 5-6, medium/dense brush
      30  Grassland                  0.035  Chow 1959 Table 5-6, high grass
      40  Cropland                   0.040  Chow 1959 Table 5-6, mature field crops
      50  Built-up                   0.080  Arcement & Schneider 1989, obstructed flow
      60  Bare / sparse vegetation   0.028  Chow 1959 Table 5-6, bare soil
      70  Snow and ice               0.020  smooth surface
      80  Permanent water bodies     0.030  Chow 1959 Table 5-6, natural channel
      90  Herbaceous wetland         0.050  Chow 1959 Table 5-6, brush and weeds
      95  Mangroves                  0.120  dense brush and trees
     100  Moss and lichen            0.030

    The previous version of this table named every class as the one below it in
    the legend and assigned built-up land n = 0.01, the value for a smooth
    concrete surface. No published WorldCover-to-Manning crosswalk is cited
    here; these are mid-range picks from the sources above.

    TODO: Verify against India-specific land-use data (if available from CWC).
    """
