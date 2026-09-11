"""
FD2320 flood hazard classification.

This is the SINGLE source of truth for hazard classification used throughout:
- 2D map visualization (color coding)
- 3D keyframe overlay (same color scheme)
- Hazard-class shapefile export (jalraksha.export.shapefile)
- Impact analysis (PAR, damage calculations)

THE HAZARD RATING
-----------------
Everything below derives from one continuous index:

    HR = depth * (|V| + 0.5) + DF

with depth in metres, |V| the depth-averaged speed in m/s, and DF the debris
factor. Classes are assigned by thresholding HR:

    HR < 0.75          low
    0.75 <= HR < 1.25  moderate
    1.25 <= HR < 2.50  significant
    HR >= 2.50         extreme

Cells drier than ``WET_THRESHOLD_M`` are ``dry`` and take HR = 0 regardless.

WHY ONE INDEX AND NOT A BAND TABLE
----------------------------------
This module previously carried a discrete (depth window x velocity ceiling)
table alongside the index above, and two other copies of the scheme lived in
jalraksha/export/shapefile.py and in the frontend. They disagreed: a cell
1.5 m deep was "moderate" on the dashboard and "high" in the exported
shapefile, both labelled FD2320.

The band table also inverted the role of velocity. It tested
``velocity <= max_velocity`` as one term of an AND with the depth window, so a
cell that exceeded a band's velocity ceiling fell OUT of that band without
being promoted into a higher one. A flow 3 m deep at 8 m/s matched no band at
all and was reported DRY. Velocity could only ever reduce hazard. In the index
form velocity enters as a positive term, so it can only raise HR.

THE DEBRIS FACTOR IS A CATEGORICAL INPUT, NOT A CONSTANT
--------------------------------------------------------
DF takes one of three published values by land use — 0 (open pasture), 0.5
(woodland, or depths below 0.25 m) and 1.0 (built-up, or urban debris
sources). It was hardcoded to 0.5 here, which silently fixed a categorical
input for every cell in every run. It is now a named parameter defaulting to
0.5, and this module deliberately does NOT infer it from land cover: that
mapping belongs beside the WorldCover legend in jalraksha.terrain.roughness
and does not exist yet.

DEPTH-ONLY CLASSIFICATION
-------------------------
When no velocity field is available, ``classify_depth_only`` evaluates the same
index at |V| = 0, giving HR = 0.5*depth + DF. At the default DF the class
boundaries fall at depths of 0.5 m, 1.5 m and 4.0 m. This is stated so a reader
of a depth-only hazard map knows exactly what it means; it is not a second
scheme.

References:
  - Defra / Environment Agency (2006). "Flood Risks to People, Phase 2:
    The Flood Risks to People Methodology." R&D Technical Report FD2320/TR1.
    HR = d(v + 0.5) + DF, the DF categories, and the 0.75 / 1.25 / 2.5 class
    boundaries are from that report.
"""

from enum import Enum
from typing import Any, Dict, List, Optional

import numpy as np

# Depth below which a cell is reported dry (m).
#
# Matches Result.wet_mask in jalraksha.solver.types: deliberately well above
# the solver's numerical h_dry (1e-6 m) so a published envelope is not
# sensitive to the wetting-front tolerance. A 5 cm sheet is below any
# depth-damage threshold but is a defensible "was wet" criterion.
WET_THRESHOLD_M = 0.05

# Debris factor (dimensionless). Defra FD2320 categories:
#   0.0  open pasture, no debris source
#   0.5  woodland, or any land use where depth < 0.25 m
#   1.0  built-up areas, or depth >= 0.25 m with an urban debris source
# 0.5 is the mid category and the screening default.
DEBRIS_FACTOR_DEFAULT = 0.5

# Class boundaries on HR (Defra FD2320).
HR_MODERATE = 0.75
HR_SIGNIFICANT = 1.25
HR_EXTREME = 2.50


