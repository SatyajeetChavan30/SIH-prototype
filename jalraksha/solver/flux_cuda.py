"""
CUDA kernels for the 2D SWE solver: float64, batched over ensemble members.

SINGLE SOURCE OF PHYSICS
------------------------
Nothing numerical is written out a second time here. minmod, the Audusse face,
HLLC, point-implicit Manning friction and the per-cell CFL estimate are the
same Python functions the CPU kernels in flux.py use (the `_impl` functions),
compiled again as CUDA device functions. This module owns only the GPU-shaped
loop around them: one thread per face or per cell, where the CPU uses one
thread per row with private scratch arrays.

Four pieces are mirrored rather than shared: the MUSCL edge extrapolation, the
tendency assembly, the SSP-RK2 stage combination and the Kurganov-Petrova
velocity recovery. The CPU versions of these live inside parallel row loops or
in vectorised NumPy, so they cannot be shared. Each mirror follows the CPU
expression term for term and in the same order, and tests/test_solver_cuda.py
pins them against the CPU.

LAYOUT
------
State arrays are (n_members, ny + 4, nx + 4), with the same two-cell ghost
ring as core.py. Face arrays hold only the faces the CPU computes:
(n_members, ny, nx + 1) for x-faces and (n_members, ny + 1, nx) for y-faces.
The bed and the Manning field are shared by every member, because an ensemble
varies the breach hydrograph and never the terrain. The third grid coordinate
(blockIdx.z) is the member index. An `active` mask lets a member that has
finished sit out while the others keep stepping.

PRECISION
---------
float64 throughout, with fastmath off (flux.py explains why fastmath breaks the
C-property). One difference from the CPU cannot be switched off from
numba-cuda: NVVM contracts a*b + c into a fused multiply-add, which rounds once
instead of twice. libdevice's pow can also differ from the C runtime's by an
ulp. GPU and CPU therefore agree to round-off, not bit for bit. Measured on the
build machine (RTX 4050, numba-cuda 0.30.4), a*b + c + sqrt(a) is bit-identical
in 89% of cases, with a maximum difference of 8.9e-16. For that reason the GPU
is held to every blocking gate on its own, at the unchanged thresholds, rather
than to equality with the CPU.
"""

import math

from numba import cuda

from .flux import (
    G,
    NO_NEIGHBOUR,
    _audusse_face_impl,
    _friction_cell_impl,
    _hllc_impl,
    _inverse_dt_cell_impl,
    _minmod_impl,
)

# Ghost cells per side. Must equal core.PAD; not imported from core to keep
# this module free of the solver driver (core imports this module lazily).
PAD = 2

# Threads per block for cell- and face-shaped kernels: 32 along the
# contiguous axis for coalesced loads, 8 rows deep.
BLOCK_2D = (32, 8, 1)

# ----------------------------------------------------------------------
# Shared physics, compiled for the device
# ----------------------------------------------------------------------

_minmod = cuda.jit(device=True)(_minmod_impl)
_hllc = cuda.jit(device=True)(_hllc_impl)
_audusse_face = cuda.jit(device=True)(_audusse_face_impl)
_friction_cell = cuda.jit(device=True)(_friction_cell_impl)
_inverse_dt_cell = cuda.jit(device=True)(_inverse_dt_cell_impl)


def launch_grid(cols: int, rows: int, members: int, block=BLOCK_2D):
    """Grid/block pair covering (members, rows, cols) with BLOCK_2D tiles."""
    return (
        (cols + block[0] - 1) // block[0],
        (rows + block[1] - 1) // block[1],
        members,
    ), block


# ----------------------------------------------------------------------
# Mirrored pieces (see module docstring)
# ----------------------------------------------------------------------


@cuda.jit(device=True)
def _slopes(h, u, v, b, m, row, col, d_row, d_col, use_muscl):
    """Minmod slopes of (eta, h, u, v) at one cell along one axis.

    (d_row, d_col) is (0, 1) for x and (1, 0) for y. Mirrors the slope loop
    of tendencies_x / tendencies_y, where eta is formed as b + h.
    """
    if not use_muscl:
        return 0.0, 0.0, 0.0, 0.0
    row_prev = row - d_row
    col_prev = col - d_col
    row_next = row + d_row
    col_next = col + d_col
    eta_here = b[row, col] + h[m, row, col]
    eta_prev = b[row_prev, col_prev] + h[m, row_prev, col_prev]
    eta_next = b[row_next, col_next] + h[m, row_next, col_next]
    return (
        _minmod(eta_here - eta_prev, eta_next - eta_here),
        _minmod(h[m, row, col] - h[m, row_prev, col_prev], h[m, row_next, col_next] - h[m, row, col]),
        _minmod(u[m, row, col] - u[m, row_prev, col_prev], u[m, row_next, col_next] - u[m, row, col]),
        _minmod(v[m, row, col] - v[m, row_prev, col_prev], v[m, row_next, col_next] - v[m, row, col]),
    )


