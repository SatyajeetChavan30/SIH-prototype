"""
Phase 1/7 static render — pvpython, headless.

Loads an XDMF time series, applies Warp By Scalar on terrain_elevation (the step
that turns a flat raster into an actual 3D mesh — Section 4), positions an
elevated/isometric camera showing the full domain, and saves a screenshot.

This exists as a script rather than a GUI walkthrough because it can be run and
its output inspected without a human looking at the screen — the same reasoning
Section 2 gives for pvpython/pvbatch: reproducible re-execution of a pipeline,
not a replacement for building it interactively first. (Nothing has been built
interactively yet since ParaView was only just installed; this script IS that
first build, kept simple per Section 0 — no texture, no lighting tuning, no
terrain base block yet. Those are Phase 2.)

Usage:
    pvpython paraview/render_static.py --xdmf data/simulation/terrain.xdmf \
        --out paraview/artifacts/phase1_terrain.png

    pvpython paraview/render_static.py --xdmf data/simulation/synthetic.xdmf \
        --time 1800 --out paraview/artifacts/phase3_water.png
"""

from __future__ import annotations

import argparse
import sys

from paraview.simple import (
    Calculator,
    ColorBy,
    GetActiveView,
    GetAnimationScene,
    GetColorTransferFunction,
    GetScalarBar,
    GetDisplayProperties,
    Hide,
    RenderAllViews,
    ResetCamera,
    SaveScreenshot,
    Show,
    Threshold,
    WarpByScalar,
    XDMFReader,
)


def build_terrain(xdmf_path: str, vertical_exaggeration: float):
    """
    Reader -> Warp By Scalar on terrain_elevation.

    Section 4's required chain. Vertical exaggeration is the Warp filter's Scale
    Factor — a pipeline parameter, never baked into the data (see
    ARCHITECTURE.md section 4) — so it can be changed here without touching a
    single file under data/simulation/.
    """
    reader = XDMFReader(FileNames=[xdmf_path])
    reader.PointArrayStatus = [
        "terrain_elevation", "water_depth", "velocity", "velocity_magnitude"]

    warp = WarpByScalar(Input=reader)
    warp.Scalars = ["POINTS", "terrain_elevation"]
    warp.ScaleFactor = vertical_exaggeration
    return reader, warp


def add_water(reader, vertical_exaggeration: float, dry_threshold: float = 0.01):
    """
    Reader -> Calculator -> Warp By Scalar -> Threshold. Section 5's exact chain.

    The Calculator step is not optional decoration. Thresholding the already-warped
    TERRAIN and recolouring it (the obvious shortcut) yields wet terrain cells, not
    a water surface: the water then sits exactly on the bed with zero thickness, so
    a 40 m flood and a 0.02 m puddle look identical. The surface has to be lifted to
    terrain_elevation + water_depth to represent depth at all.

    The warp Scale Factor must match the terrain's exactly, or the two surfaces are
    exaggerated differently and the water floats above or sinks through the valley.
    """
    calculator = Calculator(Input=reader)
    calculator.ResultArrayName = "water_surface_z"
    calculator.Function = "terrain_elevation + water_depth"

    warp = WarpByScalar(Input=calculator)
    warp.Scalars = ["POINTS", "water_surface_z"]
    warp.ScaleFactor = vertical_exaggeration

    # Dry cells become holes rather than a film of zero-depth water over the whole
    # domain, which would hide the terrain everywhere it is not actually flooded.
    threshold = Threshold(Input=warp)
    threshold.Scalars = ["POINTS", "water_depth"]
    threshold.LowerThreshold = dry_threshold
    threshold.UpperThreshold = 1.0e9
    return threshold


