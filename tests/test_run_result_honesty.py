"""
Three honesty labels must reach the run result, and from there the dashboard.

Each of these was computed or recorded somewhere in the pipeline and then
dropped before the browser could see it:

- ``is_synthetic``: ``scripts/make_synthetic_demo_run.py`` writes it to the run's
  params and ``run_summary.json``; ``GET /runs/{id}/result`` never read it, so a
  painted wave loaded into the dashboard with nothing above the map saying so.
- ``unverified_regressions``: ``ensemble_statistics`` computes it, and
  ``tasks._ensemble_summary`` copied ``regressions_used`` but not this, so a
  quarantined regression could contribute members with no trace in the payload.
- gauge boundary proximity: a gauge within a few km of the transmissive domain
  edge reports a depth partly set by the outflow condition. Only the drainage
  script checked, and only into its own JSON.

Nothing here touches the network or runs a solver.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "services" / "api"))

pytest.importorskip("jalraksha_service", reason="API service not importable")


@pytest.fixture
def service(tmp_path, monkeypatch):
    """A private database and DATA_DIR (same isolation as test_script_runs)."""
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


# A Pune-area point and the UTM zone-43 grid built around it. The gauge sits
# 3 km inside the WEST edge and well inside the other three.
GAUGE_LAT, GAUGE_LON = 18.50, 73.85


def _grid_around_gauge(west_clearance_m=3000.0, crs="EPSG:32643"):
    from jalraksha.terrain.domain import latlon_to_utm

    _zone, x, y = latlon_to_utm(GAUGE_LAT, GAUGE_LON, utm_zone=43)
    dx = dy = 100.0
    return {
        "nx": 200, "ny": 200, "dx": dx, "dy": dy,
        "x0": x - west_clearance_m, "y0": y - 10_000.0, "crs": crs,
    }


# ------------------------------------------------------- boundary proximity

class TestBoundaryClearance:
    def test_a_gauge_near_the_west_edge_reports_that_distance(self):
        from jalraksha_service.script_runs import gauge_boundary_clearance_km

        clearance = gauge_boundary_clearance_km(_grid_around_gauge(3000.0), GAUGE_LAT, GAUGE_LON)
        assert clearance == pytest.approx(3.0, abs=0.01)

    def test_a_gauge_outside_the_domain_is_negative(self):
        from jalraksha_service.script_runs import gauge_boundary_clearance_km

        clearance = gauge_boundary_clearance_km(_grid_around_gauge(-1500.0), GAUGE_LAT, GAUGE_LON)
        assert clearance == pytest.approx(-1.5, abs=0.01)

    def test_the_nearest_of_four_edges_wins(self):
        from jalraksha_service.script_runs import gauge_boundary_clearance_km

        # West edge 8 km away, but the grid is only 200 cells x 100 m = 20 km
        # wide, so the east edge is 12 km away and the south edge 10 km.
        clearance = gauge_boundary_clearance_km(_grid_around_gauge(8000.0), GAUGE_LAT, GAUGE_LON)
        assert clearance == pytest.approx(8.0, abs=0.01)

    @pytest.mark.parametrize("grid, lat, lon", [
        ({}, GAUGE_LAT, GAUGE_LON),
        (None, GAUGE_LAT, GAUGE_LON),
        # register_script_run.py deliberately leaves the origin null rather
        # than guessing it; a guessed origin would be worse than no answer.
        ({"nx": 10, "ny": 10, "dx": 100.0, "dy": 100.0, "x0": None, "y0": None,
          "crs": "EPSG:32643"}, GAUGE_LAT, GAUGE_LON),
        ("grid", None, GAUGE_LON),
    ])
    def test_unknown_geometry_gives_none_not_a_number(self, grid, lat, lon):
        from jalraksha_service.script_runs import gauge_boundary_clearance_km

        if grid == "grid":
            grid = _grid_around_gauge()
        assert gauge_boundary_clearance_km(grid, lat, lon) is None

    def test_gauge_rows_carry_the_flag(self):
        from jalraksha_service.script_runs import (
            BOUNDARY_CONTAMINATION_KM, gauge_rows_from_result,
        )

        result = {
            "grid": _grid_around_gauge(3000.0),
            "gauges": [{"name": "Hadapsar", "lat": GAUGE_LAT, "lon": GAUGE_LON}],
            "arrival_times": {"Hadapsar": {"distance_km": 18.6, "median": 7200.0}},
        }
        (row,) = gauge_rows_from_result(result)
        assert row["boundary_clearance_km"] == pytest.approx(3.0, abs=0.01)
        assert row["near_boundary"] is True
        assert 3.0 < BOUNDARY_CONTAMINATION_KM

    def test_a_row_without_a_grid_is_unflagged_rather_than_guessed(self):
        from jalraksha_service.script_runs import gauge_rows_from_result

        result = {"arrival_times": {"Hadapsar": {"distance_km": 18.6, "median": 7200.0}}}
        (row,) = gauge_rows_from_result(result)
        assert row["boundary_clearance_km"] is None
        assert row["near_boundary"] is None

    def test_the_drainage_script_uses_the_same_threshold(self):
        # One definition. Two copies of a threshold drift apart silently.
        source = (REPO_ROOT / "scripts" / "run_khadakwasla_drainage_check.py").read_text(
            encoding="utf-8")
        assert "from jalraksha_service.script_runs import BOUNDARY_CONTAMINATION_KM" in source
        assert "BOUNDARY_CONTAMINATION_KM = " not in source

    def test_the_flag_survives_the_database(self, service):
        run_id = service.create_run("khadakwasla", {"name": "t"}, "swe")
        service.insert_gauge_results(run_id, [
            {"gauge_name": "Hadapsar", "distance_km": 18.6,
             "boundary_clearance_km": 3.0, "near_boundary": True},
            {"gauge_name": "Swargate", "distance_km": 11.5},
        ])
        rows = {r["gauge_name"]: r for r in service.get_gauge_results(run_id)}
        assert rows["Hadapsar"]["near_boundary"] is True
        assert rows["Hadapsar"]["boundary_clearance_km"] == pytest.approx(3.0)
        assert rows["Swargate"]["near_boundary"] is None
        assert rows["Swargate"]["boundary_clearance_km"] is None

    def test_the_backfill_writer_fills_one_row_only(self, service):
        run_id = service.create_run("khadakwasla", {"name": "t"}, "swe")
        service.insert_gauge_results(run_id, [
            {"gauge_name": "Hadapsar", "distance_km": 18.6},
            {"gauge_name": "Swargate", "distance_km": 11.5},
        ])
        service.set_gauge_boundary(run_id, "Hadapsar", 2.91, True)
        rows = {r["gauge_name"]: r for r in service.get_gauge_results(run_id)}
        assert rows["Hadapsar"]["near_boundary"] is True
        assert rows["Hadapsar"]["boundary_clearance_km"] == pytest.approx(2.91)
        assert rows["Swargate"]["near_boundary"] is None


# --------------------------------------------------- unverified regressions

def test_the_ensemble_summary_keeps_the_unverified_regressions():
    from jalraksha_service.tasks import _ensemble_summary

    summary = _ensemble_summary({"breach_stats": {
        "q_peak_median": 1000.0,
        "regressions_used": ["froehlich_2008", "xu_zhang_2009"],
        "unverified_regressions": ["xu_zhang_2009"],
        "uses_unverified_regression": True,
        "unverified_regression_note": "xu_zhang_2009 is quarantined.",
    }})
    assert summary["unverified_regressions"] == ["xu_zhang_2009"]
    assert summary["uses_unverified_regression"] is True
    assert summary["unverified_regression_note"] == "xu_zhang_2009 is quarantined."

    from jalraksha_service.schemas import EnsembleSummary

    model = EnsembleSummary(**summary)
    assert model.unverified_regressions == ["xu_zhang_2009"]


def test_a_verified_ensemble_reports_an_empty_list():
    from jalraksha_service.tasks import _ensemble_summary

    summary = _ensemble_summary({"breach_stats": {"q_peak_median": 1000.0}})
    assert summary["unverified_regressions"] == []


# ---------------------------------------------------------------- synthetic

def _finish_run(service, tmp_path, params, summary):
    """A done run with one run_summary export, the minimum run_result reads."""
    run_id = service.create_run("khadakwasla", params, "swe")
    summary_path = tmp_path / "data" / "exports" / run_id / "run_summary.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary), encoding="utf-8")
    service.insert_exports(run_id, [{"kind": "run_summary", "path_or_url": str(summary_path)}])
    service.update_run_status(run_id, "done", 100.0)
    return run_id


def test_a_synthetic_run_says_so_from_its_params(service, tmp_path):
    from jalraksha_service import main

    run_id = _finish_run(service, tmp_path,
                         {"name": "SYNTHETIC DEMO", "is_synthetic": True,
                          "synthetic_note": "No solver ran."},
                         {"ensemble": None})
    result = main.run_result(run_id)
    assert result.is_synthetic is True
    assert result.synthetic_note == "No solver ran."


def test_a_synthetic_run_says_so_from_its_summary(service, tmp_path):
    from jalraksha_service import main

    run_id = _finish_run(service, tmp_path, {"name": "SYNTHETIC DEMO"},
                         {"is_synthetic": True, "note": "Painted, not solved."})
    result = main.run_result(run_id)
    assert result.is_synthetic is True
    assert result.synthetic_note == "Painted, not solved."


def test_a_real_run_is_not_synthetic(service, tmp_path):
    from jalraksha_service import main

    run_id = _finish_run(service, tmp_path, {"name": "Khadakwasla"}, {"note": "irrelevant"})
    result = main.run_result(run_id)
    assert result.is_synthetic is False
    assert result.synthetic_note is None
