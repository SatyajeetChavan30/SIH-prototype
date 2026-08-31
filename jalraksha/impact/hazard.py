"""
FD2320 hazard classification for dam-break inundation.

Implements the FD2320 framework for classifying flood hazard based on depth-velocity combinations.

This is the SINGLE source of truth for hazard classification used throughout:
- 2D map visualization (color coding)
- 3D keyframe overlay (same color scheme)
- Impact analysis (PAR, damage calculations)

Classification criteria (FD2320):
- Dry: h = 0 m
- Low: 0 < h ≤ 0.1 m AND v ≤ 0.5 m/s
- Moderate: 0.1 < h ≤ 0.5 m AND v ≤ 1.0 m/s
- Significant: 0.5 < h ≤ 2.0 m AND v ≤ 2.0 m/s
- Severe: 2.0 < h ≤ 5.0 m AND v ≤ 5.0 m/s
- Extreme: > 5.0 m OR v > 5.0 m/s
"""

import numpy as np
from typing import Dict, Any, Optional
from enum import Enum


class HazardLevel(Enum):
    """FD2320 hazard classification levels."""
    DRY = "dry"
    LOW = "low"
    MODERATE = "moderate"
    SIGNIFICANT = "significant"
    SEVERE = "severe"
    EXTREME = "extreme"


class HazardClassifier:
    """
    FD2320 hazard classifier for flood depth-velocity combinations.

    This class provides the SINGLE source of truth for hazard classification
    used consistently across 2D maps, 3D overlays, and impact analysis.
    """

    def __init__(self):
        """Initialize hazard classifier with FD2320 thresholds."""
        # FD2320 classification thresholds
        self.thresholds = {
            HazardLevel.LOW: {"min_depth": 0.1, "max_depth": 0.5, "max_velocity": 0.5},
            HazardLevel.MODERATE: {"min_depth": 0.5, "max_depth": 2.0, "max_velocity": 1.0},
            HazardLevel.SIGNIFICANT: {"min_depth": 2.0, "max_depth": 5.0, "max_velocity": 2.0},
            HazardLevel.SEVERE: {"min_depth": 5.0, "max_depth": 10.0, "max_velocity": 5.0},
            HazardLevel.EXTREME: {"min_depth": 10.0, "max_velocity": np.inf}
        }

        # Color mapping for visualization (consistent across 2D/3D)
        self.color_map = {
            HazardLevel.DRY: [128, 128, 128],  # Gray
            HazardLevel.LOW: [100, 200, 100],  # Light green
            HazardLevel.MODERATE: [255, 200, 0],  # Yellow/orange
            HazardLevel.SIGNIFICANT: [255, 100, 0],  # Orange/red
            HazardLevel.SEVERE: [255, 0, 0],  # Red
            HazardLevel.EXTREME: [150, 0, 150]  # Purple
        }

        # Hazard weights for impact calculations
        self.hazard_weights = {
            HazardLevel.DRY: 0.0,
            HazardLevel.LOW: 0.1,
            HazardLevel.MODERATE: 0.3,
            HazardLevel.SIGNIFICANT: 0.5,
            HazardLevel.SEVERE: 0.8,
            HazardLevel.EXTREME: 1.0
        }

    def classify(self, depth_grid: np.ndarray, velocity_grid: Optional[np.ndarray] = None) -> np.ndarray:
        """
        Classify flood hazard using FD2320 framework.

        Args:
            depth_grid: Water depth grid (meters)
            velocity_grid: Velocity grid (m/s). If None, assumes very low velocity.

        Returns:
            Classification grid with same shape as input, values are HazardLevel enum members
        """
        if velocity_grid is None:
            # Assume conservative low velocity for conservative classification
            velocity_grid = np.zeros_like(depth_grid)

        # Initialize output grid
        classification = np.full(depth_grid.shape, HazardLevel.DRY, dtype=object)

        # Apply FD2320 classification rules
        for hazard_level in [HazardLevel.LOW, HazardLevel.MODERATE, HazardLevel.SIGNIFICANT,
                           HazardLevel.SEVERE, HazardLevel.EXTREME]:
            thresholds = self.thresholds[hazard_level]

            # Depth conditions
            depth_min = depth_grid >= thresholds["min_depth"]
            if hazard_level != HazardLevel.EXTREME:
                depth_max = depth_grid < thresholds["max_depth"]
            else:
                depth_max = np.ones_like(depth_grid, dtype=bool)

            # Velocity condition
            velocity_ok = velocity_grid <= thresholds["max_velocity"]

            # Combine conditions
            condition = depth_min & depth_max & velocity_ok
            classification[condition] = hazard_level

        return classification

    def classify_depth_only(self, depth_grid: np.ndarray) -> np.ndarray:
        """
        Classify hazard based on depth only (assumes low velocity).

        Used when velocity data is unavailable.

        Args:
            depth_grid: Water depth grid (meters)

        Returns:
            Classification grid (HazardLevel enum)
        """
        classification = np.full(depth_grid.shape, HazardLevel.DRY, dtype=object)

        for hazard_level in [HazardLevel.LOW, HazardLevel.MODERATE, HazardLevel.SIGNIFICANT,
                           HazardLevel.SEVERE, HazardLevel.EXTREME]:
            thresholds = self.thresholds[hazard_level]

            depth_min = depth_grid >= thresholds["min_depth"]
            if hazard_level != HazardLevel.EXTREME:
                depth_max = depth_grid < thresholds["max_depth"]
            else:
                depth_max = np.ones_like(depth_grid, dtype=bool)

            # Conservative: assume velocity always meets velocity criteria
            condition = depth_min & depth_max
            classification[condition] = hazard_level

        return classification

    def get_color(self, hazard_level: HazardLevel) -> List[int]:
        """Get RGB color for hazard level (used for consistent visualization)."""
        return self.color_map.get(hazard_level, [128, 128, 128])

    def get_weight(self, hazard_level: HazardLevel) -> float:
        """Get hazard weight for impact calculations (0-1 scale)."""
        return self.hazard_weights.get(hazard_level, 0.0)

    def summarize(self, classification: np.ndarray) -> Dict[str, Any]:
        """Get summary statistics of hazard classification.

        Counts per HazardLevel explicitly (avoids sorting enum objects, which
        numpy.unique would attempt and which Enum does not support).
        """
        total_area = int(classification.size)

        summary = {}
        weighted_sum = 0.0
        for level in HazardLevel:
            count = int(np.sum(classification == level))
            if count == 0 and not summary and level != HazardLevel.DRY:
                # Still record every level for a stable schema.
                pass
            summary[level.value] = {
                "count": count,
                "percentage": float(count / total_area * 100) if total_area else 0.0,
                "color": self.get_color(level),
                "weight": self.get_weight(level),
            }
            weighted_sum += self.get_weight(level) * count

        summary["total_cells"] = total_area
        summary["total_area_percentage"] = 100.0
        summary["weighted_hazard_index"] = float(weighted_sum / total_area) if total_area else 0.0

        return summary

    def apply_to_rgb(self, classification: np.ndarray) -> np.ndarray:
        """
        Apply classification to RGB image (for 2D/3D visualization).

        This ensures 2D maps and 3D overlays use the EXACT same color mapping.
        """
        height, width = classification.shape
        rgb = np.zeros((height, width, 3), dtype=np.uint8)

        for i in range(height):
            for j in range(width):
                rgb[i, j] = self.get_color(classification[i, j])

        return rgb


