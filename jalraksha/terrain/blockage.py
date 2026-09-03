"""
Landslide-dam (river blockage) geometry on a DEM — Phase 2.

A landslide that dams a river is not a dam-break problem with different numbers.
The barrier does not exist in any DEM, the impounded lake has no published gross
storage, and nobody surveyed either. Everything the release model needs —
barrier volume, barrier width, lake volume, the stage-storage curve — has to be
constructed from terrain plus an observed or operator-supplied barrier geometry.
That construction is what this module does, and nothing else: it is pure
geometry on numpy arrays, with no file I/O, no network, and no knowledge of
Earth Engine, so the offline operator-supplied path has no optional dependency
at all.

WHAT THIS MODULE DELIBERATELY DOES NOT DO

1. It does not reconstruct the drowned channel beneath the pre-event water
   surface. Copernicus GLO-30 is a SURFACE model: over the pre-event river it
   samples the water, not the bed. So every volume reported here is measured
   ABOVE the pre-event water surface, and is tagged as such
   (``VOLUME_DATUM``). Inventing a bathymetry would be inventing storage.
   ``_impound_reservoir`` in the service layer only gets away with carving a bed
   because it has a *published gross storage* to carve to; a landslide dam has
   none, which is the whole reason this module exists.

2. It does not raise the bed under an observed lake to the observed water
   surface, even though a post-event surface model would show water there. Doing
   so would destroy the storage the fill is measuring: the lake occupies the
   pre-event valley, and flattening that valley to the water surface leaves
   nothing to impound. The observation is used to CALIBRATE and CHECK the
   barrier crest (see ``observed_lake_surface_elevation`` and
   ``compare_fill_to_observation``), never to overwrite the bed the storage is
   computed from. The invariant that buys: run ``stage_storage_table`` on the
   written DEM and you get the published storage back.

3. It does not decide whether a barrier is stable. ``natural_dam_indices``
   returns index VALUES; the published thresholds that turn those into a verdict
   are unvetted (see docs/VERIFICATION_LOG.md row 23), and this project flags an
   out-of-population case rather than shifting an estimate on an unverified
   number.

Row 0 of every array is the SOUTHERNMOST row, matching
``jalraksha.terrain.conditioning.load_dem_as_grid``. All lengths are metres and
all coordinates are in the grid's metric CRS; latitude/longitude is converted
once, at the boundary, in ``locate_barrier_cell``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

import numpy as np

from jalraksha.solver.types import Grid

#: Smallest barrier half-width the grid can resolve, in cells. A barrier
#: narrower than a couple of cells is a mesh artefact rather than a landform:
#: its outflow would be governed by the grid spacing instead of by the deposit.
#: Same reasoning as the three-cell floor on the Delft3D breach notch.
MIN_BARRIER_HALFWIDTH_CELLS = 2

#: How many times ``burn_barrier`` may double the half-width while trying to
#: span the valley before it gives up and raises. Eight doublings is a factor of
#: 256 — well past any plausible under-estimate of a valley width, so hitting
#: this limit means the barrier location is wrong, not merely narrow.
MAX_HALFWIDTH_GROWTH_ITERATIONS = 8

#: A lake that suddenly gains area as the level rises has found a saddle and is
#: spilling into a neighbouring catchment. Flagged when the area increment
#: exceeds this multiple of the running median increment.
#: TODO: UNVETTED — 5.0 separates a smooth valley fill from a saddle overtop in
#: the synthetic cases this module is tested against, but it is a working
#: threshold, not one taken from a publication. See docs/VERIFICATION_LOG.md.
SPILL_AREA_JUMP_FACTOR = 5.0

#: Plausible volume range for a natural (landslide/moraine) dam, cubic metres.
#: Costa, J.E. & Schuster, R.L. (1988), "The formation and failure of natural
#: dams", GSA Bulletin 100(7):1054-1068 — the surveyed population spans roughly
#: 10^6 to 10^8 m3. A burn implying 10^10 m3 of rock means the width is wrong,
#: so this is reported as a diagnostic rather than enforced as a limit.
NATURAL_DAM_VOLUME_RANGE_M3 = (1.0e6, 1.0e8)

#: What a reported lake volume is measured against. Carried into the DEM
#: provenance tags so nobody reads it as a surveyed capacity.
VOLUME_DATUM = "above pre-event water surface (Copernicus GLO-30 is a DSM)"


class BlockageError(Exception):
    """Raised when a blockage geometry cannot be trusted."""


@dataclass(frozen=True)
class BarrierResult:
    """
    A landslide barrier burned into the bed, with the evidence it holds water.

    ``downstream_leak_cells`` is the load-bearing field: a barrier that does not
    span the valley impounds nothing, and the fill quietly runs out around its
    ends instead of failing. ``burn_barrier`` refuses to return a leaking
    barrier, so a BarrierResult in hand always has this at zero.
    """

    bed_with_barrier: np.ndarray
    barrier_mask: np.ndarray
    i_barrier: int
    j_barrier: int
    crest_elevation_m: float
    crest_height_m: float
    floor_elevation_m: float
    width_m_requested: float
    width_m_final: float
    halfwidth_cells: int
    thickness_cells: int
    growth_iterations: int
    downstream_leak_cells: int
    barrier_volume_m3: float
    cells_modified: int
    max_elevation_change_m: float
    flow_direction: Tuple[float, float]
    seed_ij: Tuple[int, int]

    @property
    def volume_is_plausible_for_a_natural_dam(self) -> bool:
        low, high = NATURAL_DAM_VOLUME_RANGE_M3
        return low <= self.barrier_volume_m3 <= high


@dataclass(frozen=True)
class FillResult:
    """The impounded pool at one water level."""

    mask: np.ndarray
    level_m: float
    area_m2: float
    volume_m3: float
    n_cells: int
    n_components: int
    max_depth_m: float
    mean_depth_m: float
    downstream_leak_cells: int


@dataclass(frozen=True)
class StageStorage:
    """
    Elevation-area-capacity curve read off the DEM.

    This is a real hypsometric curve, which is more than the engineered dam-break
    path has: there, storage comes from a published gross figure and the shape is
    a power law fitted through a single point.

    ``fit_k``/``fit_b`` describe ``volume = fit_k * depth**fit_b`` and exist so
    the curve can drive the level-pool routing in Phase 3 without that phase
    having to carry the table. ``fit_residual`` says how well that power law
    actually describes this valley — a stepped Himalayan reach is not
    guaranteed to be a power law, and the residual is how you find out.
    """

    levels_m: np.ndarray
    areas_m2: np.ndarray
    volumes_m3: np.ndarray
    floor_elevation_m: float
    crest_elevation_m: float
    spill_detected_at_m: Optional[float]
    usable_crest_m: float
    volume_at_usable_crest_m3: float
    area_at_usable_crest_m2: float
    fit_k: float
    fit_b: float
    fit_residual: float
    volume_datum: str = VOLUME_DATUM

    def to_dict(self) -> Dict[str, Any]:
        """JSON-serialisable form, for the provenance sidecar."""
        return {
            "levels_m": [float(v) for v in self.levels_m],
            "areas_m2": [float(v) for v in self.areas_m2],
            "volumes_m3": [float(v) for v in self.volumes_m3],
            "floor_elevation_m": float(self.floor_elevation_m),
            "crest_elevation_m": float(self.crest_elevation_m),
            "spill_detected_at_m": (
                None if self.spill_detected_at_m is None else float(self.spill_detected_at_m)
            ),
            "usable_crest_m": float(self.usable_crest_m),
            "volume_at_usable_crest_m3": float(self.volume_at_usable_crest_m3),
            "area_at_usable_crest_m2": float(self.area_at_usable_crest_m2),
            "fit_k": float(self.fit_k),
            "fit_b": float(self.fit_b),
            "fit_residual": float(self.fit_residual),
            "volume_datum": self.volume_datum,
        }


# ── Locating the barrier ──────────────────────────────────────────────────────


def _grid_epsg(grid: Grid) -> int:
    """EPSG code of the grid's CRS, refusing rather than guessing a default."""
    crs = str(grid.crs)
    if ":" not in crs:
        raise BlockageError(
            f"Grid CRS {crs!r} is not in 'AUTHORITY:CODE' form, so the barrier "
            f"coordinates cannot be projected into the solver's grid."
        )
    try:
        return int(crs.split(":")[-1])
    except ValueError as exc:
        raise BlockageError(f"Cannot read an EPSG code from grid CRS {crs!r}.") from exc


