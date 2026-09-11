"""
Well-balanced HLLC flux and tendency kernels for the 2D SWE solver.

Scheme (Phase 1 mandate):
  - HLLC approximate Riemann solver with two-rarefaction wave speeds,
    dry-bed corrections, and transverse momentum upwinded on the contact
    wave (Toro 2001) — NOT HLL, which smears the shear layer.
  - Audusse et al. (2004) hydrostatic reconstruction for well-balancedness.
  - MUSCL reconstruction on eta = b + h (never on h alone) with the minmod
    limiter, so that a lake at rest has identically zero reconstructed slope.

WHY THE SOURCE TERM LOOKS LIKE THIS
-----------------------------------
Naively discretising -g*h*db/dx does not cancel the pressure flux at rest;
that mismatch is the sole reason a "still" reservoir develops spurious
velocities and slowly drains. The Audusse construction fixes this. Writing
face i as the interface between cells i-1 and i, and with

    z_face   = max(b_L, b_R)
    h*_L     = max(0, eta_L - z_face)
    h*_R     = max(0, eta_R - z_face)

the x-momentum update for cell i is

    d(hu)/dt = -(1/dx) [ F2_{i+1} - F2_i ]                     (HLLC on h*)
               -(g/2dx) [ P_L,{i+1} - P_R,i ]                  (Audusse correction)
               -(g/dx) h_i (s_eta,i - s_h,i)                   (interior bed slope)

with P_L = h_L² - h*_L² and P_R = h_R² - h*_R².

The third term is the MUSCL generalisation of the classic Audusse scheme.
It is usually written -(g/dx)*h_bar*(b_edge_R - b_edge_L). Substituting the
reconstructions b_edge = eta_edge - h_edge collapses it to the form above,
because h_bar = h_i exactly and (b_edge_R - b_edge_L) = s_eta - s_h. That
saves four face arrays and makes the cancellation auditable by hand.

Proof of the C-property (lake at rest, eta = eta0 = const, u = v = 0):
  s_eta = 0, so eta_edge = eta0 on both sides of every face, hence
  h*_L = h*_R and the HLLC flux reduces to F2 = (g/2) h*_L².
  Let a = h_edge_R(cell i) and c = h_edge_L(cell i); note a - c = s_h,i and
  a + c = 2 h_i. Summing the three terms:
      -(g/2dx)[a² - c²] - (g/dx) h_i (0 - s_h)
    = -(g/2dx)(s_h)(2 h_i) + (g/dx) h_i s_h
    = 0                                                    exactly, in float64.
No tolerance, no tuning constant. This is what makes the blocking
lake-at-rest gate pass at machine precision instead of "screening level".

NOTE ON fastmath
----------------
fastmath is deliberately NOT enabled on these kernels. It permits floating
point reassociation, which destroys the exact cancellation proved above and
reintroduces spurious lake-at-rest velocities. The project style guide asks
for fastmath on the flux kernel; the blocking correctness gate overrides
that preference. Measured cost of omitting it is a few percent.

References:
  - Toro, E.F. (2001). Shock-Capturing Methods for Free-Surface Shallow
    Flows. Wiley. (HLLC wave speeds, two-rarefaction estimate)
  - Audusse, E., Bouchut, F., Bristeau, M.-O., Klein, R., Perthame, B.
    (2004). "A fast and stable well-balanced scheme with hydrostatic
    reconstruction for shallow water flows." SIAM J. Sci. Comput. 25(6),
    2050-2065.
  - Liang, Q., Marche, F. (2009). "Numerical resolution of well-balanced
    shallow water equations with complex source terms." Advances in Water
    Resources 32(6), 873-884. (wetting/drying, the z_face limiting below)
  - Chow, V.T. (1959). Open-Channel Hydraulics. (Manning's n)
"""

import numpy as np
from numba import njit, prange

# Physical constant (m/s²)
G = 9.81

