"""
A run that ran the Deltares kernel must say so on every surface.

`write_run_summary` writes no "engine" block, so for a `solver="both"` run the
only place `delft3d_binary_used` is recorded is the comparison artifact. Before
this, the Comparison tab named "Delft3D FM (official dflowfm binary)" while the
Provenance tab said the engine was "not recorded for this run" — one fact in two
states, and the naming rule in CLAUDE.md turns on exactly that boolean.

Measured on run e83a8fb6 (Khadakwasla, 4 members, solver="both", 2026-09-20).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "services" / "api"))

pytest.importorskip("jalraksha_service", reason="API service not importable")

COMPARISON = {
    "delft3d_engine": "Delft3D_FM",
    "delft3d_engine_label": "Delft3D FM (official dflowfm binary)",
    "delft3d_binary_used": True,
    "delft3d_fallback_reason": None,
}


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


def _done_run(service, tmp_path, summary, comparison=None):
    run_id = service.create_run("khadakwasla", {"name": "Khadakwasla Dam"}, "both")
    export_dir = tmp_path / "data" / "exports" / run_id
    export_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    (export_dir / "run_summary.json").write_text(json.dumps(summary), encoding="utf-8")
    rows.append({"kind": "run_summary", "path_or_url": str(export_dir / "run_summary.json")})
    if comparison is not None:
        (export_dir / "comparison.json").write_text(json.dumps(comparison), encoding="utf-8")
        rows.append({"kind": "comparison_metrics",
                     "path_or_url": str(export_dir / "comparison.json")})
    service.insert_exports(run_id, rows)
    service.update_run_status(run_id, "done", 100.0)
    return run_id


def test_the_kernel_that_ran_is_named_from_the_comparison_artifact(service, tmp_path):
    from jalraksha_service import main

    run_id = _done_run(service, tmp_path, {}, COMPARISON)
    engine = main.run_result(run_id).engine
    assert engine.delft3d_binary_used is True
    assert engine.label == COMPARISON["delft3d_engine_label"]


def test_a_summary_engine_block_still_wins(service, tmp_path):
    """The summary is the run's own record; the comparison is only a fallback."""
    from jalraksha_service import main

    summary = {"engine": {"name": "jalraksha_swe", "label": "JalRaksha built-in 2D SWE",
                          "delft3d_binary_used": False, "fallback_reason": "not requested"}}
    engine = main.run_result(_done_run(service, tmp_path, summary, COMPARISON)).engine
    assert engine.label == "JalRaksha built-in 2D SWE"
    assert engine.delft3d_binary_used is False


def test_a_run_with_no_comparison_reports_no_engine(service, tmp_path):
    """Absent stays absent: an SWE-only run must not be given a kernel it never ran."""
    from jalraksha_service import main

    assert main.run_result(_done_run(service, tmp_path, {})).engine is None
