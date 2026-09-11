"""
SPH vs Delft3D Comparison Module.

Compares near-field SPH results with far-field Delft3D/SWE results:
  - Grid alignment (SPH particles → rasterised depth field)
  - Comparison metrics (RMSE, bias, CSI, arrival time difference)
  - Side-by-side summary generation for dashboard display

References:
  - Bennett et al. (2013) "Characterising performance in environmental modelling".
  - Nash & Sutcliffe (1970) "River flow forecasting through conceptual models".
"""

from __future__ import annotations

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from typing import Dict, List, Optional, Tuple


def rasterize_sph_particles(
    sph_result: Dict,
    grid_nx: int,
    grid_ny: int,
    grid_dx: float,
    grid_dy: float,
) -> np.ndarray:
    """
    Rasterize SPH particle positions into a 2D depth grid.

    Maps particle z-positions (height above bed) onto a regular grid
    by counting particles per cell and estimating depth from mass.

    Args:
        sph_result: Dict from run_near_field_sph() with 'x', 'y', 'z' arrays.
        grid_nx: Number of grid cells in x.
        grid_ny: Number of grid cells in y.
        grid_dx: Cell size x (m).
        grid_dy: Cell size y (m).

    Returns:
        2D depth array (grid_ny × grid_nx).
    """
    x = np.asarray(sph_result.get("x", np.array([])))
    y = np.asarray(sph_result.get("y", np.array([])))

    depth_grid = np.zeros((grid_ny, grid_nx), dtype=np.float32)

    if len(x) == 0:
        return depth_grid

    # Depth = (water volume in the cell) / (cell area), and the water volume is
    # the particle COUNT times the volume each particle carries.
    #
    # That per-particle volume must come from the run. It used to be the literal
    # `particle_volume = 1.0  # m³ (approximate)` — a number with no relationship
    # to the simulation, which scaled every depth in this comparison by an
    # arbitrary factor and made the RMSE and CSI against Delft3D meaningless.
    # pysph_runner reports the real value (spacing³); refuse rather than guess
    # if a caller passes a result that does not carry it.
    particle_volume = sph_result.get("particle_volume_m3")
    if particle_volume is None:
        raise ValueError(
            "sph_result has no 'particle_volume_m3'. Depth cannot be derived "
            "from particle positions without knowing the volume each particle "
            "represents, and assuming one would silently rescale every depth "
            "in this comparison. jalraksha.sph.pysph_runner reports it."
        )

    cell_i = np.clip((x / grid_dx).astype(int), 0, grid_nx - 1)
    cell_j = np.clip((y / grid_dy).astype(int), 0, grid_ny - 1)

    counts = np.zeros((grid_ny, grid_nx), dtype=np.float64)
    np.add.at(counts, (cell_j, cell_i), 1.0)

    cell_area = grid_dx * grid_dy
    depth_grid = (counts * float(particle_volume) / cell_area).astype(np.float32)

    return depth_grid


