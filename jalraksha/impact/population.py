"""
Population Exposure & Population at Risk (PAR) Module (Phase 6).

Calculates exposed population across FD2320 hazard rating categories and
estimates Population at Risk (PAR) given flood arrival lead times.

References:
  - USACE (2014) "HEC-FIA Flood Impact Analysis Technical Reference"
  - Defra/Environment Agency (2006) FD2320 "Flood Risks to People"
"""

import numpy as np
from typing import Dict, Optional
from jalraksha.impact.hazard import categorize_hazard_zones, compute_fd2320_hazard_rating


def compute_population_exposure(
    depth: np.ndarray,
    velocity_x: np.ndarray,
    velocity_y: np.ndarray,
    population_grid: np.ndarray,
    cell_area_km2: float = 0.04,
) -> Dict[str, Union[float, int, Dict]]:
    """
    Compute population exposure grouped by FD2320 hazard rating classes.

    Args:
        depth: 2D flood depth array (m)
        velocity_x: 2D velocity x (m/s)
        velocity_y: 2D velocity y (m/s)
        population_grid: 2D population density (people / cell or people / km2)
        cell_area_km2: Cell area in km2 (default 0.04 km2 for 200m grid)

    Returns:
        Dict with total_exposed, exposed_by_class (0: Low, 1: Moderate, 2: High, 3: Extreme)
    """
    hr = compute_fd2320_hazard_rating(depth, velocity_x, velocity_y)
    hazard_cls = categorize_hazard_zones(hr)

    pop_grid = np.asarray(population_grid, dtype=np.float32)
    wet_mask = depth >= 0.05

    total_pop_exposed = float(np.sum(pop_grid[wet_mask]))

    exposed_by_class = {}
    class_names = {0: "Low", 1: "Moderate", 2: "High", 3: "Extreme"}

    for cls in (0, 1, 2, 3):
        cls_mask = wet_mask & (hazard_cls == cls)
        cls_pop = float(np.sum(pop_grid[cls_mask]))
        cls_cells = int(np.sum(cls_mask))
        exposed_by_class[class_names[cls]] = {
            "class_id": cls,
            "population": cls_pop,
            "cell_count": cls_cells,
        }

    return {
        "total_exposed_population": total_pop_exposed,
        "exposed_by_class": exposed_by_class,
        "total_flooded_cells": int(np.sum(wet_mask)),
    }


def compute_par(
    population_grid: np.ndarray,
    t_arrival_grid: np.ndarray,
    warning_lead_time_s: float = 1800.0,
    par_depth_threshold: float = 0.3,
    h_max_grid: Optional[np.ndarray] = None,
) -> Dict[str, float]:
    """
    Compute Population at Risk (PAR) based on flood arrival time and warning lead time.

    PAR defined as population in areas flooded to depth >= par_depth_threshold
    where warning lead time T_lead = T_arrival - T_warning < 60 min.

    Args:
        population_grid: 2D array of population count per cell
        t_arrival_grid: 2D array of arrival times (s)
        warning_lead_time_s: Time of warning issuance from breach start (s)
        par_depth_threshold: Threshold depth for PAR consideration (m)
        h_max_grid: Optional max depth grid to apply depth threshold

    Returns:
        Dict with par_total, par_high_urgency (<15 min lead), par_medium_urgency (15-60 min lead)
    """
    pop = np.asarray(population_grid, dtype=np.float32)
    t_arr = np.asarray(t_arrival_grid, dtype=np.float32)

    # Lead time = t_arrival - warning_time
    t_lead = t_arr - warning_lead_time_s

    # PAR mask: cell arrives after warning, but lead time is positive
    valid_arrival = np.isfinite(t_arr) & (t_arr > 0)
    if h_max_grid is not None:
        valid_arrival &= (h_max_grid >= par_depth_threshold)

    # High urgency: lead time < 15 min (900 s)
    high_urgency_mask = valid_arrival & (t_lead >= 0) & (t_lead < 900)
    # Medium urgency: lead time 15-60 min (900 - 3600 s)
    med_urgency_mask = valid_arrival & (t_lead >= 900) & (t_lead < 3600)
    # Trapped / zero warning: lead time < 0 (flooded before warning issued!)
    trapped_mask = valid_arrival & (t_lead < 0)

    return {
        "par_total": float(np.sum(pop[valid_arrival & (t_lead < 3600)])),
        "par_trapped_zero_warning": float(np.sum(pop[trapped_mask])),
        "par_high_urgency_under_15min": float(np.sum(pop[high_urgency_mask])),
        "par_medium_urgency_15_60min": float(np.sum(pop[med_urgency_mask])),
        "par_sufficient_warning_over_60min": float(np.sum(pop[valid_arrival & (t_lead >= 3600)])),
    }
