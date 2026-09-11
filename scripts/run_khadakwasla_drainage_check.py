"""
Standalone Khadakwasla drainage-fix verification run.

WHY THIS EXISTS, rather than POST /runs:

A run submitted through the API executes in a subprocess spawned by the API
server (services/api/jalraksha_service/main.py::_spawn_run_subprocess). That
subprocess is a CHILD of the server, so when the server process is reaped --
which happened three times in one session, each time silently orphaning the
run and discarding hours of compute with nothing persisted, because
run_ensemble returns every member at once and writes nothing per-member --
the simulation dies with it.

This script calls the same pipeline directly, so it is nobody's child and
survives the API server coming and going. It writes its own compact hazard
time-series next to the keyframes so the result can be read back without the
service running at all.

    python scripts/run_khadakwasla_drainage_check.py

What it is verifying (see
C:/Users/satya/.claude/plans/run-khadakwasla-dam-run-wiggly-pelican.md):
a 24 h Khadakwasla run on the OLD 54x54 km dam-centred domain peaked at
t~17,876 s and then PLATEAUED -- 46 cells stuck at SEVERE through the end of
the run, ~42% of released volume permanently trapped. Three artefacts caused
it: an unbreached dam ridge in the DEM, unfilled resampling depressions, and
a domain too small to give the flood anywhere to drain to. This run exercises
all three fixes together.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "api"))

# Geometry: 240 km (E-W) x 188 km (N-S), biased downstream. The flood runs
# east down the Mutha -> Mula-Mutha -> Bhima; a dam-centred box would spend
# half its cells on the Western Ghats and the Arabian Sea.
MARGINS_KM = {"west": 40, "east": 200, "south": 94, "north": 94}

#: Domain presets. "full" is the 240 x 188 km cache superset; "mid" is 117 x 90
#: km, still 105 km of runway east down the Mutha -> Mula-Mutha -> Bhima and 4x
#: cheaper. The flood has never travelled beyond 26 km, so the extra 100 km of
#: "full" has never been used.
#:
#: "exit" is a different KIND of domain and the numbers are measured, not
#: chosen for runway. Measuring the finished h_max rasters of runs 1d3d3c45
#: (300 m, 24 h), 48f7ac59 (500 m, 24 h) and e5485691 (500 m, 48 h, corridor
#: conditioned) gives the same answer in all three: wet cells stop at EAST
#: 23.5 km and NORTH 15 km, and volume_balance.exited_mcm is ~1e-13 -- that is,
#: zero. The front is VOLUME-limited, not domain-limited: 85.3 MCM fills the
#: reachable channel to ~2.7 m mean depth and runs out. So "give it more
#: runway" cannot work, and 105 km or 200 km of east margin is a boundary the
#: wave never touches.
#:
#: The transmissive domain boundary is the only exit this model has -- no
#: infiltration, no baseflow, and at 200 m no sub-grid channel conveyance --
#: so for ANY water to leave, the boundary has to sit INSIDE 23.5 km. East 20
#: km puts it 3.5 km inside the measured front. That makes the question "when
#: does the flood clear a 28 x 26 km study area around Pune", which is a real
#: emergency-management question; it is NOT a claim that the water ceased to
#: exist, and anything published from it must say which. Two gauges (Hadapsar
#: and Magarpatta City, both 17.0 km east) then sit 3 km from that boundary and
#: are flagged by _boundary_proximity below.
DOMAINS = {
    "full": {"west": 40, "east": 200, "south": 94, "north": 94},
    "mid": {"west": 12, "east": 105, "south": 45, "north": 45},
    "exit": {"west": 8, "east": 20, "south": 8, "north": 18},
}
TARGET_RESOLUTION_M = 300.0
SOLVER_DURATION_S = 86400.0
# One frame per 24 min over 24 h. 30 (one per 48 min) is too coarse to say
# WHEN the hazard crossed a threshold, and the cost is memory only -- the
# snapshot dedup in solver/parallel.py already handles a single step crossing
# several scheduled times.
N_SNAPSHOTS = 60
# 4, not 10. The question here is whether the hazard recedes at all, and that
# trend was identical between the 10- and 100-member baselines (both peaked at
# t~17,876 s). Member count buys uncertainty bands, which this run is not
# about, and every extra member is ~1.5 h of wall clock at this grid size.
ENSEMBLE_SIZE = 4

RUN_TAG = "khadakwasla_drainage_check"


def parse_args(argv=None):
    """
    Flags exist so a coarser/shorter first look does not require editing
    constants in place. Every default reproduces the documented
    300 m / 24 h / 4-member configuration verbatim.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resolution", type=float, default=TARGET_RESOLUTION_M,
                        help=f"Grid resolution in metres (default "
                             f"{TARGET_RESOLUTION_M:.0f}). Cost scales roughly "
                             f"as 1/dx^3 -- cells times steps, since the CFL "
                             f"timestep scales with dx -- so 500 m is about "
                             f"4.6x faster than 300 m.")
    parser.add_argument("--duration-h", type=float,
                        default=SOLVER_DURATION_S / 3600.0,
                        help="Simulated duration in hours (default 24).")
    parser.add_argument("--members", type=int, default=ENSEMBLE_SIZE,
                        help=f"Ensemble size (default {ENSEMBLE_SIZE}).")
    parser.add_argument("--snapshots", type=int, default=N_SNAPSHOTS,
                        help=f"Depth snapshots recorded (default {N_SNAPSHOTS}).")
    parser.add_argument("--condition-corridor", type=float, default=0.0,
                        metavar="METRES",
                        help="Fill depressions within this height of the valley "
                             "floor COMPLETELY so the flow corridor drains "
                             "(e.g. 10). Default 0 = off. Measured on "
                             "Khadakwasla at 200 m: a 10 m corridor alters 1.03%% "
                             "of the domain and drops corridor closed capacity "
                             "from 1,686 MCM to 0. The bed becomes MODIFIED "
                             "TERRAIN and the run is labelled accordingly.")
    parser.add_argument("--domain", choices=sorted(DOMAINS), default="full",
                        help="Domain extent: 'full' = 240x188 km (default, "
                             "unchanged), 'mid' = 117x90 km with 105 km of "
                             "downstream runway at a quarter the cost, 'exit' "
                             "= 28x26 km with its east boundary 3.5 km INSIDE "
                             "the measured 23.5 km flood front, so water can "
                             "actually leave the domain. See DOMAINS.")
    parser.add_argument("--solver", choices=("swe", "both"), default="swe",
                        help="'swe' (default) runs the far-field pipeline "
                             "only. 'both' additionally runs Delft3D FM and "
                             "the one-way near-field SPH handoff on top of it, "
                             "which is what the dashboard's Comparison and SPH "
                             "tabs read. Same meaning as POST /runs.")
    parser.add_argument("--n-workers", type=int, default=None,
                        help="Ensemble members solved concurrently. Default "
                             "(unset) uses every core; lower it when the grid "
                             "is large enough that N members will not fit in "
                             "RAM at once.")
    parser.add_argument("--tag", default=RUN_TAG,
                        help="Output directory name under data/exports and "
                             "data/keyframes. Change it to keep a previous "
                             "run's series rather than overwriting it.")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    resolution_m = float(args.resolution)
    duration_s = float(args.duration_h) * 3600.0
    members = int(args.members)
    n_snapshots = int(args.snapshots)
    run_tag = str(args.tag)
    condition_corridor_m = float(args.condition_corridor)
    margins = DOMAINS[args.domain]
    solver = str(args.solver)
    n_workers = args.n_workers

    from jalraksha.presets import get_preset
    from jalraksha.run import run_dam_break_ensemble
    from jalraksha.export.keyframes import export_keyframes
    from jalraksha.impact.hazard import HazardClassifier

    preset = get_preset("khadakwasla")
    dam_config = preset.to_dam_config() if hasattr(preset, "to_dam_config") else dict(preset)
    # The hydrograph is routed for as long as the solver runs; without this the
    # release window is capped independently of the requested duration.
    dam_config["hydrograph_duration_s"] = duration_s

    # NOTE: no tag-named output directory. Artifacts go to the RUN-ID
    # directories the registration hands back below, because that is the only
    # layout the API can serve. `--tag` survives as the human-readable label
    # inside the summary, not as a path.
    dem_path = str(ROOT / "data" / "dem" / "dem_18.44_73.77_clipped.tif")

    print(f"[drainage-check] dam        : {dam_config.get('name')}")
    print(f"[drainage-check] dem        : {dem_path}")
    print(f"[drainage-check] domain     : {args.domain} {margins}")
    print(f"[drainage-check] resolution : {resolution_m} m")
    print(f"[drainage-check] duration   : {duration_s} s ({duration_s / 3600:.1f} h)")
    print(f"[drainage-check] members    : {members}")
    print(f"[drainage-check] snapshots  : {n_snapshots}")
    print(f"[drainage-check] solver     : {solver}")
    nx = int(round((margins["west"] + margins["east"]) * 1000 / resolution_m))
    ny = int(round((margins["south"] + margins["north"]) * 1000 / resolution_m))
    print(f"[drainage-check] grid       : {nx} x {ny} = {nx * ny:,} cells")

    t0 = time.time()

    # REGISTERED, so this run is visible and playable in the dashboard while it
    # solves — not just a directory on disk that nothing can load. The script
    # still owns its own process, so it keeps the durability that is the whole
    # reason long runs live here rather than behind POST /runs.
    from jalraksha_service.script_runs import bootstrap_repo_root, registered_run

    bootstrap_repo_root(ROOT)

    conditioned = condition_corridor_m > 0
    # The domain goes in the label because 'exit' is not a cheaper version of
    # the others — it deliberately clips the study area so the flood crosses a
    # boundary, and a result read without knowing that is read wrongly.
    label = (f"Khadakwasla — drainage check {resolution_m:.0f} m, "
             f"{duration_s / 3600:.0f} h, {args.domain} domain"
             + (f" [CORRIDOR-CONDITIONED {condition_corridor_m:.0f} m]"
                if conditioned else ""))
    registration = registered_run(
        dam_id="khadakwasla",
        dam_config={**dam_config, "name": label,
                    "domain_margins_km": margins,
                    "fill_max_depth_m": 3.0, "notch_breach": True,
                    "condition_corridor_m": condition_corridor_m,
                    "terrain_modified": conditioned,
                    "terrain_note": (
                        "Flow-corridor depressions filled completely so the "
                        "channel drains. This is MODIFIED TERRAIN — depths and "
                        "extents in basins along the corridor are not the "
                        "unconditioned Copernicus surface."
                    ) if conditioned else None},
        solver=solver,
        solver_params={
            "ensemble_size": members,
            "solver_duration_s": duration_s,
            "target_resolution": resolution_m,
            "domain_margins_km": margins,
            "condition_corridor_m": condition_corridor_m,
            "scenario_type": "dam_break",
        },
    )

    with registration as run:
        out_dir = run.export_dir
        kf_dir = run.keyframe_dir

        def progress(pct: float, label: str) -> None:
            print(f"[drainage-check] {pct:5.1f}%  {label}  "
                  f"(+{time.time() - t0:.0f}s)", flush=True)
            run.progress(pct, label)

        result = run_dam_break_ensemble(
            dam_config,
            dem_path,
            ensemble_size=members,
            output_dir=str(out_dir),
            solver_duration_s=duration_s,
            target_resolution=resolution_m,
            record_depth_snapshots=True,
            n_snapshots=n_snapshots,
            progress_cb=progress,
            margins_km=margins,
            fill_max_depth_m=3.0,
            notch_breach=True,
            condition_corridor_m=condition_corridor_m,
            n_workers=n_workers,
        )

        if result.get("error"):
            print(f"[drainage-check] FAILED: {result['error']}")
            run.fail(str(result["error"]))
            return 1

        if solver == "both":
            _add_comparison_and_sph(run, dam_config, progress)

        return _report_and_register(
            run, result, dam_config, kf_dir, series_args=(
                resolution_m, duration_s, members, n_snapshots, run_tag, t0,
            margins, condition_corridor_m))