def locate_barrier_cell(
    bed_elevation: np.ndarray,
    grid: Grid,
    barrier_lat: float,
    barrier_lon: float,
    snap_radius_cells: int = 3,
) -> Tuple[int, int, float]:
    """
    Project a barrier's latitude/longitude onto the solver grid.

    The returned cell is the LOWEST within ``snap_radius_cells`` of the projected
    point, so the barrier anchors in the thalweg rather than on a valley
    shoulder. At 200 m resolution a three-cell snap is 600 m, which is smaller
    than the uncertainty in a hand-placed or SAR-derived barrier position and
    larger than the offset that would put the axis on the wrong side of the
    channel.

    Falling outside the domain RAISES. It does not clamp to the edge: a clamped
    barrier would produce a complete, plausible-looking simulation of a flood
    starting somewhere the operator never asked for.

    Args:
        bed_elevation: (ny, nx) elevation, metres, row 0 southernmost.
        grid: The solver grid. Its CRS decides the projection, so a barrier near
            a UTM zone boundary is projected into the DOMAIN's zone.
        barrier_lat, barrier_lon: Barrier axis position, degrees.
        snap_radius_cells: Search radius for the thalweg snap. 0 disables it.

    Returns:
        (i, j, bed_elevation_at_cell) — column, row, metres.
    """
    from jalraksha.terrain.domain import latlon_to_utm

    epsg = _grid_epsg(grid)
    if 32601 <= epsg <= 32660:
        zone = epsg - 32600
    elif 32701 <= epsg <= 32760:
        zone = epsg - 32700
    else:
        raise BlockageError(
            f"Grid CRS EPSG:{epsg} is not a UTM zone. The solver operates "
            f"exclusively in a metric UTM CRS; a geographic grid would make "
            f"every length below a degree rather than a metre."
        )

    _, easting, northing = latlon_to_utm(barrier_lat, barrier_lon, utm_zone=zone)

    i = int(np.floor((easting - grid.x0) / grid.dx))
    j = int(np.floor((northing - grid.y0) / grid.dy))

    ny, nx = bed_elevation.shape
    if not (0 <= i < nx and 0 <= j < ny):
        east_max = grid.x0 + nx * grid.dx
        north_max = grid.y0 + ny * grid.dy
        raise BlockageError(
            f"Barrier at ({barrier_lat:.5f}, {barrier_lon:.5f}) projects to "
            f"E={easting:.0f} N={northing:.0f} in EPSG:{epsg}, which is cell "
            f"(i={i}, j={j}) — outside the {nx} x {ny} domain spanning "
            f"E {grid.x0:.0f}..{east_max:.0f}, N {grid.y0:.0f}..{north_max:.0f}. "
            f"Either the barrier coordinates are wrong or the domain is centred "
            f"on the wrong place; the run is not clamped to the domain edge "
            f"because that would simulate a flood from somewhere nobody asked for."
        )

    if snap_radius_cells > 0:
        i_lo, i_hi = max(0, i - snap_radius_cells), min(nx, i + snap_radius_cells + 1)
        j_lo, j_hi = max(0, j - snap_radius_cells), min(ny, j + snap_radius_cells + 1)
        window = bed_elevation[j_lo:j_hi, i_lo:i_hi]
        dj_local, di_local = np.unravel_index(int(np.argmin(window)), window.shape)
        i, j = i_lo + int(di_local), j_lo + int(dj_local)

    return i, j, float(bed_elevation[j, i])


