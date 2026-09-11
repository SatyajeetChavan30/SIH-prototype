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

Two dam presets (jalraksha.presets), selected with --dam:

  khadakwasla (default)  Mutha River Basin, Pune. Moderate relief, urban
                         downstream edge. No published FRL/height/storage yet
                         — --terrain-only and --reservoir work; solver modes
                         raise until those are supplied.

  tehri                  Bhagirathi Basin, Uttarakhand. The original preset;
                         behaviour for --dam tehri is unchanged from before
                         this flag existed.

Usage:
    python tools/paraview/make_dataset.py --terrain-only
    python tools/paraview/make_dataset.py --dam khadakwasla --reservoir --resolution 100
    python tools/paraview/make_dataset.py --dam tehri --synthetic
    python tools/paraview/make_dataset.py --dam tehri --duration 10800 --resolution 400

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

OUT_DIR = REPO_ROOT / "data" / "simulation"
DEM_DIR = REPO_ROOT / "data" / "dem"


def _resolve_utm_zone(lat: float, lon: float) -> int:
    """Same formula jalraksha.terrain.domain.latlon_to_utm uses when no zone
    is forced — kept local so this file doesn't need a solver import just to
    print a diagnostic zone number."""
    zone = int((lon + 180) / 6) + 1
    return max(1, min(60, zone))


def _print_locate_diagnostics(terrain, grid, i_dam: int, j_dam: int,
                              direction_search_radius_cells) -> None:
    """
    --locate-only: report what's actually at the derived dam location, so a
    coordinate error (see jalraksha/presets.py's note on the 13.8 km Tehri
    discrepancy in the spec's own UTM table) is caught before any dataset is
    written, not after a reservoir fill fails confusingly.
    """
    import math

    from tools.paraview.reservoir import _downhill_direction, estimate_pool_surface_m

    min_r, max_r = direction_search_radius_cells
    dam_elev = float(terrain[j_dam, i_dam])
    di, dj = _downhill_direction(terrain, i_dam, j_dam, min_radius=min_r, max_radius=max_r)
    bearing_deg = math.degrees(math.atan2(di, dj)) % 360.0
    compass = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"][
        int((bearing_deg + 22.5) // 45) % 8
    ]

    print(f"[locate] dam cell (i={i_dam}, j={j_dam}) elevation: {dam_elev:.1f} m")
    print(f"[locate] downstream bearing: {bearing_deg:.0f} deg ({compass})")

    try:
        pool_surface_m, diag = estimate_pool_surface_m(
            terrain, i_dam, j_dam, upstream_dir=(di, dj)
        )
        print(
            f"[locate] upstream pool plateau: {diag['plateau_cells']} cells "
            f"(of {diag['upstream_disc_cells']} in the upstream disc), "
            f"surface ~{pool_surface_m:.1f} m (min {diag['plateau_min_m']:.1f} m)"
        )
    except Exception as exc:  # noqa: BLE001 — this is a diagnostic, report and continue
        print(f"[locate] WARNING: could not find a pool plateau upstream: {exc}")

    print(
        "[locate] Sanity check: the downstream bearing should point toward "
        "the dam's known outflow direction. If it points the wrong way, the "
        "derived lat/lon is likely wrong — correct it with --dam-lat/--dam-lon "
        "rather than editing jalraksha/presets.py from memory."
    )