def _add_comparison_and_sph(run, dam_config, progress) -> None:
    """
    Delft3D FM and the near-field SPH handoff, on top of the SWE run.

    This is what ``solver="both"`` means in the API (tasks.py's dispatch), and
    it is reused rather than reimplemented: ``_run_comparison`` reads this dam's
    own gauges from ``jalraksha.presets.GAUGES`` and records the real kernel's
    verdict, including the case where the binary could not run. A second copy
    here would eventually disagree with the API about whether a given run used
    the Deltares kernel — which is exactly the claim CLAUDE.md makes
    conditional on ``delft3d_binary_used``.

    Failure is recorded, not raised: the far-field result is already complete
    and registering it matters more than the comparison tab.
    """
    progress(88.0, "Running Delft3D FM and near-field SPH")
    try:
        from jalraksha_service.tasks import _run_comparison

        comp_export = _run_comparison(run.run_id, dict(dam_config), with_sph=True)
        if comp_export:
            run.add_export(comp_export["kind"], comp_export["path_or_url"])
            print(f"[drainage-check] comparison export: "
                  f"{comp_export['path_or_url']}")
    except Exception as exc:
        print(f"[drainage-check] comparison/SPH failed "
              f"({type(exc).__name__}: {exc}); far-field result is unaffected")