def compute_comparison_metrics(
    depth_a: np.ndarray,
    depth_b: np.ndarray,
    label_a: str = "SPH",
    label_b: str = "Delft3D",
    depth_threshold: float = 0.1,
) -> Dict:
    """
    Compute comparison metrics between two depth fields.

    Args:
        depth_a: 2D depth array from model A (e.g., SPH).
        depth_b: 2D depth array from model B (e.g., Delft3D).
        label_a: Label for model A.
        label_b: Label for model B.
        depth_threshold: Wet cell threshold (m).

    Returns:
        Dict with: rmse, bias, csi, f1, wet_area_a, wet_area_b, overlap_pct.
    """
    a = np.asarray(depth_a, dtype=np.float32).ravel()
    b = np.asarray(depth_b, dtype=np.float32).ravel()

    # Ensure same size (pad shorter)
    min_len = min(len(a), len(b))
    a = a[:min_len]
    b = b[:min_len]

    # RMSE
    rmse = float(np.sqrt(np.mean((a - b) ** 2)))

    # Bias (mean difference)
    bias = float(np.mean(a - b))

    # Binary classification metrics
    wet_a = a >= depth_threshold
    wet_b = b >= depth_threshold

    tp = np.sum(wet_a & wet_b)
    fp = np.sum(~wet_a & wet_b)
    fn = np.sum(wet_a & ~wet_b)
    tn = np.sum(~wet_a & ~wet_b)

    # CSI (Critical Success Index)
    csi_denom = tp + fp + fn
    csi = float(tp / csi_denom) if csi_denom > 0 else 1.0

    # F1-Score
    precision = float(tp / (tp + fp)) if (tp + fp) > 0 else 1.0
    recall = float(tp / (tp + fn)) if (tp + fn) > 0 else 1.0
    f1 = 2.0 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

    # Wet area
    cell_count_a = int(np.sum(wet_a))
    cell_count_b = int(np.sum(wet_b))
    overlap = int(tp)
    overlap_pct = 100.0 * overlap / max(cell_count_a, cell_count_b, 1)

    return {
        "rmse_m": round(rmse, 3),
        "bias_m": round(bias, 3),
        "csi": round(csi, 4),
        "f1": round(f1, 4),
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        f"wet_cells_{label_a}": cell_count_a,
        f"wet_cells_{label_b}": cell_count_b,
        "overlap_cells": overlap,
        "overlap_pct": round(overlap_pct, 1),
        "label_a": label_a,
        "label_b": label_b,
    }


def compare_gauge_arrivals(
    arrivals_a: Dict[str, Dict],
    arrivals_b: Dict[str, Dict],
    label_a: str = "SPH",
    label_b: str = "Delft3D",
) -> List[Dict]:
    """
    Compare gauge arrival times between two models.

    Args:
        arrivals_a: Gauge arrival times from model A.
        arrivals_b: Gauge arrival times from model B.
        label_a: Label for model A.
        label_b: Label for model B.

    Returns:
        List of dicts with: gauge, arrival_a_min, arrival_b_min, delta_min, delta_pct.
    """
    all_gauges = set(list(arrivals_a.keys()) + list(arrivals_b.keys()))
    rows = []

    for gauge in sorted(all_gauges):
        a_data = arrivals_a.get(gauge, {})
        b_data = arrivals_b.get(gauge, {})

        a_min = a_data.get("median_min")
        b_min = b_data.get("median_min")

        if a_min is not None and b_min is not None:
            delta = a_min - b_min
            delta_pct = 100.0 * abs(delta) / max(a_min, b_min, 0.01)
        else:
            delta = None
            delta_pct = None

        rows.append({
            "gauge": gauge,
            f"arrival_{label_a}_min": a_min,
            f"arrival_{label_b}_min": b_min,
            "delta_min": round(delta, 1) if delta is not None else None,
            "delta_pct": round(delta_pct, 1) if delta_pct is not None else None,
            "distance_km": a_data.get("distance_km") or b_data.get("distance_km"),
        })

    return rows


def plot_comparison_depth_maps(
    depth_a: np.ndarray,
    depth_b: np.ndarray,
    label_a: str = "SPH Near-Field",
    label_b: str = "Delft3D Far-Field",
    vmax: Optional[float] = None,
) -> plt.Figure:
    """
    Create side-by-side depth map comparison figure.

    Args:
        depth_a: 2D depth array from model A.
        depth_b: 2D depth array from model B.
        label_a: Title for left panel.
        label_b: Title for right panel.
        vmax: Max depth for colour scale.

    Returns:
        matplotlib Figure.
    """
    if vmax is None:
        vmax = max(np.nanmax(depth_a), np.nanmax(depth_b), 1.0)

    fig, (ax1, ax2, ax3) = plt.subplots(1, 3, figsize=(18, 6))

    # Model A
    im1 = ax1.imshow(depth_a, cmap="Blues", vmin=0, vmax=vmax, aspect="auto")
    ax1.set_title(label_a, fontsize=14, fontweight="bold")
    ax1.set_xlabel("Cell X")
    ax1.set_ylabel("Cell Y")
    plt.colorbar(im1, ax=ax1, label="Depth (m)")

    # Model B
    im2 = ax2.imshow(depth_b, cmap="Blues", vmin=0, vmax=vmax, aspect="auto")
    ax2.set_title(label_b, fontsize=14, fontweight="bold")
    ax2.set_xlabel("Cell X")
    plt.colorbar(im2, ax=ax2, label="Depth (m)")

    # Difference
    # Align shapes
    min_y = min(depth_a.shape[0], depth_b.shape[0])
    min_x = min(depth_a.shape[1], depth_b.shape[1])
    diff = depth_a[:min_y, :min_x] - depth_b[:min_y, :min_x]

    max_diff = max(abs(np.nanmin(diff)), abs(np.nanmax(diff)), 0.1)
    im3 = ax3.imshow(diff, cmap="RdBu_r", vmin=-max_diff, vmax=max_diff, aspect="auto")
    ax3.set_title(f"Difference ({label_a} − {label_b})", fontsize=14, fontweight="bold")
    ax3.set_xlabel("Cell X")
    plt.colorbar(im3, ax=ax3, label="Depth Difference (m)")

    plt.tight_layout()
    return fig


