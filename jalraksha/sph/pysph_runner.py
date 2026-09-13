"""
Near-field WCSPH via PySPH (Phase 7).

Runs a genuine Weakly Compressible SPH simulation of the violent near-field
immediately downstream of a breach: the reservoir column collapses onto real
DEM-derived topography and the surge front is tracked as it advances.

WHY THIS MODULE EXISTS. The service layer previously synthesized its "SPH
result" from np.random and presented it in the dashboard beside solver output.
`jalraksha/sph/core.py` was no better a foundation: it had no kernel, no
neighbour search and no density evolution — `step()` applied a uniform
acceleration to every particle and discarded the pressure it computed, so
wiring it in would have swapped random numbers for ballistic trajectories
wearing a legitimate label. This module runs actual SPH instead: PySPH's
WCSPHScheme, with a Wendland quintic kernel, Monaghan artificial viscosity, the
Tait equation of state and dynamic boundary particles.

SCOPE, STATED PLAINLY:

  * ONE-WAY HANDOFF ONLY (CLAUDE.md). The breach hydrograph's peak discharge
    and the reservoir head set the SPH initial condition; nothing flows back
    from SPH into the SWE solver. This is not two-way coupling and must never
    be described as such.
  * NEAR-FIELD ONLY. The domain is a few hundred metres and the run is tens of
    seconds. It CANNOT reach the downstream gauges at 13-58 km, and therefore
    produces no gauge arrival times at all. Anything reporting SPH arrivals at
    those gauges is not coming from here.
  * 30 m Copernicus GLO-30 topography is coarse relative to SPH particle
    spacing. The terrain sets the slope and confinement the surge runs over;
    it does not resolve channel-scale features.

BACKENDS AND PRECISION (see also solver/flux_cuda.py, which argues the same way
for the SWE solver):

  * float64 on BOTH backends. The GPU path passes PySPH's --use-double, so the
    CPU/GPU choice is hardware, never precision.
  * NOT bit-comparable, and deliberately not tested as if it were. The CPU
    (Cython) and GPU (octree) neighbour searches visit a particle's neighbours
    in different ORDERS, so float64 force and density sums differ at round-off;
    in a violent collapse those differences then grow. Each backend is therefore
    held to the same PHYSICAL gates on its own -- energy bound, still-water
    equilibrium, hydrostatic pressure, particles staying over the terrain --
    rather than to agreement with the other's trajectories.
  * Python 3.14 breaks compyle, the generator behind PySPH's GPU kernels, in two
    ways; sph/compyle_compat.py repairs both for the duration of the compile and
    explains exactly what it restores and what it deliberately does not.

References:
  - Ramachandran et al. (2021) "PySPH: A Python-based Framework for SPH",
    ACM TOMS 47(4):1-38.
  - Monaghan, J.J. (1994) "Simulating Free Surface Flows with SPH",
    J. Comput. Phys. 110(2):399-406.  (WCSPH, Tait EOS, artificial viscosity)
  - Wendland, H. (1995) "Piecewise polynomial, positive definite and compactly
    supported radial functions of minimal degree", Adv. Comput. Math. 4:389-396.
  - Maranzoni & Tomirotti (2023) "3D Numerical Modelling of Real-Field
    Dam-Break Flows", Water 15(17):3130.  (near-field/far-field decomposition)
"""

from __future__ import annotations

import os
import time
from typing import Any, Dict, List, Optional

import numpy as np

from jalraksha.sph.compyle_compat import (
    RESTORED_AST_NAMES,
    compyle_python314_compat_if,
    visitor_repair_gaps,
)

GRAVITY = 9.81          # m/s2
RHO_WATER = 1000.0      # kg/m3, freshwater reference density
HDX = 1.3               # smoothing length / particle spacing (Monaghan 1994)

# Tait exponent for water. Monaghan (1994) eq. 6.
TAIT_GAMMA = 7.0

# Monaghan artificial viscosity. 0.25 is the value PySPH's own validated
# dam_break_3d.py example uses for free-surface flows; beta=0 as there is no
# strong shock to suppress. TODO: UNVETTED for real-field scale - alpha is a
# numerical dissipation parameter, not a measured property, and at 100 m+ heads
# it acts as an eddy-viscosity surrogate with no calibration behind it.
# Spec section 17 verification queue.
ALPHA_VISCOSITY = 0.25
BETA_VISCOSITY = 0.0

# Iterations over which PySPH ramps the timestep in from zero. WCSPH starts
# every particle on a lattice, which is not an equilibrium configuration however
# carefully the density is initialised, and the resulting acoustic transient
# contaminates the first fraction of a second. pysph/examples/dam_break_3d.py
# uses the same value.
N_DAMP_STEPS = 50

# Keep a demo run bounded regardless of dam size: particle spacing is derived
# from this budget rather than fixed, so a 260 m Tehri head and a 30 m barrage
# both produce a run that finishes in seconds rather than hours.
TARGET_FLUID_PARTICLES = 9000

# Depth below which a particle is not counted as part of the surge front, so a
# handful of spray particles cannot define the front position.
FRONT_MIN_PARTICLES = 8


class SPHUnavailableError(RuntimeError):
    """
    PySPH could not be imported or its generated code could not be compiled.

    Raised rather than degraded. The alternative — returning something
    plausible — is exactly the failure this module was written to remove.
    """


def is_pysph_available() -> tuple:
    """
    Report whether a real SPH run is possible here, and why not if it is not.

    Returns:
        (available: bool, detail: str) — detail names the PySPH version when
        available, and the import error otherwise.
    """
    try:
        import pysph

        return True, f"PySPH {getattr(pysph, '__version__', 'unknown')}"
    except Exception as exc:  # pragma: no cover - depends on the environment
        return False, f"{type(exc).__name__}: {exc}"


# Which hardware runs PySPH: "auto" (an OpenCL GPU with float64 if there is
# one, else the CPU), "opencl" (GPU or raise) or "cpu".
SPH_BACKEND_ENV = "JALRAKSHA_SPH_BACKEND"


