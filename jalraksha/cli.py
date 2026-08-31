"""
Command-line interface for JalRaksha.

Phase 0 responsibility: Accept dam location, fetch data, validate setup.
Entry point: jalraksha run --dam <name> --lat <lat> --lon <lon> --height <m> --storage <Mm³>

Usage:
  jalraksha run --config jalraksha.yaml
  jalraksha run --dam tehri --lat 30.389 --lon 78.341 --height 260 --storage 3540
  jalraksha validate --config jalraksha.yaml
  jalraksha cache --list
  jalraksha cache --clear

Outputs:
  - Validates configuration
  - Fetches and caches DEM
  - Ready for Phase 1 solver input
"""

import argparse
import json
from pathlib import Path
import sys
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "services" / "api"))
from jalraksha_service.db import (
    create_run,
    init_db,
    insert_exports,
    insert_gauge_results,
    update_run_status,
)

from jalraksha.config import load_config, setup_cache, ConfigError
from jalraksha.dem import fetch_dem


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(description="JalRaksha: Dam-break inundation modelling")
    subparsers = parser.add_subparsers(dest="command", help="Subcommand")

    # `jalraksha run` — orchestrate end-to-end
    run_parser = subparsers.add_parser("run", help="Run dam-break simulation")
    run_parser.add_argument("--config", type=str, help="Path to jalraksha.yaml config file")
    run_parser.add_argument("--dam", type=str, help="Dam name (e.g., 'tehri')")
    run_parser.add_argument("--lat", type=float, help="Dam latitude (metric CRS)")
    run_parser.add_argument("--lon", type=float, help="Dam longitude (metric CRS)")
    run_parser.add_argument("--height", type=float, help="Dam height (metres)")
    run_parser.add_argument("--storage", type=float, help="Gross storage (million m³)")
    run_parser.add_argument(
        "--output-dir", type=str, default="./data", help="Cache and output directory"
    )
    run_parser.add_argument(
        "--ensemble-size", type=int, default=10, help="Number of breach ensemble members"
    )
    run_parser.add_argument(
        "--time", type=float, default=1800.0, help="Simulation duration in seconds (default 1800)"
    )

    # `jalraksha validate` — check config only
    validate_parser = subparsers.add_parser("validate", help="Validate configuration")
    validate_parser.add_argument("--config", type=str, required=True)

    # `jalraksha cache` — manage local cache
    cache_parser = subparsers.add_parser("cache", help="Manage data cache")
    cache_group = cache_parser.add_mutually_exclusive_group()
    cache_group.add_argument("--list", action="store_true", help="List cached data")
    cache_group.add_argument("--clear", action="store_true", help="Clear cache")
    cache_parser.add_argument("--cache-dir", type=str, default="./data")

    args = parser.parse_args()

    if args.command == "run":
        cmd_run(args)
    elif args.command == "validate":
        cmd_validate(args)
    elif args.command == "cache":
        cmd_cache(args)
    else:
        parser.print_help()