# DEFAULT depth below which a cell is treated as dry (m).
#
# This is a solver PARAMETER, not a physical constant — every kernel below
# takes h_dry as an argument. It is exposed because it sets a hard floor on
# wetting-front accuracy: the tip of a Ritter rarefaction has vanishing
# depth, so any cell thinner than h_dry stops carrying momentum and the front
# stalls there. Measured on the Ritter case, h_dry = 1e-3 m freezes the front
# at ~79% of the analytical position no matter how fine the grid, and caps
# the L2 convergence with it. Liang & Marche (2009) quote 1e-3 m for
# laboratory flumes; for a 260 m dam that is 4e-6 of the head, but for a 1 m
# analytical benchmark it is 1e-3 of the head and dominates the error.
H_DRY_DEFAULT = 1.0e-6

# Retained under the old name for modules that already import it.
H_DRY = H_DRY_DEFAULT

# Safety ceiling on velocity magnitude (m/s).
#
# No observed natural dam-break flow approaches this: Malpasset (1959) peak
# velocities were ~30 m/s and Chamoli 2021 reconstructions give ~25 m/s. The
# cap exists solely to stop numerical noise in hu on a micron-thin film from
# collapsing the timestep. Activations are counted and reported rather than
# silently absorbed — a nonzero count means the run is being held together by
# the cap and must not be quoted without saying so.
VELOCITY_MAX_DEFAULT = 60.0

# Floor on the Audusse wet fraction phi = h*/h used in the timestep estimate.
#
# The estimate inflates the acoustic celerity by 1/phi to pay for the
# dissipation a deeply-cut face loses (see max_wave_speed_inverse_dt). Left
# unfloored, phi -> 0 would drive dt -> 0 and stall the run, which is wrong:
# a face with h* = 0 is inert and destabilises nothing. 0.25 caps the
# penalty at 4x.
#
# Measured, 60x60 lake at rest, CFL 0.30, 3000 steps, worst |V| (m/s), over
# white-noise bathymetry on a 30 m grid. Last column is the timestep the
# choice costs a realistic 1-in-10 valley:
#
#     PHI_MIN        wet 20 m    wet 40 m    dry islands    dt(valley)
#     1.00 (off)     6.0e+01     1.9e+01     1.8e+01        0.262 s
#     0.50 (2x)      2.3e-13     2.7e-11     1.6e-13        0.239 s
#     0.25 (4x)      1.4e-13     1.2e-13     1.1e-13        0.207 s
#     0.125 (8x)     1.4e-13     1.2e-13     6.8e-14        0.116 s
#
# 0.25 is the first value that reaches the round-off floor (~1e-13) on every
# bed. 0.125 buys nothing measurable and costs real terrain 1.8x in dt.
PHI_MIN = 0.25

# Guard for divisions that are structurally non-zero but can underflow.
EPS = 1.0e-14


@njit(inline="always", cache=True)
def minmod(a: float, b: float) -> float:
    """
    Minmod slope limiter.

    Returns zero if the arguments have opposite signs (extremum -> no
    reconstruction), otherwise the smaller magnitude. This is the most
    diffusive of the common TVD limiters and the most robust across a
    wetting front, which is why it is preferred here over van Leer or
    superbee for dam-break fronts on real terrain.
    """
    if a * b <= 0.0:
        return 0.0
    if abs(a) < abs(b):
        return a
    return b