def _opencl_fp64_gpu():
    """
    Find an OpenCL GPU that supports float64, preferring NVIDIA.

    The preference matters on laptops, which often expose an integrated GPU as
    a second OpenCL platform. The build machine has an NVIDIA RTX 4050 and an
    AMD gfx1103 iGPU, and PyOpenCL's default choice follows platform order,
    which nothing guarantees.

    Returns:
        ((platform_index, device_index, device_name) or None, detail)
    """
    try:
        import pyopencl as cl
    except Exception as exc:
        return None, f"pyopencl unavailable ({type(exc).__name__}: {exc})"
    try:
        candidates = []
        for platform_index, platform in enumerate(cl.get_platforms()):
            for device_index, device in enumerate(platform.get_devices()):
                if device.type & cl.device_type.GPU and "cl_khr_fp64" in device.extensions:
                    rank = 0 if "NVIDIA" in platform.name.upper() else 1
                    candidates.append((rank, platform_index, device_index, device.name))
        if not candidates:
            return None, "no OpenCL GPU with float64 (cl_khr_fp64) support"
        _, platform_index, device_index, name = min(candidates)
        return (platform_index, device_index, name), f"OpenCL device: {name}"
    except Exception as exc:
        return None, f"OpenCL probe failed ({type(exc).__name__}: {exc})"


# AST node classes that Python 3.14 removed (deprecated since 3.8). compyle, the
# code generator behind PySPH's GPU backends, still referenced ast.Str as of
# compyle 0.9.1.
_REMOVED_AST_NODES = ("Str", "Num", "NameConstant", "Bytes", "Ellipsis")


def _compyle_gpu_incompatibility() -> Optional[str]:
    """
    Why PySPH's GPU code generator cannot run on this Python, or None if it can.

    PySPH builds its OpenCL kernels through compyle, which walks Python ASTs.
    compyle 0.9.1 still tests `isinstance(node, ast.Str)`, and Python 3.14
    removed ast.Str. Measured on the build machine, the first GPU kernel (the
    neighbour search) then dies with "module 'ast' has no attribute 'Str'".
    PySPH's CPU backend generates Cython by a different route and is
    unaffected.

    The check reads compyle's own source rather than its version number, so a
    compyle release that drops ast.Str is picked up without an edit here.

    Names that `sph/compyle_compat.py` puts back do not count as blockers: the
    GPU run installs that shim around PySPH's compile. Anything removed that the
    shim does NOT restore still refuses the GPU, so a future compyle that breaks
    in a new way is caught rather than assumed fine.
    """
    import ast
    import inspect
    import sys

    try:
        import compyle
        import compyle.jit
        import compyle.translator

        source = inspect.getsource(compyle.jit) + inspect.getsource(compyle.translator)
    except Exception as exc:
        return f"compyle unavailable ({type(exc).__name__}: {exc})"

    missing = [n for n in _REMOVED_AST_NODES if f"ast.{n}" in source and not hasattr(ast, n)]
    unrepairable = [n for n in missing if n not in RESTORED_AST_NAMES]
    # The other half of the 3.14 breakage is silent: compyle's constant visitors
    # are named for removed node types, so they are never called and literals
    # come out as the word None in the generated OpenCL. compyle_compat repairs
    # that by dispatching ast.Constant, and reports any class it cannot.
    gaps = visitor_repair_gaps()
    if not unrepairable and not gaps:
        return None
    if gaps and not unrepairable:
        return "; ".join(gaps)
    return (
        f"PySPH's GPU kernels are generated by compyle "
        f"{getattr(compyle, '__version__', '(unknown version)')}, which uses "
        f"{', '.join('ast.' + n for n in unrepairable)}; Python "
        f"{sys.version_info.major}.{sys.version_info.minor} removed "
        f"{'it' if len(unrepairable) == 1 else 'them'}, and "
        f"sph/compyle_compat.py does not restore "
        f"{'it' if len(unrepairable) == 1 else 'them'}"
    )


def sph_backend_for_solver(solver_backend: Optional[str]) -> str:
    """
    The SPH backend that matches a SWE backend choice, so one control governs both.

    "cuda" maps to "opencl" because it is the same device reached through a
    different API: PySPH's CUDA backend needs pycuda and therefore nvcc, which
    this project avoids, while the NVIDIA driver's OpenCL runtime needs nothing
    extra (solver/backend.py documents the same reasoning for numba-cuda's pip
    wheels).

    Note the deliberate asymmetry with the SWE solver, which RAISES when "cuda"
    is asked for and cannot run. Here the caller is expected to degrade to the
    CPU and record why: SPH is a supplementary near-field product, losing it
    entirely to honour a flag serves nobody, and nothing can be mislabelled
    because `sph_backend`, `sph_backend_reason` and `engine_label` all name what
    actually ran. Set JALRAKSHA_SPH_BACKEND=opencl to demand it strictly.
    """
    choice = (solver_backend or "auto").strip().lower()
    if choice == "cuda":
        return "opencl"
    if choice in ("cpu", "auto", "opencl"):
        return choice
    return "auto"


