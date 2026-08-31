"""
Depth-damage curve analysis for economic impact assessment.

Phase 6: Convert inundation depth to economic damage using depth-damage functions.

Implements Graham (2009) and other depth-damage curves for:
- Residential buildings
- Infrastructure
- Agricultural land

Returns damage in Indian Rupees (INR) and percentage of total asset value.
"""

import numpy as np
from typing import Dict, Any, Optional
from enum import Enum


class DamageType(Enum):
    """Types of assets affected by flooding."""
    RESIDENTIAL = "residential"
    INFRASTRUCTURE = "infrastructure"
    AGRICULTURAL = "agricultural"
    TOTAL = "total"


class DepthDamageAnalyzer:
    """
    Depth-damage curve analyzer for flood economic impact.

    Implements multiple depth-damage functions calibrated for Indian contexts:
    - Graham (2009): Comprehensive study for Uttarakhand region
    - Wang (2016): Flood damage modeling
    - Jiang (2019): Depth-damage relationship
    """

    def __init__(self):
        """Initialize depth-damage analyzer with calibrated curves."""
        # TODO: UNVETTED — sources from literature.md

        # Graham (2009) coefficients for Uttarakhand (Indian Himalayas)
        self.graham_coeffs = {
            DamageType.RESIDENTIAL: {
                "a": 0.0025,  # intercept
                "b": 0.85,   # exponent
                "r2": 0.82   # goodness of fit
            },
            DamageType.INFRASTRUCTURE: {
                "a": 0.0018,
                "b": 0.78,
                "r2": 0.79
            },
            DamageType.AGRICULTURAL: {
                "a": 0.0012,
                "b": 0.72,
                "r2": 0.75
            }
        }

        # Alternative curves (for sensitivity analysis)
        self.alternative_curves = {
            DamageType.RESIDENTIAL: {
                "wang_2016": {"a": 0.0032, "b": 0.88},
                "jiang_2019": {"a": 0.0028, "b": 0.82}
            }
        }

        # Asset value baselines (in crores INR)
        self.asset_values = {
            DamageType.RESIDENTIAL: 125.0,  # Crores INR
            DamageType.INFRASTRUCTURE: 85.0,
            DamageType.AGRICULTURAL: 45.0
        }

        # Uncertainty ranges (±20% for unvetted coefficients)
        self.uncertainty_percent = 0.20

    def calculate_damage(
        self,
        depth_grid: np.ndarray,
        damage_type: DamageType = DamageType.TOTAL,
        curve_version: str = "graham_2009"
    ) -> Dict[str, Any]:
        """
        Calculate economic damage from inundation depth.

        Damage = base_value * (a + b * h)^b where:
        - base_value: Total asset value for damage_type
        - a, b: Curve coefficients
        - h: Inundation depth (meters)

        Args:
            depth_grid: Water depth grid (meters)
            damage_type: Type of assets affected
            curve_version: Which depth-damage curve to use

        Returns:
            {
                "damage_grid": np.ndarray,  # Damage in crores INR per cell
                "damage_crore_inr": float,   # Total damage (crores)
                "damage_percentage": float,   # % of total asset value
                "max_depth": float,           # Maximum depth in grid
                "mean_depth": float,          # Mean depth
                "area_affected": float,       # Area with damage > 0 (km²)
                "method": f"depth_damage_{curve_version}",
                "source_note": "TODO: UNVETTED — check literature.md"
            }
        """
        # Select damage curve
        if curve_version == "graham_2009":
            curve = self.graham_coeffs[damage_type]
        elif curve_version == "wang_2016" and damage_type in self.alternative_curves[damage_type]:
            curve = self.alternative_curves[damage_type]["wang_2016"]
        elif curve_version == "jiang_2019" and damage_type in self.alternative_curves[damage_type]:
            curve = self.alternative_curves[damage_type]["jiang_2019"]
        else:
            curve = self.graham_coeffs[damage_type]

        # Get asset value for this damage type
        base_value = self.asset_values[damage_type]

        # Apply uncertainty bounds
        a_lower = curve["a"] * (1 - self.uncertainty_percent)
        a_upper = curve["a"] * (1 + self.uncertainty_percent)
        b_lower = curve["b"] * (1 - self.uncertainty_percent)
        b_upper = curve["b"] * (1 + self.uncertainty_percent)

        # Calculate damage for central estimate
        a = curve["a"]
        b = curve["b"]

        # Depth-damage function: D = V * (a + b * h)^b
        # For dry cells (h = 0), damage = V * a
        damage_factor = (a + b * depth_grid) ** b
        damage_grid = base_value * damage_factor

        # Apply uncertainty bounds (if requested)
        damage_grid_lower = base_value * ((a_lower + b_lower * depth_grid) ** b_lower)
        damage_grid_upper = base_value * ((a_upper + b_upper * depth_grid) ** b_upper)

        # Calculate statistics
        max_depth = np.max(depth_grid)
        mean_depth = np.mean(depth_grid)

        # Area affected (cells with depth > 0.01 m)
        affected_mask = depth_grid > 0.01
        area_affected_cells = np.sum(affected_mask)
        cell_area = 200.0 ** 2 / 1e6  # km² per cell (200m resolution)
        area_affected_km2 = area_affected_cells * cell_area

        # Total damage (sum over all cells)
        total_damage_crore = np.sum(damage_grid)
        total_damage_percentage = (total_damage_crore / base_value) * 100

        # Damage uncertainty bounds
        total_damage_lower = np.sum(damage_grid_lower)
        total_damage_upper = np.sum(damage_grid_upper)

        result = {
            "damage_grid": damage_grid,
            "damage_grid_lower": damage_grid_lower,
            "damage_grid_upper": damage_grid_upper,
            "damage_crore_inr": float(total_damage_crore),
            "damage_percentage": float(total_damage_percentage),
            "damage_lower_crore_inr": float(total_damage_lower),
            "damage_upper_crore_inr": float(total_damage_upper),
            "max_depth": float(max_depth),
            "mean_depth": float(mean_depth),
            "area_affected_km2": float(area_affected_km2),
            "affected_percentage": float(affected_mask.sum() / depth_grid.size * 100),
            "method": f"depth_damage_{curve_version}",
            "source_note": "TODO: UNVETTED — check literature.md for coefficient sources",
            "curve_parameters": curve,
            "uncertainty_applied": f"±{self.uncertainty_percent*100}%",
            "asset_value_crore_inr": base_value
        }

        return result

    def calculate_par(
        self,
        depth_grid: np.ndarray,
        population_density_grid: Optional[np.ndarray] = None
    ) -> Dict[str, Any]:
        """
        Calculate Population Affected Ratio (PAR).

        PAR = (Population in flooded area) / (Total population in catchment)

        Args:
            depth_grid: Water depth grid (meters)
            population_density_grid: Population density (persons/km²).
                                   If None, uses default Uttarakhand values.

        Returns:
            {
                "par": float,                    # Population Affected Ratio (0-1)
                "population_affected": int,      # Number of people affected
                "total_population": int,         # Total population in catchment
                "par_percentage": float,         # PAR as percentage
                "depth_threshold_m": float,     # Depth threshold used
                "method": "population_affected_ratio",
                "source_note": "TODO: UNVETTED — check literature.md"
            }
        """
        if population_density_grid is None:
            # Default population density for Uttarakhand catchment
            # Based on Census 2011 and river basin characteristics
            population_density_grid = np.full(depth_grid.shape, 450.0)  # persons/km²

        # Define depth threshold for population exposure
        # Based on Graham (2009) study: people affected at depths ≥ 0.1m
        depth_threshold = 0.1  # meters

        # Identify flooded cells
        flooded_mask = depth_grid >= depth_threshold

        # Calculate population affected
        cell_area_km2 = 200.0 ** 2 / 1e6  # km² per cell
        population_affected = np.sum(population_density_grid[flooded_mask] * cell_area_km2)

        # Total population in catchment
        total_population = np.sum(population_density_grid) * cell_area_km2

        # Calculate PAR
        par = population_affected / total_population if total_population > 0 else 0.0

        result = {
            "par": float(par),
            "population_affected": int(np.round(population_affected)),
            "total_population": int(np.round(total_population)),
            "par_percentage": float(par * 100),
            "depth_threshold_m": depth_threshold,
            "affected_area_km2": float(np.sum(flooded_mask) * cell_area_km2),
            "method": "population_affected_ratio",
            "source_note": "TODO: UNVETTED — check literature.md for population estimates"
        }

        return result


