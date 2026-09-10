"""
A LABELLED SYNTHETIC demo run: long reach, hazard receding to green.

READ THIS BEFORE SHOWING THE OUTPUT TO ANYONE.

**Nothing here is a simulation.** No solver runs. There is no ensemble, no
breach regression, no shallow-water solution and no validation behind any number
this produces. It paints a prescribed wave onto the real Copernicus DEM so the
flood band follows the actual Mutha -> Mula-Mutha -> Bhima valley and looks
plausible on a basemap. That is its entire purpose: a demo asset showing a long
reach whose hazard advances and then recedes to green, which the real solver
cannot currently produce (see below).

WHY IT EXISTS

The real Khadakwasla runs stop around 25-26 km and the hazard never recedes.
That was diagnosed this session and it is NOT the DEM extent:

  * only 2 of 621 wet cells in run 0e78feac touch its domain edge, and the
    240 x 188 km runs also stalled at ~25 km;
  * 93.2% of the flood volume sits in terrain depressions the conditioning
    refuses to fill (5,075 surviving pits, mean 16.5 m deep, 1,659 MCM of
    closed capacity against 85 MCM released);
  * the solver has NO infiltration, evaporation or seepage sink, and
    `flux.py` zeroes velocity below `H_DRY_DEFAULT` while LEAVING DEPTH IN
    PLACE.

So water in those basins cannot leave at any duration. Reaching green for real
needs either the terrain conditioned to drain or a physical sink added; both are
open decisions. This asset stands in until then.

HOW IT IS LABELLED, three times over, so no single omission unlabels it:

  1. the run picker name begins "SYNTHETIC DEMO";
  2. the caption is BURNED INTO every keyframe PNG, so a screenshot taken out
     of the dashboard still carries it;
  3. `run_summary.json` and the run's `params_json` both carry
     `is_synthetic: true` and a note naming this script.

This mirrors the convention the repository already holds to — `demo_synthetic.py`
sets `is_synthetic=1`, which drives the mandatory red "SYNTHETIC DATA — NOT A
PHYSICAL SIMULATION" banner in the ParaView renders, and `gee/sar.py` refuses to
synthesize an observation at all. A fabricated run that looks like a result is
the single failure mode those conventions exist to prevent.

USAGE

    python scripts/make_synthetic_demo_run.py
    python scripts/make_synthetic_demo_run.py --reach-km 90 --frames 60
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "api"))

#: Khadakwasla dam.
DAM_LAT, DAM_LON = 18.4436, 73.7686

#: Resolution for the painted field. This is a picture, not a solve, so the only
#: cost of a finer grid is render time — but too coarse and the valley band
#: becomes blocky on the basemap.
RESOLUTION_M = 400.0

#: How far above the local valley floor a cell may sit and still be flooded.
#: Keeps the band inside the valley instead of spreading as a disc.
CORRIDOR_HEIGHT_M = 28.0

#: How far above the valley floor still counts as the channel itself. The
#: residual ribbon lives here once the wave has passed.
CHANNEL_HEIGHT_M = 7.0

#: Depth the channel settles to after the wave. Chosen to land inside the
#: classifier's LOW band (0.1-0.5 m), which renders light green — so the final
#: frames show a green river rather than a blank map.
RESIDUAL_DEPTH_M = 0.42

#: Caption burned into every frame.
SYNTHETIC_CAPTION = "SYNTHETIC DEMO - NOT A SIMULATION"

RUN_NAME = "SYNTHETIC DEMO - not a simulation (Khadakwasla reach)"


def build_corridor(bed: np.ndarray, grid, reach_km: float):
    """
    Which cells the wave may occupy, and how far along the valley each one is.

    Height above the local valley floor, from a large-window minimum filter:
    a cell close to its neighbourhood minimum is valley bottom, a cell well
    above it is hillside. Crude next to a real drainage network, and entirely
    adequate for placing a band that reads correctly on a basemap — which is
    all this is for.

    Returns (corridor_mask, distance_km_from_dam, height_above_valley_floor).
    """
    from scipy.ndimage import minimum_filter

    # ~6 km window: wider than the Mutha's floodplain, narrower than the
    # spacing between the valley and the Ghats.
    window = max(3, int(round(6000.0 / grid.dx)) | 1)
    valley_floor = minimum_filter(bed, size=window, mode="nearest")
    height_above_floor = bed - valley_floor

    ny, nx = bed.shape
    xs = grid.x0 + (np.arange(nx) + 0.5) * grid.dx
    ys = grid.y0 + (np.arange(ny) + 0.5) * grid.dy
    xx, yy = np.meshgrid(xs, ys)

    # Dam position in grid metres. The domain is east-biased, so the dam is not
    # at the centre — deriving it from the margins rather than assuming.
    dam_x = grid.x0 + MARGINS_KM["west"] * 1000.0
    dam_y = grid.y0 + MARGINS_KM["south"] * 1000.0

    distance_km = np.hypot(xx - dam_x, yy - dam_y) / 1000.0

    corridor = (
        (height_above_floor <= CORRIDOR_HEIGHT_M)
        & (distance_km <= reach_km)
        # Downstream only. The Mutha runs east; a symmetric disc would put a
        # flood in the Western Ghats, which anyone who knows Pune would spot.
        & (xx >= dam_x - 4000.0)
    )
    return corridor, distance_km, height_above_floor


def paint_wave(corridor, distance_km, height_above_floor, frame_t, duration_s,
               reach_km):
    """
    Depth field for one frame: a front that advances, peaks, then recedes.

    Three factors multiplied together:

      arrival   the front has reached this distance yet
      recession how long ago it passed, decaying toward zero by the last frame
      shape     deeper in the valley bottom, shallower toward the corridor edge

    The recession is the point of the whole asset — every cell must reach zero,
    so the hazard walks EXTREME -> SIGNIFICANT -> MODERATE -> LOW -> dry
    rather than plateauing the way the real runs do.
    """
    total_h = duration_s / 3600.0
    # The front clears the full reach in 60% of the run, leaving the remaining
    # 40% to show the recession. An earlier version cleared it in 45% and then
    # went completely dry for the last eight hours — a third of the animation
    # was blank frames, which reads as "the overlay broke", not "the hazard
    # receded".
    celerity_kmh = reach_km / (0.60 * total_h)
    front_km = celerity_kmh * (frame_t / 3600.0)

    arrived = distance_km <= front_km
    # Time since the front passed this cell, in hours.
    since_h = np.maximum(0.0, (front_km - distance_km) / max(celerity_kmh, 1e-6))

    # Peak shortly after arrival, then exponential recession.
    peak = np.exp(-((since_h - 0.6) ** 2) / 1.1)
    recession = np.exp(-2.4 * since_h / max(total_h, 1e-6) * 3.0)

    depth_shape = np.clip(1.0 - height_above_floor / CORRIDOR_HEIGHT_M, 0.0, 1.0)
    # Attenuate downstream: a wave spreads and shallows as it travels.
    attenuation = np.clip(1.0 - 0.55 * distance_km / max(reach_km, 1e-6), 0.25, 1.0)

    wave = 16.0 * peak * recession * depth_shape * attenuation

    # RESIDUAL CHANNEL. The wave decays toward a shallow ribbon in the valley
    # bottom rather than to nothing, so the animation ENDS on a green LOW band
    # instead of an empty map. It is also the more sensible picture: after a
    # flood passes, the river is back in its banks, not absent.
    in_channel = height_above_floor <= CHANNEL_HEIGHT_M
    residual = np.where(
        arrived & in_channel,
        RESIDUAL_DEPTH_M * np.clip(1.0 - height_above_floor / CHANNEL_HEIGHT_M, 0.0, 1.0),
        0.0,
    )

    # `arrived` gates the WAVE as well as the residual. Without it the peak
    # term — a Gaussian centred 0.6 h after passage — is non-zero even where
    # since_h is 0, so at t=0 the entire corridor came up wet and the animation
    # began at full flood instead of dry.
    depth = np.where(arrived, np.maximum(wave, residual), 0.0)
    depth = np.where(corridor, depth, 0.0)
    # Anything under the classifier's own dry threshold is dry, not a film.
    return np.where(depth < 0.05, 0.0, depth).astype(np.float32)


def burn_caption(png_path: Path, text: str) -> None:
    """
    Draw the synthetic label into the image itself.

    The dashboard shows the run's name, but a screenshot of the map does not.
    A fabricated flood footprint circulating as a picture with no provenance is
    exactly what this is guarding against, so the caption travels in the pixels.
    """
    from PIL import Image, ImageDraw

    with Image.open(png_path).convert("RGBA") as img:
        draw = ImageDraw.Draw(img)
        pad = max(4, img.width // 100)
        # A filled plate behind the text, because the overlay is transparent
        # wherever it is dry and white-on-nothing would vanish.
        bbox = draw.textbbox((0, 0), text)
        w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
        draw.rectangle([pad - 2, pad - 2, pad + w + 6, pad + h + 6],
                       fill=(180, 0, 0, 235))
        draw.text((pad + 2, pad + 2), text, fill=(255, 255, 255, 255))
        img.save(png_path, format="PNG")


MARGINS_KM = {"west": 12, "east": 105, "south": 45, "north": 45}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--reach-km", type=float, default=95.0,
                        help="How far downstream the wave travels (default 95, "
                             "against ~26 km in the real runs).")
    parser.add_argument("--frames", type=int, default=60)
    parser.add_argument("--duration-h", type=float, default=18.0)
    parser.add_argument("--resolution", type=float, default=RESOLUTION_M)
    args = parser.parse_args()

    from floodview_service.script_runs import bootstrap_repo_root, registered_run

    bootstrap_repo_root(ROOT)

    from floodview.export.keyframes import export_keyframes
    from floodview.impact.hazard import HazardClassifier
    from floodview.presets import get_gauges
    from floodview.terrain.conditioning import load_dem_as_grid

    duration_s = args.duration_h * 3600.0
    dem = str(ROOT / "data" / "dem" / "dem_18.44_73.77_clipped.tif")

    print(f"[synthetic] NOTHING HERE IS SIMULATED — painting a prescribed wave")
    print(f"[synthetic] reach {args.reach_km:.0f} km, {args.frames} frames, "
          f"{args.duration_h:.0f} h, {args.resolution:.0f} m")

    grid, bed = load_dem_as_grid(dem, DAM_LAT, DAM_LON,
                                 target_resolution=args.resolution,
                                 margins_km=MARGINS_KM)
    print(f"[synthetic] grid {grid.nx} x {grid.ny} @ {grid.dx:.0f} m")

    corridor, distance_km, height_above_floor = build_corridor(
        bed, grid, args.reach_km)
    print(f"[synthetic] corridor cells: {int(corridor.sum()):,}")

    times = np.linspace(0.0, duration_s, args.frames)
    depth_series = [
        {"time_s": float(t),
         "depth": paint_wave(corridor, distance_km, height_above_floor,
                             float(t), duration_s, args.reach_km)}
        for t in times
    ]
    wet_counts = [int((d["depth"] > 0.1).sum()) for d in depth_series]
    print(f"[synthetic] wet cells: first {wet_counts[0]}, "
          f"peak {max(wet_counts)}, last {wet_counts[-1]}")

    result = {
        "depth_series": depth_series,
        "grid": {"nx": grid.nx, "ny": grid.ny, "dx": grid.dx, "dy": grid.dy,
                 "x0": grid.x0, "y0": grid.y0, "crs": grid.crs},
        "raster_paths": {},
        "arrival_times": {},
    }

    # Gauge arrivals read off the SAME painted wave, so the Gauges tab agrees
    # with the animation rather than contradicting it.
    celerity_kmh = args.reach_km / (0.60 * args.duration_h)
    for g in get_gauges("khadakwasla") or ():
        t_arr = (g.distance_km / celerity_kmh) * 3600.0
        if t_arr <= duration_s and g.distance_km <= args.reach_km:
            result["arrival_times"][g.name] = {
                "distance_km": g.distance_km,
                "median": float(t_arr),
                "p05": float(t_arr * 0.85),
                "p95": float(t_arr * 1.2),
                "note": "SYNTHETIC — read off a painted wave, not simulated.",
            }

    with registered_run(
        dam_id="khadakwasla",
        dam_config={
            "name": RUN_NAME,
            "dam_id": "khadakwasla",
            "is_synthetic": True,
            "synthetic_note": (
                "Generated by scripts/make_synthetic_demo_run.py. No solver "
                "was run. Depths are painted, not computed. Do not quote any "
                "number from this run."
            ),
        },
        solver="swe",
        solver_params={
            "is_synthetic": True,
            "generator": "scripts/make_synthetic_demo_run.py",
            "reach_km": args.reach_km,
            "frames": args.frames,
            "solver_duration_s": duration_s,
            "target_resolution": args.resolution,
            "ensemble_size": 0,
        },
    ) as run:
        manifest = export_keyframes(
            {**result, "dam_name": RUN_NAME},
            HazardClassifier(), n_keyframes=args.frames, out_dir=run.keyframe_dir,
        )

        for kf in manifest.keyframes:
            burn_caption(run.keyframe_dir / kf.png_url, SYNTHETIC_CAPTION)
        print(f"[synthetic] burned the caption into {len(manifest.keyframes)} frames")

        run.finish(result, keyframes_already_exported=True)

        # Overwrite the summary the shared writer produced: it describes a run
        # that did not happen. The provenance must say so in the same file the
        # dashboard reads for the Ensemble and Grid panels.
        summary_path = run.export_dir / "run_summary.json"
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        summary.update({
            "source": "synthetic_demo",
            "is_synthetic": True,
            "ensemble": None,
            "note": (
                "SYNTHETIC. No solver was run. A prescribed wave was painted "
                "onto the Copernicus DEM by "
                "scripts/make_synthetic_demo_run.py so the hazard advances and "
                "recedes over a long reach. The real Khadakwasla runs stop at "
                "~25 km and never recede, because 93% of the flood volume sits "
                "in terrain depressions the conditioning cannot fill and the "
                "solver has no infiltration or evaporation sink. Nothing here "
                "is a result."
            ),
        })
        summary_path.write_text(json.dumps(summary, indent=2, default=str),
                                encoding="utf-8")

        first = manifest.keyframes[0].hazard_summary or {}
        last = manifest.keyframes[-1].hazard_summary or {}

        def counts(h):
            return {k: (h.get(k, {}) or {}).get("count", 0) for k in
                    ("low", "moderate", "significant", "extreme")}

        print(f"[synthetic] first frame: {counts(first)}")
        print(f"[synthetic] last  frame: {counts(last)}")
        print(f"[synthetic] run_id {run.run_id} — load it in the dashboard")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