class HazardLevel(Enum):
    """
    FD2320 hazard classes.

    Four wet categories, matching the published scheme. An earlier version of
    this module carried a fifth level, "severe", between significant and
    extreme. FD2320 defines no such category and publishes no boundary that
    would separate it from extreme, so it has been retired rather than given
    an invented threshold.
    """

    DRY = "dry"
    LOW = "low"
    MODERATE = "moderate"
    SIGNIFICANT = "significant"
    EXTREME = "extreme"


def hazard_rating(
    depth: np.ndarray,
    speed: np.ndarray,
    debris_factor: float = DEBRIS_FACTOR_DEFAULT,
    wet_threshold_m: float = WET_THRESHOLD_M,
) -> np.ndarray:
    """
    FD2320 hazard rating from depth and speed magnitude.

        HR = depth * (speed + 0.5) + debris_factor   where depth >= wet
        HR = 0                                        where dry

    Args:
        depth: Water depth (m).
        speed: Depth-averaged speed magnitude |V| (m/s).
        debris_factor: DF, one of 0.0 / 0.5 / 1.0 (see module docstring).
        wet_threshold_m: Depth below which a cell is dry (m).

    Returns:
        Hazard-rating grid (float64), same shape as ``depth``.
    """
    depth = np.asarray(depth, dtype=np.float64)
    speed = np.asarray(speed, dtype=np.float64)
    wet = depth >= wet_threshold_m
    return np.where(wet, depth * (speed + 0.5) + debris_factor, 0.0)


def classify_hazard_rating(hazard_rating_grid: np.ndarray) -> np.ndarray:
    """
    Map an HR grid onto HazardLevel members.

    Args:
        hazard_rating_grid: Output of ``hazard_rating``. HR of exactly 0 marks
            a dry cell, which is how ``hazard_rating`` encodes dryness.

    Returns:
        Object array of HazardLevel, same shape as the input.
    """
    hr = np.asarray(hazard_rating_grid, dtype=np.float64)
    classification = np.full(hr.shape, HazardLevel.DRY, dtype=object)
    classification[hr > 0.0] = HazardLevel.LOW
    classification[hr >= HR_MODERATE] = HazardLevel.MODERATE
    classification[hr >= HR_SIGNIFICANT] = HazardLevel.SIGNIFICANT
    classification[hr >= HR_EXTREME] = HazardLevel.EXTREME
    return classification