def resolve_sph_backend(requested: Optional[str] = None) -> Dict[str, Any]:
    """
    Decide where PySPH runs, and return the Application flags that select it.

    The GPU path runs PySPH's own OpenCL backend with --use-double, so SPH
    stays float64 like the SWE solver. PySPH's CUDA backend is not used,
    because it needs pycuda and therefore nvcc, which this project avoids; the
    NVIDIA driver's OpenCL runtime needs nothing extra.

    Raises:
        ValueError: on an unknown backend name.
        SPHUnavailableError: if "opencl" was requested and cannot run.
    """
    if requested is None or str(requested).lower() == "auto":
        requested = os.environ.get(SPH_BACKEND_ENV, "auto")
    requested = str(requested).strip().lower()
    if requested not in ("auto", "cpu", "opencl"):
        raise ValueError(f"SPH backend must be auto, cpu or opencl (got {requested!r})")

    cpu = {"sph_backend": "cpu", "argv": [], "label": "CPU (PySPH Cython, float64)"}
    if requested == "cpu":
        return {**cpu, "reason": "CPU requested"}

    # Checked before any device: a GPU that cannot be programmed is no GPU.
    incompatibility = _compyle_gpu_incompatibility()
    if incompatibility is not None:
        if requested == "opencl":
            raise SPHUnavailableError(
                f"OpenCL SPH backend requested but unavailable: {incompatibility}"
            )
        return {**cpu, "reason": f"GPU SPH unavailable, running on CPU: {incompatibility}"}

    found, detail = _opencl_fp64_gpu()
    if found is None:
        if requested == "opencl":
            raise SPHUnavailableError(f"OpenCL SPH backend requested but unavailable: {detail}")
        return {**cpu, "reason": f"OpenCL unavailable, running on CPU: {detail}"}

    platform_index, device_index, name = found
    if "PYOPENCL_CTX" in os.environ:
        detail += f" (PYOPENCL_CTX preset to {os.environ['PYOPENCL_CTX']!r} and honoured)"
    else:
        # Read by PyOpenCL when PySPH creates its context; without it the
        # choice between two platforms is left to enumeration order.
        os.environ["PYOPENCL_CTX"] = f"{platform_index}:{device_index}"
    return {
        "sph_backend": "opencl",
        # --use-double keeps SPH in float64 like the SWE solver.
        #
        # --nnps gpu_octree is NOT a tuning choice. PySPH's default GPU
        # neighbour search, ZOrderGPUNNPS, casts a size-1 device array straight
        # to a scalar -- z_order_gpu_nnps.pyx:227,
        # `<unsigned int>(self.max_cid_src.get())` -- and NumPy 2 refuses that
        # with "only 0-dimensional arrays can be converted to Python scalars".
        # It is compiled Cython in the installed wheel, so no Python-level shim
        # can reach it, and the line is on the fluid-to-boundary path that every
        # run with boundary particles takes. octree_gpu_nnps.pyx has no such
        # cast. A neighbour search is a lookup structure, not physics: it finds
        # the same neighbours within the same radius, so this changes summation
        # ORDER only, which is the round-off caveat in the module docstring.
        "argv": ["--opencl", "--use-double", "--nnps", "gpu_octree"],
        "label": f"GPU (OpenCL, {name}, float64)",
        "reason": detail,
    }


def _pull_from_device(particle_array, *props: str) -> None:
    """Copy particle properties back from the GPU. A no-op on the CPU backend."""
    device = getattr(particle_array, "gpu", None)
    if device is not None:
        device.pull(*props)


def hydrostatic_density(z: np.ndarray, surface_z: np.ndarray,
                        c0: float) -> np.ndarray:
    """
    Initial WCSPH density that already carries the hydrostatic pressure.

    Inverting the Tait equation of state (Monaghan 1994 eq. 6),

        p = B * ((rho/rho0)^gamma - 1),   B = rho0 * c0^2 / gamma

    for the hydrostatic pressure p = rho0*g*(surface - z) gives

        rho = rho0 * (1 + rho0*g*(surface - z) / B)^(1/gamma)

    Starting every particle at a uniform rho0 instead — which is what this
    function was added to stop — starts the column at zero pressure everywhere.
    The fluid then has to compress under its own weight before it can support
    itself, and the transient that follows is large enough to fail a
    hydrostatic check outright: it left the measured dp/d(depth) 29% below
    rho*g, and put visible spurious motion into water that should be at rest.
    """
    B = RHO_WATER * c0 ** 2 / TAIT_GAMMA
    pressure = RHO_WATER * GRAVITY * np.maximum(0.0, surface_z - z)
    return RHO_WATER * (1.0 + pressure / B) ** (1.0 / TAIT_GAMMA)


def orient_downhill(bed_elevation: np.ndarray) -> tuple:
    """
    Rotate a DEM window so that increasing row index (+y) points DOWNSLOPE.

    The whole near-field setup is built along +y: the reservoir sits at low y,
    the breach faces +y, the surge advances into +y and the front position is
    measured as the 99th percentile of particle y. All of that is meaningless
    unless +y is actually downstream.

    A DEM window arrives in solver row order — row 0 is the SOUTHERNMOST row —
    which is a compass direction, not a hydraulic one. Left uncorrected, a dam
    on a river flowing south would have its reservoir released UPHILL, and the
    surge would stall against the valley wall while the numbers still looked
    superficially reasonable.

    The window is rotated by whichever multiple of 90 degrees drops the bed
    furthest from its upstream edge to its downstream edge. Only the four
    lattice-preserving rotations are considered on purpose: an arbitrary-angle
    rotation would need interpolation, which invents elevations the 30 m source
    does not contain.

    Returns:
        (oriented_bed, rotations) where rotations is the np.rot90 count applied.
    """
    bed = np.asarray(bed_elevation, dtype=np.float64)

    # Score each of the four rotations by how far the bed actually falls from
    # the upstream edge to the downstream edge, and take the largest. Measuring
    # the fall directly is both simpler and more robust than fitting a gradient
    # plane and reasoning about how rot90 maps it.
    best_rot, best_drop = 0, -np.inf
    for rot in range(4):
        candidate = np.rot90(bed, rot)
        drop = float(candidate[0, :].mean() - candidate[-1, :].mean())
        if drop > best_drop:
            best_drop, best_rot = drop, rot

    return np.ascontiguousarray(np.rot90(bed, best_rot)), best_rot