@njit(inline="always", cache=True)
def hllc(
    h_left: float,
    vn_left: float,
    vt_left: float,
    h_right: float,
    vn_right: float,
    vt_right: float,
    h_dry: float = H_DRY_DEFAULT,
):
    """
    HLLC flux for the shallow-water equations across one interface.

    Written in normal/transverse form so the same routine serves both
    sweeps: pass (u, v) for an x-face and (v, u) for a y-face.

    Args:
        h_left, h_right: Audusse-reconstructed depths (m)
        vn_left, vn_right: velocity component normal to the face (m/s)
        vt_left, vt_right: velocity component tangential to the face (m/s)
        h_dry: wet/dry threshold (m)

    Returns:
        (flux_mass, flux_normal_momentum, flux_tangential_momentum)
        i.e. (h*vn, h*vn² + g h²/2, h*vn*vt)
    """
    # Both sides dry: nothing crosses the face.
    if h_left <= h_dry and h_right <= h_dry:
        return 0.0, 0.0, 0.0

    celerity_left = np.sqrt(G * h_left) if h_left > 0.0 else 0.0
    celerity_right = np.sqrt(G * h_right) if h_right > 0.0 else 0.0

    # --- Wave speed estimates -------------------------------------------
    if h_left <= h_dry:
        # Dry left: a rarefaction runs into the dry bed at vn_R - 2c_R.
        speed_left = vn_right - 2.0 * celerity_right
        speed_right = vn_right + celerity_right
    elif h_right <= h_dry:
        # Dry right: mirror image.
        speed_left = vn_left - celerity_left
        speed_right = vn_left + 2.0 * celerity_left
    else:
        # Two-rarefaction approximation (Toro 2001). Cheap, and never
        # underestimates the wave speeds for dam-break-like data, which is
        # what positivity of the update depends on.
        celerity_star = 0.5 * (celerity_left + celerity_right) + 0.25 * (vn_left - vn_right)
        if celerity_star < 0.0:
            celerity_star = 0.0
        h_star = celerity_star * celerity_star / G
        vn_star = 0.5 * (vn_left + vn_right) + celerity_left - celerity_right
        celerity_h_star = np.sqrt(G * h_star)

        speed_left = min(vn_left - celerity_left, vn_star - celerity_h_star)
        speed_right = max(vn_right + celerity_right, vn_star + celerity_h_star)

    # --- Physical fluxes on each side -----------------------------------
    flux_mass_left = h_left * vn_left
    flux_norm_left = flux_mass_left * vn_left + 0.5 * G * h_left * h_left
    flux_mass_right = h_right * vn_right
    flux_norm_right = flux_mass_right * vn_right + 0.5 * G * h_right * h_right

    # --- Supersonic cases: pure upwinding -------------------------------
    if speed_left >= 0.0:
        return flux_mass_left, flux_norm_left, flux_mass_left * vt_left
    if speed_right <= 0.0:
        return flux_mass_right, flux_norm_right, flux_mass_right * vt_right

    # --- Subsonic: HLL for mass and normal momentum ---------------------
    denom = speed_right - speed_left
    if abs(denom) < EPS:
        return 0.0, 0.0, 0.0

    flux_mass = (
        speed_right * flux_mass_left
        - speed_left * flux_mass_right
        + speed_left * speed_right * (h_right - h_left)
    ) / denom
    flux_norm = (
        speed_right * flux_norm_left
        - speed_left * flux_norm_right
        + speed_left * speed_right * (flux_mass_right - flux_mass_left)
    ) / denom

    # --- Contact wave carries the tangential momentum (the "C" in HLLC) --
    # Using HLL here instead would diffuse the shear layer across the
    # channel and under-predict velocities on the outer bank of a bend.
    numer_contact = speed_left * h_right * (vn_right - speed_right) - speed_right * h_left * (
        vn_left - speed_left
    )
    denom_contact = h_right * (vn_right - speed_right) - h_left * (vn_left - speed_left)

    if abs(denom_contact) < EPS:
        speed_contact = 0.5 * (speed_left + speed_right)
    else:
        speed_contact = numer_contact / denom_contact

    vt_upwind = vt_left if speed_contact >= 0.0 else vt_right
    return flux_mass, flux_norm, flux_mass * vt_upwind


