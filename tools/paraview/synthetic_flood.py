"""
SYNTHETIC flood generator — pipeline exercise only, NOT a physical result.

Purpose (spec sections 0 and 17, phases 3-4): prove the XDMF time series, the
ParaView pipeline and the Animation View all work before the real solver is
attached. Everything it produces is labelled `is_synthetic=1`, which travels
inside the dataset and drives the mandatory SYNTHETIC annotation downstream.

WHAT THIS IS NOT
    There is no mass conservation, no momentum, no friction, and no shallow-water
    equation here. It is a spreading water-surface elevation clipped against real
    terrain. It looks plausible precisely because the TERRAIN is real — water
    collects in the valleys and avoids the ridges for free — and that is exactly
    what makes it dangerous to mistake for a simulation. The project already has a
    validated HLLC + Audusse solver; use that for anything scientific.
"""

from __future__ import annotations

from typing import Any, Dict, List

import numpy as np

GRAVITY = 9.81


def synthesize_flood(
    terrain: np.ndarray,
    grid: Dict[str, Any],
    i_breach: int,
    j_breach: int,
    *,
    duration_s: float = 3600.0,
    n_frames: int = 40,
    peak_depth_m: float = 35.0,
    front_celerity_ms: float = 12.0,
    attenuation_km: float = 45.0,
    valley_window_cells: int = 9,
) -> List[Dict[str, Any]]:
    """
    Spreading water surface clipped against real terrain.

    Args:
        terrain: (ny, nx) bed elevation, metres. Row 0 = south.
        grid: nx, ny, dx, dy — for cell spacing.
        i_breach: column index (x) of the breach; j_breach: row index (y).
        duration_s: Simulated span to cover.
        n_frames: Number of timesteps written.
        peak_depth_m: Depth at the breach once the wave is fully developed.
        front_celerity_ms: How fast the wetting front advances.
        attenuation_km: e-folding distance over which the wave thins downstream.
        valley_window_cells: Neighbourhood used to decide what counts as valley
            floor rather than hillside.

    Returns:
        Frame dicts matching the xdmf_export contract: time_s, depth,
        velocity_x, velocity_y.
    """
    ny, nx = terrain.shape
    dx, dy = float(grid["dx"]), float(grid["dy"])

    # Straight-line distance from the breach. A real flood follows the channel,
    # but clipping a radial surface against real topography already confines the
    # water to the valleys, which is all this needs to do.
    jj, ii = np.mgrid[0:ny, 0:nx]
    distance = np.hypot((ii - i_breach) * dx, (jj - j_breach) * dy)

    # Confine water to valley floors.
    #
    # An earlier version set an absolute water-surface ELEVATION and took
    # depth = surface - terrain. Over a Himalayan gorge that produced a 462 m
    # deep lake: a near-horizontal surface across terrain that falls 400 m fills
    # every low point to the brim. Prescribing DEPTH instead keeps the magnitude
    # sane, and masking by "is this cell below its neighbourhood" keeps the water
    # in the channel instead of coating the hillsides.
    from scipy.ndimage import uniform_filter

    local_mean = uniform_filter(
        terrain.astype(np.float64), size=valley_window_cells, mode="nearest")
    relief = local_mean - terrain                       # >0 in valleys
    valley = np.clip(relief / max(relief.max(), 1e-6), 0.0, 1.0) ** 0.5

    # Downhill unit vector, for plausible Glyph directions. Terrain gradient
    # points uphill, so flow is its negation.
    grad_y, grad_x = np.gradient(terrain.astype(np.float64), dy, dx)
    slope_mag = np.hypot(grad_x, grad_y)
    safe = np.maximum(slope_mag, 1e-6)
    flow_x, flow_y = -grad_x / safe, -grad_y / safe

    times = np.linspace(0.0, duration_s, n_frames)
    frames: List[Dict[str, Any]] = []

    for t in times:
        front = front_celerity_ms * t                       # wetting front radius
        reached = distance <= front

        # Head builds over the first ~10 min rather than appearing instantly.
        ramp = float(np.clip(t / 600.0, 0.0, 1.0))
        # Thins with travel distance, so downstream floods later AND shallower.
        attenuation = np.exp(-distance / (attenuation_km * 1000.0))

        depth = np.where(reached, peak_depth_m * ramp * attenuation * valley, 0.0)
        depth = np.maximum(depth, 0.0).astype(np.float32)

        # Critical-flow scaling: fast where deep, zero where dry. Not momentum,
        # just a defensible magnitude for the vectors to show.
        speed = np.where(depth > 0.01, np.sqrt(GRAVITY * depth), 0.0)
        frames.append({
            "time_s": float(t),
            "depth": depth,
            "velocity_x": (flow_x * speed).astype(np.float32),
            "velocity_y": (flow_y * speed).astype(np.float32),
        })

    wet = int((frames[-1]["depth"] > 0.01).sum())
    print(
        f"[synthetic] {n_frames} frames over {duration_s/3600:.1f} h; "
        f"final wet cells {wet}/{ny*nx} ({100*wet/(ny*nx):.1f}%), "
        f"max depth {frames[-1]['depth'].max():.1f} m"
    )
    print("[synthetic] WARNING: not a physical simulation — labelled is_synthetic=1.")
    return frames
