"""
Evacuation directives reach every run path, and change nothing else.

The directive is computed inside the SHARED gauge_rows_from_result, so the API
path (tasks.run_dam_break_task) and the script path (RegisteredRun.finish)
cannot disagree about it. These tests pin the four things that make that true
and keep it additive:

- a gauge row is exactly what it was before, plus one new key;
- the directive survives the database and a data pack;
- a run written before directives existed reads back with evacuation None
  (absent, not "no action needed");
- the script path writes it, not only the API path.

Nothing here touches the network or runs a solver.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "services" / "api"))

pytest.importorskip("jalraksha_service", reason="API service not importable")

GAUGE_LAT, GAUGE_LON = 18.50, 73.85
OUTSIDE_NOTE = "Gauge lies outside the solver domain; increase domain_radius_km"
MINORITY_NOTE = (
    "MINORITY ARRIVAL: 1 of 4 ensemble members reached this gauge. The time "
    "shown is the median of those 1, and the p05/p95 band describes them alone "
    "— it is not evidence that the flood reliably gets here. Read it as a "
    "possible outcome, not the expected one."
)

# gauge_rows_from_result's output for _result() BEFORE directives existed,
# captured by running the previous commit's code. The feature may add the
# "evacuation" key and nothing else.
PRE_FEATURE_ROWS = [
    {
        "gauge_name": "Near edge", "distance_km": 12.1,
        "arrival_time_s": 900.0, "arrival_p05_s": 800.0, "arrival_p95_s": 1000.0,
        "max_depth_m": 2.0, "note": None, "par_estimate": None,
        "boundary_clearance_km": 3.0, "near_boundary": True,
    },
    {
        "gauge_name": "Outside", "distance_km": 60.0,
        "arrival_time_s": None, "arrival_p05_s": None, "arrival_p95_s": None,
        "max_depth_m": None, "note": OUTSIDE_NOTE, "par_estimate": None,
        "boundary_clearance_km": -104.4, "near_boundary": False,
    },
    {
        "gauge_name": "Minority", "distance_km": 20.0,
        "arrival_time_s": 5000.0, "arrival_p05_s": 5000.0, "arrival_p95_s": 5000.0,
        "max_depth_m": 0.3, "note": MINORITY_NOTE, "par_estimate": None,
        "boundary_clearance_km": None, "near_boundary": None,
    },
]


def _result():
    """A solver result with one gauge of each kind the directive must handle."""
    from jalraksha.terrain.domain import latlon_to_utm

    _zone, x, y = latlon_to_utm(GAUGE_LAT, GAUGE_LON, utm_zone=43)
    return {
        "raster_paths": {},
        "grid": {"nx": 200, "ny": 200, "dx": 100.0, "dy": 100.0,
                 "x0": x - 3000.0, "y0": y - 10_000.0, "crs": "EPSG:32643"},
        "gauges": [
            {"name": "Near edge", "lat": GAUGE_LAT, "lon": GAUGE_LON},
            {"name": "Outside", "lat": 18.0, "lon": 75.0},
        ],
        "arrival_times": {
            "Near edge": {"distance_km": 12.1, "median": 900.0, "p05": 800.0, "p95": 1000.0,
                          "max_depth_m": 2.0, "num_samples": 6, "num_members": 6},
            "Outside": {"distance_km": 60.0, "median": None, "p05": None, "p95": None,
                        "num_samples": 0, "note": OUTSIDE_NOTE},
            "Minority": {"distance_km": 20.0, "median": 5000.0, "p05": 5000.0, "p95": 5000.0,
                         "max_depth_m": 0.3, "num_samples": 1, "num_members": 4},
        },
    }


@pytest.fixture
def service(tmp_path, monkeypatch):
    """A private database and DATA_DIR (same isolation as test_script_runs.py)."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("JALRAKSHA_DATA_DIR", "./data")

    from jalraksha_service import db
    from jalraksha_service.config import settings

    monkeypatch.setattr(settings, "DATA_DIR", tmp_path / "data", raising=False)
    monkeypatch.setattr(settings, "DATABASE_URL",
                        f"sqlite:///{(tmp_path / 'test.db').as_posix()}",
                        raising=False)
    db.init_db()
    return db


def _rows():
    from jalraksha_service.script_runs import gauge_rows_from_result

    return {r["gauge_name"]: r for r in gauge_rows_from_result(_result())}