@njit(inline="always", cache=True)
def _audusse_face(
    eta_left: float,
    h_left: float,
    eta_right: float,
    h_right: float,
):
    """
    Audusse hydrostatic reconstruction at one face, with the
    Liang & Marche (2009) wet/dry limiting of the face bed elevation.

    Args:
        eta_left, h_left: reconstructed surface elevation and depth, left side
        eta_right, h_right: same, right side

    Returns:
        (h_star_left, h_star_right, pressure_corr_left, pressure_corr_right)
        where pressure_corr = h_edge² - h_star² feeds the Audusse source term.
    """
    bed_left = eta_left - h_left
    bed_right = eta_right - h_right
    bed_face = max(bed_left, bed_right)

    # Liang & Marche wet/dry limiting: if the face bed sits above BOTH water
    # surfaces we are looking at a dry step. Leaving z_face high would leave
    # a fictitious head difference across the face and drive a spurious jet
    # along the shoreline. Drop z_face to the higher surface so both
    # reconstructed depths vanish and the face is inert.
    surface_max = max(eta_left, eta_right)
    if bed_face > surface_max:
        bed_face = surface_max

    h_star_left = eta_left - bed_face
    if h_star_left < 0.0:
        h_star_left = 0.0
    h_star_right = eta_right - bed_face
    if h_star_right < 0.0:
        h_star_right = 0.0

    corr_left = h_left * h_left - h_star_left * h_star_left
    corr_right = h_right * h_right - h_star_right * h_star_right

    return h_star_left, h_star_right, corr_left, corr_right


@njit(parallel=True, cache=True)
def tendencies_x(
    h: np.ndarray,
    u: np.ndarray,
    v: np.ndarray,
    b: np.ndarray,
    dx: float,
    d_h: np.ndarray,
    d_hu: np.ndarray,
    d_hv: np.ndarray,
    use_muscl: bool,
    h_dry: float,
) -> None:
    """
    Accumulate x-direction flux divergence and bed source into the tendencies.

    Operates on arrays padded by 2 ghost cells on every side. Interior cells
    are indices [2 : ny+2] x [2 : nx+2]. Parallel over rows, which are
    independent in an x-sweep.

    Args:
        h, u, v, b: padded state arrays, shape (ny+4, nx+4)
        dx: cell size in x (m)
        d_h, d_hu, d_hv: padded tendency arrays, accumulated in place
        use_muscl: if False, fall back to first-order (zero slopes)
        h_dry: wet/dry threshold (m)
    """
    n_rows, n_cols = h.shape

    for row in prange(2, n_rows - 2):
        # Thread-private 1D scratch along the row.
        slope_eta = np.zeros(n_cols)
        slope_h = np.zeros(n_cols)
        slope_u = np.zeros(n_cols)
        slope_v = np.zeros(n_cols)
        flux_mass = np.zeros(n_cols)
        flux_xmom = np.zeros(n_cols)
        flux_ymom = np.zeros(n_cols)
        corr_l = np.zeros(n_cols)
        corr_r = np.zeros(n_cols)

        # --- limited slopes (cells 1 .. n_cols-2) -----------------------
        if use_muscl:
            for i in range(1, n_cols - 1):
                eta_here = b[row, i] + h[row, i]
                eta_prev = b[row, i - 1] + h[row, i - 1]
                eta_next = b[row, i + 1] + h[row, i + 1]
                slope_eta[i] = minmod(eta_here - eta_prev, eta_next - eta_here)
                slope_h[i] = minmod(h[row, i] - h[row, i - 1], h[row, i + 1] - h[row, i])
                slope_u[i] = minmod(u[row, i] - u[row, i - 1], u[row, i + 1] - u[row, i])
                slope_v[i] = minmod(v[row, i] - v[row, i - 1], v[row, i + 1] - v[row, i])

        # --- faces (face i separates cell i-1 from cell i) --------------
        for i in range(2, n_cols - 1):
            # Left state: right edge of cell i-1
            eta_l = (b[row, i - 1] + h[row, i - 1]) + 0.5 * slope_eta[i - 1]
            h_l = h[row, i - 1] + 0.5 * slope_h[i - 1]
            u_l = u[row, i - 1] + 0.5 * slope_u[i - 1]
            v_l = v[row, i - 1] + 0.5 * slope_v[i - 1]

            # Right state: left edge of cell i
            eta_r = (b[row, i] + h[row, i]) - 0.5 * slope_eta[i]
            h_r = h[row, i] - 0.5 * slope_h[i]
            u_r = u[row, i] - 0.5 * slope_u[i]
            v_r = v[row, i] - 0.5 * slope_v[i]

            # A limiter can overshoot into negative depth at a front.
            if h_l < 0.0:
                h_l = 0.0
            if h_r < 0.0:
                h_r = 0.0

            # Dry edges carry no momentum.
            if h_l <= h_dry:
                u_l = 0.0
                v_l = 0.0
            if h_r <= h_dry:
                u_r = 0.0
                v_r = 0.0

            h_star_l, h_star_r, c_l, c_r = _audusse_face(eta_l, h_l, eta_r, h_r)
            f_mass, f_norm, f_tang = hllc(h_star_l, u_l, v_l, h_star_r, u_r, v_r, h_dry)

            flux_mass[i] = f_mass
            flux_xmom[i] = f_norm
            flux_ymom[i] = f_tang
            corr_l[i] = c_l
            corr_r[i] = c_r

        # --- assemble cell tendencies (cells 2 .. n_cols-3) -------------
        inv_dx = 1.0 / dx
        for i in range(2, n_cols - 2):
            d_h[row, i] -= (flux_mass[i + 1] - flux_mass[i]) * inv_dx

            # Audusse correction + interior bed slope. See module docstring
            # for the proof that these cancel the pressure flux at rest.
            audusse_corr = 0.5 * G * (corr_l[i + 1] - corr_r[i]) * inv_dx
            bed_slope = G * h[row, i] * (slope_eta[i] - slope_h[i]) * inv_dx

            d_hu[row, i] -= (flux_xmom[i + 1] - flux_xmom[i]) * inv_dx + audusse_corr + bed_slope
            d_hv[row, i] -= (flux_ymom[i + 1] - flux_ymom[i]) * inv_dx


