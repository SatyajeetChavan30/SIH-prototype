"""
Backfill the impact artifacts onto runs that finished before they existed.

Two separate gaps this closes, and they have different consequences:

  * ``impact.json`` has NEVER existed on any run. `main.py` has read an export
    of kind "impact" since the endpoint was written and nothing wrote one, so
    the Impact tab's damage section is empty on every historical run.
  * ``population_at_risk.json`` exists on many runs and is WRONG on all of
    them. `reduceResolution(ee.Reducer.sum())` is area-weighted and returns a
    mean, so every pre-2026-09-06 headcount is low by (grid / 100 m)^2 —
    measured at 25.003x on a 500 m grid. See VERIFICATION_LOG row 37.

NOTHING IS RE-SOLVED. The flood fields are read back from the run's own
`h_max_median` GeoTIFF and its `run_summary.json` grid, which is exactly what
`tasks.py` passed to the same functions at the time. Only the exposure rasters
are fetched, and those are cached per domain, so a second run over the same
grid is free.

THE REGENERATED PAR REPLACES A WRONG NUMBER, AND SAYS SO. Overwriting a
historical artifact silently would leave no way to tell a corrected figure from
an original one, so every payload written here carries `backfilled_at` and
`backfill_note`. A run whose PAR was never written just gets one.

Refusals propagate unchanged: a run whose exposure cannot be fetched gets a
payload of reasons and NO figures, exactly as a live run would. Nothing here
invents a number to fill a gap.

Usage:
    python scripts/backfill_impact.py --run e2e09ea3201d4d42b7a7dbcd5fac4b81
    python scripts/backfill_impact.py --all --dry-run
    python scripts/backfill_impact.py --all
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
# DATABASE_URL and DATA_DIR are both RELATIVE (see script_runs.py): a script
# started elsewhere silently creates a second, empty database.
os.chdir(REPO_ROOT)
sys.path.insert(0, str(REPO_ROOT / "services" / "api"))

# Earth Engine needs the project id, and .claude/launch.json has no env field —
# scripts/run_api.py sets it the same way for the same reason.
os.environ.setdefault("FLOODVIEW_GEE_PROJECT", "sih-prototype-506812")

import numpy as np  # noqa: E402
import rasterio  # noqa: E402

from floodview.export.georef import to_north_up  # noqa: E402
from floodview_service import db  # noqa: E402
from floodview_service.config import settings  # noqa: E402
from floodview_service.tasks import impact_exports  # noqa: E402

BACKFILL_NOTE = (
    "Backfilled after the run completed. The flood field is the run's own "
    "h_max_median raster and nothing was re-solved; only the exposure layers "
    "were fetched. Any population figure this replaces was low by "
    "(grid / 100 m)^2 — see docs/VERIFICATION_LOG.md row 37."
)


def _artifact(run_id: str, kind: str) -> Optional[str]:
    for row in db.get_exports(run_id):
        if row["kind"] == kind:
            return row["path_or_url"]
    return None


def _hmax_path(run_id: str) -> Optional[str]:
    """The run's median maximum-depth raster, under whichever kind it was filed."""
    for row in db.get_exports(run_id):
        if "h_max_median" in row["kind"] and str(row["path_or_url"]).endswith(".tif"):
            return row["path_or_url"]
    return None


def _load_result(run_id: str) -> Optional[Dict]:
    """Rebuild the subset of a solver result the impact functions read."""
    summary_path = _artifact(run_id, "run_summary")
    hmax_path = _hmax_path(run_id)
    if not summary_path or not Path(summary_path).exists():
        return None
    if not hmax_path or not Path(hmax_path).exists():
        return None

    summary = json.loads(Path(summary_path).read_text(encoding="utf-8"))
    grid = summary.get("grid") or {}
    # x0/y0 are null on runs registered by register_script_run.py — the UTM
    # origin was never recorded there, and a guessed origin would georeference
    # the exposure raster onto the wrong ground. Skip rather than guess.
    if not all(grid.get(key) is not None
               for key in ("nx", "ny", "dx", "dy", "x0", "y0", "crs")):
        return None

    with rasterio.open(hmax_path) as src:
        h_max = to_north_up(src.read(1)).astype(np.float64)
    h_max = np.nan_to_num(h_max, nan=0.0, posinf=0.0, neginf=0.0)

    if h_max.shape != (int(grid["ny"]), int(grid["nx"])):
        print(f"  raster {h_max.shape} does not match grid "
              f"({grid['ny']}, {grid['nx']}) — skipping")
        return None

    # t_arrival is what compute_par buckets by warning urgency. Without it the
    # PAR half returns None and only the damage half is written, which is the
    # honest outcome rather than a headcount in one undifferentiated bucket.
    result = {"grid": grid, "h_max_median": h_max}
    arrival = next((row["path_or_url"] for row in db.get_exports(run_id)
                    if "t_arrival_median" in row["kind"]
                    and str(row["path_or_url"]).endswith(".tif")), None)
    if arrival and Path(arrival).exists():
        with rasterio.open(arrival) as src:
            t_arrival = to_north_up(src.read(1)).astype(np.float64)
        if t_arrival.shape == h_max.shape:
            result["t_arrival_median"] = t_arrival
    return result


