"""
The peak-envelope ParaView dataset must be built from the run's OWN domain.

scripts/build_peak_envelope_xdmf.py gives a finished run a 3D view without
re-solving: it rebuilds the terrain and lays the stored ensemble-median maximum
depth over it. Two ways that goes silently wrong are pinned here:

- a raster read back in the wrong orientation (COGs are north-up, the solver
  and the XDMF writer are south-up) renders a flood mirrored onto the wrong
  valley and still looks plausible;
- a terrain rebuilt on a different domain (wrong DEM, wrong margins) would be
  presented as the one the run was solved on.

And the dashboard must be able to tell an envelope from a time series.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "services" / "api"))

_spec = importlib.util.spec_from_file_location(
    "build_peak_envelope_xdmf", REPO_ROOT / "scripts" / "build_peak_envelope_xdmf.py")
envelope = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(envelope)

GRID = {"nx": 6, "ny": 4, "dx": 500.0, "dy": 500.0,
        "x0": 289962.5, "y0": 1839706.9, "crs": "EPSG:32643"}


def test_a_cog_reads_back_south_up_onto_the_solver_grid(tmp_path):
    pytest.importorskip("rasterio")
    from jalraksha.export.geotiff import export_raster_to_cog

    # Row index * 10 + column: a flip or transpose changes every value.
    field = (np.arange(4)[:, None] * 10 + np.arange(6)[None, :]).astype("float32")
    path = export_raster_to_cog(field, str(tmp_path / "h_max_median_cog.tif"), GRID,
                                crs_epsg=32643, data_name="h_max_median")
    back = envelope.read_cog_south_up(Path(path), GRID)
    np.testing.assert_array_equal(back, field)


def test_a_cog_from_another_domain_is_refused(tmp_path):
    pytest.importorskip("rasterio")
    from jalraksha.export.geotiff import export_raster_to_cog

    field = np.ones((4, 6), dtype="float32")
    path = export_raster_to_cog(field, str(tmp_path / "h.tif"), GRID, crs_epsg=32643)
    shifted = {**GRID, "x0": GRID["x0"] + 500.0}
    with pytest.raises(envelope.EnvelopeError, match="transform"):
        envelope.read_cog_south_up(Path(path), shifted)


@pytest.mark.parametrize("key, value", [
    ("nx", 7), ("dx", 400.0), ("x0", 289962.5 + 1.0), ("crs", "EPSG:32644"),
])
def test_a_rebuilt_grid_must_match_the_recorded_one_exactly(key, value):
    assert envelope.grids_match(dict(GRID), dict(GRID)) is None
    mismatch = envelope.grids_match({**GRID, key: value}, dict(GRID))
    assert mismatch is not None and mismatch.startswith(key)


@pytest.fixture
def service(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("JALRAKSHA_DATA_DIR", "./data")
    pytest.importorskip("jalraksha_service")
    from jalraksha_service import db
    from jalraksha_service.config import settings

    monkeypatch.setattr(settings, "DATA_DIR", tmp_path / "data", raising=False)
    monkeypatch.setattr(settings, "DATABASE_URL",
                        f"sqlite:///{(tmp_path / 'test.db').as_posix()}", raising=False)
    db.init_db()
    return db


def _done_run(service, tmp_path, summary):
    run_id = service.create_run("khadakwasla", {
        "name": "t", "lat": 18.4436, "lon": 73.7686,
        "_solver_params": {"target_resolution": 500.0},
    }, "swe")
    exports = tmp_path / "data" / "exports" / run_id
    exports.mkdir(parents=True)
    (exports / "run_summary.json").write_text(json.dumps(summary), encoding="utf-8")
    (exports / "h_max_median_cog.tif").write_bytes(b"not read before the DEM check")
    service.insert_exports(run_id, [
        {"kind": "run_summary", "path_or_url": str(exports / "run_summary.json")},
        {"kind": "cog_h_max_median", "path_or_url": str(exports / "h_max_median_cog.tif")},
    ])
    service.update_run_status(run_id, "done", 100.0)
    return run_id


def test_a_run_with_no_recorded_dem_needs_one_named(service, tmp_path):
    run_id = _done_run(service, tmp_path, {"grid": GRID, "dem": {"dem_used": None}})
    with pytest.raises(envelope.EnvelopeError, match="--dem"):
        envelope.build_envelope(run_id, None, apply=False)


def test_a_run_with_no_grid_origin_is_refused(service, tmp_path):
    run_id = _done_run(service, tmp_path, {"grid": {**GRID, "x0": None}})
    with pytest.raises(envelope.EnvelopeError, match="origin"):
        envelope.build_envelope(run_id, None, apply=False)


def test_replace_export_keeps_one_row(service):
    run_id = service.create_run("khadakwasla", {"name": "t"}, "swe")
    service.replace_export(run_id, "xdmf", "a.xdmf")
    service.replace_export(run_id, "xdmf", "b.xdmf")
    rows = [e for e in service.get_exports(run_id) if e["kind"] == "xdmf"]
    assert [r["path_or_url"] for r in rows] == ["b.xdmf"]


@pytest.mark.parametrize("declared, expected", [
    ('<Information Name="dataset_kind" Value="peak_envelope" />', "peak_envelope"),
    ('<Information Name="dataset_kind" Value="time_series" />', None),
    ("", None),
])
def test_the_result_reports_which_kind_of_3d_dataset(tmp_path, declared, expected):
    pytest.importorskip("jalraksha_service")
    from jalraksha_service import main

    path = tmp_path / "run.xdmf"
    path.write_text(f"<Xdmf><Domain>{declared}</Domain></Xdmf>", encoding="utf-8")
    assert main._xdmf_dataset_kind(str(path)) == expected
    assert main._xdmf_dataset_kind(None) is None
