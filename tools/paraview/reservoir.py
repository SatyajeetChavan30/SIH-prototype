"""
Static reservoir at full supply level — the dam-intact initial state (Phase 3).

Fills the impounded pool upstream of the dam and nothing else, so ParaView can
render the "RESERVOIR / dam intact at t=0" picture from spec section 7. This is a
geometric construction from real terrain and a published water level, NOT a
hydrodynamic result — the solver's own datasets start dry on purpose, because the
flood enters through the breach hydrograph and impounding a reservoir as well
would double-count the water.

TWO THINGS THAT MAKE THIS NON-TRIVIAL

1. A plain `terrain <= FRL` threshold floods the WRONG half of the domain.
   The gorge downstream of Tehri also sits below full supply level — the transect
   running south from the dam goes 827, 822, 807, 799, 776, 740, 724 m. Filling
   every cell below 830 m would inundate the entire downstream valley, which is
   the exact inverse of a reservoir. The fill therefore has to be barred at the
   dam and constrained to the connected component that contains the pool.

2. GLO-30 is a SURFACE model, so the reservoir is already baked into the terrain.
   The DEM samples the impounded water surface (~814 m at 30 m, 819.8 m at 400 m),
   not the drowned valley floor beneath it. The project's own briefing says as
   much: "No reservoir bathymetry in any DEM, and GLO-30 is a surface model — it
   flattens water and puts canopy in the channel."

   So the EXTENT this produces is real; the DEPTH is not. What comes back is the
   height of water above the DEM's existing surface — a ~10-15 m veneer over an
   already-flat pool — not the ~200 m of true reservoir depth. Label it
   accordingly; calling it "water depth" would be a number that looks right and
   is wrong.
"""

from __future__ import annotations

from typing import Any, Dict, Tuple

import numpy as np

# Tehri Dam levels, metres above sea level.
# TODO: UNVETTED — confirm against a primary THDC / CWC source before these are
# used for anything beyond visualization. Both are exposed as CLI flags so a
# corrected value needs no code change.
TEHRI_FRL_M = 830.0      # full reservoir level
TEHRI_CREST_M = 839.5    # dam crest


class ReservoirError(Exception):
    """Raised when the reservoir fill cannot be trusted."""


def _downhill_direction(terrain: np.ndarray, i: int, j: int,
                        min_radius: int = 5, max_radius: int = 12,
                        n_angles: int = 96) -> Tuple[float, float]:
    """
    Unit vector pointing downstream at the dam, in (di, dj) cell units.

    Found by sweeping an annulus around the dam and taking the direction of the
    LOWEST cell on it — i.e. the way water would actually go at valley scale.

    A smoothed local gradient (the obvious first choice) does not work here and
    was measured failing: the dam sits on a dead-flat impounded pool, so the
    terrain gradient there is noise, and averaging over a symmetric window is
    dominated by whatever hills happen to surround it. At Tehri that returned a
    vector pointing NORTH-EAST — up into the reservoir — placing the fill seed on
    an 855 m hillside instead of in the 814 m pool. Sampling an annulus asks the
    question directly and cannot be swayed by high ground on the far side.
    """
    ny, nx = terrain.shape
    best_elev = np.inf
    best_dir = None

    for radius in range(min_radius, max_radius + 1):
        for angle in np.linspace(0.0, 2.0 * np.pi, n_angles, endpoint=False):
            ci, si = np.cos(angle), np.sin(angle)
            ii = int(round(i + radius * ci))
            jj = int(round(j + radius * si))
            if 0 <= ii < nx and 0 <= jj < ny:
                if terrain[jj, ii] < best_elev:
                    best_elev = float(terrain[jj, ii])
                    best_dir = (float(ci), float(si))

    if best_dir is None:
        raise ReservoirError(
            f"No valid cells in the annulus around the dam at (i={i}, j={j}); "
            f"the dam is probably outside the domain."
        )
    if best_elev >= terrain[j, i]:
        raise ReservoirError(
            f"Every cell within {max_radius} cells of the dam sits at or above the "
            f"dam cell ({terrain[j, i]:.1f} m). There is no downstream direction, "
            f"so the dam location is likely wrong."
        )
    return best_dir


