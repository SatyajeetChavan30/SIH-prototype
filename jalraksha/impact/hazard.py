"""
FD2320 Hazard Rating & Classification Module (Phase 6).

Implements Defra/Environment Agency FD2320 flood hazard rating framework:
  HR = d * (v + 0.5) + DF

where:
  - d = water depth (m)
  - v = flow velocity magnitude (m/s)
  - DF = debris factor:
      - DF = 0.5  if d <= 0.25 m
      - DF = 1.0  if d <= 1.5 m (and v <= 2.0 m/s)
      - DF = 2.0  if d > 1.5 m or v > 2.0 m/s

Hazard Classes (FD2320 Table 3.2):
  - 0: Very Low / Low (< 0.75) — "Caution"
  - 1: Moderate (0.75 <= HR < 1.25) — "Dangerous for some"
  - 2: High (1.25 <= HR < 2.5) — "Dangerous for most"
  - 3: Extreme (HR >= 2.5) — "Dangerous for all"

References:
  Defra/Environment Agency (2006) FD2320/TR1 "Flood Risks to People"
"""

import numpy as np
from typing import Dict, Tuple


def compute_fd2320_hazard_rating(
    depth: np.ndarray,
    velocity_x: np.ndarray,
    velocity_y: np.ndarray,
    pasture_land: bool = False,
) -> np.ndarray:
    """
    Compute FD2320 hazard rating array HR[ny, nx].

    Args:
        depth: 2D array of water depth (m)
        velocity_x: 2D array of velocity in x direction (m/s)
        velocity_y: 2D array of velocity in y direction (m/s)
        pasture_land: If True, uses lower debris factor for open land

    Returns:
        2D array of hazard rating values (float32)
    """
    depth = np.asarray(depth, dtype=np.float32)
    vx = np.asarray(velocity_x, dtype=np.float32)
    vy = np.asarray(velocity_y, dtype=np.float32)

    v_mag = np.sqrt(vx**2 + vy**2)

    # Compute Debris Factor DF
    df = np.full_like(depth, 0.5, dtype=np.float32)

    if not pasture_land:
        # Standard urban/woodland debris factor
        mask_mid = (depth > 0.25) & (depth <= 1.5) & (v_mag <= 2.0)
        mask_high = (depth > 1.5) | (v_mag > 2.0)
        df[mask_mid] = 1.0
        df[mask_high] = 2.0
    else:
        # Pasture land: lower debris potential
        df[(depth > 0.25) & (depth <= 1.5)] = 0.5
        df[depth > 1.5] = 1.0

    # Dry cells have 0 hazard rating
    dry_mask = depth <= 0.001
    hr = depth * (v_mag + 0.5) + df
    hr[dry_mask] = 0.0

    return hr.astype(np.float32)


def categorize_hazard_zones(hr: np.ndarray) -> np.ndarray:
    """
    Categorize hazard rating into discrete FD2320 hazard classes (0, 1, 2, 3).

    Hazard Classes:
      0: Low (HR < 0.75) — Caution
      1: Moderate (0.75 <= HR < 1.25) — Dangerous for some
      2: High (1.25 <= HR < 2.5) — Dangerous for most
      3: Extreme (HR >= 2.5) — Dangerous for all

    Args:
        hr: 2D hazard rating array

    Returns:
        2D int32 array with hazard classes 0, 1, 2, 3 (dry cells = -1 or 0)
    """
    hr = np.asarray(hr, dtype=np.float32)
    hazard_class = np.zeros_like(hr, dtype=np.int32)

    hazard_class[(hr >= 0.75) & (hr < 1.25)] = 1
    hazard_class[(hr >= 1.25) & (hr < 2.5)] = 2
    hazard_class[hr >= 2.5] = 3

    return hazard_class