@njit(parallel=True, cache=True)
def tendencies_y(
    h: np.ndarray,
    u: np.ndarray,
    v: np.ndarray,
    b: np.ndarray,
    dy: float,
    d_h: np.ndarray,
    d_hu: np.ndarray,
    d_hv: np.ndarray,
    use_muscl: bool,
    h_dry: float,
) -> None:
    """
    Accumulate y-direction flux divergence and bed source into the tendencies.

    Mirror of tendencies_x, parallel over columns. In the y-sweep the roles
    of u and v swap when calling hllc: v is the normal component.

    Args:
        h, u, v, b: padded state arrays, shape (ny+4, nx+4)
        dy: cell size in y (m)
        d_h, d_hu, d_hv: padded tendency arrays, accumulated in place
        use_muscl: if False, fall back to first-order (zero slopes)
        h_dry: wet/dry threshold (m)
    """
    n_rows, n_cols = h.shape

    for col in prange(2, n_cols - 2):
        slope_eta = np.zeros(n_rows)
        slope_h = np.zeros(n_rows)
        slope_u = np.zeros(n_rows)
        slope_v = np.zeros(n_rows)
        flux_mass = np.zeros(n_rows)
        flux_xmom = np.zeros(n_rows)
        flux_ymom = np.zeros(n_rows)
        corr_l = np.zeros(n_rows)
        corr_r = np.zeros(n_rows)

        if use_muscl:
            for j in range(1, n_rows - 1):
                eta_here = b[j, col] + h[j, col]
                eta_prev = b[j - 1, col] + h[j - 1, col]
                eta_next = b[j + 1, col] + h[j + 1, col]
                slope_eta[j] = minmod(eta_here - eta_prev, eta_next - eta_here)
                slope_h[j] = minmod(h[j, col] - h[j - 1, col], h[j + 1, col] - h[j, col])
                slope_u[j] = minmod(u[j, col] - u[j - 1, col], u[j + 1, col] - u[j, col])
                slope_v[j] = minmod(v[j, col] - v[j - 1, col], v[j + 1, col] - v[j, col])

        for j in range(2, n_rows - 1):
            eta_l = (b[j - 1, col] + h[j - 1, col]) + 0.5 * slope_eta[j - 1]
            h_l = h[j - 1, col] + 0.5 * slope_h[j - 1]
            u_l = u[j - 1, col] + 0.5 * slope_u[j - 1]
            v_l = v[j - 1, col] + 0.5 * slope_v[j - 1]

            eta_r = (b[j, col] + h[j, col]) - 0.5 * slope_eta[j]
            h_r = h[j, col] - 0.5 * slope_h[j]
            u_r = u[j, col] - 0.5 * slope_u[j]
            v_r = v[j, col] - 0.5 * slope_v[j]

            if h_l < 0.0:
                h_l = 0.0
            if h_r < 0.0:
                h_r = 0.0
            if h_l <= h_dry:
                u_l = 0.0
                v_l = 0.0
            if h_r <= h_dry:
                u_r = 0.0
                v_r = 0.0

            h_star_l, h_star_r, c_l, c_r = _audusse_face(eta_l, h_l, eta_r, h_r)
            # v is normal, u is tangential for a y-face.
            f_mass, f_norm, f_tang = hllc(h_star_l, v_l, u_l, h_star_r, v_r, u_r, h_dry)

            flux_mass[j] = f_mass
            flux_ymom[j] = f_norm
            flux_xmom[j] = f_tang
            corr_l[j] = c_l
            corr_r[j] = c_r

        inv_dy = 1.0 / dy
        for j in range(2, n_rows - 2):
            d_h[j, col] -= (flux_mass[j + 1] - flux_mass[j]) * inv_dy

            audusse_corr = 0.5 * G * (corr_l[j + 1] - corr_r[j]) * inv_dy
            bed_slope = G * h[j, col] * (slope_eta[j] - slope_h[j]) * inv_dy

            d_hv[j, col] -= (flux_ymom[j + 1] - flux_ymom[j]) * inv_dy + audusse_corr + bed_slope
            d_hu[j, col] -= (flux_xmom[j + 1] - flux_xmom[j]) * inv_dy