class HazardClassifier:
    """
    FD2320 hazard classifier.

    Wraps ``hazard_rating`` + ``classify_hazard_rating`` and adds the colour
    map and weights used by the 2D map, the 3D keyframe overlay and the
    summary payload, so all three cannot drift apart.
    """

    def __init__(
        self,
        debris_factor: float = DEBRIS_FACTOR_DEFAULT,
        wet_threshold_m: float = WET_THRESHOLD_M,
    ):
        """
        Args:
            debris_factor: DF applied to every cell (see module docstring).
            wet_threshold_m: Depth below which a cell is reported dry (m).
        """
        self.debris_factor = float(debris_factor)
        self.wet_threshold_m = float(wet_threshold_m)

        # Colour mapping for visualization (consistent across 2D/3D).
        self.color_map = {
            HazardLevel.DRY: [128, 128, 128],  # Gray
            HazardLevel.LOW: [100, 200, 100],  # Light green
            HazardLevel.MODERATE: [255, 200, 0],  # Yellow/orange
            HazardLevel.SIGNIFICANT: [255, 100, 0],  # Orange/red
            HazardLevel.EXTREME: [150, 0, 150],  # Purple
        }

        # TODO: UNVETTED — these weights drive weighted_hazard_index() below,
        # which reaches the impact payload and the dashboard. FD2320 publishes
        # hazard CLASSES, not a weighting between them; no source has been
        # identified for these six numbers. Do not quote weighted_hazard_index
        # as an FD2320 quantity until one is.
        self.hazard_weights = {
            HazardLevel.DRY: 0.0,
            HazardLevel.LOW: 0.1,
            HazardLevel.MODERATE: 0.3,
            HazardLevel.SIGNIFICANT: 0.5,
            HazardLevel.EXTREME: 1.0,
        }

    def classify(
        self,
        depth_grid: np.ndarray,
        velocity_x: Optional[np.ndarray] = None,
        velocity_y: Optional[np.ndarray] = None,
    ) -> np.ndarray:
        """
        Classify flood hazard from depth and (optionally) velocity components.

        Args:
            depth_grid: Water depth grid (m).
            velocity_x, velocity_y: Velocity COMPONENTS (m/s). Pass both or
                neither; passing neither takes the speed as zero, which is
                ``classify_depth_only``.

        Returns:
            Object array of HazardLevel, same shape as ``depth_grid``.

        Raises:
            ValueError: if exactly one velocity component is supplied. An
                earlier signature took a single velocity MAGNITUDE as the
                second argument, so accepting one component here would let such
                a call through while silently classifying it at zero speed —
                i.e. under-stating the hazard rather than failing. Callers
                holding a magnitude want ``classify_from_speed``.
        """
        depth_grid = np.asarray(depth_grid, dtype=np.float64)
        if (velocity_x is None) != (velocity_y is None):
            raise ValueError(
                "classify() takes velocity COMPONENTS: pass both velocity_x "
                "and velocity_y, or neither. If you hold a speed magnitude "
                "(the solver's v_max is one), call classify_from_speed()."
            )
        if velocity_x is None:
            speed = np.zeros_like(depth_grid)
        else:
            speed = np.hypot(
                np.asarray(velocity_x, dtype=np.float64),
                np.asarray(velocity_y, dtype=np.float64),
            )
        return self.classify_from_speed(depth_grid, speed)

    def classify_from_speed(
        self, depth_grid: np.ndarray, speed_grid: np.ndarray
    ) -> np.ndarray:
        """
        Classify from depth and a speed MAGNITUDE.

        The solver's running maximum is already a magnitude
        (jalraksha.solver.parallel accumulates np.hypot(u, v)), so callers
        holding ``v_max`` want this entry point rather than ``classify``.

        Args:
            depth_grid: Water depth grid (m).
            speed_grid: Speed magnitude |V| (m/s).

        Returns:
            Object array of HazardLevel.
        """
        hr = hazard_rating(
            depth_grid, speed_grid, self.debris_factor, self.wet_threshold_m
        )
        return classify_hazard_rating(hr)

    def classify_depth_only(self, depth_grid: np.ndarray) -> np.ndarray:
        """
        Classify from depth alone, taking |V| = 0.

        HR reduces to 0.5*depth + DF, so at the default debris factor of 0.5
        the class boundaries fall at depths of:

            0.5 m   low -> moderate
            1.5 m   moderate -> significant
            4.0 m   significant -> extreme

        This UNDER-states hazard wherever the flow is fast, which is the whole
        near-field. Use ``classify`` or ``classify_from_speed`` when a velocity
        field exists.

        Args:
            depth_grid: Water depth grid (m).

        Returns:
            Object array of HazardLevel.
        """
        depth_grid = np.asarray(depth_grid, dtype=np.float64)
        return self.classify_from_speed(depth_grid, np.zeros_like(depth_grid))

    def get_color(self, hazard_level: HazardLevel) -> List[int]:
        """Get RGB color for hazard level (used for consistent visualization)."""
        return self.color_map.get(hazard_level, [128, 128, 128])

    def get_weight(self, hazard_level: HazardLevel) -> float:
        """Get hazard weight for impact calculations (0-1 scale). UNVETTED."""
        return self.hazard_weights.get(hazard_level, 0.0)

    def summarize(self, classification: np.ndarray) -> Dict[str, Any]:
        """
        Summary statistics of a hazard classification.

        Counts per HazardLevel explicitly (avoids sorting enum objects, which
        numpy.unique would attempt and which Enum does not support). Every
        level is recorded even at zero count, so the payload schema is stable.
        """
        total_area = int(classification.size)

        summary: Dict[str, Any] = {}
        weighted_sum = 0.0
        for level in HazardLevel:
            count = int(np.sum(classification == level))
            summary[level.value] = {
                "count": count,
                "percentage": float(count / total_area * 100) if total_area else 0.0,
                "color": self.get_color(level),
                "weight": self.get_weight(level),
            }
            weighted_sum += self.get_weight(level) * count

        summary["total_cells"] = total_area
        summary["total_area_percentage"] = 100.0
        summary["weighted_hazard_index"] = (
            float(weighted_sum / total_area) if total_area else 0.0
        )
        summary["debris_factor"] = self.debris_factor
        summary["scheme"] = "FD2320 HR = d(|V|+0.5)+DF, classed 0.75/1.25/2.5"

        return summary

    def apply_to_rgb(self, classification: np.ndarray) -> np.ndarray:
        """
        Apply classification to an RGB image (for 2D/3D visualization).

        This ensures 2D maps and 3D overlays use the EXACT same colour mapping.
        """
        height, width = classification.shape
        rgb = np.zeros((height, width, 3), dtype=np.uint8)

        for level, color in self.color_map.items():
            rgb[classification == level] = color

        return rgb


