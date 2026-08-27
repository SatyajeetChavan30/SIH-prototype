"""
Give already-finished runs the 3D dataset the ParaView button needs.

WHY THIS EXISTS, AND WHY IT IS EXPENSIVE
----------------------------------------
`run_dam_break_task` writes an XDMF for every new swe run. Runs created before
that wiring have none, and cannot simply be "exported now": the solver result
holding `terrain_elevation` and `depth_series` is a local variable inside the
Celery task, discarded the moment it returns. Nothing on disk or in the database
retains it.

So there is no cheap path. Producing the dataset means running the solver again,
with the same parameters, and writing the XDMF from the fresh result. That takes
minutes per run and burns real CPU, which is why this is a deliberate,
opt-in script rather than something the endpoint does silently on demand.

The re-run needs the original solver parameters. Runs submitted after this was
written carry them in `runs.params_json["_solver_params"]` and reproduce exactly.

OLDER RUNS DO NOT. Until recently the API persisted only the dam config —
duration, resolution and ensemble size lived in the Celery task arguments and
were discarded. For those runs this script REFUSES to guess: re-running at a
different resolution or duration would produce a dataset that is not the run it
claims to be, and the dashboard would present it as that run's 3D view. Supply
the values explicitly with --duration / --resolution / --ensemble if you know
them, and be aware you are asserting what the original run used.

Ensemble draws are stochastic, so gauge numbers may differ slightly from the
originally recorded ones — this script does NOT overwrite the stored gauge
results, only adds the dataset.

Usage:
    python scripts/backfill_xdmf.py --list
    python scripts/backfill_xdmf.py --run-id 857db2c2... --duration 1800 --resolution 200
    python scripts/backfill_xdmf.py --all --duration 1800 --resolution 200
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _bootstrap() -> None:
    """Match scripts/run_api.py: repo root as CWD, services/api importable."""
    os.chdir(REPO_ROOT)
    os.environ.setdefault("JALRAKSHA_DATA_DIR", "./data")
    api_dir = REPO_ROOT / "services" / "api"
    if str(api_dir) not in sys.path:
        sys.path.insert(0, str(api_dir))


def _candidates(db, settings):
    """Done swe runs that have no xdmf export row."""
    import sqlite3

    db_path = REPO_ROOT / "data" / "jalraksha.db"
    conn = sqlite3.connect(db_path)
    rows = list(conn.execute(
        "SELECT run_id, dam_id, solver FROM runs WHERE status='done'"))
    out = []
    for run_id, dam_id, solver in rows:
        kinds = {k for (k,) in conn.execute(
            "SELECT kind FROM exports WHERE run_id=?", (run_id,))}
        out.append({
            "run_id": run_id, "dam_id": dam_id, "solver": solver,
            "has_xdmf": "xdmf" in kinds,
        })
    conn.close()
    return out


def _replace_xdmf_export(run_id: str, export: dict) -> None:
    """Insert the xdmf export row, removing any previous one for this run."""
    import sqlite3

    from jalraksha_service import db

    conn = sqlite3.connect(REPO_ROOT / "data" / "jalraksha.db")
    try:
        conn.execute("DELETE FROM exports WHERE run_id=? AND kind='xdmf'", (run_id,))
        conn.commit()
    finally:
        conn.close()
    db.insert_exports(run_id, [export])


def backfill_one(run_id: str, overrides: dict | None = None) -> bool:
    from jalraksha_service import db
    from jalraksha_service.config import settings
    from jalraksha_service.tasks import _resolve_dem, _write_xdmf
    from jalraksha.run import run_dam_break_ensemble

    run = db.get_run(run_id)
    if run is None:
        print(f"[backfill] {run_id}: no such run")
        return False
    if run["status"] != "done":
        print(f"[backfill] {run_id}: status is {run['status']!r}, skipping")
        return False
    if run["solver"] != "swe":
        print(f"[backfill] {run_id}: solver={run['solver']!r} produces no depth "
              f"series — nothing to export. Skipping.")
        return False

    params = run.get("params") or {}
    dam_config = dict(params)
    dam_config.pop("progress_pct", None)
    dam_config.pop("_solver_params", None)

    recorded = params.get("_solver_params") or {}
    overrides = overrides or {}
    resolved, missing = {}, []
    for key, caster in (("solver_duration_s", float),
                        ("target_resolution", float),
                        ("ensemble_size", int)):
        value = overrides.get(key, recorded.get(key))
        if value is None:
            missing.append(key)
        else:
            resolved[key] = caster(value)
    if missing:
        print(f"[backfill] {run_id}: cannot reproduce this run — no recorded "
              f"{', '.join(missing)}.")
        print(f"[backfill]   This run predates the API persisting solver "
              f"parameters, so the values it actually used are not knowable "
              f"from the database. Re-running at guessed settings would produce "
              f"a dataset that is not this run, presented as if it were.")
        print(f"[backfill]   Pass them explicitly if you know them, e.g.: "
              f"--duration 1800 --resolution 200 --ensemble 1")
        return False
    duration = resolved["solver_duration_s"]
    resolution = resolved["target_resolution"]
    ensemble = resolved["ensemble_size"]
    source = "recorded" if not overrides else "supplied on the command line"

    try:
        dem_path = _resolve_dem(dam_config)
    except FileNotFoundError as exc:
        print(f"[backfill] {run_id}: {exc}")
        return False

    print(f"[backfill] {run_id}: re-running solver "
          f"({duration/60:.0f} min simulated @ {resolution:.0f} m, "
          f"ensemble {ensemble}; parameters {source}) — this is the slow part.")
    started = time.time()
    result = run_dam_break_ensemble(
        dam_config, dem_path,
        ensemble_size=ensemble,
        output_dir=str(settings.DATA_DIR / "exports" / run_id),
        solver_duration_s=duration,
        target_resolution=resolution,
        record_depth_snapshots=True,
        n_snapshots=30,
    )
    if "error" in result:
        print(f"[backfill] {run_id}: solver failed — {result['error']}")
        return False

    export = _write_xdmf(run_id, result, dam_config)
    if not export:
        print(f"[backfill] {run_id}: solver ran but no dataset was written")
        return False

    # insert_exports is a plain append — the exports table has no uniqueness
    # constraint — so backfilling the same run twice would leave two "xdmf" rows
    # and GET /runs/{id}/result would hand the frontend duplicate ExportRefs.
    # Drop any existing one first so re-running is idempotent.
    _replace_xdmf_export(run_id, export)
    print(f"[backfill] {run_id}: done in {time.time() - started:.0f}s -> "
          f"{export['path_or_url']}")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--list", action="store_true",
                       help="Show done runs and whether each already has a dataset.")
    group.add_argument("--run-id", help="Backfill one run.")
    group.add_argument("--all", action="store_true",
                       help="Backfill every eligible run. Re-runs the solver for "
                            "each one — expect minutes per run.")
    parser.add_argument("--duration", type=float, default=None,
                        help="solver_duration_s to re-run with. Required for runs "
                             "predating parameter persistence.")
    parser.add_argument("--resolution", type=float, default=None,
                        help="target_resolution in metres. Same condition.")
    parser.add_argument("--ensemble", type=int, default=None,
                        help="ensemble_size. Same condition.")
    args = parser.parse_args()

    overrides = {
        k: v for k, v in (
            ("solver_duration_s", args.duration),
            ("target_resolution", args.resolution),
            ("ensemble_size", args.ensemble),
        ) if v is not None
    }

    _bootstrap()
    from jalraksha_service import db
    from jalraksha_service.config import settings

    if args.list:
        rows = _candidates(db, settings)
        if not rows:
            print("No completed runs.")
            return
        print(f"{'run_id':34s} {'dam':12s} {'solver':9s} dataset")
        for r in rows:
            mark = "yes" if r["has_xdmf"] else ("n/a" if r["solver"] != "swe" else "MISSING")
            print(f"  {r['run_id']:32s} {str(r['dam_id']):12s} {r['solver']:9s} {mark}")
        missing = [r for r in rows if not r["has_xdmf"] and r["solver"] == "swe"]
        if missing:
            print(f"\n{len(missing)} run(s) could be backfilled. Each re-runs the "
                  f"solver; run with --run-id <id> or --all.")
        return

    if args.run_id:
        raise SystemExit(0 if backfill_one(args.run_id, overrides) else 1)

    rows = [r for r in _candidates(db, settings)
            if not r["has_xdmf"] and r["solver"] == "swe"]
    if not rows:
        print("Nothing to backfill.")
        return
    print(f"[backfill] {len(rows)} run(s) to process; each re-runs the solver.")
    ok = sum(1 for r in rows if backfill_one(r["run_id"], overrides))
    print(f"[backfill] {ok}/{len(rows)} succeeded.")


if __name__ == "__main__":
    main()