# ── Functional wrappers (expected by tests / downstream consumers) ────────────

def compute_fd2320_hazard_rating(
    depth: np.ndarray,
    velocity_x: np.ndarray,
    velocity_y: np.ndarray,
) -> np.ndarray:
    """
    FD2320 hazard rating as a continuous scalar.

    HR = h * (|v| + 0.5) + 0.5

    This single continuous index is used by categorize_hazard_zones() to assign
    discrete FD2320 hazard classes. Conservative (velocity-agnostic only where
    velocity is zero).

    Args:
        depth: Water depth grid (m).
        velocity_x: Velocity x-component grid (m/s).
        velocity_y: Velocity y-component grid (m/s).

    Returns:
        Hazard-rating grid (float), same shape as input.
    """
    depth = np.asarray(depth, dtype=np.float64)
    velocity_x = np.asarray(velocity_x, dtype=np.float64)
    velocity_y = np.asarray(velocity_y, dtype=np.float64)
    v_mag = np.sqrt(velocity_x**2 + velocity_y**2)
    # FD2320 screening index: HR = h*(|v|+0.5)+0.5 for wet cells, 0 for dry.
    hr = np.where(depth > 0.0, depth * (v_mag + 0.5) + 0.5, 0.0)
    return hr


def categorize_hazard_zones(hazard_rating: np.ndarray) -> np.ndarray:
    """
    Map FD2320 hazard ratings to discrete classes.

    Class boundaries (HazardRating):
      0 = dry/low            HR < 0.75
      1 = moderate           0.75 <= HR < 1.25
      2 = significant        1.25 <= HR < 2.5
      3 = severe/extreme     HR >= 2.5

    Args:
        hazard_rating: Output of compute_fd2320_hazard_rating().

    Returns:
        Integer class grid (0-3), same shape as input.
    """
    hr = np.asarray(hazard_rating, dtype=np.float64)
    classes = np.zeros_like(hr, dtype=int)
    classes[hr >= 0.75] = 1
    classes[hr >= 1.25] = 2
    classes[hr >= 2.5] = 3
    return classes