@njit(cache=True)
def apply_friction(
    h: np.ndarray,
    u: np.ndarray,
    v: np.ndarray,
    manning_n: np.ndarray,
    dt: float,
    h_dry: float,
    velocity_max: float,
) -> int:
    """
    Apply Manning bed friction point-implicitly, then clip runaway velocity.

    Momentum sink:   d(hu)/dt = -g n² u |V| / h^(1/3)
    i.e. per unit u: du/dt    = -C u   with C = g n² |V| / h^(4/3)

    Discretised as u_new = u / (1 + C dt). This form is unconditionally
    stable AND cannot reverse the sign of the velocity, which an explicit
    update can do on a thin fast sheet (h ~ 1 cm, |V| ~ 5 m/s gives
    C dt >> 1). A reversed velocity at a wetting front is the classic
    source of "flood water flowing back uphill" artefacts.

    The velocity cap is a safety net, not physics. With h_dry at 1e-6 m the
    desingularised u = 2h(hu)/(h² + max(h,h_dry)²) can still spike on the
    very first wet cell of a step. Rather than raise h_dry (which stalls the
    wetting front — see the H_DRY_DEFAULT note) the magnitude is clipped and
    the activation counted, so the run reports honestly whether it relied on
    the cap. A physically converged run activates it zero times.

    Args:
        h, u, v: interior state arrays, modified in place
        manning_n: per-cell Manning's n (spatially varying, from land cover)
        dt: timestep (s)
        h_dry: wet/dry threshold (m); velocity is zeroed below it
        velocity_max: magnitude cap (m/s); <= 0 disables the cap

    Returns:
        Number of cells whose velocity magnitude was clipped this call.
    """
    n_rows, n_cols = h.shape
    n_capped = 0
    for j in range(n_rows):
        for i in range(n_cols):
            depth = h[j, i]
            if depth <= h_dry:
                u[j, i] = 0.0
                v[j, i] = 0.0
                continue

            speed = np.sqrt(u[j, i] * u[j, i] + v[j, i] * v[j, i])
            if speed < EPS:
                continue

            n_local = manning_n[j, i]
            if n_local > 0.0:
                drag = G * n_local * n_local * speed / (depth ** (4.0 / 3.0))
                factor = 1.0 / (1.0 + drag * dt)
                u[j, i] *= factor
                v[j, i] *= factor
                speed *= factor

            if velocity_max > 0.0 and speed > velocity_max:
                scale = velocity_max / speed
                u[j, i] *= scale
                v[j, i] *= scale
                n_capped += 1

    return n_capped


