"""
Phase 13: Extended Validation & Sensitivity Analysis.

Implements:
  1. Sensitivity analysis: one-at-a-time (OAT) perturbation of dam parameters
     to quantify output sensitivity (peak outflow, arrival time).
  2. Uncertainty quantification: propagation of Wahl (2004) uncertainty bands
     through the breach regression ensemble.
  3. Convergence analysis: grid-resolution convergence check (coarse → fine).
  4. Sobol-style ranking: first-order sensitivity indices by parameter.

References:
  Saltelli et al. (2008) "Global Sensitivity Analysis: The Primer"
  Wahl (2004) "Uncertainty of Predictions of Embankment Dam Breach Parameters"
  — JRC Hydraulics Journal 130(5):389-397. TODO: VERIFY coefficient table §3.
"""

from __future__ import annotations

import numpy as np
from typing import Dict, List, Optional, Tuple


# ── One-at-a-time sensitivity analysis ───────────────────────────────────────

def oat_sensitivity(
    base_config: Dict,
    param_name: str,
    param_values: List[float],
    output_fn,
    output_key: str,
) -> Dict:
    """
    One-At-a-Time (OAT) sensitivity sweep across a named parameter.

    Runs output_fn(config) for each value in param_values, holding all
    other parameters at their base_config values.

    Args:
        base_config: Reference dam configuration dict.
        param_name: Config key to vary (e.g. "height_m").
        param_values: List of values to test.
        output_fn: Callable(config) → Dict; must return a dict with output_key.
        output_key: Key in output dict to track (e.g. "q_peak_median").

    Returns:
        {
            "param_name": "height_m",
            "param_values": [200, 260, 300],
            "output_values": [45000, 68000, 82000],
            "sensitivity_index": 0.43,   # Normalised range / base value
            "elasticity": 0.82,          # % change in output per % change in param
        }
    """
    if len(param_values) < 2:
        raise ValueError("param_values must have at least 2 elements for OAT.")

    output_values = []
    base_value = base_config[param_name]

    for val in param_values:
        test_config = dict(base_config)
        test_config[param_name] = val
        result = output_fn(test_config)
        output_values.append(float(result[output_key]))

    output_array = np.array(output_values)
    base_output_idx = np.argmin(np.abs(np.array(param_values) - base_value))
    base_output = output_array[base_output_idx]

    # Normalised sensitivity index: (max - min) / base
    sensitivity_index = (output_array.max() - output_array.min()) / (base_output + 1e-12)

    # Elasticity (log-log slope at base point)
    param_array = np.array(param_values, dtype=float)
    if base_output > 0 and len(param_values) >= 2:
        log_param = np.log(param_array + 1e-12)
        log_output = np.log(output_array + 1e-12)
        # Linear fit of log-log relationship
        fit = np.polyfit(log_param, log_output, 1)
        elasticity = float(fit[0])
    else:
        elasticity = 0.0

    return {
        "param_name": param_name,
        "param_values": list(param_values),
        "output_values": list(output_values),
        "sensitivity_index": float(sensitivity_index),
        "elasticity": elasticity,
        "output_key": output_key,
        "base_value": float(base_value),
        "base_output": float(base_output),
    }


def rank_parameters_by_sensitivity(
    sensitivity_results: List[Dict],
) -> List[Dict]:
    """
    Rank parameters from most to least sensitive based on sensitivity_index.

    Args:
        sensitivity_results: List of dicts from oat_sensitivity().

    Returns:
        Sorted list of dicts with added "rank" field.
    """
    ranked = sorted(
        sensitivity_results,
        key=lambda r: r.get("sensitivity_index", 0.0),
        reverse=True,
    )
    for i, item in enumerate(ranked):
        item["rank"] = i + 1
    return ranked


# ── Wahl (2004) Uncertainty Quantification ───────────────────────────────────

# TODO: UNVETTED — Wahl (2004) Table 3 coefficient bounds.
# Source: Wahl, T.L. (2004) "Uncertainty of Predictions of Embankment Dam
# Breach Parameters". J. Hydraulic Engineering, 130(5):389-397.
WAHL_PEAK_OUTFLOW_FACTOR_UNCERTAINTY = 1.89  # 2-sigma multiplicative band


def wahl_uncertainty_band(
    q_peak_median_m3s: float,
    confidence_level: float = 0.95,
) -> Tuple[float, float]:
    """
    Apply Wahl (2004) uncertainty band to a peak outflow estimate.

    The Wahl (2004) analysis found that embankment dam breach peak outflow
    predictions from regression equations have an 89% prediction interval
    spanning a factor of 1.89 on either side of the median.

    TODO: UNVETTED — Wahl (2004) Table 3 factor = 1.89 at 89% CI.
    Source: Wahl (2004) J. Hydraulic Eng. 130(5):389-397.

    Args:
        q_peak_median_m3s: Median peak outflow estimate (m³/s).
        confidence_level: Target confidence level (0.95 → 95% CI, approx 2σ).

    Returns:
        (q_lower, q_upper): Lower and upper bound of uncertainty band (m³/s).
    """
    # Scale factor for different confidence levels (approximate)
    if confidence_level >= 0.95:
        scale = WAHL_PEAK_OUTFLOW_FACTOR_UNCERTAINTY * 1.06  # Approx 2σ
    else:
        scale = WAHL_PEAK_OUTFLOW_FACTOR_UNCERTAINTY  # 89% CI

    q_lower = q_peak_median_m3s / scale
    q_upper = q_peak_median_m3s * scale

    return float(q_lower), float(q_upper)


