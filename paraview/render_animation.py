"""
Video export — spec Section 17 Phase 8.

Renders the flood as a PNG sequence with ``SaveAnimation`` and encodes it to
H.264 MP4 with FFmpeg. The scene is built by ``render_static.build_scene``, not
rebuilt here, so a still and the video it accompanies cannot disagree about
exaggeration, depth range, glyph density or camera — differences a viewer would
read as a change in the physics rather than in the render settings.

    pvpython paraview/render_animation.py \\
        --xdmf data/simulation/synthetic.xdmf --with-water \\
        --out paraview/artifacts/flood_simulation.mp4

WHY SEQUENCE AND NOT SNAP-TO-TIMESTEPS. Solver timesteps are unevenly spaced —
the CFL condition shortens them wherever the flow is fast — so snapping to them
produces a video whose playback speed varies with the physics: the violent part
of a dam break, which is the part worth watching, plays slowest. Sequence mode
asks ParaView to interpolate a fixed number of evenly spaced frames across the
time range, which is both a constant frame rate and a constant seconds-per-frame
in simulation time. ARCHITECTURE.md section 6 settles this the same way for the
saved ``.pvsm`` state, and Section 18 is explicit that no hand-written frame
interpolation belongs in this project.

WHAT THE ENCODE DOES NOT DO. It does not re-time, re-colour, or drop frames.
FFmpeg is handed the PNG stack ParaView wrote and asked for H.264 at the frame
rate that was requested; ``-pix_fmt yuv420p`` is set because the default for
RGB PNG input is yuv444p, which QuickTime and most browsers refuse to play, and
a video nobody can open on demo day is not an export.

THE PNG STACK IS KEPT. ``--keep-frames`` defaults on: the frames are the
deliverable that survives having no FFmpeg, and the repository already ships a
keyframe-PNG playback path. Deleting them to save disk would make a failed
encode unrecoverable without a full re-render.

The synthetic-data banner rides on every frame, because it comes from the
dataset's own ``is_synthetic`` field rather than from a flag passed here — see
``render_static.build_scene``. A video is exactly the artifact most likely to be
screenshotted out of context, so that guarantee matters more here than anywhere
else in the pipeline.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

from paraview.simple import (
    Delete,
    RenderAllViews,
    SaveAnimation,
    XDMFReader,
)

# Same import shim as render_static.py: this directory shares its name with
# ParaView's own bundled `paraview` package, so a package-qualified import
# resolves to the wrong one. See render_static.py for the full explanation.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import render_static  # noqa: E402 — after sys.path fix-up



def _timestep_count(xdmf_path: str) -> int:
    """
    How many timesteps the dataset holds, read before the scene is built.

    Opened separately and cheaply — no arrays are requested — because whether to
    interpolate depends on this number, and the pipeline that would answer it is
    the one being configured by the answer.

    THE PROBE IS DELETED, and that is not tidiness. Leaving a second XDMFReader
    on the same file alive alongside the scene's own reader made pvpython exit
    with an access violation (0xC0000005 / SIGSEGV) at interpreter shutdown —
    AFTER every frame was written and every line of output printed, so the
    artifacts looked perfect and the exit code was 139. Any CI step or wrapper
    script checking the return code would call a successful render a failure.
    """
    probe = XDMFReader(FileNames=[xdmf_path])
    probe.UpdatePipeline()
    values = probe.TimestepValues
    count = len(values) if hasattr(values, "__len__") else 1
    Delete(probe)
    del probe
    return count


#: Frames per second of the encoded video.
#:
#: 24 is cinema rate and is enough for a flood front, which moves slowly in
#: screen terms. Higher costs render time linearly for no legibility gain.
DEFAULT_FPS = 24

#: Frames rendered across the dataset's full time range in Sequence mode.
#:
#: 120 at 24 fps is a five-second clip, which is about as long as a demo
#: audience watches a loop before wanting the next thing. Independent of how
#: many timesteps the dataset holds — that is the point of Sequence mode.
DEFAULT_FRAMES = 120

#: H.264 constant-rate factor. Lower is better quality and a larger file; 18 is
#: the conventional visually-lossless setting for this codec.
DEFAULT_CRF = 18


def encode_with_ffmpeg(
    frame_pattern: str,
    output_path: Path,
    fps: int,
    crf: int,
    ffmpeg: str,
) -> None:
    """
    Encode a numbered PNG sequence to H.264 MP4.

    Args:
        frame_pattern: printf-style pattern, e.g. ``frame_%04d.png``.
        output_path: Destination .mp4.
        fps: Frame rate.
        crf: H.264 constant-rate factor.
        ffmpeg: Path to the ffmpeg executable.

    Raises:
        SystemExit: if FFmpeg fails, carrying its own last lines. A silent
            failure here would leave the PNG stack on disk and no video, with
            nothing saying which step went wrong.
    """
    command = [
        ffmpeg, "-y",
        "-framerate", str(fps),
        "-i", frame_pattern,
        "-c:v", "libx264",
        "-crf", str(crf),
        # Even dimensions are required by yuv420p. ParaView will happily render
        # 1919x1079 if asked, and libx264 then refuses the whole encode.
        "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2",
        # RGB PNG input defaults to yuv444p, which QuickTime and most browsers
        # will not play. This is the single most common reason an exported
        # animation opens nowhere but VLC.
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        str(output_path),
    ]
    completed = subprocess.run(
        command, capture_output=True, text=True, check=False
    )
    if completed.returncode != 0:
        tail = "\n".join((completed.stderr or "").strip().splitlines()[-12:])
        raise SystemExit(
            f"[render_animation] FFmpeg failed (exit {completed.returncode}).\n"
            f"The PNG frames are still on disk and can be encoded by hand.\n"
            f"{tail}"
        )


def main() -> None:
    parser = render_static.build_parser()
    parser.description = __doc__
    parser.add_argument("--frames", type=int, default=DEFAULT_FRAMES,
                        help=f"Frames rendered across the full time range in "
                             f"Sequence mode (default {DEFAULT_FRAMES}). "
                             f"Independent of the dataset's timestep count.")
    parser.add_argument("--fps", type=int, default=DEFAULT_FPS,
                        help=f"Encoded frame rate (default {DEFAULT_FPS}).")
    parser.add_argument("--crf", type=int, default=DEFAULT_CRF,
                        help=f"H.264 constant-rate factor, lower is better "
                             f"quality (default {DEFAULT_CRF}).")
    parser.add_argument("--frame-dir", type=Path, default=None,
                        help="Directory for the PNG sequence. Defaults to "
                             "<out>_frames/ beside the video.")
    parser.add_argument("--no-encode", action="store_true",
                        help="Render the PNG sequence and stop. Use when "
                             "FFmpeg is unavailable — the frames are a usable "
                             "deliverable on their own.")
    parser.add_argument("--keep-frames", action=argparse.BooleanOptionalAction,
                        default=True,
                        help="Keep the PNG sequence after encoding (default: "
                             "keep). They are what makes a failed encode "
                             "recoverable without re-rendering.")
    parser.add_argument("--interpolate", action=argparse.BooleanOptionalAction,
                        default=None,
                        help="Blend consecutive solver states so intermediate "
                             "frames genuinely differ (ParaView's own "
                             "TemporalInterpolator). Defaults ON when --frames "
                             "exceeds the dataset's timestep count, because "
                             "without it those extra frames are exact "
                             "duplicates rather than motion.")
    parser.add_argument("--ffmpeg", default=None,
                        help="Path to ffmpeg. Found on PATH when omitted.")
    args = parser.parse_args()

    if args.out is None:
        raise SystemExit(
            "--out is required: it names the .mp4 to write (or, with "
            "--no-encode, the path whose stem names the frame directory)."
        )

    output_path = Path(args.out).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    frame_dir = args.frame_dir or output_path.with_name(output_path.stem + "_frames")
    frame_dir = Path(frame_dir).expanduser().resolve()
    frame_dir.mkdir(parents=True, exist_ok=True)

    ffmpeg = args.ffmpeg or shutil.which("ffmpeg")
    if not args.no_encode and ffmpeg is None:
        raise SystemExit(
            "FFmpeg was not found on PATH and --ffmpeg was not given. Re-run "
            "with --no-encode to produce the PNG sequence alone, then encode "
            "it elsewhere; the frames are a usable deliverable by themselves."
        )

    # --time is meaningless for an animation: the whole point is to sweep the
    # range. Saying so beats silently rendering the sweep and leaving the
    # operator to wonder why their timestamp was ignored.
    if args.time is not None:
        print("[render_animation] --time ignored: an animation sweeps the "
              "whole time range. Use render_static.py for a single instant.")
        args.time = None

    # The interpolation decision needs the timestep count, which needs a
    # reader — so peek at the dataset before building the scene rather than
    # building it twice.
    n_steps = _timestep_count(str(args.xdmf))
    if args.interpolate is None:
        # ON by default, at ANY frame count. Sequence mode resamples onto evenly
        # spaced times, and the solver's timesteps are NOT evenly spaced — the
        # CFL condition shortens them wherever the flow is fast. So the
        # requested times generally fall between stored steps whatever the
        # count, and the reader answers each with the nearest one.
        #
        # Measured on the 30-step synthetic dataset: 60 frames gave 30
        # byte-identical PAIRS, and even 30 frames — one per stored step — gave
        # a duplicate at index 14/15 while some other step was skipped entirely.
        # "frames == timesteps" is NOT a safe case, which is why this is not
        # conditional on the count.
        args.interpolate = True
        print(f"[render_animation] --interpolate on by default: Sequence mode "
              f"resamples {args.frames} evenly spaced frames from {n_steps} "
              f"unevenly spaced timesteps, so without it some frames duplicate "
              f"and some steps are skipped. Pass --no-interpolate for raw "
              f"nearest-step frames.")

    view, scene, reader, source, warp, water = render_static.build_scene(args)

    if n_steps < 2:
        raise SystemExit(
            f"{args.xdmf} holds {n_steps} timestep(s). An animation of a "
            f"single instant is a still — every frame would be identical, and "
            f"a video of still water misrepresents the dataset as a completed "
            f"run that produced no flow. Use render_static.py, or export a "
            f"time-varying dataset."
        )

    # Sequence, NOT Snap To TimeSteps — see the module docstring.
    scene.PlayMode = "Sequence"
    scene.NumberOfFrames = args.frames
    RenderAllViews()

    # ParaView numbers the files itself from this stem, zero-padded to four
    # digits, which is what the printf pattern below has to match.
    frame_stem = frame_dir / "frame.png"
    for stale in frame_dir.glob("frame*.png"):
        # A shorter re-render would otherwise leave the tail of a previous,
        # longer one in place, and FFmpeg would silently encode both.
        stale.unlink()

    SaveAnimation(
        str(frame_stem), view,
        ImageResolution=[args.width, args.height],
        FrameWindow=[0, args.frames - 1],
    )

    written = sorted(frame_dir.glob("frame*.png"))
    if not written:
        raise SystemExit(
            f"SaveAnimation wrote no frames to {frame_dir}. Nothing is "
            f"encoded from an empty sequence."
        )

    print(f"[render_animation] {len(written)} frames -> {frame_dir}")
    print(f"  source timesteps : {n_steps}")
    print(f"  animation frames : {args.frames} (Sequence, "
          f"{'temporally interpolated' if args.interpolate else 'nearest timestep'})")
    print(f"  resolution       : {args.width}x{args.height}")
    print(f"  exaggeration     : {args.exaggeration}x")
    print(f"  camera           : {args.camera}")
    print(f"  with_water       : {args.with_water}")

    if args.no_encode:
        print("[render_animation] --no-encode: stopping after the PNG sequence.")
        return

    # ParaView's own numbering decides the pattern. It pads to four digits from
    # 0, so frame.0000.png; deriving the pattern from a written filename rather
    # than assuming it keeps this working if that padding ever changes.
    sample = written[0].name
    digits = len(sample.split(".")[-2])
    frame_pattern = str(frame_dir / f"frame.%0{digits}d.png")

    encode_with_ffmpeg(frame_pattern, output_path, args.fps, args.crf, ffmpeg)

    size_mb = output_path.stat().st_size / 1e6
    duration_s = len(written) / args.fps
    print(f"[render_animation] wrote {output_path}")
    print(f"  {len(written)} frames at {args.fps} fps = {duration_s:.1f} s, "
          f"{size_mb:.1f} MB, H.264 crf {args.crf}")

    if not args.keep_frames:
        shutil.rmtree(frame_dir, ignore_errors=True)
        print(f"  removed {frame_dir} (--no-keep-frames)")


if __name__ == "__main__":
    main()
