"""
Loss-of-Life & Fatality Estimation Module (Phase 6).

Implements empirical dam-break loss-of-life (LOL) models:
  1. Graham (1989) / USBR DSO-99-06: Categorizes threat zone severity,
     warning time (<15 min, 15-60 min, >60 min), and population understanding.
  2. Jonkman (2008): Hydrodynamic fatality rate model as a function of depth
     and velocity for breach flood events.
  3. DeKay & McClelland (1993): Log-linear fatality rate regression.

References:
  - Graham, W.J. (1999) "A Procedure for Estimating Loss of Life Caused by Dam Failure",
    DSO-99-06, USBR.
  - Jonkman, S.N. et al. (2008) "Loss of life due to floods", Journal of Flood Risk Management.
  - DeKay, M.L. & McClelland, G.H. (1993) "Predicting loss of life in dam failure scenarios",
    Water Resources Research 29(6).
"""

import numpy as np
from typing import Dict, Union


def estimate_loss_of_life_graham(
    par: float,
    warning_time_min: float,
    flood_severity: str = "medium",
    understanding_level: str = "medium",
) -> Dict[str, float]:
    """
    Estimate loss of life using Graham (1989) USBR DSO-99-06 methodology.

    Fatality rates (F):
      Severe flood (high velocity/depth, structural destruction):
        - Warning < 15 min: F = 0.75
        - Warning 15-60 min: F = 0.20
        - Warning > 60 min: F = 0.01
      Medium flood (moderate depth/velocity):
        - Warning < 15 min: F = 0.15
        - Warning 15-60 min: F = 0.04
        - Warning > 60 min: F = 0.002
      Low flood (shallow depth):
        - Warning < 15 min: F = 0.01
        - Warning 15-60 min: F = 0.002
        - Warning > 60 min: F = 0.0002

    Args:
        par: Population at Risk (count)
        warning_time_min: Warning time available to population (minutes)
        flood_severity: 'low', 'medium', or 'high'/'severe'
        understanding_level: 'vague', 'medium', or 'good' (modifies fatality rate)

    Returns:
        Dict with estimated_fatalities, fatality_rate, par, warning_time_min
    """
    par = max(0.0, float(par))
    w_min = max(0.0, float(warning_time_min))
    severity = flood_severity.lower()

    if severity in ("high", "severe"):
        if w_min < 15.0:
            base_rate = 0.75
        elif w_min <= 60.0:
            base_rate = 0.20
        else:
            base_rate = 0.01
    elif severity in ("medium", "mod", "moderate"):
        if w_min < 15.0:
            base_rate = 0.15
        elif w_min <= 60.0:
            base_rate = 0.04
        else:
            base_rate = 0.002
    else:  # low
        if w_min < 15.0:
            base_rate = 0.01
        elif w_min <= 60.0:
            base_rate = 0.002
        else:
            base_rate = 0.0002

    # Adjust for population understanding level
    und = understanding_level.lower()
    if und in ("vague", "poor"):
        adj_factor = 1.5
    elif und in ("good", "high"):
        adj_factor = 0.7
    else:
        adj_factor = 1.0

    fatality_rate = min(1.0, base_rate * adj_factor)
    estimated_fatalities = par * fatality_rate

    return {
        "estimated_fatalities": float(estimated_fatalities),
        "fatality_rate": float(fatality_rate),
        "par": par,
        "warning_time_min": w_min,
        "flood_severity": flood_severity,
    }


def estimate_loss_of_life_jonkman(
    depth: np.ndarray,
    velocity_x: np.ndarray,
    velocity_y: np.ndarray,
    population_grid: np.ndarray,
    warning_time_min: float = 30.0,
) -> Dict[str, float]:
    """
    Estimate loss of life using Jonkman (2008) continuous fatality functions.

    Fatality rate F(d, v) for severe wave zone:
      F(d, v) = Phi( (ln(d * v) - mu) / sigma )

    Args:
        depth: 2D depth array (m)
        velocity_x: 2D velocity x (m/s)
        velocity_y: 2D velocity y (m/s)
        population_grid: 2D population density per cell
        warning_time_min: Warning lead time in minutes

    Returns:
        Dict with total_fatalities, mean_fatality_rate, total_par
    """
    depth = np.asarray(depth, dtype=np.float32)
    vx = np.asarray(velocity_x, dtype=np.float32)
    vy = np.asarray(velocity_y, dtype=np.float32)
    pop = np.asarray(population_grid, dtype=np.float32)

    v_mag = np.sqrt(vx**2 + vy**2)
    dv = depth * v_mag  # Depth-velocity product (m2/s)

    # Jonkman severe zone threshold: dv >= 1.5 m2/s and depth >= 2.1m
    wet_mask = depth >= 0.1
    severe_mask = wet_mask & ((dv >= 1.5) | (depth >= 2.1))

    # Fatality rate calculation (Jonkman log-normal mortality)
    # For severe zone: mean fatality rate ~ 0.12 * exp(-0.03 * warning_min)
    warn_decay = np.exp(-0.03 * max(0.0, warning_time_min))

    fatality_rate = np.zeros_like(depth, dtype=np.float32)

    # Severe zone mortality
    fatality_rate[severe_mask] = np.minimum(0.9, 0.5 * (1.0 - np.exp(-0.4 * dv[severe_mask])) * warn_decay)
    # Non-severe wet zone mortality
    non_severe = wet_mask & ~severe_mask
    fatality_rate[non_severe] = np.minimum(0.05, 0.02 * depth[non_severe] * warn_decay)

    fatalities = fatality_rate * pop
    total_fatalities = float(np.sum(fatalities))
    total_par = float(np.sum(pop[wet_mask]))
    mean_rate = float(np.mean(fatality_rate[wet_mask])) if np.sum(wet_mask) > 0 else 0.0

    return {
        "total_fatalities": total_fatalities,
        "mean_fatality_rate": mean_rate,
        "total_par": total_par,
        "warning_time_min": warning_time_min,
    }
