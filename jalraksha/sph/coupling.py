"""
1-Way SWE -> SPH Coupling & Free-Surface Handoff Module (Phase 7).

Implements 1-way domain decomposition coupling:
  1. Handoff breach hydrograph discharge Q(t) and depth h(t) from SWE solver
     to drive near-field SPH particle inflow boundary.
  2. Extract free-surface elevation and particle velocity profile at SPH near-field boundary.

References:
  - Maranzoni & Tomirotti (2023) "3D Numerical Modelling of Real-Field Dam-Break Flows", Water.
  - Vacondio et al. (2020) "Grand challenges for SPH numerical schemes", CPM.
"""

import numpy as np
from typing import Dict, Tuple, Optional
from jalraksha.sph.domain import NearFieldDomain
from jalraksha.sph.core import SPHNearFieldSolver


def handoff_swe_to_sph(
    q_breach_m3_s: float,
    h_breach_m: float,
    near_field_domain: NearFieldDomain,
    breach_width_m: float = 50.0,
) -> NearFieldDomain:
    """
    Inject inflow particles into SPH near-field domain based on SWE breach discharge Q and depth h.

    One-way coupling: SWE passes (Q, h) at breach boundary -> SPH inflow particle velocity:
      u_inflow = Q / (h * width)

    Args:
        q_breach_m3_s: Outflow discharge from SWE breach solver (m3/s)
        h_breach_m: Water depth at breach cell (m)
        near_field_domain: NearFieldDomain instance
        breach_width_m: Width of breach opening (m)

    Returns:
        Updated NearFieldDomain instance
    """
    d = near_field_domain

    if h_breach_m <= 0.01 or q_breach_m3_s <= 0.0:
        return d

    # Compute inflow velocity required to sustain discharge Q
    u_inflow = float(q_breach_m3_s / (h_breach_m * breach_width_m))

    # Apply velocity update to near-field inflow particles near breach center
    breach_mask = (d.pid == 0) & (np.abs(d.x - d.center_x) < breach_width_m / 2.0)
    d.u[breach_mask] = u_inflow
    d.z[breach_mask] = np.maximum(d.z[breach_mask], d.bed_elevation + h_breach_m)

    return d


def extract_sph_free_surface(
    domain: NearFieldDomain,
    grid_res_m: float = 10.0,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Extract 2D free-surface depth map h[ny, nx] from SPH 3D particle positions.

    Args:
        domain: NearFieldDomain instance
        grid_res_m: Resolution of output depth grid (m)

    Returns:
        Tuple of (x_grid, y_grid, depth_2d)
    """
    fluid_mask = domain.pid == 0
    if not np.any(fluid_mask):
        dummy_grid = np.zeros((5, 5), dtype=np.float32)
        return (np.zeros(5), np.zeros(5), dummy_grid)

    x_f = domain.x[fluid_mask]
    y_f = domain.y[fluid_mask]
    z_f = domain.z[fluid_mask]

    min_x, max_x = np.min(x_f), np.max(x_f)
    min_y, max_y = np.min(y_f), np.max(y_f)

    xs = np.arange(min_x, max_x + grid_res_m, grid_res_m)
    ys = np.arange(min_y, max_y + grid_res_m, grid_res_m)

    depth_2d = np.zeros((len(ys), len(xs)), dtype=np.float32)

    for i, x_val in enumerate(xs):
        for j, y_val in enumerate(ys):
            cell_mask = (np.abs(x_f - x_val) <= grid_res_m / 2.0) & (np.abs(y_f - y_val) <= grid_res_m / 2.0)
            if np.any(cell_mask):
                max_z = np.max(z_f[cell_mask])
                depth_2d[j, i] = max(0.0, max_z - domain.bed_elevation)

    return (xs, ys, depth_2d)
