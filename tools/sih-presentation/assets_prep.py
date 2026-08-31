"""
Prepare the imagery the SIH idea deck embeds.

    python tools/sih-presentation/assets_prep.py

Crops the raw captures down to the part of the frame that carries meaning, adds
a thin border so a light screenshot does not bleed into a white slide, and
downsamples so the finished .pptx stays small enough to upload comfortably.

Inputs:
  tools/sih-presentation/assets/dash_*.png   from capture_dashboard.py
  paraview/artifacts/*.png                   from the ParaView pipeline
Outputs:
  tools/sih-presentation/assets/prepared/*.png
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageOps

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
RAW = HERE / "assets"
OUT = RAW / "prepared"

BORDER = (0xC8, 0xD2, 0xDE)

# name -> (source path, crop box or None, target width in px)
#
# The dashboard captures are 1904x1049. x=313 is the right edge of the control
# panel, so cropping there drops the sidebar and keeps the panel content; the
# sidebar is quoted as text on the slides instead.
JOBS: dict[str, tuple[Path, tuple[int, int, int, int] | None, int]] = {
    # Slide 2 — the two map panes and the tab bar. The sidebar is cropped off:
    # at slide scale its readouts are illegible anyway, and the numbers it
    # carries are quoted as text on slide 5.
    "workspace": (RAW / "dash_workspace.png", (313, 8, 1904, 1049), 1500),
    # Slide 4 — the three gates plus the Ritter depth profile.
    "validation": (RAW / "dash_validation.png", (313, 45, 1904, 800), 1500),
    # Slide 5 — ensemble spread and peak depth.
    "ensemble": (RAW / "dash_ensemble.png", (313, 45, 1904, 770), 1400),
    # Slide 5 — real Copernicus terrain, Bhagirathi valley, ParaView.
    "terrain3d": (ROOT / "paraview/artifacts/phase8b_tehri_real.png", (170, 60, 1810, 1010), 1300),
    # Slide 3 — reservoir at rest on real terrain.
    "reservoir": (ROOT / "paraview/artifacts/phase3_reservoir.png", (170, 60, 1810, 1010), 1200),
}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, (src, crop, width) in JOBS.items():
        if not src.exists():
            print(f"  ! missing {src}")
            continue
        im = Image.open(src).convert("RGB")
        if crop:
            im = im.crop(crop)
        if im.width > width:
            height = round(im.height * width / im.width)
            im = im.resize((width, height), Image.LANCZOS)
        im = ImageOps.expand(im, border=1, fill=BORDER)
        dst = OUT / f"{name}.png"
        im.save(dst, optimize=True)
        print(f"  {name:12s} {im.size[0]}x{im.size[1]}  {dst.stat().st_size / 1024:6.0f} KB")


if __name__ == "__main__":
    main()