# ── Functional wrappers (expected by tests / downstream consumers) ────────────


def compute_fd2320_hazard_rating(
    depth: np.ndarray,
    velocity_x: np.ndarray,
    velocity_y: np.ndarray,
    debris_factor: float = DEBRIS_FACTOR_DEFAULT,
    wet_threshold_m: float = WET_THRESHOLD_M,
) -> np.ndarray:
    """
    FD2320 hazard rating from depth and velocity COMPONENTS.

        HR = depth * (|V| + 0.5) + DF

    Args:
        depth: Water depth grid (m).
        velocity_x: Velocity x-component grid (m/s).
        velocity_y: Velocity y-component grid (m/s).
        debris_factor: DF, one of 0.0 / 0.5 / 1.0 (see module docstring).
        wet_threshold_m: Depth below which a cell is dry (m).

    Returns:
        Hazard-rating grid (float64), same shape as input.
    """
    speed = np.hypot(
        np.asarray(velocity_x, dtype=np.float64),
        np.asarray(velocity_y, dtype=np.float64),
    )
    return hazard_rating(depth, speed, debris_factor, wet_threshold_m)


def compute_fd2320_hazard_rating_from_speed(
    depth: np.ndarray,
    speed: np.ndarray,
    debris_factor: float = DEBRIS_FACTOR_DEFAULT,
    wet_threshold_m: float = WET_THRESHOLD_M,
) -> np.ndarray:
    """
    FD2320 hazard rating from depth and a speed MAGNITUDE.

    For callers holding the solver's ``v_max``, which is already
    np.hypot(u, v) — see jalraksha.solver.parallel.

    Args:
        depth: Water depth grid (m).
        speed: Speed magnitude |V| (m/s).
        debris_factor: DF, one of 0.0 / 0.5 / 1.0.
        wet_threshold_m: Depth below which a cell is dry (m).

    Returns:
        Hazard-rating grid (float64), same shape as input.
    """
    return hazard_rating(depth, speed, debris_factor, wet_threshold_m)


def categorize_hazard_zones(hazard_rating_grid: np.ndarray) -> np.ndarray:
    """
    Map FD2320 hazard ratings to discrete integer classes.

    Class boundaries (Defra FD2320):
      0 = dry / low          HR < 0.75
      1 = moderate           0.75 <= HR < 1.25
      2 = significant        1.25 <= HR < 2.5
      3 = extreme            HR >= 2.5

    Note that class 0 merges dry and low. Callers needing them apart should use
    ``classify_hazard_rating``, which keeps DRY distinct at HR = 0.

    Args:
        hazard_rating_grid: Output of compute_fd2320_hazard_rating().

    Returns:
        Integer class grid (0-3), same shape as input.
    """
    hr = np.asarray(hazard_rating_grid, dtype=np.float64)
    classes = np.zeros_like(hr, dtype=int)
    classes[hr >= HR_MODERATE] = 1
    classes[hr >= HR_SIGNIFICANT] = 2
    classes[hr >= HR_EXTREME] = 3
    return classes
