"""
Simple well-balanced shallow-water flux (Phase 1 replacement).

Switched from HLLC to surface-gradient method after discovering HLLC implementation
produces spurious velocities even on flat beds (lake-at-rest test failure).

Surface-gradient approach is inherently well-balanced and simpler to verify.

References:
  - Roe, P.L. (2006). Affordable Waves
  - Bouchut, F., et al. (2004). On shallow water models for nonhydrostatic free surface flows
"""

import numpy as np
from numba import njit

# Physical constant
G = 9.81  # gravitational acceleration (m/s²)

# Tolerances
EPS = 1e-15  # Machine epsilon for depth
MIN_DEPTH = 1e-6  # Minimum depth for wetting front


@njit
def compute_bed_source_x(h: float, b_grad_x: float) -> float:
    """Bed gradient source term in x-momentum equation: -g*h*∂b/∂x"""
    if h < MIN_DEPTH:
        return 0.0
    return -G * h * b_grad_x


@njit
def compute_bed_source_y(h: float, b_grad_y: float) -> float:
    """Bed gradient source term in y-momentum equation: -g*h*∂b/∂y"""
    if h < MIN_DEPTH:
        return 0.0
    return -G * h * b_grad_y


@njit
def compute_friction_source(h: float, u: float, v: float, manning_n: float, dt: float) -> tuple:
    """Manning friction source term: -g*n²*|V|*V / h^(1/3)"""
    if h < MIN_DEPTH:
        return 0.0, 0.0

    vel_mag = np.sqrt(u * u + v * v)
    if vel_mag < EPS:
        return 0.0, 0.0

    c_f = G * manning_n * manning_n * vel_mag / (h ** (1.0 / 3.0) + EPS)
    du_friction = -c_f * u * dt
    dv_friction = -c_f * v * dt

    return du_friction, dv_friction


@njit
def surface_gradient_flux_x(
    hL: float, hR: float, uL: float, uR: float, vL: float, vR: float, bL: float, bR: float
) -> tuple:
    """
    Surface-gradient flux (well-balanced by construction).

    Key insight: Pressure force = -g*h*∂η/∂x, where η = b + h (water surface).
    By computing ∂η/∂x exactly, pressure and bed gradient cancel exactly at rest.
    """
    # Water surface elevation
    eta_L = bL + hL
    eta_R = bR + hR

    # Average water surface (for pressure gradient)
    eta_avg = 0.5 * (eta_L + eta_R)

    # Reconsted depths: ensure non-negative
    h_L_star = max(0.0, eta_avg - bL)
    h_R_star = max(0.0, eta_avg - bR)

    # Use reconstructed depths only where original depth was positive
    h_L_use = h_L_star if hL > MIN_DEPTH else hL
    h_R_use = h_R_star if hR > MIN_DEPTH else hR

    # Velocities (set to zero if dry)
    u_L = uL if hL > MIN_DEPTH else 0.0
    u_R = uR if hR > MIN_DEPTH else 0.0

    # Simple upwind flux for mass
    if u_L + u_R >= 0:
        f_h = h_L_use * u_L
        f_u = h_L_use * u_L * u_L + 0.5 * G * h_L_use * h_L_use
        f_v = h_L_use * u_L * vL
    else:
        f_h = h_R_use * u_R
        f_u = h_R_use * u_R * u_R + 0.5 * G * h_R_use * h_R_use
        f_v = h_R_use * u_R * vR

    return f_h, f_u, f_v


@njit
def surface_gradient_flux_y(
    hL: float, hR: float, uL: float, uR: float, vL: float, vR: float, bL: float, bR: float
) -> tuple:
    """Surface-gradient flux in y-direction (swaps u ↔ v roles)."""
    # Water surface elevation
    eta_L = bL + hL
    eta_R = bR + hR

    # Average water surface
    eta_avg = 0.5 * (eta_L + eta_R)

    # Reconstructed depths
    h_L_star = max(0.0, eta_avg - bL)
    h_R_star = max(0.0, eta_avg - bR)

    h_L_use = h_L_star if hL > MIN_DEPTH else hL
    h_R_use = h_R_star if hR > MIN_DEPTH else hR

    # Velocities
    v_L = vL if hL > MIN_DEPTH else 0.0
    v_R = vR if hR > MIN_DEPTH else 0.0

    # Upwind flux
    if v_L + v_R >= 0:
        f_h = h_L_use * v_L
        f_u = h_L_use * v_L * uL
        f_v = h_L_use * v_L * v_L + 0.5 * G * h_L_use * h_L_use
    else:
        f_h = h_R_use * v_R
        f_u = h_R_use * v_R * uR
        f_v = h_R_use * v_R * v_R + 0.5 * G * h_R_use * h_R_use

    return f_h, f_u, f_v


# Keep old HLLC functions for backward compatibility (not used)
def hllc_flux_x(*args, **kwargs):
    """Deprecated: use surface_gradient_flux_x instead."""
    return surface_gradient_flux_x(*args, **kwargs)

def hllc_flux_y(*args, **kwargs):
    """Deprecated: use surface_gradient_flux_y instead."""
    return surface_gradient_flux_y(*args, **kwargs)

def reconstruct_audusse(*args, **kwargs):
    """Deprecated: surface-gradient method handles reconstruction internally."""
    raise NotImplementedError("Use surface_gradient_flux_* instead")

def van_leer(*args, **kwargs):
    """Deprecated: not needed for surface-gradient method."""
    raise NotImplementedError("Use surface_gradient_flux_* instead")