def cmd_run(args):
    """Execute: jalraksha run"""
    run_id = None
    try:
        # Load config from file or CLI args
        if args.config:
            config = load_config(args.config)
        else:
            if not all([args.dam, args.lat, args.lon, args.height, args.storage]):
                raise ConfigError(
                    "Must provide either --config or all of "
                    "--dam, --lat, --lon, --height, --storage"
                )
            config = {
                "dam_name": args.dam,
                "dam_location": (args.lat, args.lon),
                "dam_height": args.height,
                "gross_storage": args.storage,
                "crs": "EPSG:32643",
            }

        # Set up cache and ensure output dir exists
        Path(args.output_dir).mkdir(parents=True, exist_ok=True)
        init_db()
        cache_dir = setup_cache(args.output_dir)

        run_id = create_run(
            dam_id=config.get("dam_name"),
            params={
                "dam_name": config.get("dam_name"),
                "lat": config["dam_location"][0],
                "lon": config["dam_location"][1],
                "height_m": config["dam_height"],
                "storage_mm3": config["gross_storage"],
                "ensemble_size": getattr(args, "ensemble_size", 10),
                "solver_duration_s": float(getattr(args, "time", 1800.0)),
                "output_dir": args.output_dir,
            },
            solver="swe",
        )
        print(f"[RUN_ID] {run_id}")

        # Fetch DEM (Phase 0)
        print(f"\n[INFO] Preparing simulation for {config.get('dam_name', 'unnamed')} dam...")
        print(f"   Location: {config['dam_location']}")
        print(f"   Height: {config['dam_height']}m, Storage: {config['gross_storage']} MCM")

        dam_lat, dam_lon = config["dam_location"]
        dem_path = fetch_dem(dam_lat, dam_lon, cache_dir=cache_dir)
        print(f"[OK] DEM cached: {dem_path}")

        print("\n[INFO] Executing end-to-end JalRaksha dam-break simulation...")
        from jalraksha.run import run_dam_break_ensemble

        dam_config = {
            "name": config.get("dam_name", "tehri"),
            "lat": config["dam_location"][0],
            "lon": config["dam_location"][1],
            "height_m": config["dam_height"],
            "storage_mm3": config["gross_storage"],
            "dam_type": config.get("dam_type", "embankment"),
            "failure_mode": config.get("failure_mode", "overtopping"),
        }

        results = run_dam_break_ensemble(
            dam_config=dam_config,
            dem_path=str(dem_path),
            ensemble_size=getattr(args, "ensemble_size", 10),
            output_dir=args.output_dir,
            solver_duration_s=float(getattr(args, "time", 1800.0)),
            target_resolution=200.0,
        )

        update_run_status(run_id, "done", 100.0)
        # Record gauge results if present
        if results.get("arrival_times"):
            gauges = []
            for gname, g in results["arrival_times"].items():
                gauges.append({
                    "gauge_name": gname,
                    "distance_km": g.get("distance_km"),
                    "arrival_time_s": g.get("median"),
                    "max_depth_m": None,
                    "par_estimate": None,
                })
            insert_gauge_results(run_id, gauges)
        # Record exports
        exports = []
        for kind, path in (results.get("raster_paths") or {}).items():
            exports.append({"kind": kind, "path_or_url": path})
        if results.get("keyframe_manifest_url"):
            exports.append({"kind": "keyframe_manifest", "path_or_url": results["keyframe_manifest_url"]})
        insert_exports(run_id, exports)
        print(f"[RUN_ID] {run_id} — done")

        print("\n[SUCCESS] Simulation completed successfully!")

    except ConfigError as e:
        print(f"[ERROR] Config error: {e}")
        exit(1)
    except Exception as e:
        if run_id is not None:
            update_run_status(run_id, "failed", 0.0, error=str(e))
        print(f"[ERROR] Error: {e}")
        exit(1)


def cmd_validate(args):
    """Execute: jalraksha validate"""
    try:
        config = load_config(args.config)
        print("[OK] Config is valid")
    except ConfigError as e:
        print(f"[ERROR] Config error: {e}")
        exit(1)


def cmd_cache(args):
    """Execute: jalraksha cache"""
    cache_dir = Path(args.cache_dir)

    if args.list:
        if not cache_dir.exists():
            print(f"Cache directory does not exist: {cache_dir}")
            return
        print(f"Cache contents ({cache_dir}):")
        for item in sorted(cache_dir.rglob("*")):
            if item.is_file():
                print(f"  {item.relative_to(cache_dir)}")
    elif args.clear:
        import shutil

        if cache_dir.exists():
            shutil.rmtree(cache_dir)
            print(f"✓ Cache cleared: {cache_dir}")
        else:
            print(f"Cache directory does not exist: {cache_dir}")


if __name__ == "__main__":
    main()