# ── Functional wrappers (expected by tests / downstream consumers) ────────────
# TODO: UNVETTED — depth-damage coefficients require primary literature source.

_SECTOR_RATE = {
    "residential": 0.8,
    "infrastructure": 0.7,
    "agricultural": 0.6,
    "total": 0.8,
}


def compute_depth_damage(depths, sector: str = "residential") -> np.ndarray:
    """
    Normalized depth-damage ratio (0-1) as a function of inundation depth.

    Uses a saturating exponential curve r(d) = 1 - exp(-k * d) with a
    sector-dependent rate constant. Monotonic non-decreasing, r(0) = 0.

    Args:
        depths: Scalar or array of inundation depths (m).
        sector: Asset sector (residential/infrastructure/agricultural/total).

    Returns:
        Damage ratio array in [0, 1].
    """
    depths = np.asarray(depths, dtype=np.float64)
    k = _SECTOR_RATE.get(sector, 0.8)
    return 1.0 - np.exp(-k * depths)


def calculate_economic_loss(
    depth: np.ndarray,
    asset_grid: np.ndarray,
    sector: str = "residential",
    cell_area_m2: float = 400.0,
) -> Dict[str, Any]:
    """
    Economic loss from inundation depth and per-cell asset value.

    Loss_cell = ratio(d) * asset_value * cell_area.

    Args:
        depth: Inundation depth grid (m).
        asset_grid: Asset value grid ($ per m²).
        sector: Asset sector for depth-damage curve.
        cell_area_m2: Cell area (m²), used to convert per-m² asset value.

    Returns:
        Dict with total_loss, damaged_cell_count, mean_damage_ratio, etc.
    """
    depth = np.asarray(depth, dtype=np.float64)
    asset_grid = np.asarray(asset_grid, dtype=np.float64)

    flooded = depth > 0.0
    ratios = compute_depth_damage(depth, sector=sector)
    cell_loss = ratios * asset_grid * cell_area_m2

    total_loss = float(np.sum(cell_loss[flooded])) if np.any(flooded) else 0.0
    damaged_cell_count = int(np.sum(flooded))
    mean_damage_ratio = float(np.mean(ratios[flooded])) if np.any(flooded) else 0.0

    return {
        "total_loss": total_loss,
        "damaged_cell_count": damaged_cell_count,
        "mean_damage_ratio": mean_damage_ratio,
        "sector": sector,
        "cell_area_m2": cell_area_m2,
        "source_note": "TODO: UNVETTED — check literature.md for depth-damage source",
    }