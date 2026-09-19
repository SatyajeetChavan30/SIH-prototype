"""
Engine-neutral near-field geometry and result checks (Phase 7).

Two SPH engines build the same near-field case — PySPH (`pysph_runner.py`) and
DualSPHysics (`dualsphysics_runner.py`) — and they must agree on everything
that is not the SPH scheme itself: which way is downstream, how the particle
budget becomes a spacing, what velocity the breach hands across, and what
counts as a diverged run. Those rules live here so the two engines cannot
drift apart, and so a result from either one means the same thing.

Nothing in this module imports an SPH library.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np

GRAVITY = 9.81  # m/s2
RHO_WATER = 1000.0  # kg/m3, freshwater reference density

# Depth below which a particle is not counted as part of the surge front, so a
# handful of spray particles cannot define the front position.
FRONT_MIN_PARTICLES = 8


class SPHUnavailableError(RuntimeError):
    """
    No near-field SPH result can be produced here.

    Raised rather than degraded. The alternative — returning something
    plausible — is exactly the failure the SPH modules were written to remove.
    """


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


def particle_spacing_for_budget(
    domain_length_m: float,
    domain_width_m: float,
    reservoir_depth_m: float,
    dam_row_fraction: float,
    target_particles: int,
) -> float:
    """
    Particle spacing that fills the reservoir block with about `target_particles`.

    The reservoir block is (dam_row_fraction * length) x width x depth. The
    spacing is derived from the budget rather than hardcoded so a 260 m Tehri
    head and a 30 m barrage both produce a run of bounded cost. It is never
    finer than 1 m (the 30 m DEM cannot justify more) and never so coarse that
    the column is a slab of fewer than four layers.
    """
    reservoir_volume = domain_length_m * dam_row_fraction * domain_width_m * reservoir_depth_m
    spacing = float(np.cbrt(reservoir_volume / max(1, int(target_particles))))
    return float(np.clip(spacing, 1.0, max(2.0, reservoir_depth_m / 4.0)))


def breach_inflow_velocity(q_peak_m3_s: float, reservoir_depth_m: float, breach_width_m: float) -> float:
    """
    Downstream velocity handed across the breach: u = Q / (h * w), clamped.

    The same relation sph/coupling.py::handoff_swe_to_sph documents. A breach
    jet cannot exceed the free-fall speed for its own head, so the result is
    clamped to sqrt(2 g h) rather than launching particles at a physically
    impossible velocity when the regression's Q_peak and the geometry disagree.
    """
    u_inflow = float(q_peak_m3_s / max(reservoir_depth_m * breach_width_m, 1.0))
    return float(np.clip(u_inflow, 0.0, np.sqrt(2.0 * GRAVITY * reservoir_depth_m)))


def _downsample_bed(bed_elevation: np.ndarray, cell_size_m: float, spacing_m: float) -> tuple:
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


def _assert_did_not_diverge(x, y, z, u, v, w, domain_length, domain_width, bed, spacing) -> None:
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

    speed = np.sqrt(u**2 + v**2 + w**2)
    if not np.isfinite(speed).all():
        raise SPHUnavailableError("The SPH run diverged: non-finite particle velocities.")


def _sample_bed(bed: np.ndarray, x: np.ndarray, y: np.ndarray, spacing: float) -> np.ndarray:
    """Bed elevation beneath each particle, by nearest cell."""
    ny, nx = bed.shape
    i = np.clip((x / spacing).astype(int), 0, nx - 1)
    j = np.clip((y / spacing).astype(int), 0, ny - 1)
    return bed[j, i]


def _scratch_dir(dam_name: str) -> str:
    """A throwaway per-dam output directory under the system temp directory."""
    safe = "".join(ch for ch in dam_name if ch.isalnum() or ch in "-_") or "sph"
    path = Path(tempfile.gettempdir()) / f"jalraksha_sph_{safe}"
    path.mkdir(parents=True, exist_ok=True)
    return str(path)