# ── Grid Resolution Convergence Analysis ─────────────────────────────────────

def compute_grid_convergence(
    resolutions_m: List[float],
    metric_values: List[float],
    metric_name: str = "Q_peak",
) -> Dict:
    """
    Compute grid convergence ratio (Richardson extrapolation).

    Evaluates whether the solver output converges as grid resolution is refined.
    Convergence is indicated by a monotonically decreasing difference between
    successive refinements.

    Args:
        resolutions_m: Grid resolutions in metres (coarse to fine), e.g. [400, 200, 100].
        metric_values: Corresponding metric values (e.g. peak depths).
        metric_name: Human-readable label for the metric.

    Returns:
        {
            "metric_name": "Q_peak",
            "resolutions_m": [400, 200, 100],
            "metric_values": [...],
            "convergence_ratios": [...],  # Should approach 2.0 for 1st order
            "is_converging": bool,
            "extrapolated_value": float,  # Richardson extrapolation to dx → 0
        }
    """
    if len(resolutions_m) < 2:
        raise ValueError("Need at least 2 resolutions for convergence analysis.")
    if len(resolutions_m) != len(metric_values):
        raise ValueError("resolutions_m and metric_values must have same length.")

    resolutions = np.array(resolutions_m, dtype=float)
    values = np.array(metric_values, dtype=float)

    # Sort coarse to fine
    order = np.argsort(resolutions)[::-1]
    resolutions = resolutions[order]
    values = values[order]

    # Differences between successive refinements
    diffs = np.abs(np.diff(values))
    convergence_ratios = []
    if len(diffs) >= 2:
        for i in range(len(diffs) - 1):
            ratio = diffs[i] / (diffs[i + 1] + 1e-12)
            convergence_ratios.append(float(ratio))

    is_converging = all(r >= 1.0 for r in convergence_ratios) if convergence_ratios else True

    # Richardson extrapolation (requires ≥ 3 points and grid ratio ≈ 2)
    extrapolated_value = None
    if len(values) >= 3:
        # Assume grid refinement ratio ≈ 2
        r = resolutions[-2] / resolutions[-1]
        f_fine = values[-1]
        f_med = values[-2]
        p = 1.0  # Assumed order of convergence
        try:
            extrap = f_fine + (f_fine - f_med) / (r ** p - 1)
            extrapolated_value = float(extrap)
        except ZeroDivisionError:
            extrapolated_value = float(values[-1])

    return {
        "metric_name": metric_name,
        "resolutions_m": list(resolutions),
        "metric_values": list(values),
        "convergence_ratios": convergence_ratios,
        "is_converging": is_converging,
        "extrapolated_value": extrapolated_value,
    }


# ── Arrival Time Sensitivity Summary ─────────────────────────────────────────

def arrival_time_sensitivity_table(
    gauge_results: Dict[str, Dict],
) -> List[Dict]:
    """
    Compute a summary sensitivity table for arrival times at gauges.

    Args:
        gauge_results: Dict from run_dam_break_ensemble()["arrival_times"].
            Each value must have keys: median, p05, p95 (all in seconds).

    Returns:
        List of dicts, one per gauge:
        {
            "gauge": "Rishikesh",
            "median_min": 72.0,
            "p05_min": 58.0,
            "p95_min": 89.0,
            "spread_min": 31.0,
            "uncertainty_pct": 43.1,
        }
    """
    rows = []
    for gauge_name, data in gauge_results.items():
        median_s = data.get("median")
        p05_s = data.get("p05")
        p95_s = data.get("p95")

        if median_s is None:
            rows.append({
                "gauge": gauge_name,
                "median_min": None,
                "p05_min": None,
                "p95_min": None,
                "spread_min": None,
                "uncertainty_pct": None,
                "note": "No arrival detected",
            })
            continue

        median_min = median_s / 60.0
        p05_min = p05_s / 60.0 if p05_s is not None else median_min
        p95_min = p95_s / 60.0 if p95_s is not None else median_min
        spread_min = p95_min - p05_min
        uncertainty_pct = 100.0 * spread_min / (median_min + 1e-12)

        rows.append({
            "gauge": gauge_name,
            "median_min": round(median_min, 1),
            "p05_min": round(p05_min, 1),
            "p95_min": round(p95_min, 1),
            "spread_min": round(spread_min, 1),
            "uncertainty_pct": round(uncertainty_pct, 1),
        })

    return rows