def _downsample_bed(bed_elevation: np.ndarray, cell_size_m: float,
                    spacing_m: float) -> tuple:
    """
    Resample a DEM patch onto the SPH particle spacing.

    Returns (bed_on_spacing, nx, ny) where bed_on_spacing[j, i] is the bed
    elevation at local coordinates (i*spacing, j*spacing).
    """
    ny_src, nx_src = bed_elevation.shape
    width_m = nx_src * cell_size_m
    height_m = ny_src * cell_size_m

    nx = max(2, int(width_m / spacing_m))
    ny = max(2, int(height_m / spacing_m))

    # Nearest-neighbour: the DEM is already the coarser of the two grids, so
    # interpolating would invent structure the 30 m source does not contain.
    src_i = np.clip((np.arange(nx) * spacing_m / cell_size_m).astype(int), 0, nx_src - 1)
    src_j = np.clip((np.arange(ny) * spacing_m / cell_size_m).astype(int), 0, ny_src - 1)
    return bed_elevation[np.ix_(src_j, src_i)], nx, ny


def run_near_field_sph(
    bed_elevation: np.ndarray,
    cell_size_m: float,
    reservoir_depth_m: float,
    breach_width_m: float,
    q_peak_m3_s: float,
    dam_row_fraction: float = 0.25,
    duration_s: float = 30.0,
    dam_name: str = "Dam",
    target_particles: int = TARGET_FLUID_PARTICLES,
    backend: Optional[str] = "auto",
) -> Dict[str, Any]:
    """
    Run a near-field WCSPH dam-break over real terrain.

    The reservoir column is placed upstream of the breach row and released onto
    the DEM-derived bed. Nothing here is stochastic: given the same terrain and
    the same dam parameters the particle field is identical run to run, and it
    changes when either changes. That is the property the previous np.random
    stand-in could not have.

    Args:
        bed_elevation: DEM patch [ny, nx] in metres, solver row order
            (row 0 = south / upstream end), covering the near-field window.
        cell_size_m: Spacing of bed_elevation (m).
        reservoir_depth_m: Water depth behind the dam at failure (m). This is
            the SWE-side head handed across; see the one-way note in the module
            docstring.
        breach_width_m: Breach opening width (m), from the Phase 3 regressions.
        q_peak_m3_s: Peak breach outflow (m3/s), from the Phase 3 ensemble.
            Sets the initial downstream velocity of the released column via the
            existing handoff relation u = Q / (h * w).
        dam_row_fraction: Where along the domain the dam sits, as a fraction of
            the domain length. The reservoir occupies everything upstream of it.
        duration_s: Simulated time (s). Tens of seconds is the near-field scale.
        dam_name: For provenance in the returned dict.
        target_particles: Fluid-particle budget the spacing is derived from.
            Lower it to trade resolution for wall-clock; the tests use a small
            budget so the validation gates stay runnable in the default suite.
        backend: "auto", "opencl" or "cpu" (see resolve_sph_backend). Both run
            the same WCSPH scheme in float64; the result records which ran.

    Returns:
        Dict with particle arrays in a LOCAL frame (origin at the domain's
        upstream-left corner, metres), the surge-front history, and provenance:

            x, y, z          particle positions (m, local frame)
            u, v, w          particle velocities (m/s)
            particle_volume_m3, particle_mass_kg, particle_spacing_m
            front_position_m / front_time_s   surge front advance
            max_depth_m, max_speed_m_s
            n_fluid, n_boundary, wall_clock_s
            engine, engine_label, reaches_downstream_gauges (always False)

    Raises:
        SPHUnavailableError: if PySPH cannot run here. Never returns synthetic
            particles as a substitute.
    """
    available, detail = is_pysph_available()
    if not available:
        raise SPHUnavailableError(
            f"PySPH is not usable in this environment ({detail}). No near-field "
            f"SPH result can be produced. Install it with `pip install pysph` — "
            f"it compiles generated C at runtime and needs a working C/C++ "
            f"toolchain (MSVC Build Tools on Windows)."
        )

    try:
        from pysph.base.kernels import WendlandQuintic
        from pysph.base.utils import get_particle_array_wcsph
        from pysph.solver.application import Application
        from pysph.sph.scheme import WCSPHScheme
    except Exception as exc:  # pragma: no cover
        raise SPHUnavailableError(f"PySPH import failed: {type(exc).__name__}: {exc}") from exc

    bed_elevation = np.asarray(bed_elevation, dtype=np.float64)
    if bed_elevation.ndim != 2:
        raise ValueError(f"bed_elevation must be 2D, got shape {bed_elevation.shape}")

    # Make +y point downhill before anything is built along it. See
    # orient_downhill(): row order in a DEM is a compass direction, and the
    # near-field geometry needs a hydraulic one.
    bed_elevation, rotations = orient_downhill(bed_elevation)
    bed_drop_m = float(bed_elevation[0, :].mean() - bed_elevation[-1, :].mean())

    ny_src, nx_src = bed_elevation.shape
    domain_length_m = ny_src * cell_size_m       # downstream (+y)
    domain_width_m = nx_src * cell_size_m        # cross-valley (+x)
    reservoir_depth_m = float(max(reservoir_depth_m, 1.0))

    # Particle spacing from the budget, not hardcoded: the reservoir block is
    # (dam_row_fraction * length) x width x depth, so solve for the spacing that
    # fills it with roughly TARGET_FLUID_PARTICLES.
    reservoir_volume = (
        domain_length_m * dam_row_fraction * domain_width_m * reservoir_depth_m
    )
    spacing = float(np.cbrt(reservoir_volume / max(1, int(target_particles))))
    # Never finer than the DEM can justify, never so coarse the column is a slab.
    spacing = float(np.clip(spacing, 1.0, max(2.0, reservoir_depth_m / 4.0)))

    bed, nx, ny = _downsample_bed(bed_elevation, cell_size_m, spacing)
    dam_row = max(1, int(ny * dam_row_fraction))

    # ---- Fluid: the reservoir column, resting on the bed, upstream of the dam.
    fluid_x, fluid_y, fluid_z, fluid_surface = [], [], [], []
    n_layers = int(reservoir_depth_m / spacing)
    for j in range(dam_row):
        for i in range(nx):
            bed_z = bed[j, i]
            # The reservoir has a LEVEL free surface, so its height above the
            # bed varies with the terrain beneath it — deeper in the thalweg,
            # shallower against the banks. Stacking a fixed depth on every cell
            # instead would tilt the water surface to follow the valley floor,
            # which is not a reservoir at rest and would start the run with a
            # slope-driven flow that has nothing to do with the breach.
            surface_z = bed[0, :].min() + reservoir_depth_m
            for k in range(n_layers):
                z = bed_z + (k + 0.5) * spacing
                if z > surface_z:
                    break
                fluid_x.append(i * spacing)
                fluid_y.append(j * spacing)
                fluid_z.append(z)
                fluid_surface.append(surface_z)

    if not fluid_x:
        raise ValueError(
            f"No fluid particles generated (spacing={spacing:.2f} m, "
            f"reservoir_depth={reservoir_depth_m:.1f} m). The near-field window "
            f"is too small for this dam."
        )

    fluid_x = np.array(fluid_x)
    fluid_y = np.array(fluid_y)
    fluid_z = np.array(fluid_z)
    fluid_surface_z = np.array(fluid_surface)

    # ---- Boundary. The bed, plus walls closing the domain on three sides.
    #
    # The walls are not decoration. Without them the reservoir column is a
    # free-standing block that collapses in every direction at once: water runs
    # off the upstream edge, leaves the bed entirely and free-falls, which both
    # loses mass downstream and reports a spurious maximum speed from particles
    # accelerating into empty space. A breach reservoir is confined by the dam
    # abutments and the valley sides and opens only downstream, so the domain
    # is closed at y=0 (upstream) and at both x faces, and left open at the
    # downstream end where the surge is supposed to leave.
    bound_x, bound_y, bound_z = [], [], []

    for j in range(ny):
        for i in range(nx):
            for layer in range(2):
                bound_x.append(i * spacing)
                bound_y.append(j * spacing)
                bound_z.append(bed[j, i] - (layer + 0.5) * spacing)

    wall_height = reservoir_depth_m + 2.0 * spacing
    n_wall_layers = int(wall_height / spacing) + 1

    # Upstream wall (y < 0), spanning the full width.
    for i in range(nx):
        for layer in range(2):
            for k in range(n_wall_layers):
                bound_x.append(i * spacing)
                bound_y.append(-(layer + 0.5) * spacing)
                bound_z.append(bed[0, i] + (k + 0.5) * spacing)

    # Lateral walls (x < 0 and x > width), full domain length.
    for j in range(ny):
        for layer in range(2):
            for k in range(n_wall_layers):
                z_wall = bed[j, 0] + (k + 0.5) * spacing
                bound_x.append(-(layer + 0.5) * spacing)
                bound_y.append(j * spacing)
                bound_z.append(z_wall)

                z_wall = bed[j, nx - 1] + (k + 0.5) * spacing
                bound_x.append((nx - 1 + layer + 0.5) * spacing)
                bound_y.append(j * spacing)
                bound_z.append(z_wall)

    bound_x = np.array(bound_x)
    bound_y = np.array(bound_y)
    bound_z = np.array(bound_z)

    # ---- One-way SWE -> SPH handoff. The released column starts with the
    # downstream velocity the breach discharge implies, u = Q / (h * w) — the
    # same relation sph/coupling.py::handoff_swe_to_sph documents. Nothing
    # returns from SPH to the SWE side.
    u_inflow = float(q_peak_m3_s / max(reservoir_depth_m * breach_width_m, 1.0))
    # A breach jet cannot exceed the free-fall speed for its own head; clamp
    # rather than launch particles at a physically impossible velocity when the
    # regression's Q_peak and the geometry disagree.
    u_inflow = float(np.clip(u_inflow, 0.0, np.sqrt(2.0 * GRAVITY * reservoir_depth_m)))

    # The jet velocity applies AT THE BREACH, not to the whole reservoir. Mask
    # it to the breach opening — the last row of the column, centred on the
    # valley and breach_width_m wide — exactly as coupling.handoff_swe_to_sph
    # masks by |x - centre| < w/2. Giving the entire column a uniform 10 m/s
    # downstream velocity (the first version of this) starts the run with far
    # more momentum than the breach could deliver, and the surge front that
    # follows is correspondingly too fast.
    breach_centre_x = 0.5 * (nx - 1) * spacing
    breach_mask = (
        (np.abs(fluid_x - breach_centre_x) <= breach_width_m / 2.0)
        & (fluid_y >= (dam_row - 1) * spacing)
    )
    fluid_v = np.zeros_like(fluid_x)
    fluid_v[breach_mask] = u_inflow

    particle_volume = spacing ** 3
    particle_mass = RHO_WATER * particle_volume
    h0 = HDX * spacing

    # Speed of sound: 10x the maximum expected flow speed keeps density
    # fluctuations under ~1%, the standard WCSPH criterion (Monaghan 1994).
    max_expected_speed = max(np.sqrt(2.0 * GRAVITY * reservoir_depth_m), u_inflow, 1.0)
    c0 = 10.0 * max_expected_speed

    # Extent of the actual bed in the particle frame. Beyond it there is no
    # terrain, so anything out there is in free flight and must not be measured.
    domain_length_local = (ny - 1) * spacing
    domain_width_local = (nx - 1) * spacing

    front_time: List[float] = []
    front_position: List[float] = []

    class _NearFieldDamBreak(Application):
        def create_particles(self):
            fluid = get_particle_array_wcsph(
                name="fluid",
                x=fluid_x, y=fluid_y, z=fluid_z,
                m=np.full_like(fluid_x, particle_mass),
                h=np.full_like(fluid_x, h0),
                # Hydrostatic, not uniform rho0 — see hydrostatic_density().
                rho=hydrostatic_density(fluid_z, fluid_surface_z, c0),
                v=fluid_v,                           # downstream, +y (breach only)
            )
            boundary = get_particle_array_wcsph(
                name="boundary",
                x=bound_x, y=bound_y, z=bound_z,
                m=np.full_like(bound_x, particle_mass),
                h=np.full_like(bound_x, h0),
                rho=np.full_like(bound_x, RHO_WATER),
            )
            return [fluid, boundary]

        def create_scheme(self):
            scheme = WCSPHScheme(
                ["fluid"], ["boundary"], dim=3, rho0=RHO_WATER,
                c0=c0, h0=h0, hdx=HDX,
                gz=-GRAVITY,               # gravity acts on -z; +y is downstream
                alpha=ALPHA_VISCOSITY, beta=BETA_VISCOSITY, gamma=TAIT_GAMMA,
                hg_correction=True,
            )
            # Initial CFL on the acoustic speed (Monaghan 1994 eq. 3.19)...
            dt = 0.25 * h0 / (1.1 * c0)
            # ...then let PySPH ADAPT it, as its own validated dam_break_3d.py
            # does. A fixed timestep sized only on the acoustic speed ignores
            # the force and viscous limits, which tighten sharply once the
            # column collapses and particles accelerate; adapting dt is the
            # scheme's own guard against that.
            scheme.configure_solver(
                kernel=WendlandQuintic(dim=3), dt=dt, tf=duration_s,
                adaptive_timestep=True, n_damp=N_DAMP_STEPS,
                pfreq=10 ** 9,  # no intermediate dumps
            )
            return scheme

        def post_step(self, solver):
            # Surge front = furthest downstream extent of the body of fluid,
            # measured on the 99th percentile so isolated spray particles
            # cannot define it, and ONLY over particles still inside the domain.
            #
            # The domain is open downstream, which is correct — the surge has to
            # be able to leave. But there is no bed beyond the last DEM row, so
            # a particle that exits free-falls indefinitely and accelerates
            # without bound. Including those made the front advance to 1165 m in
            # a 600 m domain and pushed the reported maximum speed to 113 m/s
            # against an available-head limit of 82 m/s. Both were measurements
            # of particles in empty space, not of the flood.
            fluid = self.particles[0]
            _pull_from_device(fluid, "y")
            y = np.asarray(fluid.y)
            inside = (y >= 0.0) & (y <= domain_length_local)
            if inside.sum() < FRONT_MIN_PARTICLES:
                return
            front_time.append(float(solver.t))
            front_position.append(float(np.percentile(y[inside], 99.0)))

    sph_backend = resolve_sph_backend(backend)
    started = time.perf_counter()
    app = _NearFieldDamBreak()
    # argv is passed explicitly: PySPH's Application parses sys.argv by default,
    # and inside a Celery worker or pytest that is the HOST process's command
    # line, which it then rejects as unknown options.
    # The shim repairs compyle's Python 3.14 breakage for the duration of the
    # compile, and only on the GPU path (sph/compyle_compat.py).
    with compyle_python314_compat_if(sph_backend["sph_backend"] != "cpu"):
        app.run(argv=["--disable-output", "-d", _scratch_dir(dam_name)] + sph_backend["argv"])
    wall_clock = time.perf_counter() - started

    # COPY, not view. PySPH's particle arrays are views into buffers the
    # framework owns and reuses, so np.asarray (which does not copy when the
    # dtype already matches) hands back memory that the NEXT run overwrites.
    # Two results held at once then compared read as wildly different -
    # elevations of order 1e268 - which looks exactly like a diverged
    # simulation and is not: it is a use-after-free in this function.
    fluid = app.particles[0]
    _pull_from_device(fluid, "x", "y", "z", "u", "v", "w")
    x = np.array(fluid.x, dtype=np.float64, copy=True)
    y = np.array(fluid.y, dtype=np.float64, copy=True)
    z = np.array(fluid.z, dtype=np.float64, copy=True)
    u = np.array(fluid.u, dtype=np.float64, copy=True)
    v = np.array(fluid.v, dtype=np.float64, copy=True)
    w = np.array(fluid.w, dtype=np.float64, copy=True)

    _assert_did_not_diverge(x, y, z, u, v, w, domain_length_local,
                            domain_width_local, bed, spacing)

    speed = np.sqrt(u ** 2 + v ** 2 + w ** 2)
    bed_at_particle = _sample_bed(bed, x, y, spacing)
    depth = np.maximum(0.0, z - bed_at_particle)

    # Only particles still over the terrain describe the flood. See post_step
    # above: the downstream boundary is deliberately open, and past it there is
    # no bed to stand on.
    in_domain = (
        (y >= 0.0) & (y <= domain_length_local)
        & (x >= 0.0) & (x <= domain_width_local)
        & (z >= bed_at_particle - 3.0 * spacing)
    )
    n_escaped = int((~in_domain).sum())
    depth_in = depth[in_domain]
    speed_in = speed[in_domain]

    # An honest upper bound on speed for this configuration: a particle can
    # convert at most the full available head into kinetic energy. Exceeding it
    # means energy is coming from somewhere it should not.
    available_head_m = float(np.max(fluid_surface_z) - np.min(bed))
    energy_bound_m_s = float(np.sqrt(2.0 * GRAVITY * max(available_head_m, 0.0)))

    return {
        "x": x, "y": y, "z": z,
        "u": u, "v": v, "w": w,
        "particle_spacing_m": spacing,
        "particle_volume_m3": particle_volume,
        "particle_mass_kg": particle_mass,
        "n_fluid": int(x.size),
        "n_boundary": int(bound_x.size),
        "front_time_s": front_time,
        "front_position_m": front_position,
        "front_speed_m_s": (
            (front_position[-1] - front_position[0]) / (front_time[-1] - front_time[0])
            if len(front_time) > 1 and front_time[-1] > front_time[0] else 0.0
        ),
        "max_depth_m": float(np.max(depth_in)) if depth_in.size else 0.0,
        "max_speed_m_s": float(np.max(speed_in)) if speed_in.size else 0.0,
        "n_escaped": n_escaped,
        "n_in_domain": int(in_domain.sum()),
        "available_head_m": available_head_m,
        "energy_bound_m_s": energy_bound_m_s,
        # True when the surge reached the downstream edge before the run ended,
        # i.e. the near-field window was exhausted and the later part of the
        # front history is pinned at the boundary rather than still advancing.
        "front_exited_domain": bool(
            front_position and front_position[-1] >= 0.98 * domain_length_local),
        "domain_length_m": domain_length_m,
        "domain_width_m": domain_width_m,
        "duration_s": duration_s,
        "reservoir_depth_m": reservoir_depth_m,
        "u_inflow_m_s": u_inflow,
        "wall_clock_s": wall_clock,
        "dam_name": dam_name,
        "bed_drop_m": bed_drop_m,
        "orientation_rot90": int(rotations),
        "engine": "PySPH_WCSPH",
        "engine_label": f"PySPH WCSPH (Wendland quintic, {detail}) on {sph_backend['label']}",
        "sph_backend": sph_backend["sph_backend"],
        "sph_backend_label": sph_backend["label"],
        "sph_backend_reason": sph_backend["reason"],
        # Stated in the payload, not just in prose, so no consumer can quietly
        # assume otherwise: this domain does not reach the downstream gauges.
        "reaches_downstream_gauges": False,
        "coupling": "one-way SWE -> SPH handoff (no feedback)",
    }