def flow_direction(
    bed_elevation: np.ndarray,
    i: int,
    j: int,
    radius_cells: Tuple[int, int] = (5, 12),
    n_angles: int = 96,
) -> Tuple[float, float]:
    """
    Unit vector pointing downstream at (i, j), in (di, dj) cell units.

    Found by sweeping an annulus and taking the direction of the lowest cell on
    it — the way water would go at valley scale. A smoothed local gradient does
    not work and has been measured failing: on a dead-flat impounded reach the
    local gradient is noise, and a symmetric window is dominated by whatever high
    ground happens to surround the point. This is the same construction
    ``tools/paraview/reservoir.py`` uses, lifted here so the library does not
    depend on a ParaView-side script that is not on the install path.

    ``radius_cells`` is site-dependent and matters: (5, 12) is right for a narrow
    gorge, and wrong for broad terrain where at that scale it picks up local
    micro-relief instead of the valley trend.
    """
    ny, nx = bed_elevation.shape
    min_radius, max_radius = radius_cells
    best_elevation = np.inf
    best_direction: Optional[Tuple[float, float]] = None

    for radius in range(int(min_radius), int(max_radius) + 1):
        for angle in np.linspace(0.0, 2.0 * np.pi, n_angles, endpoint=False):
            cos_a, sin_a = float(np.cos(angle)), float(np.sin(angle))
            ii = int(round(i + radius * cos_a))
            jj = int(round(j + radius * sin_a))
            if 0 <= ii < nx and 0 <= jj < ny and bed_elevation[jj, ii] < best_elevation:
                best_elevation = float(bed_elevation[jj, ii])
                best_direction = (cos_a, sin_a)

    if best_direction is None:
        raise BlockageError(
            f"No valid cells in the annulus around cell (i={i}, j={j}); the "
            f"barrier is probably outside the domain."
        )
    if best_elevation >= bed_elevation[j, i]:
        raise BlockageError(
            f"Every cell within {max_radius} cells of the barrier sits at or "
            f"above it ({bed_elevation[j, i]:.1f} m). There is no downstream "
            f"direction, so the barrier location is likely wrong — widen "
            f"radius_cells for broad terrain, or check the coordinates."
        )
    return best_direction


# ── Burning the barrier ───────────────────────────────────────────────────────


def _seed_upstream(
    bed_elevation: np.ndarray,
    i: int,
    j: int,
    direction: Tuple[float, float],
    offset_cells: int,
    level_m: float,
    arc_degrees: float = 60.0,
    search_span_cells: int = 8,
) -> Tuple[int, int]:
    """
    Where to start the fill: the lowest cell in an upstream arc, below the crest.

    NOT a single point at a fixed offset along the flow vector. That was the
    first implementation and it fails in exactly the terrain this module is for.
    Measured on the Dhauliganga gorge below Tapovan: the barrier cell sits at
    1,703 m, the crest at 1,758 m, and the cell four steps up the flow vector is
    at 1,789 m — 31 m ABOVE the water it is supposed to seed. The fill then
    reports "no pool to grow from" for a barrier that is perfectly sound.

    Two things cause it. A gorge's longitudinal slope is steep enough that a few
    hundred metres upstream is tens of metres higher; and ``flow_direction``
    returns a valley-scale bearing, so stepping along it can climb a bank rather
    than follow the channel.

    Scanning an arc fixes both: the channel is the lowest thing upstream, and it
    is found rather than assumed to lie on one bearing.
    """
    di, dj = direction
    ny, nx = bed_elevation.shape
    base_angle = np.arctan2(dj, di) + np.pi  # upstream is against the flow
    half_arc = np.radians(arc_degrees) / 2.0

    best: Optional[Tuple[float, int, int]] = None
    for radius in range(offset_cells, offset_cells + search_span_cells + 1):
        for angle in np.linspace(base_angle - half_arc, base_angle + half_arc, 25):
            ii = int(round(i + radius * np.cos(angle)))
            jj = int(round(j + radius * np.sin(angle)))
            if not (0 <= ii < nx and 0 <= jj < ny):
                continue
            elevation = float(bed_elevation[jj, ii])
            if elevation > level_m:
                continue
            if best is None or elevation < best[0]:
                best = (elevation, ii, jj)

    if best is None:
        raise BlockageError(
            f"No cell within {offset_cells}-{offset_cells + search_span_cells} "
            f"cells upstream of the barrier sits below the {level_m:.1f} m crest, "
            f"so there is nothing for a pool to grow from. Either the barrier is "
            f"too short for this reach's longitudinal slope — a gorge can rise "
            f"tens of metres in a few hundred — or it is not on the channel."
        )
    return best[1], best[2]