def build_reservoir(
    terrain: np.ndarray,
    grid: Dict[str, Any],
    i_dam: int,
    j_dam: int,
    *,
    frl_m: float = TEHRI_FRL_M,
    crest_m: float = TEHRI_CREST_M,
    barrier_halfwidth_cells: int = 25,
    barrier_thickness_cells: int = 4,
    seed_offset_cells: int = 3,
) -> Dict[str, Any]:
    """
    Fill the pool upstream of the dam to `frl_m`.

    Args:
        terrain: (ny, nx) elevation, metres. Row 0 is the southernmost row.
        grid: nx, ny, dx, dy — for cell area.
        i_dam: column index (x) of the dam; j_dam: row index (y).
        frl_m: Water surface elevation to fill to.
        crest_m: Height the barrier is raised to. Must exceed frl_m or water
            simply flows over it and the fill escapes downstream.
        barrier_halfwidth_cells: How far the barrier extends either side of the
            dam, perpendicular to the flow. Must be wide enough to span the
            valley, or the pool leaks around its ends.
        barrier_thickness_cells: Barrier depth along the flow direction.
        seed_offset_cells: How far upstream of the dam to seed the fill.

    Returns:
        Dict with `depth` (ny, nx float32), `mask`, and diagnostics.
    """
    from scipy.ndimage import label

    if crest_m <= frl_m:
        raise ReservoirError(
            f"crest ({crest_m} m) must be above full supply level ({frl_m} m); "
            f"otherwise the barrier is submerged and the fill escapes downstream."
        )

    ny, nx = terrain.shape
    dx, dy = float(grid["dx"]), float(grid["dy"])

    di, dj = _downhill_direction(terrain, i_dam, j_dam)
    # Perpendicular to the flow — the line the dam wall runs along.
    pi, pj = -dj, di

    # Raise a short wall across the valley at the dam. This is not a trick to
    # make the algorithm behave: it *is* the intact dam, which is precisely the
    # state Phase 3 depicts.
    barred = terrain.astype(np.float64).copy()
    for step in range(-barrier_thickness_cells, barrier_thickness_cells + 1):
        for offset in range(-barrier_halfwidth_cells, barrier_halfwidth_cells + 1):
            ii = int(round(i_dam + step * di + offset * pi))
            jj = int(round(j_dam + step * dj + offset * pj))
            if 0 <= ii < nx and 0 <= jj < ny:
                barred[jj, ii] = max(barred[jj, ii], crest_m)

    # Seed upstream — the opposite direction from the flow.
    #
    # The seed must clear the barrier, or it lands ON the wall and reads as crest
    # height, and the fill aborts with "no pool to grow from". Deriving the offset
    # from the barrier thickness makes the two impossible to set inconsistently;
    # they were independent parameters and thickening the barrier promptly broke
    # the seed.
    effective_offset = max(seed_offset_cells, barrier_thickness_cells + 2)
    i_seed = int(round(i_dam - effective_offset * di))
    j_seed = int(round(j_dam - effective_offset * dj))
    if not (0 <= i_seed < nx and 0 <= j_seed < ny):
        raise ReservoirError("Seed point fell outside the domain.")
    if barred[j_seed, i_seed] > frl_m:
        raise ReservoirError(
            f"Seed cell (i={i_seed}, j={j_seed}) sits at {barred[j_seed, i_seed]:.1f} m, "
            f"above the {frl_m} m fill level, so there is no pool to grow from. "
            f"The dam location or the fill level is wrong."
        )

    submerged = barred <= frl_m
    labels, n_components = label(submerged)
    pool_label = labels[j_seed, i_seed]
    if pool_label == 0:
        raise ReservoirError("Seed landed outside the submerged region.")

    mask = labels == pool_label
    depth = np.where(mask, frl_m - terrain, 0.0)
    depth = np.maximum(depth, 0.0).astype(np.float32)

    # Diagnostics — the fill is only trustworthy if these hold.
    cell_area_km2 = (dx * dy) / 1e6
    area_km2 = float(mask.sum() * cell_area_km2)

    # Signed distance along the flow direction; positive is downstream.
    jj_idx, ii_idx = np.mgrid[0:ny, 0:nx]
    along_flow = (ii_idx - i_dam) * di + (jj_idx - j_dam) * dj
    downstream_leak = int(np.count_nonzero(mask & (along_flow > barrier_thickness_cells + 1)))

    surface = np.where(mask, terrain + depth, np.nan)
    surface_spread = float(np.nanmax(surface) - np.nanmin(surface)) if mask.any() else 0.0

    return {
        "depth": depth,
        "mask": mask,
        "area_km2": area_km2,
        "n_cells": int(mask.sum()),
        "downstream_leak_cells": downstream_leak,
        "surface_spread_m": surface_spread,
        "n_components": int(n_components),
        "max_fill_m": float(depth.max()),
        "mean_fill_m": float(depth[mask].mean()) if mask.any() else 0.0,
        "frl_m": frl_m,
        "flow_direction": (di, dj),
        "seed": (i_seed, j_seed),
        "seed_offset_cells": effective_offset,
    }


def summarize(result: Dict[str, Any]) -> str:
    """One-line-per-fact report, including the caveat that matters."""
    return (
        f"[reservoir] FRL {result['frl_m']:.1f} m\n"
        f"  extent          : {result['area_km2']:.1f} km2  ({result['n_cells']} cells)\n"
        f"  fill above DEM  : mean {result['mean_fill_m']:.1f} m, max {result['max_fill_m']:.1f} m\n"
        f"  surface spread  : {result['surface_spread_m']:.3f} m  (should be ~0 — a flat pool)\n"
        f"  downstream leak : {result['downstream_leak_cells']} cells  (must be 0)\n"
        f"  NOTE: GLO-30 is a surface model. This is water ABOVE the DEM's existing\n"
        f"        reservoir surface, not true depth to the drowned valley floor."
    )
