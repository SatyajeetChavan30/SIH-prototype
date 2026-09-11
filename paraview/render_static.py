"""
Static render — pvpython, headless. Phases 1/2/6/7 of the visualization plan.

Loads an XDMF time series, applies Warp By Scalar on terrain_elevation (the step
that turns a flat raster into an actual 3D mesh — Section 4), positions an
elevated/isometric camera showing the full domain, and saves a screenshot.
Also wires in the Phase 6 scientific overlays this file used to lack: a
mandatory SYNTHETIC-data banner, Annotate Time, velocity Glyphs, a flooded-area
readout, and (Phase 2) a terrain base block + basic lighting.

This exists as a script rather than a GUI walkthrough because it can be run and
its output inspected without a human looking at the screen — the same reasoning
Section 2 gives for pvpython/pvbatch: reproducible re-execution of a pipeline,
not a replacement for building it interactively first.

Usage:
    pvpython paraview/render_static.py --xdmf data/simulation/terrain.xdmf \
        --out paraview/artifacts/phase1_terrain.png

    pvpython paraview/render_static.py --xdmf data/simulation/synthetic.xdmf \
        --time 1800 --with-water --out paraview/artifacts/phase3_water.png

    pvpython paraview/render_static.py --xdmf data/simulation/tehri.xdmf \
        --with-water --glyphs --glyph-stride 2 --show-area \
        --base-block paraview/artifacts/tehri_terrain_base.vtp \
        --camera isometric --out paraview/artifacts/flood_t_25s.png --time 25
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

from paraview.simple import (
    AnnotateTimeFilter,
    AssignViewToLayout,
    Calculator,
    ColorBy,
    GetActiveView,
    GetAnimationScene,
    GetColorTransferFunction,
    GetLayout,
    GetDisplayProperties,
    GetScalarBar,
    Glyph,
    Hide,
    PythonAnnotation,
    RenderAllViews,
    ResetCamera,
    SaveScreenshot,
    SaveState,
    Show,
    TemporalInterpolator,
    Threshold,
    WarpByScalar,
    XDMFReader,
    XMLPolyDataReader,
)

# NOT `from paraview import camera_presets` — this project's own paraview/
# directory shares its name with ParaView's bundled `paraview` package
# (paraview.simple, imported above), so a package-qualified import resolves
# to the WRONG paraview and fails. Insert this directory itself and import
# the bare module name instead.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import camera_presets  # noqa: E402 — after sys.path fix-up

# Mirrors jalraksha.export.xdmf_export.DRY_DEPTH_M (0.01 m). Duplicated, not
# imported: pvpython's bundled Python cannot import the jalraksha package —
# jalraksha.export pulls in rasterio, which is not installed in ParaView's
# Python. Keep this in sync with xdmf_export.py by hand if either changes.
DRY_DEPTH_M = 0.01

# Roughly how many arrows a readable velocity field shows: dense enough to trace
# the flow, sparse enough not to become a solid mat. Stride is derived from this
# and the actual wet-cell count rather than fixed, because wetted extent varies
# by two orders of magnitude between the real and synthetic datasets.
TARGET_GLYPH_COUNT = 400


def build_terrain(xdmf_path: str, vertical_exaggeration: float,
                  interpolate: bool = False):
    """
    Reader -> (optional Temporal Interpolator) -> Warp By Scalar on terrain_elevation.

    Section 4's required chain. Vertical exaggeration is the Warp filter's Scale
    Factor — a pipeline parameter, never baked into the data (see
    ARCHITECTURE.md section 4) — so it can be changed here without touching a
    single file under data/simulation/.

    WHY THE INTERPOLATOR EXISTS, AND WHY IT IS OFF BY DEFAULT. A reader does not
    interpolate in time: asked for a moment between two stored timesteps it
    returns the NEARER one. Sequence-mode playback therefore moves the clock
    smoothly while the data jumps, and asking for more frames than the dataset
    has timesteps produces duplicates rather than motion — measured on the
    30-step synthetic dataset, 60 frames came back as 30 byte-identical PAIRS.
    ``TemporalInterpolator`` is ParaView's own filter for this, so Section 18's
    ban on hand-written frame interpolation is respected.

    It is opt-in because it changes what is displayed: an interpolated frame is
    a linear blend of two solver states, not a solver state. For a still that
    would be a misrepresentation at no benefit, so ``render_static`` never asks
    for it; for an animation it is the difference between motion and a
    stutter, and ``render_animation`` labels the output accordingly.
    """
    reader = XDMFReader(FileNames=[xdmf_path])
    reader.PointArrayStatus = [
        "terrain_elevation", "water_depth", "velocity", "velocity_magnitude"]

    source = TemporalInterpolator(Input=reader) if interpolate else reader

    warp = WarpByScalar(Input=source)
    warp.Scalars = ["POINTS", "terrain_elevation"]
    warp.ScaleFactor = vertical_exaggeration
    # `reader` is returned alongside `source` so callers can report the DATASET's
    # own timestep count. Everything that renders must attach to `source`, or it
    # silently bypasses the interpolator and stutters while the terrain does not.
    return reader, source, warp


def add_water(reader, vertical_exaggeration: float, dry_threshold: float = DRY_DEPTH_M):
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


def add_velocity_glyphs(threshold_water, *, stride, scale, render_time, domain_diagonal):
    """
    Glyph filter on the thresholded (wet-only) water surface, per Section 11.

    Density is a caller-supplied stride, not a constant: a real solver run can
    have as few as ~300 wet cells (a gorge-confined dam-break) or a synthetic
    demo can have ~20,000 (a wide floodplain spread) — the same stride would
    either produce almost no arrows or a solid mat, so both --glyph-stride and
    --glyph-scale are CLI-exposed rather than hardcoded.

    Returns None (and prints why) if the wet region has no velocity at all —
    a static reservoir fill has |v| == 0 everywhere by construction (see
    tools/paraview/make_dataset.py's reservoir path), and glyphing that would
    only produce degenerate zero-length arrows.
    """
    # Update at the time actually being rendered. Updating at the pipeline's
    # default (t=0) reports the DRY initial state — max |v| is 0 there for every
    # dataset, so every glyph request would silently self-skip.
    threshold_water.UpdatePipeline(render_time)
    info = threshold_water.GetDataInformation()
    n_wet = info.GetNumberOfPoints()
    if n_wet == 0:
        print("[render_static] --glyphs requested but no cells are wet at this "
              "time — skipping.")
        return None
    vmag_range = threshold_water.GetPointDataInformation().GetArray(
        "velocity_magnitude").GetRange()
    max_speed = float(vmag_range[1])
    if max_speed <= 0.0:
        print("[render_static] --glyphs requested but max velocity is 0 "
              "(a static reservoir fill has no flow by construction) — skipping.")
        return None

    if stride is None:
        # Aim for TARGET_GLYPH_COUNT arrows whatever the wetted extent, because
        # the shipped datasets differ by two orders of magnitude (311 wet cells
        # for the real gorge-confined run vs 19,216 for the synthetic sheet).
        stride = max(1, int(n_wet // TARGET_GLYPH_COUNT))
    if scale is None:
        # Longest arrow ~2.5% of the domain diagonal. A fixed multiplier cannot
        # work across domains: 50.0 gives 750 m arrows on a 120 km domain, which
        # is under a pixel at a domain-wide camera.
        scale = 0.025 * domain_diagonal / max_speed

    glyph = Glyph(Input=threshold_water, GlyphType="Arrow")
    glyph.OrientationArray = ["POINTS", "velocity"]
    glyph.ScaleArray = ["POINTS", "velocity_magnitude"]
    glyph.ScaleFactor = scale
    glyph.GlyphMode = "Every Nth Point"
    glyph.Stride = max(1, int(stride))
    print(f"[render_static] glyphs: {n_wet} wet points, stride {stride} "
          f"(~{n_wet // max(1, int(stride))} arrows), scale {scale:.1f}, "
          f"max |v| {max_speed:.2f} m/s")
    return glyph


def _dataset_path(value: str) -> Path:
    """
    argparse coercion: any path that reaches a ParaView reader must be ABSOLUTE.

    ParaView serialises a reader's file path into a saved .pvsm verbatim, and on
    restore resolves it against the CWD of whatever process opens the state —
    NOT against the state file's own location. A relative path therefore yields a
    state that loads only from the directory it happened to be generated in.

    Not hypothetical: states written before this coercion embedded a relative
    "data/simulation/<run>.xdmf". Restoring one from any other directory gave
    `vtkXdmfReader ERR| Error opening file`, points=0 and a blank render view,
    while working from the repo root — which is why it survived review. Note the
    .pvsm is itself written INTO data/simulation/, so even resolving relative to
    the state file would look for data/simulation/data/simulation/<run>.xdmf.

    Resolving here, at the boundary, means every caller — API, CLI or a human —
    gets a portable state by construction, and any reader added later inherits it.
    """
    return Path(value).expanduser().resolve()


def build_parser() -> argparse.ArgumentParser:
    """
    Every rendering flag, in one place.

    Shared with render_animation.py, which adds its own frame/encode flags
    on top. Duplicating this list would let a still and the video it is
    supposed to represent drift apart in exaggeration, depth range or
    camera — differences a viewer would read as a change in the physics.
    """
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--xdmf", required=True, type=_dataset_path,
                        help="Dataset to render. Coerced to an absolute "
                             "path — see _dataset_path for why.")
    parser.add_argument("--out", default=None,
                        help="Screenshot path. Optional: omit it with --save-state "
                             "to build a .pvsm without paying for a full render, "
                             "which is what the API's open-paraview endpoint wants.")
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
    parser.add_argument("--camera", choices=sorted(camera_presets.PRESETS),
                        default=camera_presets.DEFAULT_PRESET,
                        help="Named camera preset (Section 13) — see "
                             "paraview/camera_presets.py.")
    parser.add_argument("--depth-max", type=float, default=25.0,
                        help="Upper bound of the water-depth colour scale (m). "
                             "Fixed so colours mean the same thing in every frame.")
    parser.add_argument("--elevation-range", type=float, nargs=2, default=None,
                        metavar=("MIN", "MAX"),
                        help="Fix the terrain colour range, m, instead of "
                             "auto-scaling to this dataset's own min/max. "
                             "Useful for comparing dams side by side (e.g. "
                             "'0 7000' spans both presets' relief) — but the "
                             "default (auto) is usually the better-LOOKING "
                             "choice for a single dam: Khadakwasla's ~1400 m "
                             "relief renders almost featureless under a "
                             "range sized for Tehri's ~6900 m peaks.")
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
    parser.add_argument("--base-block", type=_dataset_path, default=None,
                        help="A .vtp written by tools/paraview/base_block.py, "
                             "built with the SAME --exaggeration as this render. "
                             "Shown as a solid earth-toned block under the "
                             "terrain so it reads as a physical 3D block "
                             "(Section 4) rather than a floating sheet.")
    parser.add_argument("--glyphs", action="store_true",
                        help="Show velocity Glyphs on the thresholded water "
                             "(requires --with-water). Skipped with a printed "
                             "notice if the dataset's water has zero velocity "
                             "(e.g. a static reservoir fill).")
    parser.add_argument("--glyph-stride", type=int, default=None,
                        help="Show every Nth wet point as an arrow. Lower for "
                             "a sparse real-solver flood (few hundred wet "
                             "cells), higher for a wide synthetic spread "
                             "(tens of thousands) — the same value looks "
                             "either empty or solid on the other dataset.")
    parser.add_argument("--glyph-scale", type=float, default=None,
                        help="Arrow length per m/s of velocity magnitude.")
    parser.add_argument("--show-area", action="store_true",
                        help="Overlay a computed flooded-area readout "
                             "(km^2, water_depth > dry threshold), per "
                             "Section 11.")
    parser.add_argument("--axes", action="store_true",
                        help="Show orientation axes. Off by default — they "
                             "clutter close-in reservoir/flood-reach shots.")
    parser.add_argument("--no-time-annotation", action="store_true",
                        help="Suppress the built-in Annotate Time overlay "
                             "(shown by default — Section 7/ARCHITECTURE.md "
                             "section 7 both call for it rather than a "
                             "hand-drawn, driftable timestamp).")
    parser.add_argument("--save-state", type=Path, default=None,
                        help="Also write a .pvsm ParaView state file (Section "
                             "13/Phase 5) with the Animation View pre-configured "
                             "to Sequence mode — opening it in the ParaView GUI "
                             "is the scrubbable-animation deliverable.")
    parser.add_argument("--save-state-frames", type=int, default=60,
                        help="NumberOfFrames for the saved state's Sequence "
                             "mode animation (default 60).")
    return parser


def build_scene(args, view=None):
    """
    Construct the full ParaView scene from parsed arguments.

    Everything up to and including the camera: terrain, optional base block,
    water, glyphs, scalar bars, the synthetic-data banner, the time and area
    annotations. Extracted from main() unchanged so a still and an animation
    are the SAME scene, differing only in what they do with it afterwards.

    Args:
        args: Namespace from build_parser().
        view: Existing render view to build into. A new one is created when
            omitted, which is what the still path does.

    Returns:
        (view, scene, reader, source, warp, water). `reader` is the raw XDMF
        reader, kept for its own TimestepValues; `source` is what everything
        renders from (the reader, or the temporal interpolator wrapping it);
        `warp` is the warped terrain and `water` the water surface or None.
    """
    reader, source, warp = build_terrain(
        str(args.xdmf), args.exaggeration,
        interpolate=getattr(args, "interpolate", False),
    )

    # Geometry facts both the glyph auto-scaling and the flooded-area readout
    # need, taken from the reader's own grid rather than assumed or hardcoded.
    reader.UpdatePipeline()
    _bx0, _bx1, _by0, _by1, _, _ = reader.GetDataInformation().GetBounds()
    _extent = reader.GetDataInformation().GetExtent()
    _nx = max(1, _extent[1] - _extent[0])
    _ny = max(1, _extent[3] - _extent[2])
    cell_area_km2 = ((_bx1 - _bx0) / _nx) * ((_by1 - _by0) / _ny) / 1.0e6
    domain_diagonal = math.dist((_bx0, _by0), (_bx1, _by1))

    scene = GetAnimationScene()
    scene.UpdateAnimationUsingDataTimeSteps()
    if args.time is not None:
        scene.AnimationTime = args.time
    elif reader.TimestepValues:
        # TimestepValues can be a scalar (single timestep) or a list.
        values = reader.TimestepValues
        last = values[-1] if hasattr(values, "__getitem__") else values
        scene.AnimationTime = last

    if view is None:
        view = GetActiveView()
    if view is None:
        from paraview.simple import CreateView
        view = CreateView("RenderView")

    # Put the view in a layout. Headless pvpython does not need one — it renders
    # and screenshots a bare view perfectly well — but the ParaView GUI builds
    # its tabs from layouts, so a state whose view belongs to no layout restores
    # as a fully populated Pipeline Browser next to an EMPTY tab: every filter
    # present, nothing drawn.
    #
    # This is exactly what shipped, and headless checks cannot see it: the usual
    # probe (LoadState then GetActiveViewOrCreate) CREATES a view when the state
    # supplies none, manufacturing the very thing that was missing and reporting
    # success. Verify with GetViews()/GetLayouts() after LoadState instead.
    if GetLayout(view) is None:
        AssignViewToLayout(view=view)

    view.ViewSize = [args.width, args.height]
    # Without this, ParaView's colour palette silently overrides Background and
    # the frame renders default grey regardless of what is set here.
    view.UseColorPaletteForBackground = 0
    view.Background = [0.85, 0.90, 0.97]
    view.OrientationAxesVisibility = 1 if args.axes else 0

    if args.base_block is not None:
        if not args.base_block.exists():
            raise SystemExit(
                f"--base-block {args.base_block} does not exist. Build it "
                f"first: python tools/paraview/base_block.py "
                f"--dataset {args.xdmf}"
            )
        block_reader = XMLPolyDataReader(FileName=[str(args.base_block)])
        # The skirt is stored flat at z=0 carrying its target elevation as a
        # scalar, so it MUST be warped by the same Scale Factor as the terrain.
        # Showing it unwarped leaves it lying at z=0 while the terrain is lifted
        # away above it — which renders as a thin sliver at the domain edge
        # rather than as the pedestal the block is supposed to be.
        block_warp = WarpByScalar(Input=block_reader)
        block_warp.Scalars = ["POINTS", "terrain_elevation"]
        block_warp.ScaleFactor = args.exaggeration
        # Polydata carries no point normals, so vtkWarpScalar would fall back to
        # an implicit +Z. Stating it removes the ambiguity: the vertical walls
        # must be displaced along Z, never along a sideways per-point normal.
        block_warp.UseNormal = 1
        block_warp.Normal = [0.0, 0.0, 1.0]
        block_display = Show(block_warp, view)
        ColorBy(block_display, None)
        # A flat earth-brown, distinct from the terrain's own colormap, so the
        # block reads as "the ground this sits on" rather than more terrain.
        block_display.DiffuseColor = [0.45, 0.36, 0.27]
        block_display.Ambient = 0.35
        block_display.Diffuse = 0.65
        block_display.Specular = 0.0

    terrain_display = Show(warp, view)
    ColorBy(terrain_display, ("POINTS", "terrain_elevation"))
    terrain_ctf = GetColorTransferFunction("terrain_elevation")
    # Preset names are build-specific; "Green to Red" does not exist in 6.2.0.
    # gist_earth is a genuine elevation ramp (low green -> high brown/white).
    terrain_ctf.ApplyPreset("gist_earth", True)
    if args.elevation_range is not None:
        # Opt-in only — see --elevation-range's help for why auto-scaling
        # (ParaView's default on first ColorBy) is the better default here.
        terrain_ctf.RescaleTransferFunction(args.elevation_range[0], args.elevation_range[1])

    # Basic lighting tuning (Phase 2) — GetDisplayProperties was imported here
    # long before anything called it. Flat default lighting is the single
    # biggest reason a warped ParaView terrain still reads as flat; a little
    # ambient/specular separation makes ridgelines and shadows legible.
    terrain_display.Ambient = 0.25
    terrain_display.Diffuse = 0.85
    terrain_display.Specular = 0.15
    terrain_display.SpecularPower = 20.0

    water = None
    if args.with_water:
        water = add_water(source, args.exaggeration)
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
            # Explicit RGB points rather than a stock preset: "Linear Blue
            # (8_31f)" is monotonic but its deep end is almost black, so at a
            # 25 m fixed range the deepest water rendered as a black hole that
            # read as shadow rather than as water. This ramp keeps the deep end
            # a saturated navy that is still recognisably blue.
            water_ctf.RGBPoints = [
                0.0, 0.78, 0.92, 0.99,
                args.depth_max * 0.25, 0.42, 0.71, 0.91,
                args.depth_max * 0.60, 0.16, 0.45, 0.78,
                args.depth_max, 0.04, 0.20, 0.47,
            ]
            water_ctf.ColorSpace = "RGB"
            # Fixed range, not per-timestep auto-scale, or colours are not comparable
            # across the animation (Section 11).
            water_ctf.RescaleTransferFunction(0.0, args.depth_max)
            water_display.Opacity = 0.92
            water_display.SetScalarBarVisibility(view, True)
            water_bar = GetScalarBar(water_ctf, view)
            water_bar.Title = args.depth_label
            water_bar.ComponentTitle = ""

        if args.glyphs:
            glyph = add_velocity_glyphs(
                water, stride=args.glyph_stride, scale=args.glyph_scale,
                render_time=scene.AnimationTime, domain_diagonal=domain_diagonal)
            if glyph is not None:
                glyph_display = Show(glyph, view)
                ColorBy(glyph_display, None)
                # Near-black, not white: arrows sit on pale-blue water and a
                # light background, where white is effectively invisible.
                glyph_display.AmbientColor = [0.05, 0.05, 0.10]
                glyph_display.DiffuseColor = [0.05, 0.05, 0.10]

    terrain_display.SetScalarBarVisibility(view, True)
    terrain_bar = GetScalarBar(terrain_ctf, view)
    terrain_bar.Title = "Elevation (m)"
    terrain_bar.ComponentTitle = ""

    # SYNTHETIC-DATA banner — NOT a flag. Spec Section 0 and ARCHITECTURE.md
    # section 9 both call a visible synthetic-data warning mandatory: a
    # fallback/demo dataset that LOOKS like a real result is the single worst
    # failure mode this project's own conventions are written to prevent. The
    # flag lives as Grid-centred XDMF field data (survives into ParaView as
    # FieldData — proven by tests/test_xdmf_export.py's own reader round-trip
    # test), so this banner cannot be silently dropped by forgetting a flag;
    # it is driven by the data itself.
    synthetic_annotation = PythonAnnotation(Input=source)
    synthetic_annotation.ArrayAssociation = "Field Data"
    synthetic_annotation.Expression = (
        "'SYNTHETIC DATA — NOT A PHYSICAL SIMULATION' "
        "if inputs[0].FieldData['is_synthetic'][0] else ''"
    )
    synthetic_display = Show(synthetic_annotation, view)
    synthetic_display.Color = [0.85, 0.05, 0.05]
    synthetic_display.FontSize = 22
    synthetic_display.Bold = 1
    synthetic_display.WindowLocation = "Upper Center"

    if not args.no_time_annotation:
        # Built-in Annotate Time filter, per Section 8/ARCHITECTURE.md section 7:
        # it reads the scene's own clock, so it cannot drift out of sync the way
        # a hand-drawn text label could.
        time_annotation = AnnotateTimeFilter(Input=reader)
        time_annotation.Format = "t = {time:.0f} s"
        time_display = Show(time_annotation, view)
        time_display.WindowLocation = "Lower Left Corner"
        time_display.FontSize = 16

    if args.show_area:
        # Flooded-extent readout, Section 11. Cell area is computed here in
        # Python from the reader's own grid spacing (not a third hardcoded
        # literal) and baked into the expression as a literal number — more
        # robust than trying to introspect spacing from inside a
        # PythonAnnotation's sandboxed expression evaluator.
        area_annotation = PythonAnnotation(Input=source)
        area_annotation.ArrayAssociation = "Point Data"
        area_annotation.Expression = (
            f"'Flooded area: %.2f km^2' % "
            f"((inputs[0].PointData['water_depth'] > {DRY_DEPTH_M}).sum() "
            f"* {cell_area_km2!r})"
        )
        area_display = Show(area_annotation, view)
        area_display.Color = [0.05, 0.05, 0.05]
        area_display.FontSize = 16
        # Upper LEFT, not right: both scalar bars dock on the right edge, and at
        # a near-nadir camera the elevation bar rides high enough to collide with
        # an upper-right annotation. Left keeps it clear of both bars, and the
        # timestamp sits lower-left so the two never overlap each other either.
        area_display.WindowLocation = "Upper Left Corner"

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
    preset = camera_presets.get_preset(args.camera)
    setup_camera(view, camera_target, elevation_deg=preset.elevation_deg,
                 azimuth_deg=preset.azimuth_deg, zoom=args.zoom,
                 pad=preset.pad, view_up=preset.view_up)
    RenderAllViews()
    return view, scene, reader, source, warp, water


def main() -> None:
    args = build_parser().parse_args()
    if args.out is None and args.save_state is None:
        raise SystemExit(
            "Nothing to produce: pass --out for a screenshot, --save-state for a "
            "ParaView state file, or both."
        )

    view, scene, reader, source, warp, water = build_scene(args)

    if args.out is not None:
        SaveScreenshot(args.out, view, ImageResolution=[args.width, args.height])

    if args.save_state is not None:
        # Sequence, not Snap To TimeSteps: ARCHITECTURE.md section 6 settles it.
        # Solver timesteps are unevenly spaced (adaptive CFL), so Sequence is what
        # gives a fixed frame rate and a fixed-length animation; ParaView does the
        # interpolation itself, so no custom interpolation code (Section 18).
        #
        # Reading the saved .pvsm back: ParaView 6.2.0 offers only two play modes
        # and serializes Sequence as 0, "Snap To TimeSteps" as 2 (verified by
        # round-tripping both). A PlayMode of 0 in the XML is therefore CORRECT —
        # it is not the old 3-value enum where 0 meant Snap To TimeSteps.
        scene.PlayMode = "Sequence"
        scene.NumberOfFrames = args.save_state_frames
        args.save_state.parent.mkdir(parents=True, exist_ok=True)
        SaveState(str(args.save_state))
        print(f"[render_static] wrote state {args.save_state} "
              f"(Sequence mode, {args.save_state_frames} frames) — open in the "
              f"ParaView GUI and use the VCR toolbar / Animation View to scrub.")

    n_steps = len(reader.TimestepValues) if hasattr(reader.TimestepValues, "__len__") else 1
    if args.out is not None:
        print(f"[render_static] wrote {args.out}")
    print(f"  source timesteps : {n_steps}")
    print(f"  rendered at t    : {scene.AnimationTime}")
    print(f"  exaggeration     : {args.exaggeration}x")
    print(f"  camera           : {args.camera}")
    print(f"  with_water       : {args.with_water}")




def setup_camera(view, source, elevation_deg: float = 32.0, azimuth_deg: float = 235.0,
                 zoom: float = 1.0, pad: float = 1.25,
                 view_up: tuple[float, float, float] = (0.0, 0.0, 1.0)):
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
    not an angle eyeballed once. elevation_deg/azimuth_deg now come from named
    presets in camera_presets.py rather than being the only two numbers in this
    function's signature with no way to reach them from the CLI.
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
    # +Z is elevation, so it is the natural up vector for every oblique view and
    # anything else tilts the horizon. The near-nadir `top` preset must override
    # it: at elevation ~90 the up vector becomes parallel to the view direction
    # and the camera degenerates to a blank frame.
    view.CameraViewUp = list(view_up)


if __name__ == "__main__":
    main()