def _leak_count(
    mask: np.ndarray, i: int, j: int, direction: Tuple[float, float], thickness_cells: int
) -> int:
    """
    Filled cells that lie downstream of the barrier.

    Signed distance along the flow direction; anything beyond the barrier's own
    thickness has got past it. A non-zero count means the pool is draining around
    the barrier's ends rather than being impounded by it.
    """
    di, dj = direction
    ny, nx = mask.shape
    jj_idx, ii_idx = np.mgrid[0:ny, 0:nx]
    along_flow = (ii_idx - i) * di + (jj_idx - j) * dj
    return int(np.count_nonzero(mask & (along_flow > thickness_cells + 1)))


def burn_barrier(
    bed_elevation: np.ndarray,
    grid: Grid,
    i_barrier: int,
    j_barrier: int,
    crest_height_m: float,
    width_m: float,
    thickness_m: Optional[float] = None,
    direction: Optional[Tuple[float, float]] = None,
    direction_search_radius_cells: Tuple[int, int] = (5, 12),
    max_growth_iterations: int = MAX_HALFWIDTH_GROWTH_ITERATIONS,
) -> BarrierResult:
    """
    Raise a landslide deposit across the valley and prove that it holds water.

    ``crest_height_m`` is measured ABOVE THE VALLEY FLOOR at the barrier cell,
    not above sea level. That conversion happens exactly once, here, so a caller
    can never accidentally pass an absolute elevation where a height was meant:
    the two differ by a thousand metres or more in the Himalaya and both look
    like plausible numbers.

    A landslide dam is only a dam if it spans the valley. A too-narrow deposit
    does not fail loudly — the fill simply runs around its ends and the model
    reports a small lake with a confident-looking volume. So the burn is
    verified: fill behind it, count cells that got downstream, and widen and
    retry while any did. Failing to span after ``max_growth_iterations``
    doublings RAISES rather than returning a leaking lake.

    The array is never mutated; the barrier is raised into a copy.

    Args:
        bed_elevation: (ny, nx) elevation, metres, row 0 southernmost.
        grid: Solver grid, for cell size.
        i_barrier, j_barrier: Barrier axis cell, from ``locate_barrier_cell``.
        crest_height_m: Deposit crest above the valley floor at that cell.
        width_m: Crest length ACROSS the valley.
        thickness_m: Deposit extent ALONG the valley. Defaults to two cells,
            which is the minimum that reads as a landform rather than a fence.
        direction: Downstream unit vector in cell units. Computed by
            ``flow_direction`` when not supplied.
        direction_search_radius_cells: Passed to ``flow_direction``.
        max_growth_iterations: Half-width doublings allowed while spanning.

    Returns:
        A BarrierResult whose ``downstream_leak_cells`` is always zero.
    """
    bed_elevation = np.asarray(bed_elevation, dtype=np.float64)
    ny, nx = bed_elevation.shape

    if crest_height_m <= 0.0:
        raise BlockageError(
            f"crest_height_m must be positive (got {crest_height_m}); a barrier "
            f"at or below the valley floor impounds nothing."
        )
    if not (0 <= i_barrier < nx and 0 <= j_barrier < ny):
        raise BlockageError(
            f"Barrier cell (i={i_barrier}, j={j_barrier}) is outside the "
            f"{nx} x {ny} domain."
        )

    cell_m = float(grid.dx)
    cell_area_m2 = float(grid.dx) * float(grid.dy)

    if direction is None:
        direction = flow_direction(
            bed_elevation, i_barrier, j_barrier, radius_cells=direction_search_radius_cells
        )
    di, dj = direction
    # The deposit runs perpendicular to the flow — that is the line a valley-
    # blocking landslide lands on.
    perp_i, perp_j = -dj, di

    if thickness_m is None:
        thickness_cells = 2
    else:
        thickness_cells = max(1, int(round(float(thickness_m) / cell_m)))

    floor_elevation_m = float(bed_elevation[j_barrier, i_barrier])
    crest_elevation_m = floor_elevation_m + float(crest_height_m)

    halfwidth_cells = max(
        MIN_BARRIER_HALFWIDTH_CELLS, int(np.ceil(float(width_m) / (2.0 * cell_m)))
    )
    seed_offset_cells = max(3, thickness_cells + 2)
    seed_ij = _seed_upstream(
        bed_elevation,
        i_barrier,
        j_barrier,
        direction,
        seed_offset_cells,
        crest_elevation_m,
    )

    growth_iterations = 0
    leak = -1
    barred = bed_elevation
    barrier_mask = np.zeros_like(bed_elevation, dtype=bool)

    while True:
        barred = bed_elevation.copy()
        for step in range(-thickness_cells, thickness_cells + 1):
            for offset in range(-halfwidth_cells, halfwidth_cells + 1):
                ii = int(round(i_barrier + step * di + offset * perp_i))
                jj = int(round(j_barrier + step * dj + offset * perp_j))
                if 0 <= ii < nx and 0 <= jj < ny:
                    barred[jj, ii] = max(barred[jj, ii], crest_elevation_m)
        barrier_mask = barred > bed_elevation

        # Fill to the crest and see whether anything got past. The barrier's own
        # cells are excluded rather than tested against a level just below the
        # crest: a freeboard would make the leak check depend on a tolerance
        # nobody chose, and the barrier is not part of the pool either way.
        probe = _fill_at_level(
            barred, grid, seed_ij, crest_elevation_m, barrier_mask=barrier_mask
        )
        leak = _leak_count(probe.mask, i_barrier, j_barrier, direction, thickness_cells)
        if leak == 0:
            break

        growth_iterations += 1
        if growth_iterations > max_growth_iterations:
            raise BlockageError(
                f"The barrier still leaks after {max_growth_iterations} widenings: "
                f"{leak} filled cells lie downstream of a deposit now "
                f"{2 * halfwidth_cells * cell_m:.0f} m across (requested "
                f"{width_m:.0f} m). A barrier that does not span the valley "
                f"impounds nothing, so no lake is reported. Check the barrier "
                f"coordinates — a deposit placed on a valley shoulder rather "
                f"than across the channel fails exactly like this."
            )
        halfwidth_cells *= 2

    delta = barred - bed_elevation
    return BarrierResult(
        bed_with_barrier=barred,
        barrier_mask=barrier_mask,
        i_barrier=int(i_barrier),
        j_barrier=int(j_barrier),
        crest_elevation_m=crest_elevation_m,
        crest_height_m=float(crest_height_m),
        floor_elevation_m=floor_elevation_m,
        width_m_requested=float(width_m),
        width_m_final=float(2 * halfwidth_cells * cell_m),
        halfwidth_cells=int(halfwidth_cells),
        thickness_cells=int(thickness_cells),
        growth_iterations=int(growth_iterations),
        downstream_leak_cells=int(leak),
        barrier_volume_m3=float(delta.sum() * cell_area_m2),
        cells_modified=int(np.count_nonzero(barrier_mask)),
        max_elevation_change_m=float(delta.max()),
        flow_direction=(float(di), float(dj)),
        seed_ij=seed_ij,
    )