#: A gauge closer than this to a domain edge has its depth and arrival shaped by
#: the transmissive boundary rather than by the flood alone. UNVETTED: chosen as
#: a few times the coarsest grid spacing this script is run at, not from a
#: published guidance figure. It exists to make contamination visible, not to
#: quantify it.
BOUNDARY_CONTAMINATION_KM = 5.0


def _boundary_proximity(dam_config, margins, threshold_km=BOUNDARY_CONTAMINATION_KM):
    """
    Gauges sitting within `threshold_km` of a domain edge, and those outside it.

    The 'exit' domain is deliberately small enough that the flood crosses its
    eastern boundary, which is the only way water leaves this model at all. The
    cost is that a gauge near that edge reports a depth partly set by the
    outflow condition. Without this note such a depth reads as a clean
    measurement, and it is the same class of error as reporting a minority
    arrival as a confident median.

    Distances are the flat-earth offsets used everywhere else in this pipeline
    for gauge geometry; at these ranges the difference from a geodesic is far
    below the 200 m grid.
    """
    import math

    from jalraksha.presets import get_gauges

    dam_lat = float(dam_config["lat"])
    dam_lon = float(dam_config["lon"])
    km_per_deg_lat = 111.0
    km_per_deg_lon = 111.0 * math.cos(math.radians(dam_lat))

    near, outside = [], []
    for gauge in get_gauges(dam_config.get("dam_id")):
        lat = getattr(gauge, "lat", None)
        lon = getattr(gauge, "lon", None)
        if lat is None or lon is None:
            continue
        east = (float(lon) - dam_lon) * km_per_deg_lon
        north = (float(lat) - dam_lat) * km_per_deg_lat
        # Signed clearance to each of the four edges; negative means outside.
        clearances = {
            "east": margins["east"] - east,
            "west": margins["west"] + east,
            "north": margins["north"] - north,
            "south": margins["south"] + north,
        }
        edge, clearance = min(clearances.items(), key=lambda kv: kv[1])
        row = {
            "gauge": gauge.name,
            "east_km": round(east, 2),
            "north_km": round(north, 2),
            "nearest_edge": edge,
            "clearance_km": round(clearance, 2),
        }
        if clearance < 0:
            outside.append(row)
        elif clearance < threshold_km:
            near.append(row)

    return {
        "threshold_km": threshold_km,
        "boundary_contaminated": near,
        "outside_domain": outside,
        "note": (
            "Gauges listed under boundary_contaminated sit within "
            f"{threshold_km:g} km of a transmissive domain edge; their peak "
            "depths and arrival times are shaped by the outflow condition as "
            "well as by the flood, and must not be quoted as clean "
            "measurements. Gauges under outside_domain are not in the grid at "
            "all and report no arrival for that reason."
        ),
    }


