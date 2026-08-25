"""
Hydrograph & Hazard Visualization Plots Module (Phase 10).

Provides Matplotlib figure generators for Streamlit and report exports:
  - Downstream gauge arrival time summary bar plot
  - Ensemble peak outflow hydrographs
  - FD2320 Hazard class breakdown chart
"""

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from typing import Dict, List, Optional


def plot_arrival_hydrographs(
    arrival_times_dict: Dict[str, Dict],
    title: str = "Downstream Flood Arrival Times",
) -> plt.Figure:
    """
    Generate bar plot of downstream gauge median & 5th-95th percentile arrival times.

    Args:
        arrival_times_dict: Dict from run_dam_break_ensemble()
        title: Plot title

    Returns:
        Matplotlib Figure object
    """
    fig, ax = plt.subplots(figsize=(8, 4.5))

    names = []
    medians = []
    p05_err = []
    p95_err = []

    for name, data in arrival_times_dict.items():
        if isinstance(data, dict) and data.get("median") is not None:
            names.append(name)
            med_min = data["median"] / 60.0
            p05_min = data.get("p05", data["median"]) / 60.0
            p95_min = data.get("p95", data["median"]) / 60.0

            medians.append(med_min)
            p05_err.append(max(0.0, med_min - p05_min))
            p95_err.append(max(0.0, p95_min - med_min))

    if not names:
        ax.text(0.5, 0.5, "No gauge arrival data available", ha="center", va="center")
        ax.set_axis_off()
        return fig

    x_pos = np.arange(len(names))
    yerr = np.array([p05_err, p95_err])

    bars = ax.bar(x_pos, medians, yerr=yerr, capsize=5, color="#1f77b4", alpha=0.85, edgecolor="#0d47a1")

    ax.set_xticks(x_pos)
    ax.set_xticklabels(names, fontweight="bold")
    ax.set_ylabel("Arrival Time (minutes)", fontweight="bold")
    ax.set_title(title, fontweight="bold")
    ax.grid(axis="y", linestyle="--", alpha=0.5)

    for bar, val in zip(bars, medians):
        ax.text(bar.get_x() + bar.get_width() / 2.0, val / 2.0, f"{val:.1f} min", ha="center", va="center", color="white", fontweight="bold")

    plt.tight_layout()
    return fig


def plot_hazard_breakdown(
    exposed_by_class: Dict[str, Dict],
    title: str = "FD2320 Hazard Class Exposure",
) -> plt.Figure:
    """
    Generate pie chart of population exposure across FD2320 hazard rating classes.

    Args:
        exposed_by_class: Dict from compute_population_exposure()
        title: Plot title

    Returns:
        Matplotlib Figure object
    """
    fig, ax = plt.subplots(figsize=(6, 5))

    labels = []
    sizes = []
    colors = ["#4caf50", "#ffeb3b", "#ff9800", "#f44336"]  # Low, Moderate, High, Extreme

    for i, (cls_name, data) in enumerate(exposed_by_class.items()):
        pop = data.get("population", 0.0)
        labels.append(f"{cls_name}\n({pop:.0f} p)")
        sizes.append(max(0.0, pop))

    if sum(sizes) == 0:
        sizes = [1]
        labels = ["No Exposure"]
        colors = ["#cccccc"]

    ax.pie(sizes, labels=labels, colors=colors[:len(sizes)], autopct="%1.1f%%", startangle=140)
    ax.set_title(title, fontweight="bold")

    plt.tight_layout()
    return fig