# ── Filling the lake ──────────────────────────────────────────────────────────


def _fill_at_level(
    bed_with_barrier: np.ndarray,
    grid: Grid,
    seed_ij: Tuple[int, int],
    level_m: float,
    barrier_mask: Optional[np.ndarray] = None,
    strict: bool = False,
) -> FillResult:
    """Seeded connected fill to ``level_m``. Internal; see ``hypsometric_fill``."""
    from scipy.ndimage import label

    cell_area_m2 = float(grid.dx) * float(grid.dy)
    i_seed, j_seed = seed_ij

    submerged = bed_with_barrier <= level_m
    if barrier_mask is not None:
        submerged &= ~barrier_mask

    labels, n_components = label(submerged)
    pool_label = int(labels[j_seed, i_seed])
    if pool_label == 0:
        if strict:
            raise BlockageError(
                f"The fill seed at (i={i_seed}, j={j_seed}) sits at "
                f"{bed_with_barrier[j_seed, i_seed]:.1f} m, above the "
                f"{level_m:.1f} m fill level, so there is no pool to grow from."
            )
        empty = np.zeros_like(submerged, dtype=bool)
        return FillResult(
            mask=empty,
            level_m=float(level_m),
            area_m2=0.0,
            volume_m3=0.0,
            n_cells=0,
            n_components=int(n_components),
            max_depth_m=0.0,
            mean_depth_m=0.0,
            downstream_leak_cells=0,
        )

    mask = labels == pool_label
    depth = np.where(mask, level_m - bed_with_barrier, 0.0)
    np.maximum(depth, 0.0, out=depth)

    return FillResult(
        mask=mask,
        level_m=float(level_m),
        area_m2=float(mask.sum() * cell_area_m2),
        volume_m3=float(depth.sum() * cell_area_m2),
        n_cells=int(mask.sum()),
        n_components=int(n_components),
        max_depth_m=float(depth.max()),
        mean_depth_m=float(depth[mask].mean()) if mask.any() else 0.0,
        downstream_leak_cells=0,
    )


def hypsometric_fill(
    bed_with_barrier: np.ndarray,
    grid: Grid,
    seed_ij: Tuple[int, int],
    level_m: float,
    barrier_mask: Optional[np.ndarray] = None,
) -> FillResult:
    """
    The pool impounded behind the barrier at one water level.

    Connected from the seed, not thresholded globally: everything below a level
    that merely happens to be low is not a lake. Measured on the Mutha at 100 m,
    a plain ``bed <= level`` threshold seeded nowhere picked up 276 km2 of the
    Pune plain against a real reservoir of about 15.

    ``volume_m3`` is measured above the pre-event surface — see ``VOLUME_DATUM``
    and this module's docstring.

    ACCURACY. Scored against the exact capacity of a sloping V-valley (a
    closed-form prism, see tests/test_blockage.py), the cell-centred sum is
    second-order accurate in the cell size:

        60 m cells   0.523% high
        30 m cells   0.127% high
        15 m cells   0.031% high

    At the 200 m the dashboard defaults to, the discretisation is the smaller of
    the two error sources by a wide margin — GLO-30's own vertical error over a
    Himalayan reach dominates it.
    """
    return _fill_at_level(
        bed_with_barrier, grid, seed_ij, level_m, barrier_mask=barrier_mask, strict=True
    )