@cuda.jit(device=True)
def _surface_and_depth_slopes(h, b, m, row, col, d_row, d_col, use_muscl):
    """Just the (eta, h) slopes, for the interior bed-slope term."""
    if not use_muscl:
        return 0.0, 0.0
    row_prev = row - d_row
    col_prev = col - d_col
    row_next = row + d_row
    col_next = col + d_col
    eta_here = b[row, col] + h[m, row, col]
    eta_prev = b[row_prev, col_prev] + h[m, row_prev, col_prev]
    eta_next = b[row_next, col_next] + h[m, row_next, col_next]
    return (
        _minmod(eta_here - eta_prev, eta_next - eta_here),
        _minmod(h[m, row, col] - h[m, row_prev, col_prev], h[m, row_next, col_next] - h[m, row, col]),
    )


@cuda.jit(device=True)
def _face(h, u, v, b, m, row_l, col_l, row_r, col_r, d_row, d_col, use_muscl, h_dry, normal_is_x):
    """
    MUSCL edge states, Audusse reconstruction and HLLC flux at one face.

    Mirrors the face loop of tendencies_x / tendencies_y.

    Returns:
        (flux_mass, flux_xmom, flux_ymom, corr_left, corr_right)
    """
    se_l, sh_l, su_l, sv_l = _slopes(h, u, v, b, m, row_l, col_l, d_row, d_col, use_muscl)
    se_r, sh_r, su_r, sv_r = _slopes(h, u, v, b, m, row_r, col_r, d_row, d_col, use_muscl)

    # Left state: far edge of the left cell.
    eta_l = (b[row_l, col_l] + h[m, row_l, col_l]) + 0.5 * se_l
    h_l = h[m, row_l, col_l] + 0.5 * sh_l
    u_l = u[m, row_l, col_l] + 0.5 * su_l
    v_l = v[m, row_l, col_l] + 0.5 * sv_l

    # Right state: near edge of the right cell.
    eta_r = (b[row_r, col_r] + h[m, row_r, col_r]) - 0.5 * se_r
    h_r = h[m, row_r, col_r] - 0.5 * sh_r
    u_r = u[m, row_r, col_r] - 0.5 * su_r
    v_r = v[m, row_r, col_r] - 0.5 * sv_r

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

    h_star_l, h_star_r, corr_l, corr_r = _audusse_face(eta_l, h_l, eta_r, h_r)
    if normal_is_x:
        f_mass, f_norm, f_tang = _hllc(h_star_l, u_l, v_l, h_star_r, u_r, v_r, h_dry)
        return f_mass, f_norm, f_tang, corr_l, corr_r
    # y-face: v is normal, u is tangential.
    f_mass, f_norm, f_tang = _hllc(h_star_l, v_l, u_l, h_star_r, v_r, u_r, h_dry)
    return f_mass, f_tang, f_norm, corr_l, corr_r


@cuda.jit(device=True)
def _to_primitive(depth, momentum_x, momentum_y, h_dry):
    """Kurganov-Petrova desingularised velocity; mirrors core._to_primitive."""
    if depth <= h_dry:
        return 0.0, 0.0
    depth_floor = depth if depth > h_dry else h_dry
    denom = depth * depth + depth_floor * depth_floor
    return 2.0 * depth * momentum_x / denom, 2.0 * depth * momentum_y / denom


# ----------------------------------------------------------------------
# Boundary conditions
# ----------------------------------------------------------------------


@cuda.jit(cache=True)
def fill_ghosts_x(h, u, v, reflect, active):
    """Left/right ghost columns for interior rows; mirrors core._fill_ghosts.

    Corner ghosts are never read by the stencil, so they are not filled.
    """
    offset, r, m = cuda.grid(3)
    ny = h.shape[1] - 2 * PAD
    nx = h.shape[2] - 2 * PAD
    if m >= h.shape[0] or r >= ny or offset >= PAD or active[m] == 0:
        return
    row = r + PAD
    lo = PAD
    hi = PAD + nx
    ghost_left = lo - 1 - offset
    ghost_right = hi + offset
    if reflect:
        src_left = min(lo + offset, hi - 1)
        src_right = max(hi - 1 - offset, lo)
        sign = -1.0
    else:
        src_left = lo
        src_right = hi - 1
        sign = 1.0
    h[m, row, ghost_left] = h[m, row, src_left]
    u[m, row, ghost_left] = sign * u[m, row, src_left]
    v[m, row, ghost_left] = v[m, row, src_left]
    h[m, row, ghost_right] = h[m, row, src_right]
    u[m, row, ghost_right] = sign * u[m, row, src_right]
    v[m, row, ghost_right] = v[m, row, src_right]


