"""
Regenerate the Delft3D-vs-SPH comparison artifact for a run that already solved.

WHY THIS EXISTS
---------------
`comparison_metrics.json` and its two PNGs are the only products of a run that
can be rebuilt after the fact. Everything else the pipeline writes depends on
`depth_series` and `terrain_elevation`, which live only in memory and are
discarded when the task returns — that is what `scripts/backfill_xdmf.py`'s
docstring records, and it is why a defect found in the comparison would
otherwise cost a full re-solve of the whole ensemble.

The comparison does not have that problem: `_run_comparison` takes only a
`dam_config`, which is persisted in the runs table, and re-derives the Delft3D
model and the SPH near-field from it. So a run whose SWE half is perfectly good
can have just its comparison rebuilt.

The specific reason it was written: two defects in the comparison path were
fixed after these runs had already been submitted, and their worker processes
had imported the old modules —

  1. `runner.py` returned D-Flow FM's flat (nFaces,) water-depth array where
     every caller expects (ny, nx). It reached imshow and raised
     "Invalid shape (160000,) for image data".
  2. `tasks.py` then caught that TypeError and wrote `delft3d_binary_used:
     false` — reporting a kernel run that had genuinely succeeded, with its
     output on disk, as never having happened.

COST. This re-runs the Delft3D FM kernel and a full PySPH near-field
simulation. The SPH half dominates, at roughly a quarter-hour per dam. It does
NOT re-run the SWE ensemble.

Usage:
    python scripts/rerun_comparison.py <run_id> [<run_id> ...]
    python scripts/rerun_comparison.py --all-both
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "services" / "api"))


def _load_dam_config(run_id: str) -> dict:
    """
    Recover the dam_config a run was submitted with.

    `_solver_params`, `progress_pct` and `phase` are status bookkeeping the task
    layer adds to the same JSON blob; they are stripped so what is handed back
    is the dam config as the solver saw it and nothing else.
    """
    from jalraksha_service import db

    row = db.get_run(run_id)
    if row is None:
        raise SystemExit(f"No run {run_id!r} in the database.")
    # db.get_run already decodes the params_json column into `params`; the raw
    # column is not exposed on the row.
    config = dict(row["params"])
    solver_params = config.pop("_solver_params", {})
    config.pop("progress_pct", None)
    config.pop("phase", None)

    # The hydrograph/Delft3D window follows the run's own duration. Without
    # this the rebuilt comparison would score the kernel over 3 h while the SWE
    # half it is being compared against ran for eight, which is precisely the
    # mismatch _delft3d_duration exists to prevent.
    duration_s = solver_params.get("solver_duration_s")
    if duration_s:
        config["hydrograph_duration_s"] = float(duration_s)
    return config


def rerun(run_id: str) -> int:
    from jalraksha_service.tasks import _run_comparison

    config = _load_dam_config(run_id)
    print(f"\n=== {run_id[:12]}  {config.get('name', '?')} "
          f"({config.get('hydrograph_duration_s', 10800) / 3600:.1f} h window) ===")

    export = _run_comparison(run_id, config, with_sph=True)
    if export is None:
        print("  FAILED: no artifact was written at all.")
        return 1

    written = json.loads(Path(export["path_or_url"]).read_text(encoding="utf-8"))
    if written.get("unavailable"):
        print(f"  STILL UNAVAILABLE: {written.get('reason')}")
        print(f"  delft3d_binary_used = {written.get('delft3d_binary_used')}"
              f"  (failed_after_kernel = {written.get('failed_after_kernel')})")
        return 1

    print(f"  OK  delft3d_binary_used = {written.get('delft3d_binary_used')}")
    print(f"      engine  = {written.get('delft3d_engine_label')}")
    print(f"      sph     = {written.get('sph_engine')}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("run_ids", nargs="*", help="Run ids to rebuild.")
    parser.add_argument("--all-both", action="store_true",
                        help="Every completed solver='both' run.")
    args = parser.parse_args()

    run_ids = list(args.run_ids)
    if args.all_both:
        from jalraksha_service import db

        run_ids += [r["run_id"] for r in db.list_runs()
                    if r.get("solver") == "both" and r.get("status") == "done"
                    and r["run_id"] not in run_ids]

    if not run_ids:
        parser.error("Give at least one run id, or --all-both.")

    return max(rerun(run_id) for run_id in run_ids)


if __name__ == "__main__":
    raise SystemExit(main())