def _fit_power_law(depths_m: np.ndarray, volumes_m3: np.ndarray) -> Tuple[float, float, float]:
    """
    Least-squares fit of ``volume = k * depth**b`` in log space.

    Returned alongside the table rather than instead of it. Phase 3's level-pool
    routing wants a power law; a stepped valley may not be one, and
    ``fit_residual`` — RMS of log10 residuals — is how the caller finds out
    whether the approximation is costing anything here.
    """
    usable = (depths_m > 0.0) & (volumes_m3 > 0.0)
    if usable.sum() < 3:
        return 0.0, 0.0, float("inf")

    log_depth = np.log10(depths_m[usable])
    log_volume = np.log10(volumes_m3[usable])
    exponent, intercept = np.polyfit(log_depth, log_volume, 1)
    residual = float(np.sqrt(np.mean((log_volume - (exponent * log_depth + intercept)) ** 2)))
    return float(10.0**intercept), float(exponent), residual


def stage_storage_table(
    bed_with_barrier: np.ndarray,
    grid: Grid,
    seed_ij: Tuple[int, int],
    floor_elevation_m: float,
    crest_elevation_m: float,
    n_levels: int = 120,
    barrier_mask: Optional[np.ndarray] = None,
) -> StageStorage:
    """
    Sweep the fill from the valley floor to the barrier crest.

    This is the elevation-area-capacity curve the release model routes against,
    read directly off the terrain.

    LATERAL SPILL. The barrier stops the pool draining downstream, but nothing
    stops it spilling sideways over a saddle into a neighbouring catchment once
    the level is high enough. That failure is silent — the volume simply keeps
    growing — so it is detected here instead: a level whose area increment
    exceeds ``SPILL_AREA_JUMP_FACTOR`` times the running median increment has
    found a sill. The usable crest is capped there and BOTH the requested crest
    and the effective sill are reported, because the difference between them is
    the difference between a lake and a lake plus the next valley.

    Args:
        bed_with_barrier: Bed with the barrier already burned in.
        grid: Solver grid.
        seed_ij: Fill seed, upstream of the barrier.
        floor_elevation_m: Bed elevation at the barrier cell.
        crest_elevation_m: Barrier crest elevation.
        n_levels: Sweep resolution. 120 levels over a 60 m barrier is 0.5 m,
            matching GLO-30's vertical resolution; finer than that resolves the
            DEM's noise rather than the valley.
        barrier_mask: Cells the barrier raised, excluded from the pool.
    """
    if crest_elevation_m <= floor_elevation_m:
        raise BlockageError(
            f"Barrier crest ({crest_elevation_m:.1f} m) is at or below the valley "
            f"floor ({floor_elevation_m:.1f} m); there is nothing to impound."
        )

    levels = np.linspace(float(floor_elevation_m), float(crest_elevation_m), int(n_levels))
    areas = np.zeros_like(levels)
    volumes = np.zeros_like(levels)

    for index, level in enumerate(levels):
        fill = _fill_at_level(
            bed_with_barrier, grid, seed_ij, float(level), barrier_mask=barrier_mask
        )
        areas[index] = fill.area_m2
        volumes[index] = fill.volume_m3

    spill_level: Optional[float] = None
    area_increments = np.diff(areas)
    for index in range(2, len(area_increments)):
        running_median = float(np.median(area_increments[:index]))
        if running_median > 0.0 and area_increments[index] > SPILL_AREA_JUMP_FACTOR * running_median:
            spill_level = float(levels[index])
            break

    if spill_level is None:
        usable_crest = float(crest_elevation_m)
        usable_index = len(levels) - 1
    else:
        usable_crest = spill_level
        usable_index = int(np.searchsorted(levels, spill_level))
        usable_index = min(usable_index, len(levels) - 1)

    depths = levels[: usable_index + 1] - float(floor_elevation_m)
    fit_k, fit_b, fit_residual = _fit_power_law(depths, volumes[: usable_index + 1])

    return StageStorage(
        levels_m=levels,
        areas_m2=areas,
        volumes_m3=volumes,
        floor_elevation_m=float(floor_elevation_m),
        crest_elevation_m=float(crest_elevation_m),
        spill_detected_at_m=spill_level,
        usable_crest_m=usable_crest,
        volume_at_usable_crest_m3=float(volumes[usable_index]),
        area_at_usable_crest_m2=float(areas[usable_index]),
        fit_k=fit_k,
        fit_b=fit_b,
        fit_residual=fit_residual,
    )


# ── Conditioning on an observation ────────────────────────────────────────────