def plot_comparison_hydrographs(
    arrivals_a: Dict[str, Dict],
    arrivals_b: Dict[str, Dict],
    label_a: str = "SPH",
    label_b: str = "Delft3D",
) -> plt.Figure:
    """
    Create overlay hydrograph comparison at each gauge.

    Args:
        arrivals_a: Gauge arrival dicts from model A.
        arrivals_b: Gauge arrival dicts from model B.
        label_a: Legend label for model A.
        label_b: Legend label for model B.

    Returns:
        matplotlib Figure.
    """
    all_gauges = sorted(set(list(arrivals_a.keys()) + list(arrivals_b.keys())))
    n_gauges = len(all_gauges)

    if n_gauges == 0:
        fig, ax = plt.subplots(1, 1, figsize=(8, 4))
        ax.text(0.5, 0.5, "No gauge data available", ha="center", va="center")
        return fig

    fig, axes = plt.subplots(1, n_gauges, figsize=(5 * n_gauges, 5), squeeze=False)

    for idx, gauge in enumerate(all_gauges):
        ax = axes[0, idx]

        # Synthetic hydrograph shape (triangular pulse)
        for data, label, color in [
            (arrivals_a.get(gauge, {}), label_a, "#1565C0"),
            (arrivals_b.get(gauge, {}), label_b, "#E53935"),
        ]:
            median_min = data.get("median_min")
            if median_min is None:
                continue

            p05 = data.get("p05_min", median_min * 0.8)
            p95 = data.get("p95_min", median_min * 1.2)

            # Generate synthetic hydrograph (triangular)
            t = np.linspace(0, median_min * 3, 200)
            rise = np.where(t < median_min, t / median_min, 0.0)
            fall = np.where(t >= median_min, np.exp(-(t - median_min) / (median_min * 0.5)), 0.0)
            q = (rise + fall) * 100.0  # Normalised discharge

            ax.plot(t, q, color=color, linewidth=2, label=label)
            ax.axvline(median_min, color=color, linestyle="--", alpha=0.5, linewidth=1)
            ax.fill_betweenx([0, max(q) * 1.1], p05, p95, color=color, alpha=0.08)

        dist = arrivals_a.get(gauge, {}).get("distance_km") or arrivals_b.get(gauge, {}).get("distance_km", "?")
        ax.set_title(f"{gauge} ({dist} km)", fontsize=12, fontweight="bold")
        ax.set_xlabel("Time (min)")
        ax.set_ylabel("Discharge (norm.)")
        ax.legend(fontsize=9)
        ax.grid(True, alpha=0.3)

    plt.tight_layout()
    return fig


