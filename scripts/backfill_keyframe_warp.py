"""
Re-register the flood overlay of runs exported before the keyframe warp existed.

    python scripts/backfill_keyframe_warp.py --run-id 044fa3e3ffe6421aa449c9c454d566f9

Older keyframe PNGs are the solver's UTM grid, flipped north-up, placed by the
viewers inside a lat/lon box built from two corners. On a large domain that puts
the flood kilometres off its river (jalraksha/export/keyframes.py explains why).
Each old PNG is exactly that grid, so it can be warped after the fact with the
same helper new exports use; nothing is re-solved.

For each run: writes <frame>_4326.png and <frame>_3857.png beside every existing
frame (originals kept), backs the manifest up to manifest.pre_warp.json, and
rewrites manifest.json to point at the warped frames. A run already marked
overlay_warped is skipped. A run whose grid origin (x0/y0) was never recorded is
REFUSED: warping against a guessed origin would move the flood somewhere else
while looking fixed.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from jalraksha.export.keyframes import _overlay_warps, _render_png, _warp_rgba  # noqa: E402


def backfill_run(run_id: str, data_dir: Path) -> str:
    from PIL import Image

    kf_dir = data_dir / "keyframes" / run_id
    manifest_path = kf_dir / "manifest.json"
    summary_path = data_dir / "exports" / run_id / "run_summary.json"
    if not manifest_path.is_file():
        return f"{run_id}: no keyframe manifest at {manifest_path}"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("simulation_info", {}).get("overlay_warped"):
        return f"{run_id}: already warped, skipped"
    if not summary_path.is_file():
        return f"{run_id}: REFUSED, no run_summary.json to read the grid from"
    grid = json.loads(summary_path.read_text(encoding="utf-8")).get("grid") or {}
    if grid.get("x0") is None or grid.get("y0") is None:
        return f"{run_id}: REFUSED, grid origin x0/y0 was never recorded"

    warps = _overlay_warps(grid)
    for kf in manifest["keyframes"]:
        frame = kf_dir / kf["png_url"]
        rgba = np.array(Image.open(frame).convert("RGBA"))
        if rgba.shape[:2] != (int(grid["ny"]), int(grid["nx"])):
            return (f"{run_id}: REFUSED, {frame.name} is {rgba.shape[1]}x{rgba.shape[0]} "
                    f"but the grid is {grid['nx']}x{grid['ny']}")
        stem = frame.stem
        geographic, mercator = f"{stem}_4326.png", f"{stem}_3857.png"
        _render_png(_warp_rgba(rgba, grid, warps["geographic"]), kf_dir / geographic)
        _render_png(_warp_rgba(rgba, grid, warps["mercator"]), kf_dir / mercator)
        kf["png_url"], kf["bounds"] = geographic, warps["geographic"]["bounds"]
        kf["png_url_mercator"], kf["bounds_mercator"] = mercator, warps["mercator"]["bounds"]

    shutil.copy2(manifest_path, kf_dir / "manifest.pre_warp.json")
    manifest.setdefault("simulation_info", {})["overlay_warped"] = True
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return f"{run_id}: warped {len(manifest['keyframes'])} frames"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", action="append", required=True)
    parser.add_argument("--data-dir", default=str(ROOT / "data"))
    args = parser.parse_args(argv)
    failed = False
    for run_id in args.run_id:
        message = backfill_run(run_id, Path(args.data_dir))
        failed |= "REFUSED" in message
        print(message)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