@cuda.jit(cache=True)
def fill_ghosts_y(h, u, v, reflect, active):
    """Bottom/top ghost rows for interior columns; mirrors core._fill_ghosts."""
    c, offset, m = cuda.grid(3)
    ny = h.shape[1] - 2 * PAD
    nx = h.shape[2] - 2 * PAD
    if m >= h.shape[0] or c >= nx or offset >= PAD or active[m] == 0:
        return
    col = c + PAD
    lo = PAD
    hi = PAD + ny
    ghost_bot = lo - 1 - offset
    ghost_top = hi + offset
    if reflect:
        src_bot = min(lo + offset, hi - 1)
        src_top = max(hi - 1 - offset, lo)
        sign = -1.0
    else:
        src_bot = lo
        src_top = hi - 1
        sign = 1.0
    h[m, ghost_bot, col] = h[m, src_bot, col]
    v[m, ghost_bot, col] = sign * v[m, src_bot, col]
    u[m, ghost_bot, col] = u[m, src_bot, col]
    h[m, ghost_top, col] = h[m, src_top, col]
    v[m, ghost_top, col] = sign * v[m, src_top, col]
    u[m, ghost_top, col] = u[m, src_top, col]


# ----------------------------------------------------------------------
# Spatial operator
# ----------------------------------------------------------------------


@cuda.jit(cache=True)
def face_flux_x(h, u, v, b, flux_mass, flux_xmom, flux_ymom, corr_left, corr_right, use_muscl, h_dry, active):
    """x-faces. Face f separates padded columns f+1 and f+2 (CPU face i = f + 2)."""
    face, r, m = cuda.grid(3)
    if m >= flux_mass.shape[0] or r >= flux_mass.shape[1] or face >= flux_mass.shape[2]:
        return
    if active[m] == 0:
        return
    row = r + PAD
    col = face + PAD
    f_mass, f_x, f_y, c_l, c_r = _face(h, u, v, b, m, row, col - 1, row, col, 0, 1, use_muscl, h_dry, True)
    flux_mass[m, r, face] = f_mass
    flux_xmom[m, r, face] = f_x
    flux_ymom[m, r, face] = f_y
    corr_left[m, r, face] = c_l
    corr_right[m, r, face] = c_r


@cuda.jit(cache=True)
def face_flux_y(h, u, v, b, flux_mass, flux_xmom, flux_ymom, corr_left, corr_right, use_muscl, h_dry, active):
    """y-faces. Face f separates padded rows f+1 and f+2 (CPU face j = f + 2)."""
    c, face, m = cuda.grid(3)
    if m >= flux_mass.shape[0] or face >= flux_mass.shape[1] or c >= flux_mass.shape[2]:
        return
    if active[m] == 0:
        return
    row = face + PAD
    col = c + PAD
    f_mass, f_x, f_y, c_l, c_r = _face(h, u, v, b, m, row - 1, col, row, col, 1, 0, use_muscl, h_dry, False)
    flux_mass[m, face, c] = f_mass
    flux_xmom[m, face, c] = f_x
    flux_ymom[m, face, c] = f_y
    corr_left[m, face, c] = c_l
    corr_right[m, face, c] = c_r


