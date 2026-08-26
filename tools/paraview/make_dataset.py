"""
Build the XDMF+HDF5 dataset ParaView loads.

Three modes, matching the spec's build order:

  --terrain-only   Seconds. Real DEM, no water. Phase 1: render the terrain block
                   before any solver is involved.

  --reservoir      Seconds. Real terrain, static pool filled to full supply
                   level upstream of the intact dam. Phase 3: the t=0 state.

  --synthetic      Seconds. Real terrain, SYNTHETIC water (is_synthetic=1).
                   Phases 3-4: prove the time series scrubs in the Animation View.

  (default)        Full run of the validated HLLC + Audusse solver. The real
                   deliverable; minutes to hours depending on duration.

Usage:
    python tools/paraview/make_dataset.py --terrain-only
    python tools/paraview/make_dataset.py --reservoir --resolution 100
    python tools/paraview/make_dataset.py --synthetic
    python tools/paraview/make_dataset.py --duration 10800 --resolution 400

Then in ParaView: File > Open > data/simulation/<name>.xdmf, and apply
Warp By Scalar on terrain_elevation. See paraview/README.md.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

DEFAULT_DEM = REPO_ROOT / "data" / "dem" / "dem_30.38_78.48_clipped.tif"
OUT_DIR = REPO_ROOT / "data" / "simulation"

TEHRI = {
    "name": "Tehri Dam",
    "lat": 30.3789,
    "lon": 78.4789,
    "height_m": 260.0,
    "storage_mm3": 3540.0,
    "dam_type": "embankment",
    "failure_mode": "overtopping",
}


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dem", type=Path, default=DEFAULT_DEM)
    parser.add_argument("--out", type=Path, default=None,
                        help="Output stem (no extension). Defaults by mode.")
    parser.add_argument("--terrain-only", action="store_true")
    parser.add_argument("--synthetic", action="store_true")
    parser.add_argument("--reservoir", action="store_true",
                        help="Static pool at full supply level (Phase 3).")
    parser.add_argument("--frl", type=float, default=None,
                        help="Full reservoir level, m. Default: Tehri 830 m.")
    parser.add_argument("--crest", type=float, default=None,
                        help="Dam crest, m — the barrier height. Default: 839.5 m.")
    parser.add_argument("--duration", type=float, default=10800.0,
                        help="Simulated seconds (default 3 h — far gauges need it).")
    parser.add_argument("--resolution", type=float, default=400.0)
    parser.add_argument("--radius-km", type=float, default=60.0)
    parser.add_argument("--frames", type=int, default=40)
    parser.add_argument("--ensemble", type=int, default=1)
    args = parser.parse_args()

    modes = [args.terrain_only, args.synthetic, args.reservoir]
    if sum(bool(m) for m in modes) > 1:
        raise SystemExit(
            "--terrain-only, --synthetic and --reservoir are mutually exclusive.")
    if not args.dem.exists():
        raise SystemExit(
            f"DEM not found: {args.dem}\nFetch it first:\n"
            f'  python -c "from jalraksha.dem import fetch_dem; '
            f"fetch_dem(30.3789, 78.4789, domain_radius_km=60.0, cache_dir='./data')\""
        )

    from jalraksha.export.xdmf_export import write_xdmf_series, frames_from_result
    from jalraksha.terrain.domain import build_domain, compute_breach_location

    default_stem = ("terrain" if args.terrain_only
                    else "reservoir" if args.reservoir
                    else "synthetic" if args.synthetic else "tehri")
    out_stem = args.out or (OUT_DIR / default_stem)
    t0 = time.time()

    if args.terrain_only or args.synthetic or args.reservoir:
        # Same load_dem_as_grid() the solver uses, so the terrain is byte-identical
        # to what a later full run produces — the 3D view and the simulation cannot
        # drift apart.
        grid, state, _ = build_domain(
            TEHRI, str(args.dem),
            target_resolution=args.resolution,
            domain_radius_km=args.radius_km,
        )
        grid_dict = {
            "nx": grid.nx, "ny": grid.ny, "dx": grid.dx, "dy": grid.dy,
            "x0": grid.x0, "y0": grid.y0, "crs": grid.crs,
        }
        terrain = state.b
        frames = None
        is_synthetic = False

        if args.reservoir:
            from tools.paraview.reservoir import (
                TEHRI_CREST_M, TEHRI_FRL_M, build_reservoir, summarize)

            i_b, j_b, _ = compute_breach_location(
                state, grid, TEHRI["lat"], TEHRI["lon"], 44)
            # 5 km of wall either side of the dam, expressed in cells so the
            # barrier spans the same real distance at any resolution.
            res = build_reservoir(
                terrain, grid_dict, i_b, j_b,
                frl_m=args.frl if args.frl is not None else TEHRI_FRL_M,
                crest_m=args.crest if args.crest is not None else TEHRI_CREST_M,
                barrier_halfwidth_cells=max(10, int(5000.0 / args.resolution)),
            )
            print(summarize(res))
            if res["downstream_leak_cells"] > 0:
                raise SystemExit(
                    f"Reservoir fill leaked {res['downstream_leak_cells']} cells "
                    f"downstream of the dam — the barrier failed to close the "
                    f"valley. Widen --resolution or barrier_halfwidth_cells."
                )
            frames = [{
                "time_s": 0.0,
                "depth": res["depth"],
                # A static pool is not flowing. Zero velocity is the honest value;
                # inventing a current would put arrows on standing water.
                "velocity_x": np.zeros_like(res["depth"]),
                "velocity_y": np.zeros_like(res["depth"]),
            }]
            is_synthetic = False

        elif args.synthetic:
            from tools.paraview.synthetic_flood import synthesize_flood

            i_b, j_b, _ = compute_breach_location(
                state, grid, TEHRI["lat"], TEHRI["lon"], 44)
            frames = synthesize_flood(
                terrain, grid_dict, i_b, j_b,
                duration_s=args.duration, n_frames=args.frames,
            )
            is_synthetic = True
    else:
        from jalraksha.run import run_dam_break_ensemble

        print(f"[solver] {args.duration/3600:.1f} h simulated @ {args.resolution:.0f} m")
        result = run_dam_break_ensemble(
            TEHRI, str(args.dem),
            ensemble_size=args.ensemble,
            solver_duration_s=args.duration,
            target_resolution=args.resolution,
            domain_radius_km=args.radius_km,
            record_depth_snapshots=True,
            n_snapshots=args.frames,
            n_workers=1,
        )
        if "error" in result:
            raise SystemExit(f"Simulation failed: {result['error']}")
        grid_dict = result["grid"]
        terrain = result["terrain_elevation"]
        frames = frames_from_result(result)
        is_synthetic = False

    write_xdmf_series(
        out_stem, grid_dict, terrain, frames,
        is_synthetic=is_synthetic,
        provenance={
            "dem_path": str(args.dem),
            "dam_name": TEHRI["name"],
            "mode": default_stem,
            "solver": ("none (terrain only)" if args.terrain_only else
                       "static geometric fill at full supply level — NOT a "
                       "hydrodynamic result; depth is height above the GLO-30 "
                       "surface, which already includes the impounded pool"
                       if args.reservoir else
                       "SYNTHETIC kinematic wave — not physical" if args.synthetic
                       else "jalraksha SWE (HLLC + Audusse, well-balanced)"),
        },
    )
    print(f"[done] {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
