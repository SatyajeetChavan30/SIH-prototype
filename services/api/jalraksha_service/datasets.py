"""
The dataset catalogue: what is actually on this machine, and under what licence.

This is the honest version of a "data centre" screen. Two rules decide
everything here:

1. **A row exists only if the file exists.** Nothing lists an expected dataset
   as loaded. A catalogue that names what a system *would* fetch is a wish
   list, and the one thing an operator needs from this screen is what they can
   work with offline right now.
2. **The licence column is load-bearing.** Copernicus DEM, GHSL, ESA WorldCover
   and Google Open Buildings are approved for redistribution; FABDEM, MERIT and
   OSM are not (CLAUDE.md, Licensing). Any path matching
   ``data_packs.FORBIDDEN_SOURCE_MARKERS`` is flagged rather than quietly
   listed, because these rows are exactly what a data pack would carry.

Superseded products are labelled, not hidden. ``gee/population.py`` writes
``ghsl_manifest_v2.json``; a directory that still carries the v1 manifest holds
a raster from before the aggregation fix, where one domain read 741,659 people
against v2's 18,646,534 on the same ground.

HASHING RUNS IN A BACKGROUND THREAD. ``data/dem`` alone is 541 MB with single
files at 70-82 MB, and ``data/dem_wide`` adds 2 GB; hashing that inside the
request would hold a worker for a minute while a run is solving. Rows come back
immediately with size and modification time, sha256 arrives on a later call,
and the cache is keyed by (path, size, mtime) so nothing is rehashed twice.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from jalraksha_service.config import settings
from jalraksha_service.data_packs import FORBIDDEN_SOURCE_MARKERS, _sha256_file

#: Where the sha256 cache lives. Same idea as validation_cache.json: an
#: expensive answer computed once and kept beside the data it describes.
CACHE_PATH_NAME = "dataset_catalog_cache.json"

#: Licence and agency per product family. Only families this repo actually
#: writes appear here; an unknown file is labelled unknown rather than guessed.
LICENCES: Dict[str, Dict[str, str]] = {
    "dem_copernicus": {
        "agency": "ESA / Copernicus (DLR, Airbus)",
        "licence": "Copernicus free, full and open — approved for redistribution",
        "product": "Copernicus DEM GLO-30",
    },
    "dem_updated": {
        "agency": "ESA / Copernicus, modified by this project",
        "licence": "Copernicus terms apply to the source; the modification is ours",
        "product": "Observation-conditioned DEM — NOT A SURVEY",
    },
    "ghsl": {
        "agency": "European Commission JRC",
        "licence": "CC BY 4.0 — approved",
        "product": "GHSL population / built-up surface",
    },
    "worldcover": {
        "agency": "ESA WorldCover consortium",
        "licence": "CC BY 4.0 — approved",
        "product": "ESA WorldCover v200 land cover",
    },
    "sentinel1": {
        "agency": "ESA / Copernicus",
        "licence": "Copernicus free, full and open — approved",
        "product": "Sentinel-1 SAR derived water mask",
    },
    "engine": {
        "agency": "external program",
        "licence": "not redistributed by this project",
        "product": "solver engine on this machine",
    },
    "unknown": {
        "agency": "unknown",
        "licence": "unknown — check before redistributing",
        "product": "unclassified file",
    },
}

_HASH_LOCK = threading.Lock()
_HASH_RUNNING = {"active": False}

#: The engine probes glob Program Files and stat a DualSPHysics tree, which
#: measured at about a second - most of this endpoint's cold cost. Where an
#: engine lives does not change while the process runs, so it is probed once,
#: the same stance solver_backend_info takes for the GPU probe.
_ENGINE_LOCK = threading.Lock()
_ENGINE_ROWS: List[Dict[str, Any]] = []


# --------------------------------------------------------------------------- #
# The sha256 cache
# --------------------------------------------------------------------------- #

def _cache_path() -> Path:
    return settings.DATA_DIR / CACHE_PATH_NAME


def _cache_key(path: Path) -> Optional[str]:
    try:
        stat = path.stat()
    except OSError:
        return None
    return f"{path.as_posix()}|{stat.st_size}|{int(stat.st_mtime)}"


def _load_hashes() -> Dict[str, str]:
    try:
        return json.loads(_cache_path().read_text(encoding="utf-8"))
    except Exception:
        return {}


def _store_hashes(hashes: Dict[str, str]) -> None:
    try:
        _cache_path().parent.mkdir(parents=True, exist_ok=True)
        _cache_path().write_text(json.dumps(hashes, indent=2), encoding="utf-8")
    except Exception as exc:  # a catalogue must not fail because a cache cannot be written
        print(f"[datasets] could not write the hash cache: {type(exc).__name__}: {exc}")


#: Checkpoint the cache this often. Measured: a pass over this machine's 2.8 GB
#: takes long enough that a process exiting first (a CLI, a test, a restart)
#: threw away every hash it had just computed.
_CHECKPOINT_EVERY = 8


def _hash_missing(paths: List[Path]) -> None:
    """Hash everything not already cached. Runs off the request thread."""
    try:
        hashes = _load_hashes()
        since_write = 0
        for path in paths:
            key = _cache_key(path)
            if not key or key in hashes:
                continue
            try:
                hashes[key] = _sha256_file(path)
                since_write += 1
            except Exception as exc:
                print(f"[datasets] could not hash {path}: {type(exc).__name__}: {exc}")
            if since_write >= _CHECKPOINT_EVERY:
                _store_hashes(hashes)
                since_write = 0
        if since_write:
            _store_hashes(hashes)
    finally:
        with _HASH_LOCK:
            _HASH_RUNNING["active"] = False


# --------------------------------------------------------------------------- #
# Rows
# --------------------------------------------------------------------------- #

def _relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(settings.DATA_DIR.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _forbidden(rel: str) -> Optional[str]:
    lowered = rel.lower()
    hit = next((marker for marker in FORBIDDEN_SOURCE_MARKERS if marker in lowered), None)
    return (f"Path names {hit!r}, which this project must not redistribute "
            f"(CLAUDE.md, Licensing).") if hit else None


def _file_row(path: Path, family: str, *, name: str, note: Optional[str] = None,
              fetched_at: Optional[str] = None, extra: Optional[Dict[str, Any]] = None
              ) -> Dict[str, Any]:
    stat = path.stat()
    rel = _relative(path)
    licence = LICENCES.get(family, LICENCES["unknown"])
    row = {
        "name": name,
        "family": family,
        "product": licence["product"],
        "agency": licence["agency"],
        "licence": licence["licence"],
        "path": rel,
        "format": path.suffix.lstrip(".").lower() or "file",
        "bytes": stat.st_size,
        "modified_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
        "fetched_at": fetched_at,
        "sha256": None,
        "note": note,
        "redistribution": "forbidden" if _forbidden(rel) else "approved",
        "redistribution_reason": _forbidden(rel),
        "superseded": False,
    }
    if extra:
        row.update(extra)
    return row


def _dem_family(path: Path) -> Tuple[str, str, Optional[str]]:
    name = path.name
    if "updated" in path.parts:
        return "dem_updated", name, (
            "Copernicus GLO-30 with a barrier burned in. Not photogrammetry, not "
            "InSAR, not a survey; every pixel outside the barrier footprint is "
            "bit-identical to the source.")
    if name.startswith("Copernicus_DSM"):
        return "dem_copernicus", name, (
            "A cached WINDOW of this tile, not the whole tile: it covers whatever "
            "domain first asked for it.")
    if name.startswith("mosaic_"):
        return "dem_copernicus", name, "Untrimmed multi-tile merge."
    if name.startswith("dem_") and name.endswith("_clipped.tif"):
        return "dem_copernicus", name, "Clipped domain product, nodata edges removed."
    return "dem_copernicus", name, None


def _dem_rows() -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for base in (settings.DATA_DIR / "dem", settings.DATA_DIR / "dem_wide"):
        if not base.exists():
            continue
        for path in sorted(base.rglob("*.tif")):
            family, name, note = _dem_family(path)
            if base.name == "dem_wide":
                note = ((note + " ") if note else "") + (
                    "Under data/dem_wide, which no live code path reads.")
            sidecar = path.with_suffix(".provenance.json")
            fetched_at = None
            if sidecar.exists():
                try:
                    provenance = json.loads(sidecar.read_text(encoding="utf-8"))
                    fetched_at = provenance.get("generated_at") or provenance.get("created_at")
                except Exception:
                    fetched_at = None
            rows.append(_file_row(path, family, name=name, note=note, fetched_at=fetched_at))
    return rows


def _manifest_info(directory: Path) -> Tuple[Optional[Dict[str, Any]], bool]:
    """(manifest, superseded). A v1 GHSL manifest is superseded by construction."""
    for manifest_name in ("ghsl_manifest_v2.json", "ghs_built_manifest.json",
                          "worldcover_cropland_manifest.json", "manifest.json"):
        candidate = directory / manifest_name
        if candidate.exists():
            try:
                return json.loads(candidate.read_text(encoding="utf-8")), False
            except Exception:
                return None, False
    legacy = directory / "ghsl_manifest.json"
    if legacy.exists():
        try:
            return json.loads(legacy.read_text(encoding="utf-8")), True
        except Exception:
            return None, True
    return None, False


def _gee_rows() -> List[Dict[str, Any]]:
    """
    Earth Engine caches, read through their own manifests.

    A raster whose directory still has only the v1 GHSL manifest predates the
    aggregation fix and is labelled superseded: every population figure it
    produced is low by the square of the ratio between the solver grid and
    100 m (verification row 37).
    """
    base = settings.DATA_DIR / "gee"
    if not base.exists():
        return []
    families = {"ghsl": "ghsl", "ghs_built": "ghsl", "worldcover_grid": "worldcover",
                "sar": "sentinel1", "blockage": "sentinel1",
                "blockage_experiment": "sentinel1"}
    rows: List[Dict[str, Any]] = []
    for product_dir in sorted(p for p in base.iterdir() if p.is_dir()):
        family = families.get(product_dir.name, "unknown")
        for domain_dir in sorted(p for p in product_dir.rglob("*") if p.is_dir()):
            manifest, legacy_only = _manifest_info(domain_dir)
            v1_present = (domain_dir / "ghsl_manifest.json").exists()
            v2_present = (domain_dir / "ghsl_manifest_v2.json").exists()
            for path in sorted(domain_dir.glob("*.tif")):
                superseded = legacy_only or (
                    v1_present and v2_present and "areacorrected" not in path.name
                    and product_dir.name == "ghsl")
                note = None
                if superseded:
                    note = ("Written before the 2026-09-06 Earth Engine aggregation fix; "
                            "its population totals are low by (grid / 100 m)^2. "
                            "Verification log row 37.")
                row = _file_row(
                    path, family, name=f"{product_dir.name} / {domain_dir.name} / {path.name}",
                    note=note,
                    fetched_at=(manifest or {}).get("fetched_at"),
                    extra={"collection": (manifest or {}).get("collection"),
                           "aggregation": (manifest or {}).get("aggregation")})
                row["superseded"] = bool(superseded)
                rows.append(row)
    return rows


def _engine_rows() -> List[Dict[str, Any]]:
    """
    The external engines, reported as present or absent WITH the path checked.

    Neither is bundled or redistributed: Delft3D FM is an installed Deltares
    product and DualSPHysics is LGPL and lives outside the repo. "Absent" here
    is a fact about this machine, not a defect.
    """
    rows: List[Dict[str, Any]] = []

    try:
        from jalraksha.delft3d.runner import resolve_dflowfm

        dflowfm = resolve_dflowfm()
    except Exception as exc:
        dflowfm, note = None, f"probe failed: {type(exc).__name__}: {exc}"
    else:
        note = None
    rows.append({
        "name": "Delft3D FM kernel (dflowfm-cli)",
        "family": "engine", "product": "Deltares D-Flow FM",
        "agency": LICENCES["engine"]["agency"], "licence": LICENCES["engine"]["licence"],
        "path": dflowfm, "format": "exe", "bytes": None, "modified_at": None,
        "fetched_at": None, "sha256": None, "superseded": False,
        "present": bool(dflowfm),
        "note": note or ("Installed on this machine; the cross-check names it only "
                         "when a run actually used it."
                         if dflowfm else "Not found on this machine."),
        "redistribution": "not redistributed", "redistribution_reason": None,
    })

    try:
        from jalraksha.sph.dualsphysics_runner import is_dualsphysics_available

        available, reason = is_dualsphysics_available()
    except Exception as exc:
        available, reason = False, f"probe failed: {type(exc).__name__}: {exc}"
    rows.append({
        "name": "DualSPHysics v5.4",
        "family": "engine", "product": "DualSPHysics near-field SPH",
        "agency": "DualSPHysics project", "licence": "LGPL-2.1 — external, never bundled",
        "path": None, "format": "exe", "bytes": None, "modified_at": None,
        "fetched_at": None, "sha256": None, "superseded": False,
        "present": bool(available), "note": reason,
        "redistribution": "not redistributed", "redistribution_reason": None,
    })
    return rows


def engine_rows() -> List[Dict[str, Any]]:
    """The engine rows, probed once per process."""
    with _ENGINE_LOCK:
        if not _ENGINE_ROWS:
            _ENGINE_ROWS.extend(_engine_rows())
        return [dict(row) for row in _ENGINE_ROWS]


def dataset_rows(start_hashing: bool = True) -> Dict[str, Any]:
    """
    Everything on this machine, with hashes where they have been computed.

    Returns immediately. sha256 values appear on a later call once the
    background pass finishes; ``hashing.status`` says which state this is.
    """
    rows = _dem_rows() + _gee_rows() + engine_rows()
    hashes = _load_hashes()
    to_hash: List[Path] = []
    for row in rows:
        if not row.get("path") or row.get("bytes") is None:
            continue
        path = settings.DATA_DIR / row["path"]
        if not path.exists():
            path = Path(row["path"])
        key = _cache_key(path)
        if key and key in hashes:
            row["sha256"] = hashes[key]
        elif key:
            to_hash.append(path)

    started = False
    if to_hash and start_hashing:
        with _HASH_LOCK:
            if not _HASH_RUNNING["active"]:
                _HASH_RUNNING["active"] = True
                started = True
                threading.Thread(target=_hash_missing, args=(to_hash,), daemon=True).start()

    total_bytes = sum(row["bytes"] or 0 for row in rows)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "data_dir": str(settings.DATA_DIR),
        "rows": rows,
        "total_bytes": total_bytes,
        "hashing": {
            "status": ("running" if (started or _HASH_RUNNING["active"])
                       else ("done" if not to_hash else "pending")),
            "pending": len(to_hash),
            "note": ("sha256 is computed off the request thread; "
                     "re-request to pick up the finished values."),
        },
    }