@cuda.jit(cache=True)
def assemble_tendencies(
    h,
    b,
    fx_mass,
    fx_xmom,
    fx_ymom,
    cx_left,
    cx_right,
    fy_mass,
    fy_xmom,
    fy_ymom,
    cy_left,
    cy_right,
    d_h,
    d_hu,
    d_hv,
    dx,
    dy,
    use_muscl,
    active_x,
    active_y,
    active,
):
    """
    Flux divergence + Audusse correction + interior bed slope per cell.

    Mirrors the assembly loops of tendencies_x then tendencies_y: the CPU
    zero-fills the tendency arrays, subtracts the x-terms, then subtracts the
    y-terms, and this does the same in the same order.
    """
    c, r, m = cuda.grid(3)
    if m >= d_h.shape[0] or r >= d_h.shape[1] or c >= d_h.shape[2] or active[m] == 0:
        return
    row = r + PAD
    col = c + PAD
    tend_h = 0.0
    tend_hu = 0.0
    tend_hv = 0.0

    if active_x:
        inv_dx = 1.0 / dx
        tend_h -= (fx_mass[m, r, c + 1] - fx_mass[m, r, c]) * inv_dx
        audusse_corr = 0.5 * G * (cx_left[m, r, c + 1] - cx_right[m, r, c]) * inv_dx
        slope_eta, slope_h = _surface_and_depth_slopes(h, b, m, row, col, 0, 1, use_muscl)
        bed_slope = G * h[m, row, col] * (slope_eta - slope_h) * inv_dx
        tend_hu -= (fx_xmom[m, r, c + 1] - fx_xmom[m, r, c]) * inv_dx + audusse_corr + bed_slope
        tend_hv -= (fx_ymom[m, r, c + 1] - fx_ymom[m, r, c]) * inv_dx

    if active_y:
        inv_dy = 1.0 / dy
        tend_h -= (fy_mass[m, r + 1, c] - fy_mass[m, r, c]) * inv_dy
        audusse_corr = 0.5 * G * (cy_left[m, r + 1, c] - cy_right[m, r, c]) * inv_dy
        slope_eta, slope_h = _surface_and_depth_slopes(h, b, m, row, col, 1, 0, use_muscl)
        bed_slope = G * h[m, row, col] * (slope_eta - slope_h) * inv_dy
        tend_hv -= (fy_ymom[m, r + 1, c] - fy_ymom[m, r, c]) * inv_dy + audusse_corr + bed_slope
        tend_hu -= (fy_xmom[m, r + 1, c] - fy_xmom[m, r, c]) * inv_dy

    d_h[m, r, c] = tend_h
    d_hu[m, r, c] = tend_hu
    d_hv[m, r, c] = tend_hv


# ----------------------------------------------------------------------
# Time integration (SSP-RK2 / Heun) and friction
# ----------------------------------------------------------------------


@cuda.jit(cache=True)
def rk_stage1(h, u, v, d_h, d_hu, d_hv, h1, u1, v1, hu1, hv1, dt, h_dry, active):
    """U* = U^n + dt L(U^n), then clip and recover velocity. Mirrors core._advance."""
    c, r, m = cuda.grid(3)
    if m >= d_h.shape[0] or r >= d_h.shape[1] or c >= d_h.shape[2] or active[m] == 0:
        return
    row = r + PAD
    col = c + PAD
    step = dt[m]
    h_old = h[m, row, col]
    hu_old = h_old * u[m, row, col]
    hv_old = h_old * v[m, row, col]

    h_1 = h_old + step * d_h[m, r, c]
    hu_1 = hu_old + step * d_hu[m, r, c]
    hv_1 = hv_old + step * d_hv[m, r, c]
    if h_1 < 0.0:
        h_1 = 0.0
    u_1, v_1 = _to_primitive(h_1, hu_1, hv_1, h_dry)

    h1[m, row, col] = h_1
    u1[m, row, col] = u_1
    v1[m, row, col] = v_1
    hu1[m, r, c] = hu_1
    hv1[m, r, c] = hv_1


@cuda.jit(cache=True)
def rk_stage2_friction(
    h, u, v, h1, hu1, hv1, d_h, d_hu, d_hv, manning, dt, h_dry, velocity_max, n_capped, active
):
    """
    U^n+1 = 1/2 U^n + 1/2 (U* + dt L(U*)), clip, recover velocity, then
    point-implicit friction. Writes the new state in place over U^n.

    Friction is fused in because apply_friction is elementwise: running it as
    a separate pass over the array (as the CPU does) gives the same result.
    """
    c, r, m = cuda.grid(3)
    if m >= d_h.shape[0] or r >= d_h.shape[1] or c >= d_h.shape[2] or active[m] == 0:
        return
    row = r + PAD
    col = c + PAD
    step = dt[m]
    h_old = h[m, row, col]
    hu_old = h_old * u[m, row, col]
    hv_old = h_old * v[m, row, col]

    h_new = 0.5 * (h_old + h1[m, row, col] + step * d_h[m, r, c])
    hu_new = 0.5 * (hu_old + hu1[m, r, c] + step * d_hu[m, r, c])
    hv_new = 0.5 * (hv_old + hv1[m, r, c] + step * d_hv[m, r, c])
    if h_new < 0.0:
        h_new = 0.0
    u_new, v_new = _to_primitive(h_new, hu_new, hv_new, h_dry)

    u_new, v_new, capped = _friction_cell(h_new, u_new, v_new, manning[r, c], step, h_dry, velocity_max)
    if capped != 0:
        cuda.atomic.add(n_capped, m, capped)

    h[m, row, col] = h_new
    u[m, row, col] = u_new
    v[m, row, col] = v_new


