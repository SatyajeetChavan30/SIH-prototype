"""
Standalone river-blockage (landslide dam) run, for any blockage site.

WHY THIS EXISTS, rather than POST /runs:

A run submitted through the API executes in a subprocess spawned by the API
server, so it dies when the server is reaped -- three runs were lost that way
in one session, because run_ensemble returns every member at once and writes
nothing per-member. This script calls the same pipeline directly, so it is
nobody's child, and it registers itself through
``jalraksha_service.script_runs`` so the run is ALSO listed and playable in the
dashboard while it solves. Durable and visible used to be mutually exclusive.

    python scripts/run_blockage.py --site rishi_ganga --crest 110 --duration-h 4
    python scripts/run_blockage.py --site mutha_temghar

WHAT THE BARRIER IS, AND IS NOT:

Crest height and width are OPERATOR-SUPPLIED at every site, and the two sites
are not equally hypothetical:

  * rishi_ganga models a REAL blockage (7 February 2021) whose geometry is
    merely unmeasured -- measurable by differencing Zenodo 4554647 against
    4558692, verification row 26.
  * mutha_temghar is HYPOTHETICAL. No landslide dam has been recorded on that
    reach of the Mutha. Nothing published from such a run may describe the
    barrier as observed.

Each preset's ``barrier_source`` carries that distinction; this script prints it
so the log carries it too.

The impounded volume is NOT supplied here and cannot be. It is measured off the
burned geometry by ``terrain/dem_update.py`` and handed over by
``tasks._apply_blockage_provenance``; ``breach._synthesize_blockage_ensemble``
refuses a blockage run whose ``storage_source`` is user-supplied, which is what
stops a slider from driving the outburst volume.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "api"))

#: Per-site defaults. Every number here is operator input, not a survey.
#:
#: rishi_ganga repeats the 2026-09-02 barrier so the only deliberate difference
#: from run a62cd246084445699524a73a89b63615 is the duration and the drainage
#: fixes that landed after it.
#:
#: mutha_temghar: crest 45 m keeps the impounded surface at ~662 m, below the
#: ~700 m Temghar dam toe -- above roughly 80 m the lake reaches Temghar's own
#: pool and the hypsometric fill starts counting an existing reservoir as
#: impounded volume. Width 1600 m spans a valley measured at 1,380 m across at
#: bed+50 m. The margins bias the domain east down the Mutha through Pune,
#: because a barrier-centred square would spend half its cells on the Ghats.
#: They fit the clip staged for this site, dem_18.45_73.59_clipped.tif
#: (lon 73.4168-73.9963, lat 18.2418-18.6560): the box spans lon 73.446-73.986
#: and lat 18.269-18.629, inside it on every edge. EAST STOPS AT 42 km ON
#: PURPOSE -- 45 km would reach lon 74.014, past the eastern edge of the cached
#: Copernicus E073 tile, and staging it would need a network fetch. Hadapsar,
#: the furthest gauge, is 36.1 km straight-line east and comfortably inside.
#: 6 h because the corridor is 44.6 km of channel at 4.2 m/km.
SITE_DEFAULTS = {
    "rishi_ganga": {
        "crest_m": 110.0,
        "width_m": 1500.0,
        "members": 4,
        "resolution_m": 100.0,
        "duration_h": 4.0,
        "margins_km": None,          # dam-centred, per the preset's radius
        "tag": "rishi-blockage",
    },
    "mutha_temghar": {
        "crest_m": 45.0,
        "width_m": 1600.0,
        "members": 4,
        "resolution_m": 150.0,
        "duration_h": 6.0,
        "margins_km": {"west": 15.0, "east": 42.0, "south": 20.0, "north": 20.0},
        "tag": "mutha-blockage",
    },
}

N_SNAPSHOTS = 30


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a river-blockage (landslide dam) simulation.")
    parser.add_argument("--site", default="rishi_ganga",
                        choices=sorted(SITE_DEFAULTS),
                        help="Blockage site from jalraksha.presets.")
    parser.add_argument("--crest", type=float, default=None,
                        help="Barrier crest height above the valley floor (m). "
                             "OPERATOR-SUPPLIED at every site. Default is the "
                             "site's entry in SITE_DEFAULTS.")
    parser.add_argument("--width", type=float, default=None,
                        help="Barrier width across the valley (m). Must span "
                             "the valley; blockage.py proves it does and "
                             "widens up to 8 doublings before refusing.")
    parser.add_argument("--thickness", type=float, default=None,
                        help="Barrier thickness along the channel (m). "
                             "Defaults to the blockage module's own rule.")
    parser.add_argument("--barrier-lat", type=float, default=None,
                        help="Barrier latitude. Defaults to the preset's "
                             "terrain-derived suggested position.")
    parser.add_argument("--barrier-lon", type=float, default=None,
                        help="Barrier longitude. Defaults as above.")
    parser.add_argument("--breach-mode", default="overtop",
                        help="Barrier failure mode passed to BlockageSpec.")
    parser.add_argument("--members", type=int, default=None,
                        help="Ensemble members. The spread comes from "
                             "NATURAL_DAM_LOG_CYCLES, not from four competing "
                             "regressions -- quote the range, never a single "
                             "discharge.")
    parser.add_argument("--resolution", type=float, default=None,
                        help="Grid resolution (m).")
    parser.add_argument("--duration-h", type=float, default=None,
                        help="Simulated duration (hours).")
    parser.add_argument("--snapshots", type=int, default=N_SNAPSHOTS,
                        help="Depth snapshots recorded, i.e. keyframes.")
    parser.add_argument("--fill-max-depth", type=float, default=3.0,
                        help="Threshold-limited depression fill (m). Fills "
                             "resampling noise, not genuine basins.")
    parser.add_argument("--no-notch", action="store_true",
                        help="Disable the breach notch, which is on by "
                             "default.")
    for edge in ("west", "east", "south", "north"):
        parser.add_argument(f"--margin-{edge}", type=float, default=None,
                            help=f"Domain extent {edge} of the barrier (km). "
                                 f"Supplying any margin replaces the preset's "
                                 f"dam-centred radius entirely.")
    parser.add_argument("--n-workers", type=int, default=None,
                        help="Solver worker processes (default: pipeline's).")
    parser.add_argument("--tag", default=None,
                        help="Human-readable label carried in the summary. "
                             "NOT a directory name -- artifacts go to the "
                             "run-id directories the registration hands back, "
                             "because that is the only layout the API serves.")
    return parser.parse_args(argv)


def _resolve_margins(args, defaults):
    """
    Domain extent: explicit --margin-* flags, else the site default.

    A PARTIAL override is completed from the site default rather than refused,
    so `--margin-east 60` widens the runway without having to restate the other
    three. A site whose default is None and which is given no flags stays
    dam-centred on the preset's radius.
    """
    explicit = {edge: getattr(args, f"margin_{edge}")
                for edge in ("west", "east", "south", "north")}
    if all(v is None for v in explicit.values()):
        return defaults["margins_km"]
    base = dict(defaults["margins_km"] or {})
    for edge, value in explicit.items():
        if value is not None:
            base[edge] = float(value)
    missing = [e for e in ("west", "east", "south", "north") if e not in base]
    if missing:
        raise SystemExit(
            f"--margin-* given for some edges but this site has no default "
            f"margins to complete it; supply {missing} too."
        )
    return base


def main(argv=None) -> int:
    args = parse_args(argv)
    site = str(args.site)
    defaults = SITE_DEFAULTS[site]

    def pick(name, key):
        value = getattr(args, name)
        return defaults[key] if value is None else value

    resolution_m = float(pick("resolution", "resolution_m"))
    duration_s = float(pick("duration_h", "duration_h")) * 3600.0
    members = int(pick("members", "members"))
    crest_m = float(pick("crest", "crest_m"))
    width_m = float(pick("width", "width_m"))
    run_tag = str(args.tag or defaults["tag"])
    n_snapshots = int(args.snapshots)
    notch = not args.no_notch
    margins = _resolve_margins(args, defaults)

    from jalraksha.presets import get_blockage_preset
    from jalraksha.run import run_dam_break_ensemble

    preset = get_blockage_preset(site)
    dam_config = preset.to_dam_config()

    barrier_lat = args.barrier_lat if args.barrier_lat is not None \
        else preset.suggested_barrier_lat
    barrier_lon = args.barrier_lon if args.barrier_lon is not None \
        else preset.suggested_barrier_lon
    if barrier_lat is None or barrier_lon is None:
        print("[blockage] no barrier position: pass --barrier-lat/--barrier-lon")
        return 2

    # The barrier geometry the run is asked to burn. to_dam_config() emits no
    # storage and storage_source="hypsometric_fill_pending"; that marker is
    # replaced below by the MEASURED volume, and only by it.
    dam_config.update({
        "blockage_lat": barrier_lat,
        "blockage_lon": barrier_lon,
        "blockage_crest_height_m": crest_m,
        "blockage_width_m": width_m,
        "blockage_thickness_m": args.thickness,
        "blockage_breach_mode": str(args.breach_mode),
        "blockage_source": "manual_operator_input",
        # Route the release for as long as the solver runs; without this the
        # release window is capped independently of the requested duration.
        "hydrograph_duration_s": duration_s,
        "fill_max_depth_m": float(args.fill_max_depth),
        "notch_breach": notch,
    })
    if margins:
        dam_config["domain_margins_km"] = margins
    # The label says whose numbers these are. The barrier is never surveyed and
    # the suggested position is terrain-derived, so a name that read simply
    # "<site> blockage" would let both be mistaken for observations.
    dam_config["name"] = (
        f"{preset.name} — OPERATOR-SUPPLIED barrier "
        f"{crest_m:.0f} m x {width_m:.0f} m, {resolution_m:.0f} m, "
        f"{duration_s / 3600:.1f} h"
        + ("" if notch else " [NO NOTCH]")
    )

    origin = ("terrain-derived default" if args.barrier_lat is None
              else "operator-specified")
    print(f"[blockage] site       : {site} — {preset.name}")
    print(f"[blockage] barrier    : {barrier_lat:.4f}, {barrier_lon:.4f}  ({origin})")
    print(f"[blockage] provenance : {preset.barrier_source}")
    print(f"[blockage] crest      : {crest_m:g} m   width: {width_m:g} m   "
          f"mode: {args.breach_mode}")
    print(f"[blockage] resolution : {resolution_m:g} m")
    print(f"[blockage] duration   : {duration_s:.0f} s ({duration_s / 3600:.1f} h)")
    print(f"[blockage] members    : {members}")
    if margins:
        nx = int(round((margins["west"] + margins["east"]) * 1000 / resolution_m))
        ny = int(round((margins["south"] + margins["north"]) * 1000 / resolution_m))
        print(f"[blockage] domain     : {margins} — {nx} x {ny} = {nx * ny:,} cells")
    else:
        print(f"[blockage] domain     : {preset.domain_radius_km} km radius, "
              f"barrier-centred")
    print(f"[blockage] notch      : {notch}   fill: {args.fill_max_depth:g} m")

    t0 = time.time()

    from jalraksha_service.script_runs import bootstrap_repo_root, registered_run

    # DATABASE_URL and DATA_DIR are both relative to the process CWD; without
    # this a script started elsewhere silently creates a second, empty database.
    bootstrap_repo_root(ROOT)

    registration = registered_run(
        dam_id=preset.site_id,
        dam_config=dam_config,
        solver="swe",
        solver_params={
            "ensemble_size": members,
            "solver_duration_s": duration_s,
            "target_resolution": resolution_m,
            "scenario_type": "river_blockage",
            "blockage_crest_height_m": crest_m,
            "blockage_width_m": width_m,
            "domain_margins_km": margins,
            "notch_breach": notch,
            "fill_max_depth_m": float(args.fill_max_depth),
            "tag": run_tag,
        },
    )

    with registration as run:
        def progress(pct: float, label: str = "") -> None:
            print(f"[blockage] {pct:5.1f}%  {label}  (+{time.time() - t0:.0f}s)",
                  flush=True)
            run.progress(pct, label)

        # The barrier burn and the measured-storage handoff. Imported from
        # tasks.py rather than reimplemented: a local copy is how the
        # slider-sets-the-physics failure would return by another door.
        from jalraksha_service.tasks import (
            _apply_blockage_provenance,
            _resolve_dem_for_run,
        )

        dem_path, provenance = _resolve_dem_for_run(
            dam_config, target_resolution=resolution_m, report=progress,
        )
        if provenance is None:
            run.fail("No blockage provenance was produced, so the impounded "
                     "volume was never measured. Refusing to solve.")
            return 1

        solved_config = _apply_blockage_provenance(dam_config, provenance)

        lake = provenance.lake
        barrier = provenance.barrier
        print(f"[blockage] updated DEM : {dem_path}")
        print("[blockage] MEASURED off the burned geometry "
              "(not published, not user-supplied):")
        print(f"    impounded volume : {lake['volume_mm3']:9.3f} MCM")
        print(f"    surface area     : {lake['area_km2']:9.3f} km2")
        print(f"    surface elevation: {lake['surface_elevation_m']:9.1f} m")
        print(f"    barrier crest    : {barrier['crest_height_m']:9.1f} m "
              f"above floor {barrier['floor_elevation_m']:.1f} m")
        print(f"    injection point  : {solved_config['inject_lat']:.4f}, "
              f"{solved_config['inject_lon']:.4f}")

        result = run_dam_break_ensemble(
            solved_config,
            dem_path,
            ensemble_size=members,
            output_dir=str(run.export_dir),
            solver_duration_s=duration_s,
            target_resolution=resolution_m,
            record_depth_snapshots=True,
            n_snapshots=n_snapshots,
            progress_cb=progress,
            # margins_km, when given, replaces the radius entirely.
            domain_radius_km=float(preset.domain_radius_km),
            margins_km=margins,
            fill_max_depth_m=float(args.fill_max_depth),
            notch_breach=notch,
            n_workers=args.n_workers,
        )

        if result.get("error"):
            print(f"[blockage] FAILED: {result['error']}")
            run.fail(str(result["error"]))
            return 1

        _report_volume_balance(result)

        # finish() exports keyframes, writes the summary and inserts gauge rows
        # through the SHARED gauge_rows_from_result, so the minority-arrival
        # note reads identically to the API's. It flips the row to "done" LAST.
        run.finish(result, n_keyframes=n_snapshots, dem_path=dem_path)
        print(f"[blockage] complete in {time.time() - t0:.0f}s — "
              f"run_id {run.run_id}")
        _report_gauges(result)
        return 0


def _report_volume_balance(result) -> None:
    """
    Where the released water ended up.

    Read `exited` against the domain, not as a physical claim: water leaves
    this model only across a transmissive boundary, so a front that never
    reaches one reports 0% exited whether it is genuinely ponded or simply
    still inside the grid.
    """
    balance = result.get("volume_balance") or {}
    if not balance.get("available"):
        return
    print(f"[blockage] VOLUME BALANCE (median of {balance['n_members']} members)")
    print(f"    released : {balance['released_mcm']:9.3f} MCM")
    print(f"    exited   : {balance['exited_mcm']:9.3f} MCM  "
          f"({balance['exited_fraction'] * 100:5.1f}%)")
    print(f"    retained : {balance['retained_mcm']:9.3f} MCM  "
          f"({balance['retained_fraction'] * 100:5.1f}%)")
    print(f"    closure  : {balance['closure_error'] * 100:.3f}%")


def _report_gauges(result) -> None:
    """
    The question this run exists to answer, printed where the log can be read.

    A minority arrival is labelled as one by the shared gauge mapping; echoing
    the note here keeps the console from reading as a confident median.
    """
    from jalraksha_service.script_runs import gauge_rows_from_result

    print("[blockage] GAUGES")
    for row in gauge_rows_from_result(result):
        arrival = row.get("arrival_time_s")
        when = f"{arrival / 60.0:6.1f} min" if arrival else "  no arrival"
        print(f"    {row['gauge_name']:<32} {row['distance_km']:5.1f} km  "
              f"{when}   peak {row.get('max_depth_m') or 0.0:5.2f} m")
        note = row.get("note")
        if note:
            print(f"        {note}")


if __name__ == "__main__":
    raise SystemExit(main())
