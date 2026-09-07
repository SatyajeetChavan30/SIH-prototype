"""
Grid-aligned Earth Engine raster download (Phase 9).

Every raster this project pulls from Earth Engine has to land on the SOLVER's
own grid — same metric CRS, same cell size, same origin — because it is about
to be multiplied cell-by-cell against a depth field. Getting that right takes
four specific decisions, and each one of them fails quietly when it is wrong:

  1. CLIP BEFORE reduceResolution. Aggregating an unclipped global image makes
     Earth Engine try to load the whole planet at the source posting, and the
     request dies with "Number of pixels requested from Image.load exceeds the
     maximum allowed (2^31)".
  2. crsTransform + dimensions, NOT region + scale. The latter returns a grid
     one cell larger with its own origin (241x241 starting at 197500 rather
     than 240x240 at 197736), which puts the fetched raster half a cell off the
     depth raster it is about to be intersected with.
  3. AN EXTENSIVE QUANTITY MUST BE RESCALED BY THE CELL-AREA RATIO. See below —
     this one shipped wrong for months.
  4. REFUSE a raster whose shape is not exactly (ny, nx). A misaligned raster
     that is merely close still describes different ground.

DECISION 3, AT LENGTH, BECAUSE IT WAS WRONG AND LOOKED RIGHT.
``reduceResolution(ee.Reducer.sum())`` does NOT sum the source cells falling
inside an output cell. Earth Engine WEIGHTS each contributing pixel by the
fraction of the OUTPUT pixel it covers, and those weights sum to one — so a
weighted sum is arithmetically a MEAN, and an extensive quantity aggregated
that way is divided by the cell-count ratio. Measured over a 480x376 domain at
500 m on 100 m GHSL: the module that documented this exact hazard and switched
to ``sum()`` to avoid it returned 741,659 people where the native-resolution
total is 18,543,954 — short by a factor of 25.003, which is (500/100)^2.

``ee.Reducer.sum().unweighted()`` does not fix it either: it counts every
touched source pixel in full and overshoots by 1.49x on the same domain.

What is correct, and what this module does, is to stop treating a per-cell
count as something that can be resampled at all. A count per source cell is
converted to a DENSITY per m2 (dividing by ``ee.Image.pixelArea()`` declared in
the source projection), aggregated as the intensive quantity it now is, and
multiplied back by the OUTPUT cell area. That is exact whatever the source
posting is, and it does not need the source resolution hardcoded anywhere.
Measured against the native-resolution totals: population 1.0055, built-up
surface 1.0059 — the residual is clip-boundary handling, identical for both
products, not a scale error.

So callers declare what their band MEANS, not which reducer to use:

  * ``extensive=True``  — the value is a quantity PER SOURCE CELL: people,
    built-up m2, dwellings. Rescaled as above.
  * ``extensive=False`` — the value is INTENSIVE: a fraction, a density, a
    class share, an angle. Plain area-weighted mean, which is already right.

WHY THIS IS A SHALLOW SHARED MODULE. CLAUDE.md's Architecture Rule 1 warns
against shallow helpers, and this one is deliberately an exception. The
alternative is two — soon three — copies of the four decisions above, and this
repository's own precedent (``gauge_rows_from_result``, ``flatness_verdict()``)
is that a duplicated correctness-bearing routine eventually disagrees with
itself. Decision 3 is the proof: it was wrong in the one copy that existed, and
a second copy would have been wrong in a different way.

This module must not import any other ``floodview.gee`` module: they import it.

References:
  - Gorelick, N. et al. (2017) "Google Earth Engine", RSE 202:18-27.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Sequence, Tuple

import numpy as np

#: Source pixels allowed to contribute to one output pixel. Earth Engine's own
#: ceiling is 65535 and its default is 64 — far too low here, where a 10 m
#: WorldCover source on a 500 m solver grid needs 2,500 and fails the request
#: with a bare HTTP 400 rather than a message that says so.
MAX_SOURCE_PIXELS_PER_CELL = 65535


class GridFetchError(RuntimeError):
    """
    A grid-aligned Earth Engine download could not be produced or trusted.

    Deliberately neutral: this module knows nothing about what the raster
    means. Callers translate it into their own domain refusal
    (``PopulationUnavailableError``, ``BuiltUpUnavailableError``,
    ``LandCoverUnavailableError``) so that the three-states-and-no-fourth
    contract stays with the module that owns the data product.
    """


def grid_region(grid_dict: Dict, crs_epsg: int):
    """
    The solver domain as an Earth Engine rectangle in the solver's own CRS.

    Separate from :func:`fetch_image_on_grid` because a caller often needs the
    region BEFORE it has an image — to filter a collection by intersection, or
    to derive a threshold from the domain rather than the globe.
    """
    import ee

    from floodview.export.georef import grid_affine

    ny = int(grid_dict["ny"])
    nx = int(grid_dict["nx"])
    affine = grid_affine(grid_dict)
    return ee.Geometry.Rectangle(
        [affine.c, affine.f + affine.e * ny, affine.c + affine.a * nx, affine.f],
        proj=ee.Projection(f"EPSG:{crs_epsg}"), geodesic=False,
    )


def fetch_image_on_grid(
    image,
    bands: Sequence[str],
    grid_dict: Dict,
    crs_epsg: int,
    destination,
    extensive: bool,
    stage_scale_m: float | None = None,
    timeout_s: int = 300,
) -> Tuple[np.ndarray, Dict]:
    """
    Download an Earth Engine image onto the solver grid, one band per plane.

    Args:
        image: An ``ee.Image``. Band selection happens here, so pass the whole
            image and name the bands you want.
        bands: Band names, fetched in ONE request so that they cannot land on
            different grids and one shape check covers all of them. Every band
            in a single call must have the same extensive/intensive character.
        grid_dict: {"nx","ny","dx","dy","x0","y0"} from the run's Grid.
        crs_epsg: The run's metric EPSG code.
        destination: Path for the downloaded GeoTIFF.
        extensive: True when the band value is a quantity PER SOURCE CELL
            (people, built-up m2); False when it is a fraction or density. No
            default — getting this wrong is a silent factor-of-N error, so the
            caller has to say which it is. See the module docstring.
        stage_scale_m: Intermediate posting, metres. A source far finer than
            the solver grid cannot be aggregated in one hop: Earth Engine caps
            the source pixels per output pixel (10 m WorldCover onto a 500 m
            grid needs 3,081 against a default of 1,024), and raising that cap
            instead trips the other limit — "Reprojection output too large
            (27412x20470 pixels)" — because the whole domain then has to be
            materialised at 10 m. Staging through a middle scale keeps both
            ratios small. Leave None whenever the source is within about 30x of
            the grid, which covers every 100 m GHSL product here.
        timeout_s: HTTP timeout for the download.

    Returns:
        (stack, meta) where ``stack`` is [len(bands), ny, nx] float32 in SOLVER
        row order (row 0 south) with NaN/inf zeroed, and ``meta`` carries
        ``geotiff_path``, ``crs_epsg`` as read back from the file, and
        ``aggregation``.

    Raises:
        GridFetchError: when the download does not come back on the requested
            grid, or does not carry every requested band.
    """
    import ee
    import rasterio
    import requests

    from floodview.export.georef import grid_affine, to_north_up

    bands = list(bands)
    if not bands:
        raise GridFetchError("fetch_image_on_grid was given no band names.")

    nx, ny = int(grid_dict["nx"]), int(grid_dict["ny"])
    cell_area_m2 = float(grid_dict["dx"]) * float(grid_dict["dy"])
    affine = grid_affine(grid_dict)
    # Earth Engine's crsTransform is [xScale, xShear, xTranslate,
    # yShear, yScale, yTranslate] — the same six numbers as a GDAL/Affine
    # transform in the same order.
    crs_transform = [affine.a, affine.b, affine.c, affine.d, affine.e, affine.f]

    # Decision 1: clip first. See the module docstring.
    region = grid_region(grid_dict, crs_epsg)
    selected = image.select(bands)

    if extensive:
        # Decision 3. A count per source cell becomes a density per m2, so that
        # the area-weighted mean below is the right operation on it. pixelArea
        # is given the SOURCE projection explicitly: an ee.Image with no
        # declared projection is evaluated at whatever scale the consumer asks
        # for, which here would silently be the output scale and would cancel
        # the correction it exists to make.
        selected = selected.divide(
            ee.Image.pixelArea().setDefaultProjection(selected.projection()))

    staged = selected.clip(region)
    if stage_scale_m:
        # STAGE IN THE SOURCE CRS, not the solver's. Reprojecting a 10 m source
        # into UTM at the intermediate scale still forces Earth Engine to
        # materialise the whole domain at 10 m in the new projection, and the
        # request dies with "Reprojection output too large (27424x20482
        # pixels)" — measured identically at 50, 100 and 200 m staging, which
        # is what shows the stage scale was never the problem. Coarsening
        # within the source projection first keeps that step local.
        #
        # Both hops are means over the same quantity (extensive inputs became
        # densities above), so splitting them approximates nothing: staging at
        # 100 m and at 200 m return the same cropland area to the last decimal.
        staged = (
            staged
            .reduceResolution(reducer=ee.Reducer.mean(),
                              maxPixels=MAX_SOURCE_PIXELS_PER_CELL)
            .reproject(crs=selected.projection().crs(),
                       scale=float(stage_scale_m))
        )

    aggregated = (
        staged
        .reduceResolution(reducer=ee.Reducer.mean(),
                          maxPixels=MAX_SOURCE_PIXELS_PER_CELL)
        .reproject(crs=f"EPSG:{crs_epsg}", crsTransform=crs_transform)
    )
    if extensive:
        aggregated = aggregated.multiply(cell_area_m2)

    # Decision 2: crsTransform + dimensions, never region + scale.
    url = aggregated.getDownloadURL({
        "format": "GEO_TIFF",
        "crsTransform": crs_transform,
        "dimensions": [nx, ny],
    })

    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    response = requests.get(url, timeout=timeout_s)
    response.raise_for_status()
    destination.write_bytes(response.content)

    with rasterio.open(destination) as src:
        raster = src.read()
        raster_crs = src.crs.to_epsg() if src.crs else None

    # Decision 4: refuse rather than use something merely close.
    if raster.shape[0] != len(bands):
        raise GridFetchError(
            f"Download came back with {raster.shape[0]} band(s) but "
            f"{len(bands)} were requested ({', '.join(bands)}). Refusing to "
            f"guess which band is which."
        )
    if (raster.shape[1], raster.shape[2]) != (ny, nx):
        raise GridFetchError(
            f"Download came back {(raster.shape[1], raster.shape[2])} but the "
            f"solver grid is ({ny}, {nx}). Refusing to use a misaligned grid."
        )

    planes: List[np.ndarray] = []
    for index in range(len(bands)):
        # The GeoTIFF is north-up; the solver is south-up. to_north_up is its
        # own inverse for a vertical flip, so it converts either way.
        plane = to_north_up(raster[index]).astype(np.float32)
        planes.append(np.nan_to_num(plane, nan=0.0, posinf=0.0, neginf=0.0))

    meta = {
        "geotiff_path": str(destination),
        "crs_epsg": raster_crs,
        "aggregation": (
            ("per-cell quantity converted to a density, area-weighted mean onto "
             "the solver grid, multiplied by the solver cell area"
             if extensive else
             "area-weighted mean of an intensive quantity onto the solver grid")
            + (f" (staged via {float(stage_scale_m):.0f} m)"
               if stage_scale_m else "")
        ),
    }
    return np.stack(planes, axis=0), meta


def read_cached_stack(geotiff, n_bands: int) -> np.ndarray:
    """
    Re-read a cached grid-aligned GeoTIFF in solver row order.

    The counterpart to :func:`fetch_image_on_grid`'s return value, so the live
    and cached paths cannot disagree about row order or about how non-finite
    values are handled.
    """
    import rasterio

    from floodview.export.georef import to_north_up

    with rasterio.open(geotiff) as src:
        raster = src.read()

    if raster.shape[0] < n_bands:
        raise GridFetchError(
            f"Cached raster {geotiff} has {raster.shape[0]} band(s); "
            f"{n_bands} were expected."
        )

    planes = [
        np.nan_to_num(to_north_up(raster[index]).astype(np.float32),
                      nan=0.0, posinf=0.0, neginf=0.0)
        for index in range(n_bands)
    ]
    return np.stack(planes, axis=0)