def observed_lake_surface_elevation(
    bed_elevation: np.ndarray,
    observed_water_mask: np.ndarray,
    statistic: str = "median",
) -> Tuple[float, Dict[str, Any]]:
    """
    Read a lake's water-surface elevation off the pre-event DEM at its shoreline.

    This is the step that makes "observation-conditioned" mean something. The
    satellite sees WHERE the water is, never how high it is; the DEM knows how
    high the ground is, but predates the lake. Sampling the stale DEM along the
    observed shoreline combines the two: the shoreline is exactly the contour the
    water surface intersects, so the ground elevation there IS the water level.

    The median is used rather than the mean because a shoreline ring inevitably
    clips a few hillside cells, and one 200 m cliff cell would drag a mean far
    more than it shifts a median.

    Returns:
        (elevation_m, diagnostics). Diagnostics carry the shoreline cell count
        and the spread, which is the honest measure of how well-defined the
        reading is: a tight spread means a real flat-water shoreline, a wide one
        means the mask edge is running up a slope and the number should not be
        trusted.
    """
    from scipy.ndimage import binary_erosion

    mask = np.asarray(observed_water_mask, dtype=bool)
    if not mask.any():
        raise BlockageError(
            "The observed water mask is empty, so no shoreline elevation can be "
            "read from it."
        )

    shoreline = mask & ~binary_erosion(mask)
    if not shoreline.any():
        shoreline = mask

    samples = np.asarray(bed_elevation, dtype=np.float64)[shoreline]
    if statistic == "median":
        elevation = float(np.median(samples))
    elif statistic == "mean":
        elevation = float(np.mean(samples))
    else:
        raise BlockageError(f"Unknown shoreline statistic {statistic!r}; use median or mean.")

    return elevation, {
        "shoreline_cells": int(shoreline.sum()),
        "shoreline_elevation_p05_m": float(np.percentile(samples, 5)),
        "shoreline_elevation_p95_m": float(np.percentile(samples, 95)),
        "shoreline_elevation_spread_m": float(samples.max() - samples.min()),
        "statistic": statistic,
    }


def compare_fill_to_observation(
    modelled_mask: np.ndarray, observed_water_mask: np.ndarray
) -> Dict[str, float]:
    """
    How well the burned barrier reproduces the lake the satellite saw.

    The intersection-over-union is the single most useful honesty number in the
    blockage path: it is the only place the constructed geometry is checked
    against something nobody constructed. A high IoU says the barrier crest and
    position are consistent with the observation; a low one says the model is
    telling a story about a different lake, and should be reported rather than
    quietly averaged away.
    """
    modelled = np.asarray(modelled_mask, dtype=bool)
    observed = np.asarray(observed_water_mask, dtype=bool)

    intersection = float(np.count_nonzero(modelled & observed))
    union = float(np.count_nonzero(modelled | observed))
    n_modelled = float(np.count_nonzero(modelled))
    n_observed = float(np.count_nonzero(observed))

    return {
        "iou": intersection / union if union > 0 else 0.0,
        "precision": intersection / n_modelled if n_modelled > 0 else 0.0,
        "recall": intersection / n_observed if n_observed > 0 else 0.0,
        "modelled_cells": int(n_modelled),
        "observed_cells": int(n_observed),
    }


# ── Stability indices ─────────────────────────────────────────────────────────


