"""
One-off migration: make existing keyframe PNGs transparent where they are dry.

WHY
---
Keyframe PNGs are drawn OVER a basemap — Leaflet's ImageOverlay in the 2D panel
and Cesium's SingleTileImageryProvider in the 3D one. They used to be written as
3-channel RGB, and `HazardClassifier` paints dry cells [128, 128, 128], so every
frame was a solid grey rectangle the size of the whole domain with a thin
coloured flood line on it. Both panels apply a layer opacity (0.7 / 0.75), which
made the grey translucent rather than absent — the map just looked washed out,
which reads as a style choice rather than a bug.

`jalraksha/export/keyframes.py` now writes RGBA with dry fully transparent, so
NEW runs are correct without this script. But the depth arrays a run was
rendered from are discarded once it finishes, so already-exported frames cannot
be re-rendered without re-running the solver. This converts them in place
instead.

WHY KEYING ON THE COLOUR IS SAFE HERE
-------------------------------------
Normally "make one colour transparent" is a fragile trick. It is safe in this
specific case because the FD2320 palette has no other grey:

    dry          128,128,128     <- the one made transparent
    low          100,200,100
    moderate     255,200,0
    significant  255,100,0
    severe       255,0,0
    extreme      150,0,150

Exact-match only, no tolerance, so anti-aliased or blended pixels are left
alone. Frames already carrying an alpha channel are skipped as already migrated.

Usage:
    python scripts/make_keyframes_transparent.py [--data-dir ./data] [--dry-run]
"""

from __future__ import annotations

import argparse
from pathlib import Path

#: The exact RGB the classifier uses for DRY. Must match
#: jalraksha/impact/hazard.py::HazardClassifier.color_map[HazardLevel.DRY].
DRY_RGB = (128, 128, 128)


def migrate_png(path: Path, dry_run: bool = False) -> str:
    """Convert one keyframe to RGBA with dry pixels transparent."""
    import numpy as np
    from PIL import Image

    with Image.open(path) as image:
        if image.mode == "RGBA":
            return "skipped (already RGBA)"
        rgb = np.array(image.convert("RGB"))

    dry = np.all(rgb == np.array(DRY_RGB, dtype=rgb.dtype), axis=-1)
    if not dry.any():
        return "skipped (no dry pixels)"

    alpha = np.where(dry, 0, 255).astype(np.uint8)
    rgba = np.dstack([rgb, alpha])
    pct = 100.0 * dry.mean()

    if dry_run:
        return f"would clear {pct:.1f}% of pixels"

    Image.fromarray(rgba, mode="RGBA").save(path, format="PNG")
    return f"cleared {pct:.1f}% of pixels"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data-dir", default="./data",
                        help="Root holding keyframes/<run_id>/*.png")
    parser.add_argument("--dry-run", action="store_true",
                        help="Report what would change without writing.")
    args = parser.parse_args()

    keyframe_root = Path(args.data_dir) / "keyframes"
    if not keyframe_root.exists():
        print(f"No keyframe directory at {keyframe_root}")
        return 1

    runs = sorted(p for p in keyframe_root.iterdir() if p.is_dir())
    total, changed = 0, 0
    for run_dir in runs:
        pngs = sorted(run_dir.glob("*.png"))
        if not pngs:
            continue
        results = [migrate_png(p, args.dry_run) for p in pngs]
        done = sum(1 for r in results if r.startswith(("cleared", "would")))
        total += len(pngs)
        changed += done
        print(f"  {run_dir.name[:12]}  {done:3d}/{len(pngs):3d} frames  {results[0]}")

    verb = "would convert" if args.dry_run else "converted"
    print(f"\n{verb} {changed} of {total} frames across {len(runs)} run(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