def compare_sph_vs_delft3d(
    sph_result: Dict,
    delft3d_result: Dict,
    gauge_locations: Optional[List[Dict]] = None,
) -> Dict:
    """
    Full SPH vs Delft3D comparison.

    Computes metrics, aligns grids, generates plots.

    Args:
        sph_result: Dict from SPH simulation.
        delft3d_result: Dict from run_delft3d_simulation().
        gauge_locations: Optional gauge list.

    Returns:
        Dict with:
            'metrics': comparison metrics dict
            'gauge_comparison': list of gauge arrival comparisons
            'depth_fig': matplotlib Figure of depth maps
            'hydro_fig': matplotlib Figure of hydrographs
            'sph_engine': str
            'delft3d_engine': str
    """
    # Get or generate depth fields
    grid_nx = delft3d_result.get("grid_nx", 100)
    grid_ny = delft3d_result.get("grid_ny", 200)
    grid_dx = delft3d_result.get("grid_dx", 30.0)
    grid_dy = delft3d_result.get("grid_dy", 30.0)

    # SPH depth (rasterize particles)
    sph_depth = rasterize_sph_particles(sph_result, grid_nx, grid_ny, grid_dx, grid_dy)

    # Delft3D depth
    d3d_depth = delft3d_result.get("max_depth", np.zeros((grid_ny, grid_nx)))

    # Metrics
    metrics = compute_comparison_metrics(sph_depth, d3d_depth, "SPH", "Delft3D")

    # Gauge arrivals
    sph_arrivals = sph_result.get("gauge_arrivals", sph_result.get("arrival_times", {}))
    d3d_arrivals = delft3d_result.get("gauge_arrivals", {})
    gauge_comparison = compare_gauge_arrivals(sph_arrivals, d3d_arrivals, "SPH", "Delft3D")

    # Plots
    depth_fig = plot_comparison_depth_maps(sph_depth, d3d_depth)
    hydro_fig = plot_comparison_hydrographs(sph_arrivals, d3d_arrivals)

    return {
        "metrics": metrics,
        "gauge_comparison": gauge_comparison,
        "depth_fig": depth_fig,
        "hydro_fig": hydro_fig,
        # Named from the run, not hardcoded. The bare literal "SPH_WCSPH" that
        # used to sit here described a result that was np.random output.
        "sph_engine": sph_result.get("engine_label") or sph_result.get("engine"),
        "sph_error": None,
        # What the near-field run actually measured. These are the honest SPH
        # deliverables — the arrival-time column is not one of them, because a
        # few-hundred-metre domain cannot reach a gauge at 13 km.
        "sph_near_field": {
            "n_fluid": sph_result.get("n_fluid"),
            "particle_spacing_m": sph_result.get("particle_spacing_m"),
            "max_depth_m": sph_result.get("max_depth_m"),
            "max_speed_m_s": sph_result.get("max_speed_m_s"),
            "front_speed_m_s": sph_result.get("front_speed_m_s"),
            "front_advance_m": (
                sph_result["front_position_m"][-1] - sph_result["front_position_m"][0]
                if sph_result.get("front_position_m") else None),
            "duration_s": sph_result.get("duration_s"),
            "domain_length_m": sph_result.get("domain_length_m"),
            "wall_clock_s": sph_result.get("wall_clock_s"),
            "coupling": sph_result.get("coupling"),
            "reaches_downstream_gauges": sph_result.get("reaches_downstream_gauges", False),
        },
        "delft3d_engine": delft3d_result.get("engine", "unknown"),
        "delft3d_engine_label": delft3d_result.get("engine_label", "Unknown"),
        # Whether the OFFICIAL Delft3D FM binary produced these numbers, and if
        # not, why. Carried explicitly rather than inferred from the label
        # string, so the dashboard can render an unambiguous banner instead of
        # asking a reader to notice the wording (runner.run_delft3d_simulation).
        "delft3d_binary_used": bool(delft3d_result.get("delft3d_binary_used", False)),
        "delft3d_fallback_reason": delft3d_result.get("fallback_reason"),
        # How the Delft3D-side gauge arrivals were obtained. "ritter_celerity_estimate"
        # means a closed-form formula, not a reading from the simulation.
        "gauge_arrival_method": next(
            (v.get("method") for v in d3d_arrivals.values() if v.get("method")), None
        ),
    }