def _dam_config(run_id: str) -> Dict:
    run = db.get_run(run_id) or {}
    params = run.get("params") or {}
    if isinstance(params, str):
        try:
            params = json.loads(params)
        except Exception:
            params = {}
    return params if isinstance(params, dict) else {}


def eligible_runs() -> List[str]:
    """Completed runs that carry both a grid and a depth raster."""
    ids = []
    # list_runs defaults to 50 and this database holds more than that.
    for run in db.list_runs(limit=10000):
        if run.get("status") != "done":
            continue
        run_id = run["run_id"]
        if _artifact(run_id, "run_summary") and _hmax_path(run_id):
            ids.append(run_id)
    return ids


def backfill(run_id: str, dry_run: bool = False) -> bool:
    run = db.get_run(run_id)
    if run is None:
        print(f"{run_id[:8]}: no such run")
        return False
    if run.get("status") != "done":
        print(f"{run_id[:8]}: status is {run.get('status')!r}, not done — skipping")
        return False

    result = _load_result(run_id)
    if result is None:
        print(f"{run_id[:8]}: no usable grid + depth raster — skipping")
        return False

    existing = {row["kind"] for row in db.get_exports(run_id)}
    label = "regenerating" if "population_at_risk" in existing else "writing"
    print(f"{run_id[:8]}: {label} impact artifacts "
          f"({result['grid']['nx']}x{result['grid']['ny']} at "
          f"{result['grid']['dx']:.0f} m)")

    if dry_run:
        print("  dry run — nothing written")
        return True

    rows = impact_exports(run_id, result, _dam_config(run_id))
    if not rows:
        print("  nothing produced")
        return False

    stamp = _dt.datetime.now(_dt.timezone.utc).isoformat()
    for row in rows:
        path = Path(row["path_or_url"])
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["backfilled_at"] = stamp
        payload["backfill_note"] = BACKFILL_NOTE
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    # `db.insert_exports` is a plain INSERT, not an upsert, so re-registering a
    # kind this run already has would DUPLICATE the row and the Downloads panel
    # would list the same file twice. The file itself was overwritten in place
    # above and the existing row already points at that path, so only genuinely
    # new kinds need a database row.
    new_rows = [row for row in rows if row["kind"] not in existing]
    if new_rows:
        db.insert_exports(run_id, new_rows)
    for row in rows:
        if row["kind"] in existing:
            print(f"  {row['kind']}: file rewritten, export row already present")

    for row in rows:
        payload = json.loads(Path(row["path_or_url"]).read_text(encoding="utf-8"))
        if row["kind"] == "impact":
            damage = payload.get("damage", {})
            total = damage.get("total_crore_inr")
            print(f"  impact: total "
                  f"{'None (sectors missing: ' + ', '.join(damage.get('missing_sectors', [])) + ')' if total is None else f'{total:,.1f} crore INR'}")
        else:
            print(f"  population_at_risk: "
                  f"{payload.get('total_population_in_domain', 0):,.0f} in domain, "
                  f"{(payload.get('par') or {}).get('total_par', 0):,.0f} at risk")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="append", default=[],
                        help="Run id to backfill (repeatable).")
    parser.add_argument("--all", action="store_true",
                        help="Every completed run with a grid and a depth raster.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Report what would be written and stop.")
    args = parser.parse_args()

    if not args.run and not args.all:
        parser.error("give --run <id> or --all")

    targets = args.run or eligible_runs()
    print(f"{len(targets)} run(s) to process\n")

    done = sum(1 for run_id in targets if backfill(run_id, args.dry_run))
    print(f"\n{done} of {len(targets)} run(s) {'would be ' if args.dry_run else ''}"
          f"updated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
