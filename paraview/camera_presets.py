"""
Named, reproducible camera placements (spec Section 13).

Section 13 asks for cameras that can be reproduced exactly across runs rather
than an angle eyeballed once in the GUI. Before this module, `render_static.py`
hardcoded elevation/azimuth as defaults in `setup_camera`'s signature and
exposed only `--zoom` on the command line, so the two angles that actually
determine the composition were unreachable without editing the script.

This module holds only the numbers. The placement maths — and the two ParaView
bugs it has to work around — stay in `render_static.py::setup_camera`, because
they are properties of how a ParaView camera is set, not of any one preset.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CameraPreset:
    """
    One reproducible camera placement.

    elevation_deg: angle above the terrain plane. 0 is edge-on, 90 is straight down.
    azimuth_deg:   bearing of the camera around the target, anticlockwise from +X.
    pad:           multiplier on the fitted distance; >1 leaves margin at the frame edge.
    view_up:       which axis points "up" in the image. +Z is elevation and is
                   right for every oblique view, but at a near-vertical elevation
                   the up vector becomes parallel to the view direction and the
                   view degenerates to a blank frame — so `top` overrides it to +Y.
    """

    name: str
    elevation_deg: float
    azimuth_deg: float
    pad: float = 1.25
    view_up: tuple[float, float, float] = (0.0, 0.0, 1.0)
    description: str = ""


# `perspective` reproduces the exact angles Phases 1/3/4 were signed off with.
# Changing them would invalidate artifacts that have already been reviewed, so
# they are carried over verbatim rather than "improved".
PRESETS: dict[str, CameraPreset] = {
    "perspective": CameraPreset(
        name="perspective", elevation_deg=32.0, azimuth_deg=235.0, pad=1.25,
        description="Default elevated oblique. The signed-off Phase 1/3/4 framing.",
    ),
    "isometric": CameraPreset(
        name="isometric", elevation_deg=35.264, azimuth_deg=225.0, pad=1.30,
        description="True isometric (atan(1/sqrt(2))), for a technical, "
                    "un-foreshortened read of the block.",
    ),
    "oblique_low": CameraPreset(
        name="oblique_low", elevation_deg=18.0, azimuth_deg=215.0, pad=1.35,
        description="Low, dramatic angle. Exaggerates relief and the block's "
                    "side walls; poor for judging planform flood extent.",
    ),
    "top": CameraPreset(
        name="top", elevation_deg=88.0, azimuth_deg=270.0, pad=1.05,
        view_up=(0.0, 1.0, 0.0),
        description="Near-nadir map view. Best for reading inundation planform "
                    "and for velocity glyphs, which are flat in the XY plane.",
    ),
}

DEFAULT_PRESET = "perspective"


def get_preset(name: str) -> CameraPreset:
    """Look up a preset by name, failing with the available options listed."""
    try:
        return PRESETS[name]
    except KeyError:
        raise SystemExit(
            f"Unknown camera preset {name!r}. Available: {', '.join(sorted(PRESETS))}"
        ) from None


def describe() -> str:
    """Human-readable table, for --help text and the README."""
    return "\n".join(
        f"  {p.name:12s} el={p.elevation_deg:6.2f} az={p.azimuth_deg:6.1f}  {p.description}"
        for p in sorted(PRESETS.values(), key=lambda preset: preset.name)
    )
