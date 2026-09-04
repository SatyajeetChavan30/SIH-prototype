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
    print(f"[drainage-check] margins_km : {MARGINS_KM}")
    print(f"[drainage-check] resolution : {resolution_m} m")
    print(f"[drainage-check] duration   : {duration_s} s ({duration_s / 3600:.1f} h)")
    print(f"[drainage-check] members    : {members}")
    print(f"[drainage-check] snapshots  : {n_snapshots}")
    nx = int(round((MARGINS_KM["west"] + MARGINS_KM["east"]) * 1000 / resolution_m))
    ny = int(round((MARGINS_KM["south"] + MARGINS_KM["north"]) * 1000 / resolution_m))
    print(f"[drainage-check] grid       : {nx} x {ny} = {nx * ny:,} cells")

    t0 = time.time()

    # REGISTERED, so this run is visible and playable in the dashboard while it
    # solves — not just a directory on disk that nothing can load. The script
    # still owns its own process, so it keeps the durability that is the whole
    # reason long runs live here rather than behind POST /runs.
    from jalraksha_service.script_runs import bootstrap_repo_root, registered_run

    bootstrap_repo_root(ROOT)

    label = (f"Khadakwasla — drainage check {resolution_m:.0f} m, "
             f"{duration_s / 3600:.0f} h")
    registration = registered_run(
        dam_id="khadakwasla",
        dam_config={**dam_config, "name": label,
                    "domain_margins_km": MARGINS_KM,
                    "fill_max_depth_m": 3.0, "notch_breach": True},
        solver="swe",
        solver_params={
            "ensemble_size": members,
            "solver_duration_s": duration_s,
            "target_resolution": resolution_m,
            "domain_margins_km": MARGINS_KM,
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
            margins_km=MARGINS_KM,
            fill_max_depth_m=3.0,
            notch_breach=True,
        )

        if result.get("error"):
            print(f"[drainage-check] FAILED: {result['error']}")
            run.fail(str(result["error"]))
            return 1

        return _report_and_register(
            run, result, dam_config, kf_dir, series_args=(
                resolution_m, duration_s, members, n_snapshots, run_tag, t0))


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

    resolution_m, duration_s, members, n_snapshots, run_tag, t0 = series_args

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
    WEIGHTS = {"low": 0.1, "moderate": 0.3, "significant": 0.5,
               "severe": 0.8, "extreme": 1.0}

    series = []
    for kf in manifest.keyframes:
        h = kf.hazard_summary or {}
        counts = {k: (h.get(k, {}).get("count") or 0) for k in
                  ("dry", "low", "moderate", "significant", "severe", "extreme")}
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
    # yellow, SIGNIFICANT orange, SEVERE red, EXTREME purple.
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
        # Nothing red or purple: the direct answer to the 46 stuck SEVERE cells.
        "safe_at_s": _first_time_zero("severe", "extreme"),
        # Only LOW and DRY remain -- no cell anywhere at or above 0.5 m.
        "fully_green_at_s": _first_time_zero(
            "moderate", "significant", "severe", "extreme"),
        "final_counts": {k: last.get(k) for k in
                         ("low", "moderate", "significant", "severe", "extreme")},
        "final_wet_severity": last.get("wet_severity"),
        "baseline_for_comparison": {
            "severe": 46, "significant": 139, "moderate": 75,
            "note": "27 km dam-centred domain, 24 h, plateaued from t~17,876 s "
                    "(docs/validation_findings.md section 8)",
        },
    }
    print(f"[drainage-check] VERDICT: safe_at={verdict['safe_at_s']} s, "
          f"fully_green_at={verdict['fully_green_at_s']} s")
    print(f"[drainage-check] final counts: {verdict['final_counts']}")

    summary = {
        "run_tag": run_tag,
        "margins_km": MARGINS_KM,
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
