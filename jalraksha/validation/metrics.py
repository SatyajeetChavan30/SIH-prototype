"""
Hydrodynamic Performance Metrics Module (Phase 8).

Implements standard spatial and temporal validation metrics:
  - Critical Success Index (CSI / Threat Score)
  - F1-Score (Harmonic mean of precision and recall)
  - Root Mean Square Error (RMSE)
  - Nash-Sutcliffe Efficiency (NSE) for discharge & depth time-series

References:
  - Bennett, N.D. et al. (2013) "Characterising performance in environmental modelling", EM&S.
  - Nash, J.E. & Sutcliffe, J.V. (1970) "River flow forecasting through conceptual models", J. Hydrol.
"""

import numpy as np
from typing import Dict, Optional, Union


def compute_csi(
    observed: np.ndarray,
    simulated: np.ndarray,
    threshold: float = 0.1,
) -> float:
    """
    Compute Critical Success Index (CSI / Threat Score) for binary inundation extent.

    CSI = TP / (TP + FP + FN)

    Args:
        observed: 2D observed depth or binary mask
        simulated: 2D simulated depth or binary mask
        threshold: Depth threshold for wet cell classification (m)

    Returns:
        CSI score in range [0.0, 1.0] (1.0 = perfect match)
    """
    obs_wet = np.asarray(observed, dtype=np.float32) >= threshold
    sim_wet = np.asarray(simulated, dtype=np.float32) >= threshold

    tp = np.sum(obs_wet & sim_wet)
    fp = np.sum(~obs_wet & sim_wet)
    fn = np.sum(obs_wet & ~sim_wet)

    denominator = tp + fp + fn
    if denominator == 0:
        return 1.0

    return float(tp / denominator)


def compute_f1_score(
    observed: np.ndarray,
    simulated: np.ndarray,
    threshold: float = 0.1,
) -> float:
    """
    Compute F1-Score for binary inundation extent.

    F1 = 2 * Precision * Recall / (Precision + Recall)

    Args:
        observed: 2D observed depth or binary mask
        simulated: 2D simulated depth or binary mask
        threshold: Depth threshold for wet cell classification (m)

    Returns:
        F1 score in range [0.0, 1.0]
    """
    obs_wet = np.asarray(observed, dtype=np.float32) >= threshold
    sim_wet = np.asarray(simulated, dtype=np.float32) >= threshold

    tp = np.sum(obs_wet & sim_wet)
    fp = np.sum(~obs_wet & sim_wet)
    fn = np.sum(obs_wet & ~sim_wet)

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0

    if (precision + recall) == 0:
        return 0.0

    return float(2.0 * precision * recall / (precision + recall))


def compute_rmse(
    observed: np.ndarray,
    simulated: np.ndarray,
    mask: Optional[np.ndarray] = None,
) -> float:
    """
    Compute Root Mean Square Error (RMSE).

    Args:
        observed: Array of observed values
        simulated: Array of simulated values
        mask: Optional boolean mask of valid cells to evaluate

    Returns:
        RMSE value (same units as input)
    """
    obs = np.asarray(observed, dtype=np.float32)
    sim = np.asarray(simulated, dtype=np.float32)

    if mask is not None:
        valid = np.asarray(mask, dtype=bool) & np.isfinite(obs) & np.isfinite(sim)
    else:
        valid = np.isfinite(obs) & np.isfinite(sim)

    if np.sum(valid) == 0:
        return 0.0

    diff = sim[valid] - obs[valid]
    return float(np.sqrt(np.mean(diff**2)))


def compute_nse(
    observed: np.ndarray,
    simulated: np.ndarray,
) -> float:
    """
    Compute Nash-Sutcliffe Efficiency (NSE) for time-series.

    NSE = 1 - sum((obs - sim)^2) / sum((obs - mean(obs))^2)

    Args:
        observed: 1D time-series of observed values
        simulated: 1D time-series of simulated values

    Returns:
        NSE value (-inf to 1.0, 1.0 = perfect match, 0.0 = performance equal to mean)
    """
    obs = np.asarray(observed, dtype=np.float32)
    sim = np.asarray(simulated, dtype=np.float32)

    valid = np.isfinite(obs) & np.isfinite(sim)
    if np.sum(valid) < 2:
        return 0.0

    obs_valid = obs[valid]
    sim_valid = sim[valid]

    denom = np.sum((obs_valid - np.mean(obs_valid))**2)
    if denom == 0:
        return 1.0

    numer = np.sum((obs_valid - sim_valid)**2)
    return float(1.0 - (numer / denom))
