"""
POST /runs/{id}/report writes one artifact, from what the run recorded.

Three things this pins, each of which fails looking like something else:

- **One row, not two.** Regenerating must REPLACE the export row. Appending
  (insert_exports has no uniqueness constraint) would list the same document
  twice in the Downloads tab, which reads as two reports.
- **The figures are the run's own.** The peak-wet frame is chosen by the same
  rule the dashboard's scrubber uses, and a frame with no hazard summary yields
  no peak figure rather than a guessed one.
- **Volume balance now survives the run.** The solver computed it and the
  summary writer dropped it; a run written before 2026-09-20 still reads None,
  and the document says so rather than printing a zero.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "services" / "api"))

pytest.importorskip("jalraksha_service", reason="API service not importable")
pytest.importorskip("docx", reason="python-docx not installed")


@pytest.fixture
def service(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("JALRAKSHA_DATA_DIR", "./data")

    from jalraksha_service import db
    from jalraksha_service.config import settings

    monkeypatch.setattr(settings, "DATA_DIR", tmp_path / "data", raising=False)
    monkeypatch.setattr(settings, "DATABASE_URL",
                        f"sqlite:///{(tmp_path / 'test.db').as_posix()}", raising=False)
    db.init_db()
    return db


def _done_run(service, tmp_path, *, summary=None, keyframes=None):
    run_id = service.create_run("khadakwasla", {"name": "Khadakwasla Dam"}, "swe")
    exports_dir = tmp_path / "data" / "exports" / run_id
    exports_dir.mkdir(parents=True, exist_ok=True)
    rows = []

    summary_path = exports_dir / "run_summary.json"
    summary_path.write_text(json.dumps(summary or {}), encoding="utf-8")
    rows.append({"kind": "run_summary", "path_or_url": str(summary_path)})

    if keyframes is not None:
        kf_dir = tmp_path / "data" / "keyframes" / run_id
        kf_dir.mkdir(parents=True, exist_ok=True)
        # A 1x1 PNG: python-docx must be able to embed whatever we point it at.
        png = bytes.fromhex(
            "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
            "890000000a49444154789c63000100000500010d0a2db40000000049454e44ae426082")
        for index, _ in enumerate(keyframes):
            (kf_dir / f"kf_{index:04d}.png").write_bytes(png)
        manifest = {"keyframes": [
            {"time_s": frame["time_s"], "png_url": f"kf_{index:04d}.png",
             **({"hazard_summary": frame["hazard_summary"]} if "hazard_summary" in frame else {})}
            for index, frame in enumerate(keyframes)]}
        manifest_path = kf_dir / "manifest.json"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        rows.append({"kind": "keyframe_manifest", "path_or_url": str(manifest_path)})

    service.insert_exports(run_id, rows)
    service.insert_gauge_results(run_id, [{"gauge_name": "Pune", "distance_km": 12.0,
                                           "arrival_time_s": 3600.0, "max_depth_m": 2.5}])
    service.update_run_status(run_id, "done", 100.0)
    return run_id


def _wet(count):
    return {"low": {"count": count}, "extreme": {"count": 0}}


class TestArtifact:
    def test_the_report_is_written_and_registered_once(self, service, tmp_path):
        from jalraksha_service import main

        run_id = _done_run(service, tmp_path)
        first = main.generate_report(run_id)
        assert first.kind == "report_docx"
        path = tmp_path / "data" / "exports" / run_id / f"report_{run_id}.docx"
        assert path.exists()

        main.generate_report(run_id)
        rows = [e for e in service.get_exports(run_id) if e["kind"] == "report_docx"]
        assert len(rows) == 1, "regenerating must replace the row, not append to it"

    def test_a_run_that_is_not_done_is_refused(self, service, tmp_path):
        from fastapi import HTTPException
        from jalraksha_service import main

        run_id = service.create_run("khadakwasla", {"name": "Running"}, "swe")
        service.update_run_status(run_id, "running", 10.0)
        with pytest.raises(HTTPException) as excinfo:
            main.generate_report(run_id)
        assert excinfo.value.status_code == 409


class TestFigures:
    def test_the_peak_frame_is_the_run_s_own(self, service, tmp_path):
        from jalraksha_service import main

        run_id = _done_run(service, tmp_path, keyframes=[
            {"time_s": 0.0, "hazard_summary": _wet(1)},
            {"time_s": 600.0, "hazard_summary": _wet(90)},
            {"time_s": 1200.0, "hazard_summary": _wet(20)},
        ])
        figures = main._report_figures(run_id, service.get_exports(run_id), None)
        captions = [f["caption"] for f in figures]
        assert any(c.startswith("First frame") for c in captions)
        assert any(c.startswith("Peak wet extent") and "600" in c for c in captions)
        assert any(c.startswith("Last frame") for c in captions)

    def test_no_hazard_summary_means_no_peak_figure_rather_than_a_guess(self, service, tmp_path):
        from jalraksha_service import main

        run_id = _done_run(service, tmp_path, keyframes=[
            {"time_s": 0.0}, {"time_s": 600.0}, {"time_s": 1200.0}])
        captions = [f["caption"] for f in
                    main._report_figures(run_id, service.get_exports(run_id), None)]
        assert not any(c.startswith("Peak wet extent") for c in captions)
        assert len(captions) == 2


class TestVolumeBalance:
    BALANCE = {"available": True, "released_mcm": 85.314, "exited_mcm": 82.219,
               "retained_mcm": 3.09, "retained_fraction": 0.0362, "n_members": 6}

    def test_the_shared_writer_keeps_it(self, service, tmp_path):
        from jalraksha_service.script_runs import write_run_summary

        row = write_run_summary(
            "run-1",
            {"raster_paths": {}, "arrival_times": {}, "volume_balance": self.BALANCE},
            {"name": "Khadakwasla Dam"}, {"ensemble_size": 1})
        stored = json.loads(Path(row["path_or_url"]).read_text(encoding="utf-8"))
        assert stored["volume_balance"] == self.BALANCE

    def test_a_run_written_before_this_reads_none(self, service, tmp_path):
        from jalraksha_service import main

        run_id = _done_run(service, tmp_path, summary={"ensemble": None})
        assert main.run_result(run_id).volume_balance is None

    def test_it_reaches_the_result_payload(self, service, tmp_path):
        from jalraksha_service import main

        run_id = _done_run(service, tmp_path, summary={"volume_balance": self.BALANCE})
        assert main.run_result(run_id).volume_balance == self.BALANCE