def main() -> None:
    from jalraksha.presets import DEFAULT_PRESET_ID, PRESETS, get_preset

    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dam", choices=sorted(PRESETS), default=DEFAULT_PRESET_ID,
                        help=f"Dam preset (default: {DEFAULT_PRESET_ID}).")
    parser.add_argument("--dem", type=Path, default=None,
                        help="DEM GeoTIFF. Default: the preset's cached clip "
                             "under data/dem/.")
    parser.add_argument("--out", type=Path, default=None,
                        help="Output stem (no extension). Defaults to "
                             "data/simulation/<dam>_<mode>.")
    parser.add_argument("--terrain-only", action="store_true")
    parser.add_argument("--synthetic", action="store_true")
    parser.add_argument("--reservoir", action="store_true",
                        help="Static pool at full supply level (Phase 3).")
    parser.add_argument("--frl", type=float, default=None,
                        help="Full reservoir level, m. Default: the preset's "
                             "value, or DEM-derived if the preset has none.")
    parser.add_argument("--crest", type=float, default=None,
                        help="Dam crest, m — the barrier height. Default: "
                             "the preset's value, or derived from --frl.")
    parser.add_argument("--dam-lat", type=float, default=None,
                        help="Override the preset's dam latitude — use if "
                             "--locate-only shows the preset location is wrong.")
    parser.add_argument("--dam-lon", type=float, default=None,
                        help="Override the preset's dam longitude.")
    parser.add_argument("--locate-only", action="store_true",
                        help="Build the domain, print diagnostics about the "
                             "dam location, and exit without writing a dataset.")
    parser.add_argument("--duration", type=float, default=10800.0,
                        help="Simulated seconds (default 3 h — far gauges need it).")
    parser.add_argument("--resolution", type=float, default=400.0)
    parser.add_argument("--radius-km", type=float, default=None,
                        help="Domain half-width, km. Default: the preset's.")
    parser.add_argument("--frames", type=int, default=40)
    parser.add_argument("--ensemble", type=int, default=1)
    args = parser.parse_args()

    modes = [args.terrain_only, args.synthetic, args.reservoir]
    if sum(bool(m) for m in modes) > 1:
        raise SystemExit(
            "--terrain-only, --synthetic and --reservoir are mutually exclusive.")

    preset = get_preset(args.dam)
    if args.dam_lat is not None or args.dam_lon is not None:
        preset = preset.with_location(args.dam_lat, args.dam_lon)
        print("[dam] location OVERRIDDEN on the command line — the cached "
              "DEM path is re-derived from it too.")

    radius_km = args.radius_km if args.radius_km is not None else preset.domain_radius_km
    dem_path = args.dem or (DEM_DIR / preset.dem_filename())

    print(f"[dam] {preset.name} ({preset.region})")
    print(f"      {preset.lat:.6f} N, {preset.lon:.6f} E  ->  expect EPSG:{preset.epsg}")
    print(f"      radius {radius_km:g} km   dem {dem_path.name}")

    if not dem_path.exists():
        raise SystemExit(
            f"DEM not found: {dem_path}\nFetch it first:\n"
            f'  python -c "from jalraksha.dem import fetch_dem; '
            f"fetch_dem({preset.lat}, {preset.lon}, "
            f"domain_radius_km={radius_km}, cache_dir='./data')\""
        )

    from jalraksha.export.xdmf_export import write_xdmf_series, frames_from_result
    from jalraksha.terrain.domain import build_domain, compute_breach_location

    mode_name = ("terrain" if args.terrain_only
                 else "reservoir" if args.reservoir
                 else "synthetic" if args.synthetic else "solver")
    out_stem = args.out or (OUT_DIR / f"{preset.dam_id}_{mode_name}")
    t0 = time.time()

    if args.terrain_only or args.synthetic or args.reservoir or args.locate_only:
        # Same load_dem_as_grid() the solver uses, so the terrain is byte-identical
        # to what a later full run produces — the 3D view and the simulation cannot
        # drift apart.
        grid, state, _ = build_domain(
            preset.to_dam_config() if _has_solver_fields(preset) else _viz_only_dam_config(preset),
            str(dem_path),
            target_resolution=args.resolution,
            domain_radius_km=radius_km,
        )
        if grid.crs != f"EPSG:{preset.epsg}":
            raise SystemExit(
                f"CRS mismatch: build_domain auto-detected {grid.crs} from "
                f"({preset.lat}, {preset.lon}), but the {preset.name} preset "
                f"declares EPSG:{preset.epsg}. Fix jalraksha/presets.py — the "
                f"declared epsg must match what the coordinate actually "
                f"produces, or every downstream CRS assumption is wrong."
            )
        grid_dict = {
            "nx": grid.nx, "ny": grid.ny, "dx": grid.dx, "dy": grid.dy,
            "x0": grid.x0, "y0": grid.y0, "crs": grid.crs,
        }
        terrain = state.b
        utm_zone = _resolve_utm_zone(preset.lat, preset.lon)
        i_b, j_b, _ = compute_breach_location(
            state, grid, preset.lat, preset.lon, utm_zone)

        if args.locate_only:
            _print_locate_diagnostics(
                terrain, grid_dict, i_b, j_b, preset.direction_search_radius_cells)
            print(f"[done] {time.time() - t0:.1f}s (--locate-only, nothing written)")
            return

        frames = None
        is_synthetic = False
        frl_m = crest_m = None
        frl_source = ""

        if args.reservoir:
            from tools.paraview.reservoir import (
                _downhill_direction, build_reservoir, estimate_pool_surface_m, summarize)

            # FRL resolution ladder: CLI flag > preset value > DEM-derived.
            if args.frl is not None:
                frl_m = args.frl
                frl_source = "--frl on the command line"
            elif preset.frl_m is not None:
                frl_m = preset.frl_m
                frl_source = preset.frl_source
            else:
                min_r, max_r = preset.direction_search_radius_cells
                di, dj = _downhill_direction(
                    terrain, i_b, j_b, min_radius=min_r, max_radius=max_r)
                pool_surface_m, diag = estimate_pool_surface_m(
                    terrain, i_b, j_b, upstream_dir=(di, dj))
                frl_m = pool_surface_m + preset.render_freeboard_m
                frl_source = (
                    f"DEM-derived pool surface {pool_surface_m:.1f} m "
                    f"+ {preset.render_freeboard_m:.1f} m rendering freeboard "
                    f"({diag['plateau_cells']} plateau cells) — "
                    f"{preset.frl_source}"
                )

            if args.crest is not None:
                crest_m = args.crest
            elif preset.crest_m is not None and args.frl is None:
                crest_m = preset.crest_m
            else:
                crest_m = frl_m + preset.barrier_freeboard_m

            print(f"[reservoir] FRL source: {frl_source}")

            res = build_reservoir(
                terrain, grid_dict, i_b, j_b,
                frl_m=frl_m,
                crest_m=crest_m,
                barrier_halfwidth_cells=max(
                    10, int(preset.barrier_halfwidth_m / args.resolution)),
                direction_search_radius_cells=preset.direction_search_radius_cells,
            )
            print(summarize(res))
            if res["downstream_leak_cells"] > 0:
                raise SystemExit(
                    f"Reservoir fill leaked {res['downstream_leak_cells']} cells "
                    f"downstream of the dam — the barrier failed to close the "
                    f"valley. Widen --resolution, or the preset's "
                    f"barrier_halfwidth_m (currently {preset.barrier_halfwidth_m:g} m)."
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

            frames = synthesize_flood(
                terrain, grid_dict, i_b, j_b,
                duration_s=args.duration, n_frames=args.frames,
            )
            is_synthetic = True
    else:
        from jalraksha.run import run_dam_break_ensemble

        dam_config = preset.to_dam_config()  # raises PresetError if unvetted
        print(f"[solver] {args.duration/3600:.1f} h simulated @ {args.resolution:.0f} m")
        result = run_dam_break_ensemble(
            dam_config, str(dem_path),
            ensemble_size=args.ensemble,
            solver_duration_s=args.duration,
            target_resolution=args.resolution,
            domain_radius_km=radius_km,
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
        frl_m = crest_m = None
        frl_source = ""

    write_xdmf_series(
        out_stem, grid_dict, terrain, frames,
        is_synthetic=is_synthetic,
        provenance={
            "dem_path": str(dem_path),
            "dam_id": preset.dam_id,
            "dam_name": preset.name,
            "dam_lat": preset.lat,
            "dam_lon": preset.lon,
            "region": preset.region,
            "epsg": preset.epsg,
            "domain_radius_km": radius_km,
            "frl_m": frl_m if frl_m is not None else "n/a",
            "crest_m": crest_m if crest_m is not None else "n/a",
            "frl_source": frl_source,
            "mode": mode_name,
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

    depth_max = preset.nominal_depth_m
    if args.terrain_only:
        water_flags = ""
    elif args.reservoir:
        water_flags = "--with-water --water-solid --focus-water "
    else:
        water_flags = "--with-water --focus-water "
    print(
        "[render] "
        '"/c/Program Files/ParaView 6.2.0/bin/pvpython" paraview/render_static.py '
        f"--xdmf {out_stem}.xdmf {water_flags}"
        f"--exaggeration {preset.vertical_exaggeration:g} --depth-max {depth_max:g} "
        f"--out paraview/artifacts/phase3_{preset.dam_id}_{mode_name}.png"
    )


def _has_solver_fields(preset) -> bool:
    return preset.height_m is not None


def _viz_only_dam_config(preset):
    """
    build_domain() only reads name/lat/lon (plus an optional manning_n) —
    it does not touch height_m/storage_mm3/dam_type. So --terrain-only,
    --reservoir and --locate-only work for a preset with no vetted solver
    fields (e.g. Khadakwasla today); only run_dam_break_ensemble's breach
    regressions actually need them, which is what to_dam_config() gates.
    """
    return {"name": preset.name, "lat": preset.lat, "lon": preset.lon}


if __name__ == "__main__":
    main()
