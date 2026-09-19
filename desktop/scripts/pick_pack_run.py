"""
Choose the run a site's data pack should carry. Prints its id, or nothing.

    python desktop/scripts/pick_pack_run.py khadakwasla [--prefer <run_id>]

A run qualifies only if it is `done` AND its keyframe manifest exists on disk —
a run the picker would list but that shows no imagery is not worth shipping.
The preferred run wins when it qualifies; otherwise the newest qualifying run.
Reads the checkout's data/jalraksha.db read-only.
"""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("dam_id")
    parser.add_argument("--prefer", default="")
    args = parser.parse_args()

    db = sqlite3.connect(f"file:{REPO_ROOT / 'data' / 'jalraksha.db'}?mode=ro", uri=True)

    def usable(run_id: str) -> bool:
        row = db.execute(
            "SELECT path_or_url FROM exports WHERE run_id = ? AND kind = 'keyframe_manifest'",
            (run_id,)).fetchone()
        if row is None:
            return False
        path = Path(row[0].replace("\\", "/"))
        return (path if path.is_absolute() else REPO_ROOT / path).is_file()

    if args.prefer:
        status = db.execute("SELECT status, dam_id FROM runs WHERE run_id = ?", (args.prefer,)).fetchone()
        if status and status[0] == "done" and status[1] == args.dam_id and usable(args.prefer):
            print(args.prefer)
            return 0
    for (run_id,) in db.execute(
            "SELECT run_id FROM runs WHERE dam_id = ? AND status = 'done' ORDER BY created_at DESC",
            (args.dam_id,)):
        if usable(run_id):
            print(run_id)
            return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