def run_still_water_validation(
    depth_m: float = 10.0,
    spacing_m: float = 0.5,
    duration_s: float = 2.0,
    tank_cells: int = 20,
    backend: Optional[str] = "auto",
) -> Dict[str, Any]:
    """
    Hydrostatic gate: water at rest in a closed tank must STAY at rest.

    This is the SPH counterpart of the lake-at-rest test that gates the SWE
    solver (CLAUDE.md testing strategy), and it exercises the exact WCSPHScheme
    configuration run_near_field_sph uses — same kernel, same Tait gamma, same
    artificial viscosity, same c0 rule — so passing it says something about the
    production setup rather than about a separate toy.

    Two things are checked, and both are properties of correct SPH rather than
    of a particular benchmark dataset, so neither depends on an unvetted
    published coefficient:

      1. NO SPURIOUS MOTION. Still water under gravity in a closed box is an
         equilibrium. A scheme with a broken pressure gradient, or boundary
         particles that do not support the column, shows it immediately as
         particles drifting or the free surface collapsing.
      2. HYDROSTATIC PRESSURE. p(z) = rho*g*(h - z) is exact for a fluid at
         rest. The measured profile is regressed against depth and the slope
         compared to rho*g.

    Returns:
        Dict with max_speed_m_s, mean_speed_m_s, surface_drop_m,
        hydrostatic_slope, expected_slope, slope_error_pct, density_error_pct.
    """
    available, detail = is_pysph_available()
    if not available:
        raise SPHUnavailableError(f"PySPH is not usable here ({detail}).")

    from pysph.base.kernels import WendlandQuintic
    from pysph.base.utils import get_particle_array_wcsph
    from pysph.solver.application import Application
    from pysph.sph.scheme import WCSPHScheme

    nx = max(4, int(tank_cells))   # a squat box; the column, not the span, matters
    nz = max(4, int(depth_m / spacing_m))

    xs, ys, zs = [], [], []
    for i in range(nx):
        for j in range(nx):
            for k in range(nz):
                xs.append(i * spacing_m)
                ys.append(j * spacing_m)
                zs.append((k + 0.5) * spacing_m)
    xs, ys, zs = np.array(xs), np.array(ys), np.array(zs)

    bx, by, bz = [], [], []
    for i in range(-2, nx + 2):
        for j in range(-2, nx + 2):
            for layer in range(2):
                bx.append(i * spacing_m); by.append(j * spacing_m)
                bz.append(-(layer + 0.5) * spacing_m)
    for k in range(nz + 2):
        for j in range(-2, nx + 2):
            for layer in range(2):
                bx.append(-(layer + 0.5) * spacing_m); by.append(j * spacing_m)
                bz.append((k + 0.5) * spacing_m)
                bx.append((nx - 1 + layer + 0.5) * spacing_m); by.append(j * spacing_m)
                bz.append((k + 0.5) * spacing_m)
        for i in range(-2, nx + 2):
            for layer in range(2):
                bx.append(i * spacing_m); by.append(-(layer + 0.5) * spacing_m)
                bz.append((k + 0.5) * spacing_m)
                bx.append(i * spacing_m); by.append((nx - 1 + layer + 0.5) * spacing_m)
                bz.append((k + 0.5) * spacing_m)
    bx, by, bz = np.array(bx), np.array(by), np.array(bz)

    mass = RHO_WATER * spacing_m ** 3
    h0 = HDX * spacing_m
    c0 = 10.0 * np.sqrt(2.0 * GRAVITY * depth_m)

    class _StillWater(Application):
        def create_particles(self):
            fluid = get_particle_array_wcsph(
                name="fluid", x=xs, y=ys, z=zs,
                m=np.full_like(xs, mass), h=np.full_like(xs, h0),
                rho=hydrostatic_density(zs, np.full_like(zs, zs.max()), c0))
            boundary = get_particle_array_wcsph(
                name="boundary", x=bx, y=by, z=bz,
                m=np.full_like(bx, mass), h=np.full_like(bx, h0),
                rho=np.full_like(bx, RHO_WATER))
            return [fluid, boundary]

        def create_scheme(self):
            scheme = WCSPHScheme(
                ["fluid"], ["boundary"], dim=3, rho0=RHO_WATER,
                c0=c0, h0=h0, hdx=HDX, gz=-GRAVITY,
                alpha=ALPHA_VISCOSITY, beta=BETA_VISCOSITY, gamma=TAIT_GAMMA,
                hg_correction=True,
            )
            scheme.configure_solver(
                kernel=WendlandQuintic(dim=3), dt=0.25 * h0 / (1.1 * c0),
                tf=duration_s, adaptive_timestep=False,
                n_damp=N_DAMP_STEPS, pfreq=10 ** 9)
            return scheme

    surface_before = float(zs.max())
    sph_backend = resolve_sph_backend(backend)
    app = _StillWater()
    with compyle_python314_compat_if(sph_backend["sph_backend"] != "cpu"):
        app.run(argv=["--disable-output", "-d", _scratch_dir("stillwater")] + sph_backend["argv"])

    fluid = app.particles[0]
    _pull_from_device(fluid, "z", "p", "rho", "u", "v", "w")
    z = np.asarray(fluid.z, dtype=np.float64)
    p = np.asarray(fluid.p, dtype=np.float64)
    rho = np.asarray(fluid.rho, dtype=np.float64)
    speed = np.sqrt(np.asarray(fluid.u) ** 2 + np.asarray(fluid.v) ** 2
                    + np.asarray(fluid.w) ** 2)

    # Fit p against depth below the free surface; the slope should be rho*g.
    #
    # Interior particles only: pressure goes to zero at the free surface by
    # construction and the outermost layer is kernel-truncated, so including
    # either measures the boundary treatment rather than the pressure gradient.
    #
    # That trimming is also why this measurement is RESOLUTION-DEPENDENT, and
    # why it reports None rather than a number when it cannot be made. At
    # spacing 0.8 m in a 4 m column the interior band is barely one particle
    # layer thick, and fitting a gradient through it returned errors of 27% and
    # 123% for the same physics at two run lengths. A meaningless number
    # presented as a measurement is worse than an honest "not measurable here".
    surface = float(np.percentile(z, 98))
    depth_below = surface - z
    interior = (depth_below > 2.0 * spacing_m) & (depth_below < depth_m - 2.0 * spacing_m)

    expected = RHO_WATER * GRAVITY
    distinct_layers = int(np.unique(np.round(z[interior] / spacing_m)).size)
    if interior.sum() >= 50 and distinct_layers >= 4:
        slope = float(np.polyfit(depth_below[interior], p[interior], 1)[0])
        slope_error_pct = 100.0 * abs(slope - expected) / expected
        slope_note = f"fitted over {int(interior.sum())} particles in {distinct_layers} layers"
    else:
        slope = None
        slope_error_pct = None
        slope_note = (
            f"NOT MEASURED: only {int(interior.sum())} interior particles across "
            f"{distinct_layers} layers. A pressure gradient needs at least 4 "
            f"layers; use a finer spacing_m or a deeper column."
        )

    return {
        "max_speed_m_s": float(np.max(speed)),
        "mean_speed_m_s": float(np.mean(speed)),
        "surface_drop_m": surface_before - surface,
        "hydrostatic_slope": slope,
        "expected_slope": expected,
        "slope_error_pct": slope_error_pct,
        "slope_note": slope_note,
        "density_error_pct": 100.0 * float(np.max(np.abs(rho - RHO_WATER))) / RHO_WATER,
        "all_finite": bool(np.all(np.isfinite(z)) and np.all(np.isfinite(p))),
        "n_fluid": int(z.size),
        "spacing_m": spacing_m,
        "duration_s": duration_s,
        "sph_backend": sph_backend["sph_backend"],
        "sph_backend_label": sph_backend["label"],
        "sph_backend_reason": sph_backend["reason"],
    }


