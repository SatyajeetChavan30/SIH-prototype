"""
Population impact assessment for dam-break simulations.

Phase 6+: Estimate population affected by inundation using:
- Population density grids (from census data)
- Settlement location data
- Vulnerability analysis

Returns PAR (Population Affected Ratio) and demographic breakdowns.
"""

import numpy as np
from typing import Dict, Any, List, Optional, Tuple
from enum import Enum


class DemographicGroup(Enum):
    """Demographic groups for vulnerability analysis."""
    CHILDREN = "children"
    ELDERLY = "elderly"
    WOMEN = "women"
    WORK_AGE = "working_age"


class PopulationEstimator:
    """
    Population impact analyzer for flood-affected areas.

    Estimates population exposure and vulnerability based on:
    - Settlement location data ( villages, towns)
    - Population density (census-based)
    - Demographic composition
    - Flood vulnerability factors
    """

    def __init__(self):
        """Initialize population estimator."""
        # TODO: UNVETTED — sources from literature.md

        # Settlement type data for Uttarakhand (based on census 2011)
        self.settlement_data = {
            "village": {
                "population_density": 400.0,  # persons/km²
                "vulnerability_multiplier": 1.2,  # Higher vulnerability
                "elderly_percentage": 12.0,
                "children_percentage": 18.0
            },
            "town": {
                "population_density": 1200.0,
                "vulnerability_multiplier": 1.0,
                "elderly_percentage": 10.0,
                "children_percentage": 15.0
            },
            "city": {
                "population_density": 4000.0,
                "vulnerability_multiplier": 0.8,  # Better infrastructure
                "elderly_percentage": 9.0,
                "children_percentage": 12.0
            }
        }

        # Exposure depth thresholds (meters)
        self.exposure_thresholds = {
            "minimal": 0.1,  # Minimal impact depth
            "moderate": 0.5,  # Significant impact
            "severe": 1.0,  # Severe impact
            "catastrophic": 2.0  # Catastrophic impact
        }

    def estimate_population(
        self,
        depth_grid: np.ndarray,
        settlement_grid: Optional[np.ndarray] = None,
        land_use_grid: Optional[np.ndarray] = None,
        cell_size_m: float = 200.0,
        allow_synthetic_settlements: bool = False,
    ) -> Dict[str, Any]:
        """
        Estimate population affected by flood depth.

        PREFER compute_population_exposure() / compute_par() BELOW when a real
        per-cell population count is available (jalraksha.gee.population fetches
        GHSL onto the solver grid). Those take census-derived counts directly.
        This method instead infers density from settlement TYPE using the
        hardcoded per-type figures in __init__, every one of which is flagged
        UNVETTED — so it is a fallback for when no gridded population exists,
        not the preferred route to a population-at-risk number.

        Args:
            depth_grid: Water depth grid (meters)
            settlement_grid: Settlement type grid (0=village, 1=town, 2=city).
            land_use_grid: Land use classification (0=agricultural, 1=urban).
                          If None, assumes uniform land use.
            cell_size_m: Grid cell size (m). Used to convert density to counts.
                Previously hardcoded to 200 m, which silently scaled every
                population figure by (cell_size/200)^2 whenever a run used any
                other resolution.
            allow_synthetic_settlements: Permit fabricating a settlement layout
                when settlement_grid is None. Off by default: the synthesis is
                np.random over terrain and produces a population figure with no
                relationship to who actually lives there.

        Raises:
            ValueError: if settlement_grid is None and synthesis was not
                explicitly permitted.

        Returns:
            {
                "total_population": int,
                "population_affected": int,
                "par": float,  # Population Affected Ratio
                "par_percentage": float,
                "demographic_breakdown": {...},
                "vulnerability_index": float,
                "affected_settlement_types": [...],
                "depth_analysis": {...},
                "method": "settlement_based_population_estimation",
                "source_note": "TODO: UNVETTED — check literature.md"
            }
        """
        synthetic_settlements = settlement_grid is None
        if synthetic_settlements:
            if not allow_synthetic_settlements:
                raise ValueError(
                    "No settlement_grid supplied. Generating one places "
                    "villages and towns at random over the terrain, and the "
                    "population figure that follows describes nobody. Supply a "
                    "real grid (see jalraksha.gee.population for GHSL), or use "
                    "compute_population_exposure()/compute_par() with census "
                    "counts, or pass allow_synthetic_settlements=True if a "
                    "fabricated layout is genuinely what you want."
                )
            settlement_grid = self._generate_synthetic_settlements(depth_grid.shape)

        if land_use_grid is None:
            # Default to uniform land use
            land_use_grid = np.zeros(depth_grid.shape, dtype=int)

        # Get population density for each cell
        population_density = self._get_population_density(settlement_grid, land_use_grid)

        # Calculate total population in catchment
        cell_area_km2 = float(cell_size_m) ** 2 / 1e6  # km² per cell
        total_population = int(np.sum(population_density) * cell_area_km2)

        # Analyze population affected by depth
        depth_analysis = self._analyze_depth_impact(depth_grid, population_density, cell_area_km2)

        # Estimate demographic breakdown
        demographic_breakdown = self._estimate_demographics(depth_analysis["population_affected"])

        # Calculate vulnerability index
        vulnerability_index = self._calculate_vulnerability_index(
            depth_analysis, demographic_breakdown
        )

        result = {
            "total_population": total_population,
            "population_affected": depth_analysis["population_affected"],
            "par": float(depth_analysis["par"]),
            "par_percentage": float(depth_analysis["par_percentage"] * 100),
            "demographic_breakdown": demographic_breakdown,
            "vulnerability_index": vulnerability_index,
            "affected_settlement_types": depth_analysis["affected_settlement_types"],
            "depth_analysis": depth_analysis,
            "method": "settlement_based_population_estimation",
            "cell_size_m": float(cell_size_m),
            # Says which layout produced the number, rather than leaving a
            # reader to assume it came from data.
            "settlement_source": (
                "SYNTHETIC_random_layout" if synthetic_settlements
                else "caller_supplied_settlement_grid"),
            "source_note": (
                "TODO: UNVETTED — per-settlement-type densities and demographic "
                "splits in PopulationEstimator.__init__ have no primary source; "
                "see literature.md. For a census-derived figure use "
                "compute_par() with a GHSL population grid."
            ),
        }

        return result

    def _generate_synthetic_settlements(
        self, shape: Tuple[int, int]
    ) -> np.ndarray:
        """Generate synthetic settlement distribution based on terrain."""
        ny, nx = shape
        settlement_grid = np.zeros(shape, dtype=int)

        # Create settlement pattern based on river valley
        river_center_y = ny // 2
        river_width = ny // 8

        # River valley (high settlement)
        for i in range(ny):
            for j in range(nx):
                # Distance from river
                dist_from_river = abs(i - river_center_y)
                if dist_from_river <= river_width:
                    # Settlement probability higher near river
                    settlement_prob = 0.7 - (dist_from_river / river_width) * 0.5
                    if np.random.random() < settlement_prob:
                        # Assign settlement type based on distance
                        if dist_from_river <= river_width // 3:
                            settlement_grid[i, j] = 1  # Town
                        elif dist_from_river <= river_width // 2:
                            settlement_grid[i, j] = 0  # Village
                        else:
                            settlement_grid[i, j] = 2  # City

        return settlement_grid

    def _get_population_density(
        self,
        settlement_grid: np.ndarray,
        land_use_grid: np.ndarray
    ) -> np.ndarray:
        """Get population density for each cell based on settlement type and land use."""
        ny, nx = settlement_grid.shape
        population_density = np.zeros((ny, nx))

        for i in range(ny):
            for j in range(nx):
                settlement_type = settlement_grid[i, j]
                land_use = land_use_grid[i, j]

                if settlement_type in self.settlement_data:
                    base_density = self.settlement_data[settlement_type]["population_density"]

                    # Adjust for land use
                    if land_use == 1:  # Urban
                        density = base_density * 1.1
                    else:  # Agricultural
                        density = base_density * 0.9

                    # Apply vulnerability multiplier
                    vulnerability = self.settlement_data[settlement_type]["vulnerability_multiplier"]
                    population_density[i, j] = density * vulnerability

        return population_density

    def _analyze_depth_impact(
        self,
        depth_grid: np.ndarray,
        population_density: np.ndarray,
        cell_area_km2: float
    ) -> Dict[str, Any]:
        """Analyze population impact based on depth thresholds."""
        ny, nx = depth_grid.shape

        # Initialize analysis
        analysis = {
            "population_affected": 0,
            "par": 0.0,
            "par_percentage": 0.0,
            "affected_settlement_types": {},
            "depth_distribution": {}
        }

        # Analyze by depth thresholds
        for threshold_name, threshold in self.exposure_thresholds.items():
            # Identify cells exceeding threshold
            affected_mask = depth_grid >= threshold

            # Calculate population affected
            pop_affected = np.sum(population_density[affected_mask] * cell_area_km2)
            analysis["population_affected"] += int(np.round(pop_affected))

            # Track by settlement type
            for settlement_type, data in self.settlement_data.items():
                if settlement_type not in analysis["affected_settlement_types"]:
                    analysis["affected_settlement_types"][settlement_type] = 0

        # Calculate PAR (Population Affected Ratio)
        cell_area_km2 = 200.0 ** 2 / 1e6
        total_population = np.sum(population_density) * cell_area_km2
        analysis["population_affected"] = int(np.round(analysis["population_affected"]))
        analysis["par"] = analysis["population_affected"] / total_population if total_population > 0 else 0.0
        analysis["par_percentage"] = analysis["par"] * 100

        # Analyze depth distribution
        depth_hist, depth_bins = np.histogram(depth_grid, bins=10)
        analysis["depth_distribution"] = {
            "bins": depth_bins.tolist(),
            "counts": depth_hist.tolist()
        }

        return analysis

    def _estimate_demographics(
        self,
        total_affected_population: int
    ) -> Dict[str, Any]:
        """Estimate demographic breakdown of affected population."""
        if total_affected_population == 0:
            return {
                "children": 0,
                "elderly": 0,
                "women": 0,
                "working_age": 0,
                "total": 0
            }

        # Distribution based on national averages adjusted for Uttarakhand
        # Source: Census 2011, Sample Registration System
        demographics = {
            "children": int(total_affected_population * 0.18),  # 18% children
            "elderly": int(total_affected_population * 0.11),   # 11% elderly (65+)
            "women": int(total_affected_population * 0.48),    # 48% women
            "working_age": int(total_affected_population * 0.62) # 62% working age (15-59)
        }

        # Adjust for vulnerability multipliers
        demographics["children"] = int(demographics["children"] * 1.1)
        demographics["elderly"] = int(demographics["elderly"] * 1.3)
        demographics["women"] = int(demographics["women"] * 1.05)
        demographics["working_age"] = int(demographics["working_age"] * 0.9)

        demographics["total"] = sum(demographics.values())

        return demographics

    def _calculate_vulnerability_index(
        self,
        depth_analysis: Dict[str, Any],
        demographic_breakdown: Dict[str, int]
    ) -> float:
        """
        Calculate vulnerability index based on depth and demographics.

        Higher values indicate greater vulnerability.
        """
        # Base vulnerability from depth exposure
        depth_vulnerability = min(depth_analysis["par_percentage"] / 100, 1.0)

        # A flood that reaches nobody is a real and important result — an
        # inundation envelope over empty ground — not an error. Dividing by the
        # affected total unguarded raised ZeroDivisionError for exactly that
        # case; with no one exposed there is no demographic vulnerability to
        # weight, so it is zero.
        affected_total = demographic_breakdown.get("total", 0)
        if affected_total <= 0:
            demographic_vuln = 0.0
        else:
            demographic_vuln = (
                (demographic_breakdown["children"] / affected_total * 1.2) +
                (demographic_breakdown["elderly"] / affected_total * 1.5) +
                (demographic_breakdown["women"] / affected_total * 1.1)
            ) / 3.0

        # Combined vulnerability index
        vulnerability_index = (depth_vulnerability * 0.7 + demographic_vuln * 0.3)

        return float(vulnerability_index)


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

    arrived = np.isfinite(arrival_time_grid) & (arrival_time_grid > 0)
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