# ----------------------------------------------------------------------
# Timestep (CFL) and reductions
# ----------------------------------------------------------------------


@cuda.jit(cache=True)
def inverse_dt_cells(h, u, v, b, inv_dt, dx, dy, active_x, active_y, h_dry, active):
    """Per-member max of the summed inverse timescale; mirrors max_wave_speed_inverse_dt.

    Max is order-independent, so the atomic reduction matches the CPU exactly.
    """
    c, r, m = cuda.grid(3)
    ny = h.shape[1] - 2 * PAD
    nx = h.shape[2] - 2 * PAD
    if m >= h.shape[0] or r >= ny or c >= nx or active[m] == 0:
        return
    row = r + PAD
    col = c + PAD
    depth = h[m, row, col]
    if depth <= h_dry:
        return
    total = _inverse_dt_cell(
        depth,
        u[m, row, col],
        v[m, row, col],
        b[row, col],
        b[row, col - 1] if c > 0 else NO_NEIGHBOUR,
        b[row, col + 1] if c < nx - 1 else NO_NEIGHBOUR,
        b[row - 1, col] if r > 0 else NO_NEIGHBOUR,
        b[row + 1, col] if r < ny - 1 else NO_NEIGHBOUR,
        dx,
        dy,
        active_x,
        active_y,
    )
    cuda.atomic.max(inv_dt, m, total)


@cuda.jit(cache=True)
def finalize_dt(inv_dt, dt_out, cfl, dt_max, active):
    """dt = cfl / max(inverse dt), capped; mirrors SWESolver.compute_cfl_timestep.

    Resets inv_dt to zero so the next CFL evaluation starts clean.
    """
    m = cuda.grid(1)
    if m >= inv_dt.shape[0]:
        return
    if active[m] != 0:
        inverse = inv_dt[m]
        if inverse <= 0.0:
            dt_out[m] = dt_max
        else:
            dt_out[m] = min(cfl / inverse, dt_max)
    inv_dt[m] = 0.0


@cuda.jit(cache=True)
def row_sums(h, partial, active):
    """Sum of depth along each interior row, one thread per (member, row).

    A fixed summation order, rather than atomics, keeps the result
    deterministic from run to run.
    """
    r, m = cuda.grid(2)
    if m >= partial.shape[0] or r >= partial.shape[1] or active[m] == 0:
        return
    nx = h.shape[2] - 2 * PAD
    total = 0.0
    for c in range(nx):
        total += h[m, r + PAD, c + PAD]
    partial[m, r] = total


@cuda.jit(cache=True)
def member_sums(partial, out, active):
    """Sum the row partials into one total per member."""
    m = cuda.grid(1)
    if m >= out.shape[0] or active[m] == 0:
        return
    total = 0.0
    for r in range(partial.shape[1]):
        total += partial[m, r]
    out[m] = total


@cuda.jit(cache=True)
def accumulate_outflow(sum_before, sum_after, exited, cell_area, active):
    """Boundary outflow of one step; mirrors SWESolver.volume_exited_m3."""
    m = cuda.grid(1)
    if m >= exited.shape[0] or active[m] == 0:
        return
    exited[m] += (sum_before[m] - sum_after[m]) * cell_area


@cuda.jit(cache=True)
def run_maxima(h, u, v, h_max, u_max, v_max, t_arrival, t_now, threshold, nonfinite):
    """
    Running maxima for SWESolver.run (member 0 only); mirrors Result.update.

    u_max holds the speed sqrt(u^2 + v^2) and v_max holds |v|, exactly as
    Result.update does. Arrival is stamped where depth is strictly above
    `threshold`.
    """
    c, r = cuda.grid(2)
    ny = h_max.shape[0]
    nx = h_max.shape[1]
    if r >= ny or c >= nx:
        return
    depth = h[0, r + PAD, c + PAD]
    vel_x = u[0, r + PAD, c + PAD]
    vel_y = v[0, r + PAD, c + PAD]
    if not (math.isfinite(depth) and math.isfinite(vel_x) and math.isfinite(vel_y)):
        nonfinite[0] = 1
    if depth > h_max[r, c]:
        h_max[r, c] = depth
    speed = math.sqrt(vel_x * vel_x + vel_y * vel_y)
    if speed > u_max[r, c]:
        u_max[r, c] = speed
    if abs(vel_y) > v_max[r, c]:
        v_max[r, c] = abs(vel_y)
    if depth > threshold and not math.isfinite(t_arrival[r, c]):
        t_arrival[r, c] = t_now