class TestGaugeRows:
    def test_a_row_is_unchanged_apart_from_the_new_key(self):
        from jalraksha_service.script_runs import gauge_rows_from_result

        rows = gauge_rows_from_result(_result())
        stripped = [{k: v for k, v in r.items() if k != "evacuation"} for r in rows]
        assert stripped == PRE_FEATURE_ROWS
        assert all(set(r) - set(pre) == {"evacuation"} for r, pre in zip(rows, PRE_FEATURE_ROWS))

    def test_a_significant_depth_is_told_to_evacuate_and_keeps_its_boundary_flag(self):
        evac = _rows()["Near edge"]["evacuation"]
        assert evac["directive"] == "evacuate"
        assert evac["hazard_level"] == "significant"
        assert evac["near_boundary"] is True

    def test_an_outside_gauge_is_not_assessed_with_its_note(self):
        evac = _rows()["Outside"]["evacuation"]
        assert evac["directive"] == "no_arrival"
        assert evac["note"] == OUTSIDE_NOTE

    def test_a_minority_arrival_says_so(self):
        evac = _rows()["Minority"]["evacuation"]
        assert evac["minority_arrival"] is True
        assert evac["note"].startswith("MINORITY ARRIVAL")

    def test_every_directive_carries_the_unvetted_label(self):
        assert all(r["evacuation"]["thresholds_unvetted"] is True for r in _rows().values())


class TestPersistence:
    def test_the_directive_survives_the_database(self, service):
        from jalraksha_service.script_runs import gauge_rows_from_result

        run_id = service.create_run("khadakwasla", {"name": "Directive run"}, "swe")
        rows = gauge_rows_from_result(_result())
        service.insert_gauge_results(run_id, rows)
        stored = {g["gauge_name"]: g for g in service.get_gauge_results(run_id)}
        for row in rows:
            assert stored[row["gauge_name"]]["evacuation"] == row["evacuation"]

    def test_a_run_written_before_directives_reads_back_as_absent(self, service, tmp_path):
        """Rule 3 of the spec: the old run deserializes, and says nothing new."""
        import json

        from jalraksha_service import main

        run_id = service.create_run("khadakwasla", {"name": "Old run"}, "swe")
        service.insert_gauge_results(run_id, [{"gauge_name": "Pune", "distance_km": 12.0,
                                               "arrival_time_s": 3600.0, "max_depth_m": 2.5}])
        summary = tmp_path / "data" / "exports" / run_id / "run_summary.json"
        summary.parent.mkdir(parents=True, exist_ok=True)
        summary.write_text(json.dumps({}), encoding="utf-8")
        service.insert_exports(run_id, [{"kind": "run_summary", "path_or_url": str(summary)}])
        service.update_run_status(run_id, "done", 100.0)

        result = main.run_result(run_id)
        assert result.gauges[0].evacuation is None

    def test_the_script_path_writes_directives(self, service):
        from jalraksha_service.script_runs import registered_run

        with registered_run("khadakwasla", {"name": "Script run"}, "swe", {}) as run:
            run.finish(_result())
            run_id = run.run_id

        stored = {g["gauge_name"]: g for g in service.get_gauge_results(run_id)}
        assert stored["Near edge"]["evacuation"]["directive"] == "evacuate"
        assert stored["Outside"]["evacuation"]["directive"] == "no_arrival"

    def test_the_api_path_uses_the_same_shared_rows(self):
        """tasks.py gets directives only because it calls the shared function."""
        import inspect

        from jalraksha_service import tasks

        assert "gauge_rows_from_result" in inspect.getsource(tasks.run_dam_break_task)

    def test_a_data_pack_keeps_the_directive(self, service, tmp_path, monkeypatch):
        import json

        from jalraksha_service import config, data_packs
        from jalraksha_service.script_runs import gauge_rows_from_result

        data_dir = config.settings.DATA_DIR
        run_id = service.create_run("khadakwasla", {"name": "Packed"}, "swe")
        exports = data_dir / "exports" / run_id
        exports.mkdir(parents=True)
        (exports / "run_summary.json").write_text(json.dumps({"run_id": run_id}))
        service.insert_exports(run_id, [{"kind": "run_summary",
                                         "path_or_url": str(exports / "run_summary.json")}])
        rows = gauge_rows_from_result(_result())
        service.insert_gauge_results(run_id, rows)
        service.update_run_status(run_id, "done", 100.0)

        pack = tmp_path / "packs" / "test.jrpack"
        data_packs.export_pack([run_id], pack, "Directive pack")

        target = tmp_path / "target" / "data"
        target.mkdir(parents=True)
        monkeypatch.setattr(config.settings, "DATA_DIR", target)
        monkeypatch.setattr(config.settings, "DATABASE_URL", f"sqlite:///{target}/jalraksha.db")
        service.init_db()
        data_packs.import_pack(pack)

        stored = {g["gauge_name"]: g for g in service.get_gauge_results(run_id)}
        for row in rows:
            assert stored[row["gauge_name"]]["evacuation"] == row["evacuation"]