def natural_dam_indices(
    barrier_volume_m3: float,
    barrier_height_m: float,
    lake_volume_m3: float,
    catchment_area_km2: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Geometric stability indices for a landslide dam.

    For HADR the first question is "should we worry at all", and these answer it
    from geometry in milliseconds — long before anyone runs a solver. That is why
    they are worth computing even though the thresholds that turn them into a
    verdict are not yet transcribed.

    The INDEX VALUES are returned; no stable/unstable verdict is. The published
    threshold bands (Ermini & Casagli 2003 draw stability and instability
    envelopes on the DBI) are in the verification queue as row 23, and this
    project does not turn an unvetted constant into an operational judgement.

    TODO: UNVETTED — the index DEFINITIONS below follow the forms summarised in
    literature.md section 6, but neither the exact logarithm base and unit
    convention nor the threshold envelopes have been transcribed from the primary
    sources. Sources to check: Casagli & Ermini (1999), "Geomorphic analysis of
    landslide dams in the Northern Apennine"; Ermini, L. & Casagli, N. (2003),
    "Prediction of the behaviour of landslide dams using a geomorphological
    dimensionless index", Earth Surface Processes and Landforms 28(1):31-47.
    """
    indices: Dict[str, Any] = {
        "barrier_volume_m3": float(barrier_volume_m3),
        "barrier_height_m": float(barrier_height_m),
        "lake_volume_m3": float(lake_volume_m3),
        "catchment_area_km2": (
            None if catchment_area_km2 is None else float(catchment_area_km2)
        ),
        "verdict": None,
        "note": (
            "Index values only. The published stability envelopes that turn these "
            "into a stable/unstable judgement are UNVETTED (verification queue "
            "row 23) and are deliberately not applied."
        ),
    }

    # Impoundment Index: dam volume against impounded volume. Needs no catchment
    # data, so it is always computable from what this module already has.
    if lake_volume_m3 > 0.0 and barrier_volume_m3 > 0.0:
        indices["impoundment_index"] = float(np.log10(barrier_volume_m3 / lake_volume_m3))
    else:
        indices["impoundment_index"] = None

    # Blockage Index and Dimensionless Blockage Index both need the upstream
    # catchment area, which this module cannot derive: it would take a flow-
    # accumulation pass over a DEM extending well beyond the simulation domain.
    # Returned as None rather than estimated from the domain, which would be a
    # number that looks right and is wrong.
    if catchment_area_km2 and catchment_area_km2 > 0.0 and barrier_volume_m3 > 0.0:
        indices["blockage_index"] = float(
            np.log10(barrier_volume_m3 / catchment_area_km2)
        )
        if barrier_height_m > 0.0:
            indices["dimensionless_blockage_index"] = float(
                np.log10(catchment_area_km2 * barrier_height_m / barrier_volume_m3)
            )
        else:
            indices["dimensionless_blockage_index"] = None
    else:
        indices["blockage_index"] = None
        indices["dimensionless_blockage_index"] = None
        indices["catchment_note"] = (
            "Upstream catchment area was not supplied, so the Blockage Index and "
            "DBI are not computed. Deriving it would need flow accumulation over "
            "a DEM larger than the simulation domain; estimating it from the "
            "domain would be a plausible-looking wrong number."
        )

    return indices


# ── One-call construction ─────────────────────────────────────────────────────


@dataclass(frozen=True)
class BlockageGeometry:
    """Everything the release model and the DEM writer need, from one call."""

    barrier: BarrierResult
    stage_storage: StageStorage
    lake: FillResult
    observation: Dict[str, Any] = field(default_factory=dict)
    indices: Dict[str, Any] = field(default_factory=dict)

    @property
    def lake_volume_mm3(self) -> float:
        """Impounded volume in million cubic metres, the project's storage unit."""
        return self.stage_storage.volume_at_usable_crest_m3 / 1.0e6

    @property
    def lake_area_km2(self) -> float:
        return self.stage_storage.area_at_usable_crest_m2 / 1.0e6


def build_blockage_geometry(
    bed_elevation: np.ndarray,
    grid: Grid,
    barrier_lat: float,
    barrier_lon: float,
    crest_height_m: float,
    width_m: float,
    thickness_m: Optional[float] = None,
    observed_water_mask: Optional[np.ndarray] = None,
    catchment_area_km2: Optional[float] = None,
    direction_search_radius_cells: Tuple[int, int] = (5, 12),
    n_levels: int = 120,
    snap_radius_cells: int = 3,
) -> BlockageGeometry:
    """
    Locate, burn, fill, and (where an observation exists) check a landslide dam.

    The deep-module entry point: a caller supplies a position and a deposit size
    and gets back an impounded volume it can route, without having to know about
    seeds, connected components, spill sills or shoreline statistics.

    When ``observed_water_mask`` is given, the observed shoreline elevation is
    read off the STALE DEM and compared against the barrier crest. A lake surface
    observed ABOVE the crest contradicts the geometry — the deposit must be at
    least as tall as the water it is holding back — so the crest is raised to the
    observation and the adjustment is recorded. It is never silently reconciled
    in the other direction, and the bed beneath the lake is never overwritten;
    see this module's docstring for why.
    """
    i_barrier, j_barrier, _ = locate_barrier_cell(
        bed_elevation, grid, barrier_lat, barrier_lon, snap_radius_cells=snap_radius_cells
    )
    floor_elevation_m = float(bed_elevation[j_barrier, i_barrier])

    observation: Dict[str, Any] = {}
    effective_crest_height_m = float(crest_height_m)

    if observed_water_mask is not None:
        observed_elevation, shoreline_diagnostics = observed_lake_surface_elevation(
            bed_elevation, observed_water_mask
        )
        observation.update(shoreline_diagnostics)
        observation["observed_lake_surface_elevation_m"] = observed_elevation
        observation["lake_surface_elevation_source"] = "observed_shoreline_median"

        proposed_crest_elevation = floor_elevation_m + effective_crest_height_m
        if observed_elevation > proposed_crest_elevation:
            observation["crest_raised_by_m"] = float(
                observed_elevation - proposed_crest_elevation
            )
            observation["crest_raise_reason"] = (
                f"The observed lake surface sits at {observed_elevation:.1f} m, "
                f"above the {proposed_crest_elevation:.1f} m crest implied by the "
                f"supplied deposit height. A barrier cannot be shorter than the "
                f"water it retains, so the crest was raised to the observation."
            )
            effective_crest_height_m = float(observed_elevation - floor_elevation_m)
        else:
            observation["crest_raised_by_m"] = 0.0

    barrier = burn_barrier(
        bed_elevation,
        grid,
        i_barrier,
        j_barrier,
        effective_crest_height_m,
        width_m,
        thickness_m=thickness_m,
        direction_search_radius_cells=direction_search_radius_cells,
    )

    stage_storage = stage_storage_table(
        barrier.bed_with_barrier,
        grid,
        barrier.seed_ij,
        barrier.floor_elevation_m,
        barrier.crest_elevation_m,
        n_levels=n_levels,
        barrier_mask=barrier.barrier_mask,
    )

    lake = hypsometric_fill(
        barrier.bed_with_barrier,
        grid,
        barrier.seed_ij,
        stage_storage.usable_crest_m,
        barrier_mask=barrier.barrier_mask,
    )

    # The same refusal the Delft3D reservoir builder makes: a mean depth deeper
    # than the barrier is tall means the fill and the geometry describe different
    # things, and one of them is wrong.
    mean_depth_m = lake.volume_m3 / lake.area_m2 if lake.area_m2 > 0 else 0.0
    if mean_depth_m > barrier.crest_height_m + 1e-6:
        raise BlockageError(
            f"The impounded pool has a mean depth of {mean_depth_m:.1f} m behind a "
            f"barrier only {barrier.crest_height_m:.1f} m tall. The fill and the "
            f"barrier geometry are inconsistent, so the storage is not usable."
        )

    if observed_water_mask is not None:
        observation.update(compare_fill_to_observation(lake.mask, observed_water_mask))

    indices = natural_dam_indices(
        barrier.barrier_volume_m3,
        barrier.crest_height_m,
        stage_storage.volume_at_usable_crest_m3,
        catchment_area_km2=catchment_area_km2,
    )

    return BlockageGeometry(
        barrier=barrier,
        stage_storage=stage_storage,
        lake=lake,
        observation=observation,
        indices=indices,
    )
