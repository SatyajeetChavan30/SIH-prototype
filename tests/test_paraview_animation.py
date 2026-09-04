"""
Video export (spec Section 17 Phase 8) must produce frames that actually differ.

THE DEFECT THIS GUARDS. Setting ``PlayMode = "Sequence"`` and asking for more
frames than the dataset has timesteps looks like it works: ParaView writes every
frame, FFmpeg encodes them, and the video plays. It is still wrong. A reader does
not interpolate in time — asked for a moment between two stored steps it returns
the nearer one — so the clock advances smoothly while the data jumps. Measured on
the 30-step synthetic dataset, 60 requested frames came back as 30 byte-identical
PAIRS: half the video was duplicate frames, and nothing in the output said so.

A video is the artifact most likely to be shown without its provenance, and a
stuttering one misrepresents the solver's temporal resolution. So the assertion
here is on the PIXELS, not on the exit code or the file's existence: byte-equal
consecutive frames mean the interpolator is not in the pipeline.

Requires ParaView. Skipped where absent, matching test_paraview_state.py.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
ANIMATION_SCRIPT = REPO_ROOT / "paraview" / "render_animation.py"

PVPYTHON = Path(os.environ.get(
    "JALRAKSHA_PVPYTHON_EXE", r"C:/Program Files/ParaView 6.2.0/bin/pvpython.exe"))

# 30 timesteps, and small. The point is temporal behaviour, not fidelity.
DATASET = REPO_ROOT / "data" / "simulation" / "synthetic.xdmf"

pytestmark = [
    pytest.mark.skipif(not PVPYTHON.exists(),
                       reason=f"pvpython not found at {PVPYTHON}"),
    pytest.mark.skipif(not DATASET.exists(),
                       reason=f"dataset not built: {DATASET}"),
]

# Small and few: this is a behavioural test, and every frame costs a full render.
WIDTH, HEIGHT = 320, 240
SOURCE_TIMESTEPS = 30


def _render(tmp_path: Path, *extra: str, frames: int) -> tuple[list[Path], str]:
    """Run the animation script and return the written frames, newest run only."""
    out = tmp_path / "clip.mp4"
    completed = subprocess.run(
        [str(PVPYTHON), str(ANIMATION_SCRIPT),
         "--xdmf", str(DATASET),
         "--out", str(out),
         "--with-water",
         "--frames", str(frames),
         "--width", str(WIDTH), "--height", str(HEIGHT),
         # No encode: FFmpeg is a separate dependency and this test is about
         # what ParaView rendered, not about H.264.
         "--no-encode",
         *extra],
        capture_output=True, text=True, cwd=str(REPO_ROOT), check=False,
    )
    assert completed.returncode == 0, (
        f"render_animation failed:\n{completed.stdout}\n{completed.stderr}"
    )
    frame_dir = out.with_name(out.stem + "_frames")
    return sorted(frame_dir.glob("frame*.png")), completed.stdout


def _digests(frames: list[Path]) -> list[str]:
    return [hashlib.sha256(f.read_bytes()).hexdigest() for f in frames]


def test_more_frames_than_timesteps_are_not_duplicates(tmp_path):
    """
    THE REGRESSION. 60 frames over 30 timesteps must be 60 DISTINCT images.

    Without the temporal interpolator this produced exactly 30 duplicate pairs.
    Interpolation is enabled automatically here precisely because frames exceed
    timesteps, so no flag is passed — the default has to be the safe one.
    """
    frames, stdout = _render(tmp_path, frames=60)

    assert len(frames) == 60
    digests = _digests(frames)
    duplicates = sum(1 for a, b in zip(digests, digests[1:]) if a == b)
    assert duplicates == 0, (
        f"{duplicates} of {len(digests) - 1} consecutive frame pairs are "
        f"byte-identical; the temporal interpolator is not in the pipeline."
    )
    # The operator must be told the render was interpolated, not just given it.
    assert "interpolate" in stdout.lower()


def test_render_exits_cleanly(tmp_path):
    """
    Exit code 0, not merely correct output.

    An orphaned second XDMFReader (the probe that counts timesteps) left
    pvpython exiting with an access violation at interpreter shutdown, AFTER
    every frame was written and every line printed. The artifacts were perfect
    and the exit code was 139, so any CI step or wrapper checking the return
    code would have called a good render a failure.
    """
    out = tmp_path / "clean.mp4"
    completed = subprocess.run(
        [str(PVPYTHON), str(ANIMATION_SCRIPT),
         "--xdmf", str(DATASET), "--out", str(out),
         "--frames", "4", "--no-encode",
         "--width", str(WIDTH), "--height", str(HEIGHT)],
        capture_output=True, text=True, cwd=str(REPO_ROOT), check=False,
    )
    assert completed.returncode == 0, (
        f"pvpython exited {completed.returncode} despite rendering:\n"
        f"{completed.stdout}\n{completed.stderr}"
    )


def test_the_render_is_labelled_interpolated_or_not(tmp_path):
    """
    --no-interpolate is honest about what it produces rather than being refused.

    Someone checking the solver's raw output wants exactly the stored steps, and
    the duplicates are then the correct answer. What must never happen is
    duplicates while the output claims interpolation.
    """
    frames, stdout = _render(tmp_path, "--no-interpolate", frames=60)

    assert len(frames) == 60
    assert "nearest timestep" in stdout
    digests = _digests(frames)
    duplicates = sum(1 for a, b in zip(digests, digests[1:]) if a == b)
    # Without interpolation, 60 frames over 30 steps IS duplicated — that is the
    # documented behaviour of a reader, and the reason the default differs.
    assert duplicates > 0


def test_frames_equal_to_timesteps_still_needs_interpolation(tmp_path):
    """
    "One frame per stored step" is NOT a safe case, and assuming it was is how
    this test first failed.

    Sequence mode resamples onto evenly spaced times; the solver's timesteps are
    unevenly spaced because the CFL condition shortens them wherever the flow is
    fast. Asking for exactly 30 frames from 30 stored steps therefore does not
    map one-to-one — measured, it produced a duplicate at index 14/15 while some
    other step was skipped entirely. So interpolation defaults on at every frame
    count, not only when frames exceed timesteps.
    """
    frames, stdout = _render(tmp_path, frames=SOURCE_TIMESTEPS)

    assert len(frames) == SOURCE_TIMESTEPS
    assert "on by default" in stdout
    digests = _digests(frames)
    assert len(set(digests)) == SOURCE_TIMESTEPS, (
        "frames are not distinct even with interpolation enabled"
    )


def test_raw_nearest_step_frames_collide_even_at_matching_counts(tmp_path):
    """
    The measurement behind the default above, pinned so it cannot be quietly
    reverted to a frames > timesteps condition.
    """
    frames, stdout = _render(tmp_path, "--no-interpolate",
                             frames=SOURCE_TIMESTEPS)

    assert "nearest timestep" in stdout
    digests = _digests(frames)
    assert len(set(digests)) < SOURCE_TIMESTEPS, (
        "no collision at frames == timesteps; if the dataset's timesteps became "
        "evenly spaced this test is obsolete, but the default must stay on for "
        "adaptive-CFL solver output"
    )


def test_water_grows_over_the_animation(tmp_path):
    """
    The frames must show the flood ADVANCING, not merely differing.

    Frames could all differ through nothing but a jittering annotation. The
    synthetic dataset floods monotonically (0 -> 5,127 -> 19,216 wet cells), so
    the last frame must carry visibly more water than the first.
    """
    Image = pytest.importorskip("PIL.Image", reason="Pillow not installed")
    import numpy as np

    frames, _ = _render(tmp_path, frames=SOURCE_TIMESTEPS)

    def blue_excess(path: Path) -> float:
        rgb = np.asarray(Image.open(path).convert("RGB"), dtype=np.int16)
        # Water is drawn on a pale-blue background, so "blue" alone is not
        # enough — require blue to dominate red by more than the background's
        # own margin (217, 230, 247 => B - R = 30).
        return float(((rgb[:, :, 2] - rgb[:, :, 0]) > 45).mean())

    assert blue_excess(frames[-1]) > blue_excess(frames[0]), (
        "the last frame holds no more water than the first; the animation is "
        "not showing the flood advance"
    )


def test_single_timestep_dataset_is_refused(tmp_path):
    """
    A video of one instant is a still, and rendering it as a video would
    present a run that produced no flow as a completed simulation.
    """
    terrain = REPO_ROOT / "data" / "simulation" / "khadakwasla_terrain.xdmf"
    if not terrain.exists():
        pytest.skip(f"dataset not built: {terrain}")

    completed = subprocess.run(
        [str(PVPYTHON), str(ANIMATION_SCRIPT),
         "--xdmf", str(terrain),
         "--out", str(tmp_path / "still.mp4"),
         "--frames", "10", "--no-encode",
         "--width", str(WIDTH), "--height", str(HEIGHT)],
        capture_output=True, text=True, cwd=str(REPO_ROOT), check=False,
    )
    assert completed.returncode != 0
    assert "timestep" in (completed.stdout + completed.stderr).lower()


def test_out_is_required(tmp_path):
    """No default output path: a video written somewhere unexpected is lost."""
    completed = subprocess.run(
        [str(PVPYTHON), str(ANIMATION_SCRIPT), "--xdmf", str(DATASET)],
        capture_output=True, text=True, cwd=str(REPO_ROOT), check=False,
    )
    assert completed.returncode != 0
    assert "--out" in (completed.stdout + completed.stderr)
