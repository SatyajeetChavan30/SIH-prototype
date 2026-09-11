"""
Produce the .mat the MATLAB viewer loads.

Two modes, matching the spec's build order:

  --terrain-only   Fast (seconds). Real DEM, no water. This is what phases 1-2
                   need: MATLAB renders the terrain block before any solver runs.

  (default)        Full run of the validated shallow-water solver, producing the
                   water depth / velocity time series for phase 8b.

Usage:
    python tools/matlab/make_demo_dataset.py --terrain-only
    python tools/matlab/make_demo_dataset.py --duration 10800 --resolution 400

The output lands in matlab/data/simulation/ where loadSimulationData.m looks.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

DEFAULT_DEM = REPO_ROOT / "data" / "dem" / "dem_30.38_78.48_clipped.tif"
DEFAULT_OUT = REPO_ROOT / "matlab" / "data" / "simulation" / "tehri.mat"

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
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dem", type=Path, default=DEFAULT_DEM)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--terrain-only", action="store_true",
                        help="Skip the solver; export terrain alone (phases 1-2).")
    parser.add_argument("--duration", type=float, default=10800.0,
                        help="Simulated seconds (default 3 h — the far gauges need it).")
    parser.add_argument("--resolution", type=float, default=400.0,
                        help="Grid resolution in metres.")
    parser.add_argument("--radius-km", type=float, default=60.0)
    parser.add_argument("--snapshots", type=int, default=60,
                        help="Frames in the time series. More = smoother video, bigger file.")
    parser.add_argument("--ensemble", type=int, default=1)
    args = parser.parse_args()

    if not args.dem.exists():
        raise SystemExit(
            f"DEM not found: {args.dem}\n"
            f"Fetch it first:\n"
            f'  python -c "from jalraksha.dem import fetch_dem; '
            f"fetch_dem(30.3789, 78.4789, domain_radius_km=60.0, cache_dir='./data')\""
        )

    from jalraksha.export.matlab_export import export_simulation_mat

    t0 = time.time()

    if args.terrain_only:
        # Build the domain directly — no solver, no breach ensemble. Same
        # load_dem_as_grid() the solver uses, so the terrain is identical to what
        # a later full run will produce.
        from jalraksha.terrain.domain import build_domain

        print(f"[terrain-only] {args.dem}")
        grid, state, _ = build_domain(
            TEHRI, str(args.dem),
            target_resolution=args.resolution,
            domain_radius_km=args.radius_km,
        )
        result = {
            "dam_name": TEHRI["name"],
            "grid": {
                "nx": grid.nx, "ny": grid.ny, "dx": grid.dx, "dy": grid.dy,
                "x0": grid.x0, "y0": grid.y0, "crs": grid.crs,
            },
            "terrain_elevation": state.b,
            "num_ensemble": 0,
            "num_completed": 0,
        }
    else:
        from jalraksha.run import run_dam_break_ensemble

        print(f"[full run] {args.duration/3600:.1f} h simulated @ {args.resolution:.0f} m")
        result = run_dam_break_ensemble(
            TEHRI, str(args.dem),
            ensemble_size=args.ensemble,
            solver_duration_s=args.duration,
            target_resolution=args.resolution,
            domain_radius_km=args.radius_km,
            record_depth_snapshots=True,
            n_snapshots=args.snapshots,
            n_workers=1,
        )
        if "error" in result:
            raise SystemExit(f"Simulation failed: {result['error']}")

    export_simulation_mat(
        result, args.out,
        is_synthetic=False,        # real Copernicus DEM, real solver
        dem_path=str(args.dem),
        dam_config=TEHRI,
    )
    print(f"[done] {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
