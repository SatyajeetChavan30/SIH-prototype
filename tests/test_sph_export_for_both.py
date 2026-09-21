"""
A solver="both" run does the near-field SPH, so it must have an SPH tab.

Measured on run e83a8fb6 (Khadakwasla, 2026-09-20): 232,426 fluid particles on
the GPU, 89 s of real simulation — and no SPH tab, because the tab reads an
export of kind "sph_near_field" that only the solver="sph" path ever wrote. The
only surviving copy was the reduced summary inside comparison_metrics.json,
which carries neither the front history nor the particle cloud the panel draws.

Nothing here runs Delft3D, SPH or a solver: the comparison's two external calls
are stubbed, because what is under test is which artifacts get written.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "services" / "api"))

pytest.importorskip("jalraksha_service", reason="API service not importable")
pytest.importorskip("matplotlib", reason="the comparison writes figures")

DAM_CONFIG = {"dam_id": "khadakwasla", "name": "Khadakwasla Dam",
              "lat": 18.44, "lon": 73.77, "height_m": 51.3, "storage_mm3": 33.5}


@pytest.fixture
def stubbed(tmp_path, monkeypatch):
    """The comparison, with its two external engines replaced by stubs."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    from jalraksha.delft3d import comparison as comparison_mod
    from jalraksha.delft3d import runner as runner_mod
    from jalraksha_service import tasks
    from jalraksha_service.config import settings

    monkeypatch.setattr(settings, "DATA_DIR", tmp_path / "data", raising=False)

    sph_result = {
        "engine": "DualSPHysics", "engine_label": "DualSPHysics v5.4 on GPU",
        "n_fluid": 232426, "n_boundary": 40000, "particle_spacing_m": 3.85,
        "max_depth_m": 33.6, "max_speed_m_s": 40.6, "front_speed_m_s": 16.9,
        "front_time_s": [0.0, 7.5, 15.0], "front_position_m": [0.0, 120.0, 246.7],
        "duration_s": 15.0, "domain_length_m": 1200.0, "wall_clock_s": 89.4,
        "x": [0.0, 1.0], "y": [0.0, 1.0], "z": [0.0, 1.0],
        "particle_volume_m3": 57.0,
    }
    monkeypatch.setattr(tasks, "_run_near_field_sph", lambda cfg: (sph_result, None))
    monkeypatch.setattr(runner_mod, "run_delft3d_simulation",
                        lambda *a, **k: {"engine": "Delft3D_FM", "depth": None})

    def fake_compare(sph_res, d3d_res, gauges):
        return {
            "metrics": {"rmse_m": 0.8, "bias_m": -0.06},
            "gauge_comparison": [],
            "sph_engine": sph_res.get("engine_label"),
            "sph_near_field": {"n_fluid": sph_res.get("n_fluid")},
            "delft3d_engine": "Delft3D_FM",
            "delft3d_engine_label": "Delft3D FM (official dflowfm binary)",
            "delft3d_binary_used": True,
            "delft3d_fallback_reason": None,
            "gauge_arrival_method": "delft3d_fm_his",
            "depth_fig": plt.figure(), "hydro_fig": plt.figure(),
        }

    monkeypatch.setattr(comparison_mod, "compare_sph_vs_delft3d", fake_compare)
    return tasks


def test_the_comparison_path_writes_the_sph_artifact_when_asked(stubbed, tmp_path):
    exports: list = []
    comp_export = stubbed._run_comparison("run-both", dict(DAM_CONFIG),
                                          with_sph=True, extra_exports=exports)

    assert comp_export["kind"] == "comparison_metrics"
    assert [row["kind"] for row in exports] == ["sph_near_field"]

    payload = json.loads(Path(exports[0]["path_or_url"]).read_text(encoding="utf-8"))
    assert payload["available"] is True
    assert payload["n_fluid"] == 232426
    # The two things comparison_metrics.json does NOT carry, and the panel draws.
    assert payload["front_position_m"], "the surge-front history must survive"
    assert payload["particles"]["x"], "the particle cloud must survive"


def test_old_callers_are_unchanged(stubbed, tmp_path):
    """rerun_comparison.py passes no extra_exports, and writes nothing new."""
    comp_export = stubbed._run_comparison("run-plain", dict(DAM_CONFIG), with_sph=True)

    assert comp_export["kind"] == "comparison_metrics"
    assert not (tmp_path / "data" / "exports" / "run-plain" / "sph_near_field.json").exists()


def test_the_run_task_passes_its_own_export_list(stubbed):
    """Wiring check: the 'both' branch must hand its list in, or nothing changes."""
    import inspect

    source = inspect.getsource(stubbed.run_dam_break_task)
    assert "extra_exports=exports" in source


def test_the_script_path_passes_its_own_export_list():
    """
    The long runs live in scripts/, not POST /runs, so the script path is the
    one that could least afford to lose the artifact. It registers every row
    the comparison hands back, beside comparison_metrics itself.
    """
    import inspect
    import sys

    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    import run_khadakwasla_drainage_check as script

    source = inspect.getsource(script._add_comparison_and_sph)
    assert "extra_exports=extra_exports" in source
    assert 'run.add_export(row["kind"], row["path_or_url"])' in source
