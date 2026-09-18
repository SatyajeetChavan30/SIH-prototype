"""
Data packs: move completed runs (and the cached inputs they need) between installs.

WHY THIS EXISTS
---------------
The Windows desktop app ships NO data. A fresh install has an empty
``%LOCALAPPDATA%\\JalRaksha\\data``, so the offline demo path — the run picker
loading a finished run instantly — has nothing to load. A data pack is how a
finished run gets there: exported once on a machine that has it, imported on any
other, with no network.

FORMAT (``.jrpack``, a zip)
---------------------------
  manifest.json   pack_format, name, created_at, source git SHA, jalraksha
                  version, and one entry per file: DATA_DIR-relative path,
                  size, sha256, and its licence / attribution
  db.json         runs, gauge_results and exports rows for every packed run,
                  with each export path rewritten DATA_DIR-relative
  files/<rel>     the files themselves, at their DATA_DIR-relative paths

WHAT IMPORT GUARANTEES
----------------------
  * Every check runs BEFORE anything is written: manifest shape, every sha256,
    every path. A pack that fails any of them changes nothing.
  * No path can land outside DATA_DIR (absolute paths, drive letters and ``..``
    are refused — the zip-slip class of bug).
  * Nothing is overwritten. A file already present with the same sha256 is
    skipped; one present with DIFFERENT content aborts the import, because the
    run that referenced it would silently display someone else's data. A run id
    already in the database is skipped, never replaced.
  * A run whose parameters say ``is_synthetic`` is refused unless the manifest
    declares it synthetic too. A fabricated run that arrives looking like a
    result is the failure scripts/make_synthetic_demo_run.py's triple labelling
    exists to prevent, and a pack must not become the way around it.

There is deliberately no HTTP endpoint for any of this. Import writes files and
database rows from an arbitrary local path; exposing that on the API would let
any page in any browser on the machine trigger it. It runs as a CLI — from a
checkout (``python -m jalraksha_service.data_packs``) or from the desktop app's
File menu, which calls the frozen backend's ``pack`` subcommand.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Dict, Iterable, List, Optional, Tuple

PACK_FORMAT = 1
PACK_SUFFIX = ".jrpack"

#: Licence text attached to files a run produced. The products are JalRaksha's
#: own output; the terrain under them is Copernicus GLO-30, which is approved
#: for redistribution with attribution.
RUN_OUTPUT_LICENCE = (
    "JalRaksha model output (Tier-1 screening; point depths indicative only). "
    "Terrain: Copernicus DEM GLO-30, (c) DLR e.V. 2010-2014 and (c) Airbus 2014-2018, "
    "provided under COPERNICUS by the European Union and ESA."
)

#: Substrings that mark a dataset this project must not redistribute
#: (CLAUDE.md, Licensing). Checked against every packed path, case-insensitive.
FORBIDDEN_SOURCE_MARKERS = ("fabdem", "merit", "osm", "openstreetmap")


class PackError(RuntimeError):
    """A pack that cannot be exported or imported, with the reason."""


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _settings():
    from jalraksha_service.config import settings

    return settings


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_sha() -> str:
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True, timeout=10)
        return out.stdout.strip() if out.returncode == 0 else "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def safe_relative(rel: str) -> PurePosixPath:
    """
    Validate a DATA_DIR-relative path from a pack; raise PackError if unsafe.

    Refuses absolute paths, drive letters, backslash tricks and any ``..``
    component, so an entry can never resolve outside the data directory.
    """
    if not rel or "\\" in rel or ":" in rel:
        raise PackError(f"unsafe path in pack: {rel!r}")
    posix = PurePosixPath(rel)
    if posix.is_absolute() or any(part in ("..", "") for part in posix.parts):
        raise PackError(f"unsafe path in pack: {rel!r}")
    return posix


def _resolve_stored_path(path_str: str) -> Path:
    """
    An export path as the database stores it, made absolute.

    Stored paths are relative to the API's working directory (``data\\exports\\..``
    in a checkout), or absolute. Mixed separators occur in real rows.
    """
    path = Path(path_str.replace("\\", "/"))
    return path if path.is_absolute() else (Path.cwd() / path)


def _relative_to_data_dir(path: Path, data_dir: Path) -> Optional[str]:
    try:
        return path.resolve().relative_to(data_dir.resolve()).as_posix()
    except ValueError:
        return None


def _check_licensable(rel: str) -> None:
    lowered = rel.lower()
    for marker in FORBIDDEN_SOURCE_MARKERS:
        if marker in lowered:
            raise PackError(
                f"{rel!r} looks like a {marker.upper()}-derived file, which this "
                f"project must not redistribute (CLAUDE.md, Licensing)."
            )


# --------------------------------------------------------------------------- #
# Export
# --------------------------------------------------------------------------- #

def _run_rows(run_id: str) -> Tuple[Dict[str, Any], List[Dict[str, Any]], List[Dict[str, Any]]]:
    from jalraksha_service import db

    run = db.get_run(run_id)
    if run is None:
        raise PackError(f"run {run_id} is not in the database")
    if run["status"] != "done":
        raise PackError(f"run {run_id} has status {run['status']!r}; only 'done' runs can be packed")
    return run, db.get_gauge_results(run_id), db.get_exports(run_id)


def _run_files(run_id: str, exports: List[Dict[str, Any]], data_dir: Path) -> List[Path]:
    """
    Every file a run needs to display, as absolute paths under DATA_DIR.

    The export rows alone are not enough: a keyframe manifest's PNGs are its
    SIBLINGS (the frontend resolves each png_url against the manifest URL), and
    an .xdmf reads a .h5 beside it. So the run's own directories are packed
    whole, plus every file the rows name.
    """
    files: Dict[str, Path] = {}

    def add(path: Path) -> None:
        if path.is_file():
            files[str(path.resolve())] = path.resolve()

    for directory in (data_dir / "exports" / run_id, data_dir / "keyframes" / run_id):
        if directory.is_dir():
            for path in directory.rglob("*"):
                add(path)
    simulation = data_dir / "simulation"
    if simulation.is_dir():
        for path in simulation.glob(f"{run_id}.*"):
            add(path)

    for export in exports:
        target = _resolve_stored_path(export["path_or_url"])
        if export["path_or_url"].startswith(("http://", "https://")):
            continue
        if _relative_to_data_dir(target, data_dir) is None:
            raise PackError(
                f"run {run_id} export {export['kind']!r} lives outside the data "
                f"directory ({target}); it cannot be packed portably"
            )
        if not target.is_file():
            raise PackError(f"run {run_id} export {export['kind']!r} is missing on disk: {target}")
        add(target)
        if export["kind"] == "keyframe_manifest":
            for sibling in target.parent.iterdir():
                add(sibling)
    return sorted(files.values())


def export_pack(run_ids: Iterable[str], out_path: Path, name: str,
                includes: Iterable[Tuple[Path, str]] = (),
                allow_synthetic: bool = False) -> Dict[str, Any]:
    """
    Write a .jrpack holding the given runs and any extra DATA_DIR files.

    Args:
        run_ids: completed runs to pack.
        out_path: destination file.
        name: human-readable pack name, shown after import.
        includes: (path, licence) pairs for cached inputs — e.g. the staged DEM a
            fresh run at the same site needs offline. Each must lie under
            DATA_DIR, and a directory is packed recursively.
        allow_synthetic: pack runs flagged ``is_synthetic``. They are then
            declared synthetic in the manifest, which import requires.
    """
    from jalraksha import __version__

    data_dir = _settings().DATA_DIR
    entries: Dict[str, Dict[str, Any]] = {}
    runs_json, gauges_json, exports_json = [], [], []
    synthetic_runs: List[str] = []

    def register(path: Path, licence: str) -> None:
        rel = _relative_to_data_dir(path, data_dir)
        if rel is None:
            raise PackError(f"{path} is not under the data directory {data_dir.resolve()}")
        _check_licensable(rel)
        entries.setdefault(rel, {"path": rel, "source": path, "licence": licence})

    for run_id in run_ids:
        run, gauges, exports = _run_rows(run_id)
        params = dict(run["params"] or {})
        # Machine-local bookkeeping: a pid means nothing on another machine and
        # mark_stale_runs_failed would read it as a live claim.
        params.pop("worker_pid", None)
        if params.get("is_synthetic"):
            if not allow_synthetic:
                raise PackError(
                    f"run {run_id} is SYNTHETIC (params is_synthetic=true). Pass "
                    f"--allow-synthetic to pack it; it will be declared synthetic "
                    f"in the manifest."
                )
            synthetic_runs.append(run_id)
        for path in _run_files(run_id, exports, data_dir):
            register(path, RUN_OUTPUT_LICENCE)
        runs_json.append({
            "run_id": run["run_id"], "dam_id": run["dam_id"], "params": params,
            "status": run["status"], "created_at": run["created_at"],
            "solver": run["solver"], "error": run["error"],
        })
        gauges_json.extend({"run_id": run_id, **g} for g in gauges)
        for export in exports:
            stored = export["path_or_url"]
            if stored.startswith(("http://", "https://")):
                exports_json.append({"run_id": run_id, "kind": export["kind"], "url": stored})
                continue
            rel = _relative_to_data_dir(_resolve_stored_path(stored), data_dir)
            exports_json.append({"run_id": run_id, "kind": export["kind"], "path": rel})

    for path, licence in includes:
        if not licence.strip():
            raise PackError(f"--include {path} needs a licence / attribution")
        path = Path(path)
        if not path.is_absolute():
            path = Path.cwd() / path
        if path.is_dir():
            for child in sorted(path.rglob("*")):
                if child.is_file():
                    register(child, licence)
        elif path.is_file():
            register(path, licence)
        else:
            raise PackError(f"--include {path} does not exist")

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_files = []
    tmp_path = out_path.with_suffix(out_path.suffix + ".partial")
    with zipfile.ZipFile(tmp_path, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as zf:
        for rel in sorted(entries):
            source = entries[rel]["source"]
            zf.write(source, f"files/{rel}")
            manifest_files.append({
                "path": rel, "size": source.stat().st_size,
                "sha256": _sha256_file(source), "licence": entries[rel]["licence"],
            })
        manifest = {
            "pack_format": PACK_FORMAT,
            "name": name,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "source_git_sha": _git_sha(),
            "jalraksha_version": __version__,
            "run_ids": [r["run_id"] for r in runs_json],
            "synthetic_run_ids": synthetic_runs,
            "files": manifest_files,
        }
        zf.writestr("manifest.json", json.dumps(manifest, indent=2))
        zf.writestr("db.json", json.dumps(
            {"runs": runs_json, "gauge_results": gauges_json, "exports": exports_json},
            indent=2))
    # Renamed into place last, so an interrupted export never leaves a file
    # that looks like a complete pack.
    tmp_path.replace(out_path)
    return {"pack": str(out_path), "name": name, "runs": manifest["run_ids"],
            "files": len(manifest_files),
            "bytes": out_path.stat().st_size, "synthetic_run_ids": synthetic_runs}


# --------------------------------------------------------------------------- #
# Import
# --------------------------------------------------------------------------- #

def _read_json(zf: zipfile.ZipFile, member: str) -> Dict[str, Any]:
    try:
        return json.loads(zf.read(member).decode("utf-8"))
    except KeyError as exc:
        raise PackError(f"pack has no {member}") from exc
    except ValueError as exc:
        raise PackError(f"pack {member} is not valid JSON: {exc}") from exc


def _sha256_member(zf: zipfile.ZipFile, member: str) -> str:
    digest = hashlib.sha256()
    with zf.open(member) as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run_exists(cur: Any, run_id: str) -> bool:
    from jalraksha_service import db

    cur.execute(f"SELECT 1 FROM runs WHERE run_id = {db._placeholder(1)}", (run_id,))
    return cur.fetchone() is not None


def import_pack(pack_path: Path) -> Dict[str, Any]:
    """Validate a .jrpack completely, then copy its files and rows in. See module doc."""
    from jalraksha_service import db

    settings = _settings()
    data_dir = settings.DATA_DIR.resolve()
    pack_path = Path(pack_path)
    if not pack_path.is_file():
        raise PackError(f"no such pack: {pack_path}")
    try:
        zf = zipfile.ZipFile(pack_path)
    except zipfile.BadZipFile as exc:
        raise PackError(f"{pack_path} is not a valid pack (not a zip): {exc}") from exc

    with zf:
        manifest = _read_json(zf, "manifest.json")
        tables = _read_json(zf, "db.json")
        if manifest.get("pack_format") != PACK_FORMAT:
            raise PackError(
                f"unsupported pack_format {manifest.get('pack_format')!r}; this build reads {PACK_FORMAT}")

        # ---- Preflight: nothing below writes anything. ----
        members = set(zf.namelist())
        declared = {}
        for entry in manifest.get("files", []):
            rel = safe_relative(str(entry.get("path", "")))
            _check_licensable(str(rel))
            member = f"files/{rel}"
            if member not in members:
                raise PackError(f"manifest lists {rel} but the pack does not contain it")
            if _sha256_member(zf, member) != entry.get("sha256"):
                raise PackError(f"checksum mismatch for {rel}; the pack is corrupt or was modified")
            declared[str(rel)] = entry
        undeclared = [m for m in members
                      if m.startswith("files/") and not m.endswith("/")
                      and m[len("files/"):] not in declared]
        if undeclared:
            raise PackError(f"pack contains files its manifest does not declare: {undeclared[:3]}")

        to_copy, already_present = [], []
        for rel, entry in declared.items():
            target = data_dir.joinpath(*PurePosixPath(rel).parts)
            # Belt and braces after safe_relative: a symlinked directory inside
            # DATA_DIR could still point elsewhere.
            if data_dir not in target.resolve().parents:
                raise PackError(f"unsafe path in pack: {rel!r}")
            if target.exists():
                if _sha256_file(target) == entry["sha256"]:
                    already_present.append(rel)
                    continue
                raise PackError(
                    f"{target} already exists with DIFFERENT content. Import refused "
                    f"rather than overwrite it or show a run over the wrong data."
                )
            to_copy.append((rel, target))

        synthetic_declared = set(manifest.get("synthetic_run_ids") or [])
        runs = tables.get("runs") or []
        for run in runs:
            params = run.get("params") or {}
            if params.get("is_synthetic") and run.get("run_id") not in synthetic_declared:
                raise PackError(
                    f"run {run.get('run_id')} is synthetic but the pack does not "
                    f"declare it so; refusing to import a fabricated run unlabelled."
                )
            if run.get("status") != "done":
                raise PackError(f"run {run.get('run_id')} is not a completed run")
        for export in tables.get("exports") or []:
            if "path" in export and export["path"] not in declared:
                raise PackError(f"export {export.get('kind')} points at an undeclared file {export['path']}")

        # ---- Write files. ----
        for rel, target in to_copy:
            target.parent.mkdir(parents=True, exist_ok=True)
            partial = target.with_name(target.name + ".partial")
            with zf.open(f"files/{rel}") as src, open(partial, "wb") as dst:
                for chunk in iter(lambda: src.read(1 << 20), b""):
                    dst.write(chunk)
            partial.replace(target)

    # ---- Write rows. Runs already present are skipped, never replaced. ----
    db.init_db()
    imported, skipped = [], []
    conn = db._connect()
    try:
        cur = conn.cursor()
        ph = db._placeholder
        for run in runs:
            run_id = run["run_id"]
            if _run_exists(cur, run_id):
                skipped.append(run_id)
                continue
            cur.execute(
                f"INSERT INTO runs (run_id, dam_id, params_json, status, created_at, solver, error) "
                f"VALUES ({ph(7)})",
                (run_id, run.get("dam_id"), json.dumps(run.get("params") or {}),
                 run["status"], run.get("created_at"), run.get("solver"), run.get("error")),
            )
            for g in tables.get("gauge_results") or []:
                if g.get("run_id") != run_id:
                    continue
                cur.execute(
                    f"INSERT INTO gauge_results (run_id, gauge_name, distance_km, arrival_time_s, "
                    f"max_depth_m, par_estimate, arrival_p05_s, arrival_p95_s, note) VALUES ({ph(9)})",
                    (run_id, g.get("gauge_name"), g.get("distance_km"), g.get("arrival_time_s"),
                     g.get("max_depth_m"), g.get("par_estimate"), g.get("arrival_p05_s"),
                     g.get("arrival_p95_s"), g.get("note")),
                )
            for e in tables.get("exports") or []:
                if e.get("run_id") != run_id:
                    continue
                # Absolute under THIS install's data directory, so the row does
                # not depend on the API's working directory the way a checkout's
                # relative rows do.
                stored = e["url"] if "url" in e else str(data_dir.joinpath(*PurePosixPath(e["path"]).parts))
                cur.execute(f"INSERT INTO exports (run_id, kind, path_or_url) VALUES ({ph(3)})",
                            (run_id, e["kind"], stored))
            imported.append(run_id)
        conn.commit()
    finally:
        conn.close()

    return {
        "pack": str(pack_path), "name": manifest.get("name"),
        "imported_runs": imported, "skipped_existing_runs": skipped,
        "files_copied": len(to_copy), "files_already_present": len(already_present),
        "synthetic_run_ids": sorted(synthetic_declared),
        "data_dir": str(data_dir),
    }


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def _parse_include(value: str) -> Tuple[Path, str]:
    path, sep, licence = value.partition("=")
    if not sep or not licence.strip():
        raise argparse.ArgumentTypeError("--include expects PATH=LICENCE")
    return Path(path), licence.strip()


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="jalraksha pack", description="JalRaksha data packs")
    sub = parser.add_subparsers(dest="command", required=True)

    exp = sub.add_parser("export", help="write a .jrpack from completed runs")
    exp.add_argument("--run-id", action="append", required=True, dest="run_ids")
    exp.add_argument("--out", required=True, type=Path)
    exp.add_argument("--name", required=True)
    exp.add_argument("--include", action="append", default=[], type=_parse_include,
                     metavar="PATH=LICENCE", help="extra DATA_DIR file or directory, with its licence")
    exp.add_argument("--allow-synthetic", action="store_true")

    imp = sub.add_parser("import", help="import a .jrpack into this data directory")
    imp.add_argument("pack", type=Path)

    args = parser.parse_args(argv)
    try:
        if args.command == "export":
            result = export_pack(args.run_ids, args.out, args.name, args.include,
                                 allow_synthetic=args.allow_synthetic)
        else:
            result = import_pack(args.pack)
    except PackError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 1
    print(json.dumps({"ok": True, **result}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