@njit(cache=True)
def max_wave_speed_inverse_dt(
    h: np.ndarray,
    u: np.ndarray,
    v: np.ndarray,
    b: np.ndarray,
    dx: float,
    dy: float,
    active_x: bool,
    active_y: bool,
    h_dry: float,
) -> float:
    """
    Reciprocal of the stable timestep at unit Courant number: the maximum
    over cells of the summed inverse timescales in each active direction.

    Two contributions are summed per direction:

    1. Acoustic. (|u| + c)/dx with c = sqrt(g*h). The additive 2D form is
       used rather than min(dx/(|u|+c), dy/(|v|+c)) because the latter
       over-estimates the stable step for a dimensionally unsplit update.

    2. Bed step. Audusse reconstruction sets the face depth to
       h* = eta - max(b_L, b_R) = h - max(0, db), so a face loses
       d = min(max(0, db), h) of depth while the cell it updates still
       carries the full hydrostatic pressure of h. Two consequences:

       - The HLLC dissipation at that face scales with sqrt(g*h*), so it
         weakens as the cut deepens, while the pressure coupling driving
         the face still scales with h. The high-wavenumber modes are left
         under-damped in proportion to h/h*.
       - One explicit step leaves a velocity residual of order g*d*dt/dx
         from the incomplete cancellation between the HLLC flux and the
         Audusse correction (that cancellation is exact at rest -- the
         C-property -- but not for a perturbation about rest).

       Both scale with the wet fraction phi = h*/h, so the acoustic
       celerity is inflated by 1/phi, floored at PHI_MIN because a face
       with h* = 0 is inert and couples nothing at all:

           c_eff = c / max(phi, PHI_MIN)

       This is identically 1 on a flat bed and is capped at 1/PHI_MIN, so
       the worst case is a bounded cut in dt applied only where terrain is
       steep relative to depth.

       Measured, on a 60x60 lake at rest, growth per step of the at-rest
       residual at CFL 0.45 with no bed-step term at all:

           bed step / depth  ~4     1.0251
           bed step / depth  ~1     1.0044
           bed step / depth  ~0.4   1.0015
           bed step / depth  ~0.05  1.0007  (round-off random walk floor)

       A 1-in-10 valley and a gorge with 60 m parabolic walls both sit at
       the floor, so realistic terrain never needed the correction; white
       noise bathymetry at 30 m does.

    Args:
        h, u, v, b: interior state arrays (depth, velocities, bed elevation)
        dx, dy: cell sizes (m)
        active_x, active_y: include that direction (a 1-cell-thick
            direction has no interior faces and must not contribute)
        h_dry: wet/dry threshold (m); cells below it do not constrain dt

    Returns:
        Maximum of the summed inverse timescales (1/s). Zero if fully dry.
    """
    n_rows, n_cols = h.shape
    worst = 0.0
    for j in range(n_rows):
        for i in range(n_cols):
            depth = h[j, i]
            if depth <= h_dry:
                continue
            celerity = np.sqrt(G * depth)
            bed = b[j, i]
            total = 0.0
            if active_x:
                # Deepest Audusse cut to an x-neighbour: the largest upward
                # bed step, clipped at the depth (past that the face is dry).
                rise = 0.0
                if i > 0 and b[j, i - 1] - bed > rise:
                    rise = b[j, i - 1] - bed
                if i < n_cols - 1 and b[j, i + 1] - bed > rise:
                    rise = b[j, i + 1] - bed
                if rise > depth:
                    rise = depth
                wet_fraction = (depth - rise) / depth
                if wet_fraction < PHI_MIN:
                    wet_fraction = PHI_MIN
                total += (abs(u[j, i]) + celerity / wet_fraction) / dx
            if active_y:
                rise = 0.0
                if j > 0 and b[j - 1, i] - bed > rise:
                    rise = b[j - 1, i] - bed
                if j < n_rows - 1 and b[j + 1, i] - bed > rise:
                    rise = b[j + 1, i] - bed
                if rise > depth:
                    rise = depth
                wet_fraction = (depth - rise) / depth
                if wet_fraction < PHI_MIN:
                    wet_fraction = PHI_MIN
                total += (abs(v[j, i]) + celerity / wet_fraction) / dy
            if total > worst:
                worst = total
    return worst


