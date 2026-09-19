"""
Fill the gauge boundary-proximity columns for runs finished before they existed.

``gauge_results.boundary_clearance_km`` / ``near_boundary`` are written by
``script_runs.gauge_rows_from_result`` for every new run. Older rows read NULL
and the dashboard shows no boundary label for them — which is the honest answer
until this script has measured them.

A row is filled only when BOTH of these are known, and skipped (and reported)
otherwise:

* the run's grid ORIGIN, from its ``run_summary.json``. ``register_script_run``
  deliberately leaves ``x0``/``y0`` null rather than guessing, because a wrong
  origin misplaces every gauge — worse than no answer;
* the gauge's position, from the run's dam preset matched by gauge name. That is
  the preset's CURRENT coordinate; a preset edited since the run was solved
  would be measured at its new position, which is why the dry run prints every
  row before anything is written.

Dry run by default. ``--apply`` writes. Nothing is re-solved.

    python scripts/backfill_gauge_boundary.py                   # every done run
    python scripts/backfill_gauge_boundary.py e2e09ea3... --apply
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _bootstrap():
    sys.path.insert(0, str(REPO_ROOT / "services" / "api"))
    from jalraksha_service.script_runs import bootstrap_repo_root

    bootstrap_repo_root(REPO_ROOT)


def _grid_for(db, run_id):
    for export in db.get_exports(run_id):
        if export["kind"] == "run_summary" and Path(export["path_or_url"]).exists():
            summary = json.loads(Path(export["path_or_url"]).read_text(encoding="utf-8"))
            return summary.get("grid") or {}
    return {}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("run_ids", nargs="*", help="run ids (default: every done run)")
    parser.add_argument("--apply", action="store_true", help="write; default is a dry run")
    args = parser.parse_args(argv)

    _bootstrap()
    from jalraksha.presets import get_gauges
    from jalraksha_service import db
    from jalraksha_service.script_runs import (
        BOUNDARY_CONTAMINATION_KM, gauge_boundary_clearance_km,
    )

    run_ids = args.run_ids or [r["run_id"] for r in db.list_runs(1000) if r["status"] == "done"]
    filled = skipped = 0
    for run_id in run_ids:
        run = db.get_run(run_id)
        if not run:
            print(f"{run_id[:8]}  SKIP  no such run")
            skipped += 1
            continue
        grid = _grid_for(db, run_id)
        if grid.get("x0") is None or grid.get("y0") is None:
            print(f"{run_id[:8]}  SKIP  grid origin not recorded")
            skipped += 1
            continue
        dam_id = run.get("dam_id") or run["params"].get("dam_id")
        positions = {g.name: (g.lat, g.lon) for g in get_gauges(dam_id)}
        for row in db.get_gauge_results(run_id):
            name = row["gauge_name"]
            if name not in positions:
                print(f"{run_id[:8]}  SKIP  {name}: not in the {dam_id!r} preset")
                skipped += 1
                continue
            clearance = gauge_boundary_clearance_km(grid, *positions[name])
            if clearance is None:
                print(f"{run_id[:8]}  SKIP  {name}: clearance not computable")
                skipped += 1
                continue
            near = 0 <= clearance < BOUNDARY_CONTAMINATION_KM
            flag = "NEAR EDGE" if near else ("outside" if clearance < 0 else "clear")
            print(f"{run_id[:8]}  {name:<24} {clearance:8.2f} km  {flag}")
            if args.apply:
                db.set_gauge_boundary(run_id, name, clearance, near)
            filled += 1

    verb = "filled" if args.apply else "would fill (dry run; pass --apply)"
    print(f"\n{filled} rows {verb}; {skipped} skipped.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