def _assert_did_not_diverge(x, y, z, u, v, w, domain_length, domain_width,
                            bed, spacing) -> None:
    """
    Refuse to report a blown-up run.

    An `isfinite` check is not enough on its own: 1e268 is a perfectly finite
    float, and a particle at that elevation would then be silently excluded by
    the in-domain filter that computes the reported maxima — leaving a run that
    looks healthy because the broken half of it was filtered out of view. This
    guard therefore bounds positions physically rather than merely checking
    they are numbers.

    The bound is deliberately loose — several domain-widths past the terrain —
    because particles are allowed to leave through the open downstream boundary
    and fall. It exists to catch numerical explosion, not to police physics.

    Raises:
        SPHUnavailableError: so the caller reports "no SPH result" and its
        reason, rather than publishing numbers from a failed integration.
    """
    finite = np.isfinite(x) & np.isfinite(y) & np.isfinite(z)
    if not finite.all():
        raise SPHUnavailableError(
            f"The SPH run diverged: {int((~finite).sum())} of {x.size} particles "
            f"have non-finite positions. Refusing to report the result."
        )

    scale = max(domain_length, domain_width, 1.0)
    runaway = (
        (np.abs(x) > 100.0 * scale)
        | (np.abs(y) > 100.0 * scale)
        | (np.abs(z - float(np.mean(bed))) > 100.0 * scale)
    )
    if runaway.any():
        worst = float(np.max(np.abs(z)))
        raise SPHUnavailableError(
            f"The SPH run diverged: {int(runaway.sum())} of {x.size} particles "
            f"left the domain by more than 100x its size (largest |z| = "
            f"{worst:.3e} m against a {scale:.0f} m domain). This is numerical "
            f"blow-up, not flow. Refusing to report the result."
        )

    speed = np.sqrt(u ** 2 + v ** 2 + w ** 2)
    if not np.isfinite(speed).all():
        raise SPHUnavailableError(
            "The SPH run diverged: non-finite particle velocities."
        )


def _sample_bed(bed: np.ndarray, x: np.ndarray, y: np.ndarray,
                spacing: float) -> np.ndarray:
    """Bed elevation beneath each particle, by nearest cell."""
    ny, nx = bed.shape
    i = np.clip((x / spacing).astype(int), 0, nx - 1)
    j = np.clip((y / spacing).astype(int), 0, ny - 1)
    return bed[j, i]


def _scratch_dir(dam_name: str) -> str:
    """A throwaway output directory; particle state is read from memory."""
    import tempfile
    from pathlib import Path

    safe = "".join(ch for ch in dam_name if ch.isalnum() or ch in "-_") or "sph"
    path = Path(tempfile.gettempdir()) / f"jalraksha_sph_{safe}"
    path.mkdir(parents=True, exist_ok=True)
    return str(path)