def _report_and_register(run, result, dam_config, kf_dir, series_args) -> int:
    """
    Everything after the solve: keyframes, the hazard series, and registration.

    Split out so the solve above reads as one block. `run.finish` is what makes
    the run appear in the picker as "done"; the hazard series is this script's
    own verdict and has no equivalent in the API, so it is written beside the
    manifest and registered as its own export kind rather than being lost.
    """
    import time as _time

    from jalraksha.impact.hazard import HazardClassifier
    from jalraksha.export.keyframes import export_keyframes

    (resolution_m, duration_s, members, n_snapshots, run_tag, t0,
     margins, condition_corridor_m) = series_args

    print(f"[drainage-check] solve complete in {_time.time() - t0:.0f}s; "
          f"exporting keyframes")

    balance = result.get("volume_balance") or {}
    if balance.get("available"):
        print(f"[drainage-check] VOLUME BALANCE (median of {balance['n_members']} members)")
        print(f"    released : {balance['released_mcm']:9.3f} MCM")
        print(f"    exited   : {balance['exited_mcm']:9.3f} MCM  "
              f"({balance['exited_fraction'] * 100:5.1f}%)")
        print(f"    retained : {balance['retained_mcm']:9.3f} MCM  "
              f"({balance['retained_fraction'] * 100:5.1f}%)   "
              f"[pre-fix baseline was ~42%]")
        print(f"    closure  : {balance['closure_error'] * 100:.3f}% "
              f"(released vs exited+retained)")

    # Into the RUN-ID directory the registration handed us, not a tag-named
    # one: the API serves a keyframe only if it resolves under DATA_DIR, and the
    # frontend resolves each png_url as a sibling of the manifest.
    manifest = export_keyframes(
        {**result, "dam_name": dam_config.get("name", "Khadakwasla Dam")},
        HazardClassifier(), n_keyframes=n_snapshots, out_dir=kf_dir,
    )

    # Compact hazard time-series, so the verdict can be read without the API.
    #
    # WET_SEVERITY IS THE FIGURE TO READ, not `index`. The stored
    # weighted_hazard_index divides by EVERY cell in the domain, dry included
    # (impact/hazard.py), so on a ~180,000-cell domain where the flood wets a
    # few hundred cells it reads ~0.002 for a genuinely dangerous flood, and it
    # moves as the DRY count changes -- which is not a severity signal at all.
    # The pre-fix baseline's "index flat 0.00184 -> 0.00179" is exactly this
    # diluted quantity, and is part of why the plateau was hard to characterise.
    # Both dashboard panels already recompute a wet-cells-only severity; this
    # mirrors them so the script and the UI agree.
    # Weights mirror HazardClassifier.hazard_weights, which no longer carries a
    # SEVERE level: FD2320 publishes four wet categories and no boundary that
    # would split extreme, so the fifth level was retired rather than given an
    # invented threshold. Counts from runs finished before that change still
    # carry a "severe" key; it is read below and folded into EXTREME so an old
    # run's series stays comparable instead of silently losing cells.
    WEIGHTS = {"low": 0.1, "moderate": 0.3, "significant": 0.5, "extreme": 1.0}
    LEGACY_MERGED_INTO_EXTREME = ("severe",)

    series = []
    for kf in manifest.keyframes:
        h = kf.hazard_summary or {}
        counts = {k: (h.get(k, {}).get("count") or 0) for k in
                  ("dry", "low", "moderate", "significant", "extreme")}
        for legacy in LEGACY_MERGED_INTO_EXTREME:
            counts["extreme"] += (h.get(legacy, {}) or {}).get("count") or 0
        wet = sum(counts[k] for k in WEIGHTS)
        wet_severity = (
            sum(WEIGHTS[k] * counts[k] for k in WEIGHTS) / wet if wet else 0.0
        )
        series.append({
            "t": round(float(kf.time_s), 1),
            **counts,
            "wet_cells": wet,
            "wet_severity": round(wet_severity, 6),
            "index": h.get("weighted_hazard_index"),
        })

    # Verdict, computed rather than eyeballed. Green is literal: LOW renders
    # light green [100,200,100] in HazardClassifier.color_map; MODERATE is
    # yellow, SIGNIFICANT orange, EXTREME purple.
    def _first_time_zero(*levels: str):
        """Earliest frame time at which every named level is 0, and stays 0."""
        for i, row in enumerate(series):
            if all(not row[lv] for lv in levels) and all(
                all(not later[lv] for lv in levels) for later in series[i:]
            ):
                return row["t"]
        return None

    last = series[-1] if series else {}
    verdict = {
        # Nothing orange or purple: the direct answer to the stuck high-hazard
        # cells of the pre-fix baseline (recorded there under the old SEVERE
        # level, which is folded into EXTREME above).
        "safe_at_s": _first_time_zero("significant", "extreme"),
        # Only LOW and DRY remain.
        "fully_green_at_s": _first_time_zero(
            "moderate", "significant", "extreme"),
        # READ THESE TWO FIRST. The transmissive boundary is the only exit this
        # model has, so if exited_mcm is ~0 no water left and the two times
        # above describe a pond that simply has nowhere to go -- the run did
        # not test drainage at all, whatever the hazard counts say. Every
        # Khadakwasla run before the 'exit' domain scored exited_mcm ~1e-13
        # with retained_fraction 0.9999999.
        "exited_mcm": balance.get("exited_mcm"),
        "retained_fraction": balance.get("retained_fraction"),
        "final_counts": {k: last.get(k) for k in
                         ("low", "moderate", "significant", "extreme")},
        "final_wet_severity": last.get("wet_severity"),
        "baseline_for_comparison": {
            "severe": 46, "significant": 139, "moderate": 75,
            "note": "27 km dam-centred domain, 24 h, plateaued from t~17,876 s "
                    "(docs/validation_findings.md section 8). NOT COMPARABLE "
                    "cell-for-cell with a new run: these counts came from the "
                    "old depth/velocity band table, which the FD2320 hazard "
                    "rating replaced. Compare the SHAPE of the recession and "
                    "the volume balance, not the individual class counts.",
        },
    }
    print(f"[drainage-check] VERDICT: safe_at={verdict['safe_at_s']} s, "
          f"fully_green_at={verdict['fully_green_at_s']} s")
    print(f"[drainage-check] final counts: {verdict['final_counts']}")
    exited_mcm = verdict.get("exited_mcm")
    if exited_mcm is not None and exited_mcm <= 1e-6:
        print(f"[drainage-check] WARNING: exited_mcm={exited_mcm:.3g} -- no "
              f"water left the domain, so this run does not test drainage. "
              f"The flood front did not reach a boundary.")

    proximity = _boundary_proximity(dam_config, margins)
    for row in proximity["boundary_contaminated"]:
        print(f"[drainage-check] BOUNDARY-CONTAMINATED: {row['gauge']} is "
              f"{row['clearance_km']} km from the {row['nearest_edge']} edge")

    summary = {
        "run_tag": run_tag,
        "margins_km": margins,
        "boundary_proximity": proximity,
        "condition_corridor_m": condition_corridor_m,
        "terrain_modified": condition_corridor_m > 0,
        "target_resolution_m": resolution_m,
        "solver_duration_s": duration_s,
        "ensemble_size": members,
        "volume_balance": balance,
        "verdict": verdict,
        "wall_clock_s": round(time.time() - t0, 1),
        "arrival_times": {
            name: {k: v for k, v in g.items() if k in ("mean", "p05", "p95", "note")}
            for name, g in (result.get("arrival_times") or {}).items()
        },
        "hazard_series": series,
    }
    # Beside the manifest, so the whole run is one directory and the series
    # travels with the frames it describes.
    summary_path = kf_dir / "hazard_series.json"
    summary_path.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")

    # This script's own verdict has no equivalent in the API's schema, so it is
    # registered as its own export kind rather than being left as a file only
    # someone who knew the path could find.
    run.add_export("hazard_series", summary_path)

    # Registers gauges, exports and status="done" — the point at which the run
    # becomes selectable in the dashboard picker. The manifest was exported
    # above (the series is derived from its per-frame hazard counts), so finish
    # reuses it instead of rendering all 60 frames a second time.
    run.finish(result, keyframes_already_exported=True)

    print(f"[drainage-check] wrote {summary_path}")
    print(f"[drainage-check] first: {series[0] if series else None}")
    print(f"[drainage-check] last : {series[-1] if series else None}")
    print(f"[drainage-check] DONE in {_time.time() - t0:.0f}s")
    print(f"[drainage-check] load it in the dashboard: run {run.run_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
