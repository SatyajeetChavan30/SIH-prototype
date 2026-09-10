"""
Population impact assessment for dam-break simulations.

Phase 6+: population exposure and population-at-risk from a GRIDDED
per-cell population count -- GHSL, fetched onto the solver grid by
floodview.gee.population -- and the solver's own depth and arrival-time
rasters.

WHAT WAS REMOVED, AND WHY IT IS NOT COMING BACK
-----------------------------------------------
This module used to also carry a ``PopulationEstimator`` that inferred
density from a settlement-TYPE grid when no gridded population existed. It
returned zero population on every input it could ever be given, and had done
since it was written: its lookup keys were the strings "village" / "town" /
"city", while the settlement grid it documented (and the one its own
synthesiser produced) held the integers 0 / 1 / 2, so the membership test
could not fire and the density array stayed all zeros. Two further defects
sat in the same call: the PAR denominator re-hardcoded a 200 m cell,
discarding the caller's resolution, and the exposure loop summed four NESTED
depth thresholds, counting a 2 m-deep cell four times.

It had no caller outside its own tests. ``compute_population_exposure`` and
``compute_par`` below take census-derived counts directly and are what
services/api/floodview_service/tasks.py uses, so the broken fallback was
deleted rather than repaired -- a fallback nobody calls is not worth three
fixes and a set of UNVETTED per-settlement-type densities.

Returns PAR (Population Affected Ratio) and warning-urgency buckets.
"""

import numpy as np
from typing import Dict, Any, Optional


# ── Functional wrappers (expected by tests / downstream consumers) ────────────

def compute_population_exposure(
    depth: np.ndarray,
    velocity_x: np.ndarray,
    velocity_y: np.ndarray,
    population_grid: np.ndarray,
    depth_threshold_m: float = 0.1,
) -> Dict[str, Any]:
    """
    Population exposed to inundation (persons per cell basis).

    Args:
        depth: Water depth grid (m).
        velocity_x, velocity_y: Velocity grids (m/s), accepted for API symmetry.
        population_grid: Population count per cell.
        depth_threshold_m: Flooding depth threshold (m).

    Returns:
        Dict with total_exposed_population and total_flooded_cells.
    """
    depth = np.asarray(depth, dtype=np.float64)
    population_grid = np.asarray(population_grid, dtype=np.float64)

    flooded = depth >= depth_threshold_m
    return {
        "total_exposed_population": float(np.sum(population_grid[flooded])),
        "total_flooded_cells": int(np.sum(flooded)),
        "depth_threshold_m": depth_threshold_m,
        "method": "depth_threshold_exposure",
    }


def compute_par(
    population_grid: np.ndarray,
    arrival_time_grid: np.ndarray,
    warning_lead_time_s: float = 0.0,
    h_max_grid: Optional[np.ndarray] = None,
) -> Dict[str, Any]:
    """
    Population At Risk (PAR) bucketed by warning lead time.

    Lead time per cell = arrival_time - warning_lead_time (clipped at 0).
    Buckets:
      - high urgency:   lead < 15 min
      - medium urgency: 15 <= lead <= 60 min
      - low urgency:    lead > 60 min

    Args:
        population_grid: Population count per cell.
        arrival_time_grid: Arrival-time grid (s; inf/NaN = no arrival).
        warning_lead_time_s: Warning issued at this many seconds before t0.
        h_max_grid: Optional max-depth grid to restrict to flooded cells.

    Returns:
        Dict with per-bucket PAR counts and totals.
    """
    population_grid = np.asarray(population_grid, dtype=np.float64)
    arrival_time_grid = np.asarray(arrival_time_grid, dtype=np.float64)

    # isfinite is what rejects the inf-means-never-wet sentinel and any NaN.
    # The bound is >= 0, not > 0: a cell wet at exactly t = 0 is the breach
    # cell and its neighbours, i.e. the population with the LEAST warning of
    # anyone in the domain, and > 0 silently dropped them from every bucket.
    arrived = np.isfinite(arrival_time_grid) & (arrival_time_grid >= 0)
    if h_max_grid is not None:
        h_max_grid = np.asarray(h_max_grid, dtype=np.float64)
        arrived = arrived & (h_max_grid > 0.0)

    lead_s = np.clip(arrival_time_grid - warning_lead_time_s, 0.0, None)
    lead_min = lead_s / 60.0

    high = arrived & (lead_min < 15.0)
    medium = arrived & (lead_min >= 15.0) & (lead_min <= 60.0)
    low = arrived & (lead_min > 60.0)

    par_high = float(np.sum(population_grid[high]))
    par_medium = float(np.sum(population_grid[medium]))
    par_low = float(np.sum(population_grid[low]))

    return {
        "par_high_urgency_under_15min": par_high,
        "par_medium_urgency_15_60min": par_medium,
        "par_low_urgency_over_60min": par_low,
        "total_par": par_high + par_medium + par_low,
        "n_arrived_cells": int(np.sum(arrived)),
    }
