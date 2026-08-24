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
from pathlib import Path
from typing import Optional

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

        # Set up cache
        cache_dir = setup_cache(args.output_dir)

        # Fetch DEM (Phase 0)
        print(f"\n📍 Preparing simulation for {config.get('dam_name', 'unnamed')} dam...")
        print(f"   Location: {config['dam_location']}")
        print(f"   Height: {config['dam_height']}m, Storage: {config['gross_storage']}Mm³")

        dem_path = fetch_dem(config["dam_location"], cache_dir)
        print(f"✓ DEM cached: {dem_path}")

        print("\n✓ Phase 0 setup complete. Ready for Phase 1 solver.")
        print("  Next: Run `/build-phase 1` to implement solver core (HLLC, Audusse)")

    except ConfigError as e:
        print(f"❌ Config error: {e}")
        exit(1)
    except Exception as e:
        print(f"❌ Error: {e}")
        exit(1)


def cmd_validate(args):
    """Execute: jalraksha validate"""
    try:
        config = load_config(args.config)
        print("✓ Config is valid")
    except ConfigError as e:
        print(f"❌ Config error: {e}")
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
