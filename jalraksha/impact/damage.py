"""
Depth-Damage & Economic Loss Estimation Module (Phase 6).

Implements Joint Research Centre (JRC) depth-damage functions tailored for Asia/India:
  - Residential structures (JRC Residential Asia curve)
  - Commercial / Industrial structures
  - Infrastructure / Roads
  - Agricultural land

Fractional damage ratio r in [0, 1] as a function of water depth d (m):
  r(d) = d / (d + d_half)   or   empirical piecewise polynomial

References:
  Huizinga, J., de Moel, H. & Szewczyk, W. (2017)
  "Global flood depth-damage functions", JRC Technical Report, EUR 28552 EN.
"""

import numpy as np
from typing import Dict, Union


def compute_depth_damage(
    depth: np.ndarray,
    sector: str = "residential",
) -> np.ndarray:
    """
    Compute fractional damage ratio r in [0.0, 1.0] for a given depth array.

    Args:
        depth: 2D or 1D array of flood depth (m)
        sector: Sector name ('residential', 'commercial', 'industrial', 'infrastructure', 'agricultural')

    Returns:
        Array of damage ratios [0.0 to 1.0] matching input depth shape.
    """
    depth = np.maximum(0.0, np.asarray(depth, dtype=np.float32))

    sector_lower = sector.lower()

    if sector_lower in ("residential", "res"):
        # JRC Residential Asia curve: steep rise up to 2m depth, saturating at 6m
        # r = 1 - exp(-0.6 * d)
        damage = 1.0 - np.exp(-0.6 * depth)
    elif sector_lower in ("commercial", "com"):
        # JRC Commercial: r = 1 - exp(-0.5 * d)
        damage = 1.0 - np.exp(-0.5 * depth)
    elif sector_lower in ("industrial", "ind"):
        # JRC Industrial: r = 1 - exp(-0.4 * d)
        damage = 1.0 - np.exp(-0.4 * depth)
    elif sector_lower in ("infrastructure", "infra", "road"):
        # Infrastructure: slower onset, damage = min(1.0, 0.2 * d)
        damage = np.minimum(1.0, 0.25 * depth)
    elif sector_lower in ("agricultural", "agri", "crop"):
        # Agriculture: rapid damage even at low depth, saturates at 1.5m
        damage = np.minimum(1.0, 0.7 * depth)
    else:
        # Generic default
        damage = 1.0 - np.exp(-0.5 * depth)

    # Zero damage for depth < 0.05m
    damage[depth < 0.05] = 0.0

    return np.clip(damage, 0.0, 1.0).astype(np.float32)


def calculate_economic_loss(
    depth: np.ndarray,
    asset_value_grid: np.ndarray,
    sector: str = "residential",
    cell_area_m2: float = 400.0,
) -> Dict[str, float]:
    """
    Calculate total economic loss across grid.

    Args:
        depth: 2D flood depth array (m)
        asset_value_grid: 2D asset value density array (USD/m2 or INR/m2)
        sector: Sector type
        cell_area_m2: Area per cell (m2)

    Returns:
        Dict with total_loss, max_cell_loss, damaged_area_m2, mean_damage_ratio
    """
    depth = np.asarray(depth, dtype=np.float32)
    asset_val = np.asarray(asset_value_grid, dtype=np.float32)

    damage_ratios = compute_depth_damage(depth, sector=sector)
    loss_per_cell = damage_ratios * asset_val * cell_area_m2

    total_loss = float(np.sum(loss_per_cell))
    max_loss = float(np.max(loss_per_cell)) if loss_per_cell.size > 0 else 0.0
    damaged_cells = np.sum(depth >= 0.05)
    damaged_area = float(damaged_cells * cell_area_m2)
    mean_ratio = float(np.mean(damage_ratios[depth >= 0.05])) if damaged_cells > 0 else 0.0

    return {
        "total_loss": total_loss,
        "max_cell_loss": max_loss,
        "damaged_area_m2": damaged_area,
        "mean_damage_ratio": mean_ratio,
        "damaged_cell_count": int(damaged_cells),
    }