# ----------------------------------------------------------------------
# Backwards-compatible aliases.
#
# Earlier builds exposed surface_gradient_flux_x/_y from a first-order
# upwind scheme that replaced HLLC. That scheme is gone: it was not
# well-balanced and could not pass the lake-at-rest gate over real
# bathymetry. These names now forward to the HLLC solver so that any
# remaining caller keeps working, but new code should call hllc directly.
# ----------------------------------------------------------------------


@njit(cache=True)
def surface_gradient_flux_x(
    hL: float,
    hR: float,
    uL: float,
    uR: float,
    vL: float,
    vR: float,
    bL: float,
    bR: float,
):
    """Deprecated shim. Applies Audusse reconstruction then HLLC on an x-face."""
    h_star_l, h_star_r, _, _ = _audusse_face(bL + hL, hL, bR + hR, hR)
    return hllc(h_star_l, uL, vL, h_star_r, uR, vR)


@njit(cache=True)
def surface_gradient_flux_y(
    hL: float,
    hR: float,
    uL: float,
    uR: float,
    vL: float,
    vR: float,
    bL: float,
    bR: float,
):
    """Deprecated shim. Applies Audusse reconstruction then HLLC on a y-face."""
    h_star_l, h_star_r, _, _ = _audusse_face(bL + hL, hL, bR + hR, hR)
    f_mass, f_norm, f_tang = hllc(h_star_l, vL, uL, h_star_r, vR, uR)
    return f_mass, f_tang, f_norm


def hllc_flux_x(hL, uL, vL, hR, uR, vR):
    """Public HLLC on an x-face (no reconstruction). Returns (mass, xmom, ymom)."""
    return hllc(hL, uL, vL, hR, uR, vR)


def hllc_flux_y(hL, uL, vL, hR, uR, vR):
    """Public HLLC on a y-face (no reconstruction). Returns (mass, xmom, ymom)."""
    f_mass, f_norm, f_tang = hllc(hL, vL, uL, hR, vR, uR)
    return f_mass, f_tang, f_norm


def reconstruct_audusse(eta_left, h_left, eta_right, h_right):
    """Public Audusse hydrostatic reconstruction at one face."""
    return _audusse_face(eta_left, h_left, eta_right, h_right)
