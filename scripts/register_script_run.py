"""
Make an already-finished, script-launched run loadable in the dashboard.

WHY THIS EXISTS

Two completed Khadakwasla drainage runs — a 500 m and a 300 m, 50 export
products and 60 keyframes each — were unreachable from the browser. They were
launched from `scripts/run_khadakwasla_drainage_check.py`, which deliberately
avoids the API so a five-hour solve survives the server restarting. The cost was
that nothing called `db.create_run`, so no row existed and `GET /runs` could not
list them.

Re-solving to get a row would burn five hours of CPU to produce output that is
already on disk. This registers what exists instead.

WHAT IT DOES NOT DO. It does not re-run the solver, so it cannot recover
anything the original run did not write. In particular the full result dict —
`h_max`, `depth_series`, `terrain_elevation` — is long gone, so the Ensemble and
Grid panels are populated from what the keyframe manifest and the run's own
summary recorded, not recomputed. Those are stated as `source: "backfilled"` in
the written `run_summary.json` so a reader can tell the difference.

DIRECTORIES ARE MOVED, NOT COPIED. Artifacts must live under
`data/exports/<run_id>/` and `data/keyframes/<run_id>/`: the API serves a file
only if it resolves under DATA_DIR, and the frontend resolves each keyframe's
`png_url` as a SIBLING of the manifest. Copying would leave two divergent
50-file trees; moving keeps exactly one, and the sibling convention survives any
directory name.

USAGE

    python scripts/register_script_run.py --list
    python scripts/register_script_run.py --tag khadakwasla_drainage_300m \\
        --dam-id khadakwasla --name "Khadakwasla — drainage check 300 m"
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

#: Export kinds inferred from a filename, so the Downloads panel groups them the
#: way an API-produced run does. Anything unmatched is registered under its own
#: stem, which is still downloadable — just not grouped.
KIND_BY_SUFFIX = {
    ".tif": "cog",
    ".zip": "shapefile",
    ".kml": "kml",
    ".kmz": "kmz",
    ".png": "image",
    ".json": "json",
}


def _bootstrap():
    sys.path.insert(0, str(REPO_ROOT / "services" / "api"))
    from jalraksha_service.script_runs import bootstrap_repo_root

    bootstrap_repo_root(REPO_ROOT)


def _export_kind(path: Path) -> str:
    """
    A stable export kind for a file the standard pipeline did not name.

    The stem is preferred over the extension because it is what a reader sees in
    the Downloads panel: "h_max_median_cog" says more than "cog".
    """
    stem = path.stem
    if stem in ("manifest",):
        return "keyframe_manifest"
    if stem == "run_summary":
        return "run_summary"
    if stem == "hazard_series":
        return "hazard_series"
    return stem or KIND_BY_SUFFIX.get(path.suffix.lower(), "export")


def _find_tagged_runs():
    """Tag-named directories under data/keyframes that carry a manifest."""
    kf_root = REPO_ROOT / "data" / "keyframes"
    found = []
    for d in sorted(kf_root.iterdir()) if kf_root.exists() else []:
        # A run_id directory is 32 hex characters; anything else is a tag.
        if not d.is_dir() or (len(d.name) == 32 and all(c in "0123456789abcdef" for c in d.name)):
            continue
        if (d / "manifest.json").exists():
            found.append(d.name)
    return found


def _synthesise_run_summary(series: dict, manifest: dict) -> dict:
    """
    A run_summary.json from what the finished run recorded.

    The result dict that `_ensemble_summary` / `_grid_summary` would normally
    read is gone, so this reconstructs only what was actually persisted. Marked
    `source: "backfilled"` so nothing reads these as freshly computed —
    an ensemble block that silently lacked its q_peak band would be worse than
    an absent one.
    """
    info = manifest.get("simulation_info") or {}
    balance = series.get("volume_balance") or {}
    return {
        "source": "backfilled",
        "note": (
            "Registered from artifacts on disk by "
            "scripts/register_script_run.py. The solver result was not "
            "retained, so fields normally derived from it are absent rather "
            "than recomputed."
        ),
        "ensemble": None,
        "grid": {
            "resolution_m": info.get("grid_resolution_m")
            or series.get("target_resolution_m"),
        },
        "solver_params": {
            "ensemble_size": series.get("ensemble_size"),
            "solver_duration_s": series.get("solver_duration_s"),
            "target_resolution": series.get("target_resolution_m"),
            "domain_margins_km": series.get("margins_km"),
            "scenario_type": "dam_break",
        },
        "volume_balance": balance,
        "verdict": series.get("verdict"),
        "dem": {"dem_used": None, "dem_update": None},
    }


def _gauge_rows(series: dict, dam_id: str):
    """
    Gauge rows from the run's recorded arrival times joined to the preset.

    `distance_km` must be non-null or `GET /runs/{id}/result` raises a
    ValidationError and 500s, and the drainage summary records arrival times by
    gauge NAME only — the distances live in the preset.
    """
    from jalraksha.presets import get_gauges

    # get_gauges returns GaugePoint DATACLASSES, not dicts — attribute access,
    # not subscripting.
    by_name = {g.name: g for g in (get_gauges(dam_id) or ())}
    rows = []
    for name, g in (series.get("arrival_times") or {}).items():
        preset = by_name.get(name)
        distance = g.get("distance_km") or getattr(preset, "distance_km", None)
        if distance is None:
            print(f"  ! skipping gauge {name!r}: no distance_km in the summary "
                  f"or the {dam_id} preset, and a null would 500 the result "
                  f"endpoint")
            continue
        rows.append({
            "gauge_name": name,
            "distance_km": distance,
            "arrival_time_s": g.get("mean") or g.get("median"),
            "arrival_p05_s": g.get("p05"),
            "arrival_p95_s": g.get("p95"),
            "max_depth_m": g.get("peak_depth_m"),
            "note": g.get("note"),
            "par_estimate": None,
        })
    return rows


def register(tag: str, dam_id: str, name: str, solver: str = "swe") -> int:
    from jalraksha_service import db
    from jalraksha_service.config import settings

    kf_src = REPO_ROOT / "data" / "keyframes" / tag
    ex_src = REPO_ROOT / "data" / "exports" / tag
    manifest_path = kf_src / "manifest.json"

    if not manifest_path.exists():
        print(f"No keyframe manifest at {manifest_path}. Without it the run "
              f"would list in the picker but never play back, so this refuses "
              f"rather than registering something unplayable.")
        return 1

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    n_frames = len(manifest.get("keyframes") or [])
    if n_frames == 0:
        print(f"{manifest_path} has no keyframes. Refusing for the same reason.")
        return 1

    series_path = kf_src / "hazard_series.json"
    series = json.loads(series_path.read_text(encoding="utf-8")) if series_path.exists() else {}

    # Computed FIRST, before anything is created or moved. This failed once
    # after the directories had already been renamed, leaving a half-registered
    # run with no source directory to retry from. Nothing here has side effects,
    # so a failure at this point costs nothing.
    gauges = _gauge_rows(series, dam_id)

    db.init_db()
    run_id = db.create_run(
        dam_id,
        {
            "name": name,
            "dam_id": dam_id,
            "scenario_type": "dam_break",
            "_solver_params": {
                "ensemble_size": series.get("ensemble_size"),
                "solver_duration_s": series.get("solver_duration_s"),
                "target_resolution": series.get("target_resolution_m"),
                "domain_margins_km": series.get("margins_km"),
            },
            "_registered_from": tag,
        },
        solver,
    )
    print(f"  run_id {run_id}")

    kf_dst = settings.DATA_DIR / "keyframes" / run_id
    ex_dst = settings.DATA_DIR / "exports" / run_id
    for dst in (kf_dst, ex_dst):
        if dst.exists():
            print(f"  ! {dst} already exists — refusing to merge into it")
            return 1

    shutil.move(str(kf_src), str(kf_dst))
    print(f"  moved keyframes -> {kf_dst} ({n_frames} frames)")
    if ex_src.exists():
        shutil.move(str(ex_src), str(ex_dst))
        print(f"  moved exports   -> {ex_dst}")
    else:
        ex_dst.mkdir(parents=True, exist_ok=True)

    summary = _synthesise_run_summary(series, manifest)
    (ex_dst / "run_summary.json").write_text(
        json.dumps(summary, indent=2, default=str), encoding="utf-8"
    )

    exports = [{"kind": "keyframe_manifest",
                "path_or_url": str(kf_dst / "manifest.json")}]
    if (kf_dst / "hazard_series.json").exists():
        exports.append({"kind": "hazard_series",
                        "path_or_url": str(kf_dst / "hazard_series.json")})
    for f in sorted(ex_dst.iterdir()):
        # Shapefile sidecars (.shp/.dbf/.shx/.prj/.cpg) are covered by the .zip
        # the pipeline already produces; listing each individually would bury
        # the Downloads panel in fragments that are useless on their own.
        if f.is_file() and f.suffix.lower() not in (".shp", ".dbf", ".shx", ".prj", ".cpg"):
            exports.append({"kind": _export_kind(f), "path_or_url": str(f)})

    from jalraksha_service.tasks import _existing_exports

    exports = _existing_exports(run_id, exports)
    db.insert_exports(run_id, exports)

    db.insert_gauge_results(run_id, gauges)

    # LAST. "done" is exactly what the picker filters on, so flipping it before
    # the export rows exist would briefly list a complete run with nothing in it.
    db.update_run_status(run_id, "done", 100.0, phase="Complete")

    print(f"  {len(exports)} export rows, {len(gauges)} gauge rows")
    print(f"  registered — load it in the dashboard picker as {name!r}")
    return 0


def complete(run_id: str, dam_id: str) -> int:
    """
    Finish a run whose directories were already moved but which never reached
    "done" — the state a failure between the move and the final status leaves.

    Registration is deliberately not atomic across a filesystem move and a set
    of database writes, so this is the repair path rather than a reason to
    pretend it is.
    """
    from jalraksha_service import db
    from jalraksha_service.config import settings
    from jalraksha_service.tasks import _existing_exports

    run = db.get_run(run_id)
    if run is None:
        print(f"No run {run_id}.")
        return 1
    if run.get("status") == "done":
        print(f"{run_id} is already done — nothing to repair.")
        return 0

    kf_dir = settings.DATA_DIR / "keyframes" / run_id
    ex_dir = settings.DATA_DIR / "exports" / run_id
    if not (kf_dir / "manifest.json").exists():
        print(f"No manifest at {kf_dir} — this run has no artifacts to finish.")
        return 1

    series_path = kf_dir / "hazard_series.json"
    series = json.loads(series_path.read_text(encoding="utf-8")) if series_path.exists() else {}

    gauges = _gauge_rows(series, dam_id)
    if gauges:
        db.insert_gauge_results(run_id, gauges)

    if not db.get_exports(run_id):
        exports = [{"kind": "keyframe_manifest",
                    "path_or_url": str(kf_dir / "manifest.json")}]
        for f in sorted(ex_dir.iterdir()) if ex_dir.exists() else []:
            if f.is_file() and f.suffix.lower() not in (".shp", ".dbf", ".shx", ".prj", ".cpg"):
                exports.append({"kind": _export_kind(f), "path_or_url": str(f)})
        db.insert_exports(run_id, _existing_exports(run_id, exports))

    db.update_run_status(run_id, "done", 100.0, phase="Complete")
    print(f"  completed {run_id}: {len(db.get_exports(run_id))} exports, "
          f"{len(gauges)} gauge rows")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--list", action="store_true",
                        help="Show tag-named runs on disk that are not registered.")
    parser.add_argument("--tag", help="Directory name under data/keyframes.")
    parser.add_argument("--dam-id", default="khadakwasla")
    parser.add_argument("--name", help="Label shown in the run picker. Make it "
                                       "say what the run IS.")
    parser.add_argument("--solver", default="swe")
    parser.add_argument("--complete", metavar="RUN_ID",
                        help="Finish a run whose directories were already moved "
                             "but which never reached \"done\".")
    args = parser.parse_args()

    _bootstrap()

    if args.complete:
        return complete(args.complete, args.dam_id)

    if args.list or not args.tag:
        found = _find_tagged_runs()
        if not found:
            print("No unregistered tag-named runs under data/keyframes.")
        else:
            print("Unregistered runs on disk:")
            for t in found:
                print(f"  {t}")
            print("\nRegister one with:\n"
                  "  python scripts/register_script_run.py --tag <tag> "
                  "--name \"...\"")
        return 0

    return register(args.tag, args.dam_id,
                    args.name or args.tag.replace("_", " "), args.solver)


if __name__ == "__main__":
    raise SystemExit(main())