def setup_camera(view, source, elevation_deg: float = 32.0, azimuth_deg: float = 235.0,
                 zoom: float = 1.0, pad: float = 1.25):
    """
    Elevated perspective centred on `source`, which need not be the whole domain.

    Two things this deliberately does NOT do:

    * It does not use ResetCamera + Elevation() + Azimuth(). That relative
      approach put the camera nearly edge-on to the terrain plate — because the
      surface normal is +Z, rotating from ParaView's default view left Z pointing
      into the screen and the terrain rendered as a foreshortened sliver.
    * It does not call ResetCamera at all, because ResetCamera fits every visible
      prop. When the subject is the reservoir (0.2% of a 120 km domain) or the
      flood channel, fitting everything is exactly what buries it. Distance is
      computed from the chosen source's own bounds instead, so passing the water
      rather than the terrain frames the water.

    Absolute placement is also what Section 13 asks for: reproducible run to run,
    not an angle eyeballed once.
    """
    import math

    source.UpdatePipeline()
    xmin, xmax, ymin, ymax, zmin, zmax = source.GetDataInformation().GetBounds()
    cx, cy, cz = (xmin + xmax) / 2, (ymin + ymax) / 2, (zmin + zmax) / 2
    radius = 0.5 * math.dist((xmin, ymin, zmin), (xmax, ymax, zmax))
    if radius <= 0:
        raise SystemExit(
            "Camera target has zero extent — the source is empty. For a water "
            "focus this usually means the depth threshold excluded every cell."
        )

    # Distance that fits a sphere of `radius` in ParaView's default 30-degree
    # vertical view angle, with a little padding, then the caller's zoom.
    half_angle = math.radians(view.CameraViewAngle if hasattr(view, "CameraViewAngle") else 30.0) / 2
    distance = (radius * pad) / max(math.tan(half_angle), 1e-6) / max(zoom, 1e-6)

    el, az = math.radians(elevation_deg), math.radians(azimuth_deg)
    # Set the VIEW PROXY's camera properties, not GetActiveCamera()'s vtkCamera.
    # Mutating the vtkCamera directly appears to work and then silently does
    # nothing: RenderAllViews() pushes the proxy's stored CameraPosition back over
    # it, so the frame renders from wherever the proxy last was. That was masked
    # while ResetCamera was still in the chain (ResetCamera updates the proxy);
    # removing it exposed the bug as a camera that ignored --focus-water entirely.
    view.CameraFocalPoint = [cx, cy, cz]
    view.CameraPosition = [
        cx + distance * math.cos(el) * math.cos(az),
        cy + distance * math.cos(el) * math.sin(az),
        cz + distance * math.sin(el),
    ]
    view.CameraViewUp = [0.0, 0.0, 1.0]  # +Z is elevation; anything else tilts the horizon


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--xdmf", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--exaggeration", type=float, default=1.5,
                        help="Warp By Scalar Scale Factor (default 1.5 — real "
                             "Himalayan relief is dramatic enough that 1.0 "
                             "already reads as 3D; 1.5 makes it unambiguous "
                             "at a glance).")
    parser.add_argument("--time", type=float, default=None,
                        help="Simulation time to render. Omit for the last "
                             "available timestep.")
    parser.add_argument("--width", type=int, default=1920)
    parser.add_argument("--height", type=int, default=1080)
    parser.add_argument("--zoom", type=float, default=1.0,
                        help="Camera zoom after fitting. A real dam-break wets a "
                             "tiny fraction of a 120 km domain, so the default "
                             "wide shot renders it as a hairline; raise this to "
                             "inspect the flooded reach.")
    parser.add_argument("--depth-max", type=float, default=25.0,
                        help="Upper bound of the water-depth colour scale (m). "
                             "Fixed so colours mean the same thing in every frame.")
    parser.add_argument("--water-solid", action="store_true",
                        help="Render water as one flat colour instead of a depth "
                             "ramp. Right for the static reservoir: the fill is "
                             "near-uniform (~14 m) and, because GLO-30 already "
                             "contains the pool, the variation that remains is not "
                             "physically meaningful. A ramp there implies precision "
                             "the data does not have.")
    parser.add_argument("--focus-water", action="store_true",
                        help="Frame the camera on the wetted area instead of the "
                             "whole domain. The reservoir is ~0.2%% of a 120 km "
                             "domain and the flood channel is narrower still, so a "
                             "domain-wide shot renders either as a hairline.")
    parser.add_argument("--depth-label", default="Water Depth (m)",
                        help="Colour-bar title for the water field. Override for "
                             "the reservoir dataset, where the value is height "
                             "above the GLO-30 surface rather than true depth — "
                             "GLO-30 already contains the impounded pool.")
    parser.add_argument("--with-water", action="store_true",
                        help="Threshold and show water_depth as well as terrain.")
    args = parser.parse_args()

    reader, warp = build_terrain(args.xdmf, args.exaggeration)

    scene = GetAnimationScene()
    scene.UpdateAnimationUsingDataTimeSteps()
    if args.time is not None:
        scene.AnimationTime = args.time
    elif reader.TimestepValues:
        # TimestepValues can be a scalar (single timestep) or a list.
        values = reader.TimestepValues
        last = values[-1] if hasattr(values, "__getitem__") else values
        scene.AnimationTime = last

    view = GetActiveView()
    if view is None:
        from paraview.simple import CreateView
        view = CreateView("RenderView")
    view.ViewSize = [args.width, args.height]
    # Without this, ParaView's colour palette silently overrides Background and
    # the frame renders default grey regardless of what is set here.
    view.UseColorPaletteForBackground = 0
    view.Background = [0.85, 0.90, 0.97]
    view.OrientationAxesVisibility = 0

    terrain_display = Show(warp, view)
    ColorBy(terrain_display, ("POINTS", "terrain_elevation"))
    terrain_ctf = GetColorTransferFunction("terrain_elevation")
    # Preset names are build-specific; "Green to Red" does not exist in 6.2.0.
    # gist_earth is a genuine elevation ramp (low green -> high brown/white).
    terrain_ctf.ApplyPreset("gist_earth", True)

    water = None
    if args.with_water:
        water = add_water(reader, args.exaggeration)
        water_display = Show(water, view)
        if args.water_solid:
            ColorBy(water_display, None)          # drop scalar colouring entirely
            water_display.DiffuseColor = [0.10, 0.35, 0.70]
            water_display.Opacity = 1.0
        else:
            ColorBy(water_display, ("POINTS", "water_depth"))
            water_ctf = GetColorTransferFunction("water_depth")
            # A divergent map rendered deep water orange, reading as terrain rather
            # than water. A monotonic blue ramp keeps shallow->deep legible as water.
            water_ctf.ApplyPreset("Linear Blue (8_31f)", True)
            # Fixed range, not per-timestep auto-scale, or colours are not comparable
            # across the animation (Section 11).
            water_ctf.RescaleTransferFunction(0.0, args.depth_max)
            water_display.Opacity = 0.92
            water_display.SetScalarBarVisibility(view, True)
            water_bar = GetScalarBar(water_ctf, view)
            water_bar.Title = args.depth_label
            water_bar.ComponentTitle = ""

    terrain_display.SetScalarBarVisibility(view, True)
    terrain_bar = GetScalarBar(terrain_ctf, view)
    terrain_bar.Title = "Elevation (m)"
    terrain_bar.ComponentTitle = ""

    camera_target = water if (args.focus_water and args.with_water) else warp
    if args.focus_water and not args.with_water:
        print("[render_static] --focus-water ignored: no water shown (--with-water not set).")
    # Render ONCE before positioning the camera. A view that has never rendered
    # auto-resets its camera on first render, which silently discards whatever was
    # set beforehand — measured: a position of [217221, 3325397, 40767] came back
    # as [97637, 3134823, 183328], i.e. refitted to the whole 120 km domain, so
    # --focus-water appeared to do nothing at all. Rendering first consumes that
    # reset; the camera set afterwards survives.
    RenderAllViews()
    setup_camera(view, camera_target, zoom=args.zoom)
    RenderAllViews()
    SaveScreenshot(args.out, view, ImageResolution=[args.width, args.height])

    n_steps = len(reader.TimestepValues) if hasattr(reader.TimestepValues, "__len__") else 1
    print(f"[render_static] wrote {args.out}")
    print(f"  source timesteps : {n_steps}")
    print(f"  rendered at t    : {scene.AnimationTime}")
    print(f"  exaggeration     : {args.exaggeration}x")
    print(f"  with_water       : {args.with_water}")


if __name__ == "__main__":
    main()
