"""
Data packs move finished runs between installs, and must never corrupt either.

A desktop install ships with no data, so a pack is the only way a completed run
reaches it. These tests pin the round trip (export on one data directory, import
into another, and the result endpoint still resolves every file) and every
refusal import promises: unsafe paths, checksum mismatches, conflicting files,
unlabelled synthetic runs. Also pins stopping in-flight runs on desktop exit.

Nothing here solves or touches the real data directory.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
import zipfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "services" / "api"))

pytest.importorskip("jalraksha_service", reason="API service not importable")

from jalraksha_service import config, data_packs, db, run_control  # noqa: E402


def _use_data_dir(monkeypatch, data_dir: Path) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(config.settings, "DATA_DIR", data_dir)
    monkeypatch.setattr(config.settings, "DATABASE_URL", f"sqlite:///{data_dir}/jalraksha.db")
    db.init_db()


def _make_done_run(data_dir: Path, *, synthetic: bool = False) -> str:
    """A completed run laid out the way tasks.py writes one."""
    params = {"name": "Khadakwasla Dam", "worker_pid": 4242}
    if synthetic:
        params["is_synthetic"] = True
    run_id = db.create_run("khadakwasla", params, "swe")
    exports = data_dir / "exports" / run_id
    keyframes = data_dir / "keyframes" / run_id
    exports.mkdir(parents=True)
    keyframes.mkdir(parents=True)
    (exports / "run_summary.json").write_text(json.dumps({"run_id": run_id}))
    (exports / "h_max_median_cog.tif").write_bytes(b"\x00tif" * 100)
    (keyframes / "manifest.json").write_text(json.dumps({"keyframes": [{"png_url": "kf_000.png"}]}))
    (keyframes / "kf_000.png").write_bytes(b"\x89PNG" + b"\x01" * 64)
    db.insert_exports(run_id, [
        {"kind": "run_summary", "path_or_url": str(exports / "run_summary.json")},
        {"kind": "geotiff", "path_or_url": str(exports / "h_max_median_cog.tif")},
        {"kind": "keyframe_manifest", "path_or_url": str(keyframes / "manifest.json")},
    ])
    db.insert_gauge_results(run_id, [{"gauge_name": "Pune", "distance_km": 12.0,
                                      "arrival_time_s": 3600.0, "max_depth_m": 2.5,
                                      "boundary_clearance_km": 3.0, "near_boundary": True}])
    db.update_run_status(run_id, "done", 100.0, phase="Done")
    return run_id


@pytest.fixture
def source(tmp_path, monkeypatch):
    data_dir = tmp_path / "source" / "data"
    _use_data_dir(monkeypatch, data_dir)
    return data_dir


def _export(tmp_path, run_ids, **kwargs) -> Path:
    out = tmp_path / "packs" / "test.jrpack"
    data_packs.export_pack(run_ids, out, "Test pack", **kwargs)
    return out


def test_round_trip_preserves_the_run(tmp_path, monkeypatch, source):
    run_id = _make_done_run(source)
    dem = source / "dem" / "dem_18.44_73.77_clipped.tif"
    dem.parent.mkdir()
    dem.write_bytes(b"dem" * 1000)
    pack = _export(tmp_path, [run_id], includes=[(dem, "Copernicus DEM GLO-30")])

    manifest = json.loads(zipfile.ZipFile(pack).read("manifest.json"))
    assert {f["path"] for f in manifest["files"]} == {
        f"exports/{run_id}/run_summary.json", f"exports/{run_id}/h_max_median_cog.tif",
        f"keyframes/{run_id}/manifest.json", f"keyframes/{run_id}/kf_000.png",
        "dem/dem_18.44_73.77_clipped.tif",
    }
    assert all(f["licence"] for f in manifest["files"])

    target = tmp_path / "target" / "data"
    _use_data_dir(monkeypatch, target)
    result = data_packs.import_pack(pack)
    assert result["imported_runs"] == [run_id]
    assert result["files_copied"] == 5

    run = db.get_run(run_id)
    assert run["status"] == "done"
    # A pid is machine-local; carried over it would read as a live claim.
    assert "worker_pid" not in run["params"]
    gauge = db.get_gauge_results(run_id)[0]
    assert gauge["gauge_name"] == "Pune"
    # The boundary flag is an honesty label; a pack must not drop it.
    assert gauge["near_boundary"] is True
    assert gauge["boundary_clearance_km"] == 3.0
    for export in db.get_exports(run_id):
        path = Path(export["path_or_url"])
        assert path.is_absolute() and path.is_file()
        assert target.resolve() in path.resolve().parents
    assert (target / "dem" / "dem_18.44_73.77_clipped.tif").read_bytes() == b"dem" * 1000


def test_reimport_skips_and_never_overwrites(tmp_path, monkeypatch, source):
    run_id = _make_done_run(source)
    pack = _export(tmp_path, [run_id])
    _use_data_dir(monkeypatch, tmp_path / "target" / "data")
    data_packs.import_pack(pack)

    again = data_packs.import_pack(pack)
    assert again["imported_runs"] == []
    assert again["skipped_existing_runs"] == [run_id]
    assert again["files_copied"] == 0
    assert len(db.get_exports(run_id)) == 3


def test_conflicting_file_aborts_before_any_write(tmp_path, monkeypatch, source):
    run_id = _make_done_run(source)
    pack = _export(tmp_path, [run_id])
    target = tmp_path / "target" / "data"
    _use_data_dir(monkeypatch, target)
    clash = target / "keyframes" / run_id / "kf_000.png"
    clash.parent.mkdir(parents=True)
    clash.write_bytes(b"somebody else's frame")

    with pytest.raises(data_packs.PackError, match="DIFFERENT content"):
        data_packs.import_pack(pack)
    assert clash.read_bytes() == b"somebody else's frame"
    assert db.get_run(run_id) is None
    assert not (target / "exports" / run_id).exists()


def _rewrite(pack: Path, out: Path, mutate) -> Path:
    with zipfile.ZipFile(pack) as src:
        members = {name: src.read(name) for name in src.namelist()}
    mutate(members)
    with zipfile.ZipFile(out, "w") as dst:
        for name, data in members.items():
            dst.writestr(name, data)
    return out


def test_checksum_mismatch_is_refused(tmp_path, monkeypatch, source):
    run_id = _make_done_run(source)
    pack = _export(tmp_path, [run_id])

    def tamper(members):
        members[f"files/keyframes/{run_id}/kf_000.png"] = b"tampered"

    bad = _rewrite(pack, tmp_path / "bad.jrpack", tamper)
    _use_data_dir(monkeypatch, tmp_path / "target" / "data")
    with pytest.raises(data_packs.PackError, match="checksum mismatch"):
        data_packs.import_pack(bad)
    assert db.get_run(run_id) is None


@pytest.mark.parametrize("evil", ["../outside.txt", "/etc/passwd", "C:/Windows/x.dll",
                                  "dem\\..\\..\\x", "exports/../../x"])
def test_zip_slip_paths_are_refused(tmp_path, monkeypatch, source, evil):
    run_id = _make_done_run(source)
    pack = _export(tmp_path, [run_id])

    def inject(members):
        manifest = json.loads(members["manifest.json"])
        manifest["files"].append({"path": evil, "size": 1, "sha256": "0", "licence": "x"})
        members["manifest.json"] = json.dumps(manifest).encode()
        members[f"files/{evil}"] = b"x"

    bad = _rewrite(pack, tmp_path / "evil.jrpack", inject)
    target = tmp_path / "target" / "data"
    _use_data_dir(monkeypatch, target)
    with pytest.raises(data_packs.PackError, match="unsafe path"):
        data_packs.import_pack(bad)
    assert not (tmp_path / "target" / "outside.txt").exists()


def test_synthetic_run_needs_an_explicit_flag_and_a_declaration(tmp_path, monkeypatch, source):
    run_id = _make_done_run(source, synthetic=True)
    with pytest.raises(data_packs.PackError, match="SYNTHETIC"):
        _export(tmp_path, [run_id])

    pack = _export(tmp_path, [run_id], allow_synthetic=True)

    def undeclare(members):
        manifest = json.loads(members["manifest.json"])
        manifest["synthetic_run_ids"] = []
        members["manifest.json"] = json.dumps(manifest).encode()

    unlabelled = _rewrite(pack, tmp_path / "unlabelled.jrpack", undeclare)
    _use_data_dir(monkeypatch, tmp_path / "target" / "data")
    with pytest.raises(data_packs.PackError, match="synthetic"):
        data_packs.import_pack(unlabelled)
    assert data_packs.import_pack(pack)["synthetic_run_ids"] == [run_id]


def test_unfinished_run_cannot_be_packed(tmp_path, source):
    run_id = db.create_run("khadakwasla", {}, "swe")
    with pytest.raises(data_packs.PackError, match="only 'done'"):
        _export(tmp_path, [run_id])


def test_forbidden_source_is_refused(tmp_path, source):
    run_id = _make_done_run(source)
    fab = source / "dem" / "fabdem_tile.tif"
    fab.parent.mkdir()
    fab.write_bytes(b"x")
    with pytest.raises(data_packs.PackError, match="FABDEM"):
        _export(tmp_path, [run_id], includes=[(fab, "CC BY-NC-SA")])


def test_cli_reports_json(tmp_path, source, capsys):
    run_id = _make_done_run(source)
    out = tmp_path / "cli.jrpack"
    assert data_packs.main(["export", "--run-id", run_id, "--out", str(out), "--name", "cli"]) == 0
    assert json.loads(capsys.readouterr().out)["runs"] == [run_id]
    assert data_packs.main(["import", str(tmp_path / "missing.jrpack")]) == 1
    assert json.loads(capsys.readouterr().out)["ok"] is False


# ----------------------------------------------------------------------
# Stopping in-flight runs on desktop exit
# ----------------------------------------------------------------------


def test_stop_active_runs_terminates_the_worker(tmp_path, monkeypatch):
    _use_data_dir(monkeypatch, tmp_path / "data")
    worker = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
    try:
        live = db.create_run("tehri", {}, "swe")
        db.update_run_status(live, "running", 30.0)
        db.record_worker_pid(live, worker.pid)
        queued = db.create_run("tehri", {}, "swe")
        done = _make_done_run(tmp_path / "data")

        result = run_control.stop_active_runs()
        assert result["stopped_runs"] == [live]
        assert result["marked_without_live_worker"] == [queued]
        worker.wait(timeout=30)
        time.sleep(0.2)
        assert not db._process_is_alive(worker.pid)
        for run_id in (live, queued):
            row = db.get_run(run_id)
            assert row["status"] == "failed"
            assert row["error"] == run_control.STOPPED_ERROR
        assert db.get_run(done)["status"] == "done"
    finally:
        if worker.poll() is None:
            worker.kill()
