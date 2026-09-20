"""
The Word report prints what a run recorded, and says so when it recorded nothing.

The defect these tests exist to prevent is a document that reads as evidence
because its gaps look like measurements. A null rendered as 0.0, as a bare dash
or as "TBD" is indistinguishable from a measured zero, and a reader cannot
challenge what they cannot see is missing. So:

- every null renders as the one sanctioned phrase;
- a measured zero still renders as zero (the flagship reaching zero extreme
  cells IS the finding);
- every honesty label the run carries appears in the document, on page two.

The document is read back with python-docx rather than inspected as XML: if the
text is not reachable through the public API, it is not reachable by a reader
either.
"""

from __future__ import annotations

from pathlib import Path

import pytest

docx = pytest.importorskip("docx", reason="python-docx not installed (pip install -e '.[report]')")

from jalraksha.export.docx_report import (  # noqa: E402
    NOT_RECORDED,
    build_report,
    fmt,
    fmt_duration,
    fmt_year,
    honesty_lines,
)

# Renderings a missing value must never take. NOT_RECORDED is the only one.
# Matched as whole words: "nan" is a substring of "provenance", and a test that
# fails on the word "provenance" teaches nobody anything.
FORBIDDEN_FOR_NULL = ("TBD", "N/A", "None", "nan", "null", "undefined")


def _run(**overrides):
    """A RunResult-shaped dict with the fields a finished run really carries."""
    run = {
        "run_id": "abc123def456",
        "dam_name": "Khadakwasla Dam",
        "solver": "both",
        "is_synthetic": False,
        "synthetic_note": None,
        "exports": [],
        "dem_used": "data/dem/dem_18.44_73.77_clipped.tif",
        "dem_update": None,
        "solver_backend": {
            "solver_backend_label": "GPU (CUDA, NVIDIA GeForce RTX 4050 Laptop GPU, float64)",
            "solver_backend_reason": "CUDA device available",
            "solver_device": "NVIDIA GeForce RTX 4050 Laptop GPU",
        },
        "engine": {"label": "Delft3D FM (official dflowfm binary)",
                   "delft3d_binary_used": True, "fallback_reason": None},
        "grid": {"nx": 270, "ny": 270, "dx": 200.0, "dy": 200.0, "crs": "EPSG:32643"},
        "ensemble": {
            "regressions_used": ["costa_1985", "froehlich_1995"],
            "q_peak_median_m3s": 12147.27, "q_peak_p05_m3s": 10867.09,
            "q_peak_p95_m3s": 42313.01, "t_fail_median_s": 1575.29,
            "num_completed": 4, "num_ensemble": 4, "scenario_type": "dam_break",
            "dam_type": "embankment", "h_max_stats": {"median": 14.73, "p05": 14.41, "p95": 19.28},
            "unverified_regressions": [], "uses_unverified_regression": False,
            "dam_class_outside_fitted_population": False,
        },
        "hazard_summary": {
            "dry": {"count": 72500, "percentage": 99.45},
            "low": {"count": 31, "percentage": 0.04},
            "moderate": {"count": 56, "percentage": 0.08},
            "significant": {"count": 90, "percentage": 0.12},
            "extreme": {"count": 223, "percentage": 0.31},
            "scheme": "FD2320 HR = d(|V|+0.5)+DF, classed 0.75/1.25/2.5",
            "debris_factor": 0.5,
        },
        "gauges": [
            {"gauge_name": "Deccan Gymkhana", "distance_km": 10.5, "arrival_time_s": 5216.5,
             "arrival_p05_s": 4274.2, "arrival_p95_s": 6494.8, "max_depth_m": 13.21,
             "note": None, "near_boundary": False, "boundary_clearance_km": 9.1,
             "evacuation": {"directive": "evacuate", "label": "Evacuate",
                            "hazard_level": "extreme", "thresholds_unvetted": True,
                            "threshold_source": "UNVETTED: chosen for screening"}},
            {"gauge_name": "Swargate", "distance_km": 11.5, "arrival_time_s": None,
             "arrival_p05_s": None, "arrival_p95_s": None, "max_depth_m": 0.0,
             "note": "No arrival within the simulated time.", "near_boundary": False,
             "boundary_clearance_km": 8.0,
             "evacuation": {"directive": "no_arrival", "label": "Not assessed",
                            "hazard_level": None, "thresholds_unvetted": True,
                            "threshold_source": "UNVETTED: chosen for screening"}},
        ],
        "population_at_risk": {
            "available": True, "population_source": "GHSL_P2023A", "population_epoch": "2020",
            "total_population_in_domain": 7019072.5, "warning_lead_time_s": 1800.0,
            "exposure": {"total_exposed_population": 149434.5},
            "par": {"total_par": 168453.0, "par_high_urgency_under_15min": 11597.6,
                    "par_medium_urgency_15_60min": 58015.5,
                    "par_low_urgency_over_60min": 98840.0},
        },
        "impact": {
            "available": True,
            "damage": {
                "total_crore_inr": 4171.78, "total_lower_crore_inr": 2920.25,
                "total_upper_crore_inr": 5423.31, "missing_sectors": [],
                "model_is_published": False,
                "sectors": {
                    "residential": {"available": True, "damage_crore_inr": 4012.72,
                                    "exposed_area_km2": 2.602, "unit_cost_inr_per_m2": 20000.0,
                                    "unit_cost_price_year": 2024},
                    "non_residential": {"available": True, "damage_crore_inr": 157.0,
                                        "exposed_area_km2": 0.151,
                                        "unit_cost_inr_per_m2": 25000.0,
                                        "unit_cost_price_year": 2024},
                    "agricultural": {"available": True, "damage_crore_inr": 2.06,
                                     "exposed_area_km2": 2.15, "unit_cost_inr_per_m2": 12.0,
                                     "unit_cost_price_year": 2024},
                },
            },
        },
        "volume_balance": None,
    }
    run.update(overrides)
    return run


def _payload(**overrides):
    payload = {
        "run": _run(),
        "params": {"name": "Khadakwasla Dam", "lat": 18.44, "lon": 73.77, "height_m": 51.3,
                   "storage_mm3": 33.5, "dam_type": "masonry_gravity", "notch_breach": True,
                   "fill_max_depth_m": 3.0},
        "solver_params": {"solver_duration_s": 10800.0, "target_resolution": 200.0},
        "roughness": {"applied": "per_cell", "is_uniform": True, "fraction_at_default": 1.0,
                      "min_n": 0.03, "max_n": 0.03, "note": "Uniform roughness."},
        "comparison": None,
        "hazard_series": None,
        "validation": None,
        "figures": [],
        "wall_clock_s": None,
        "version": "1.0.0",
    }
    payload.update(overrides)
    return payload


def _text(path: Path) -> str:
    """Every paragraph and table cell of a document, as one string."""
    document = docx.Document(str(path))
    parts = [p.text for p in document.paragraphs]
    for table in document.tables:
        for row in table.rows:
            parts.extend(cell.text for cell in row.cells)
    return "\n".join(parts)


def _build(tmp_path, payload) -> str:
    out = build_report(payload, tmp_path / "report.docx")
    assert out.exists() and out.stat().st_size > 0
    return _text(out)


class TestMissingValues:
    def test_a_null_renders_only_as_the_sanctioned_phrase(self, tmp_path):
        """A document full of 0.0 where data is absent reads as measurement."""
        sparse = _run(solver_backend=None, engine=None, grid={}, ensemble={},
                      hazard_summary=None, population_at_risk=None, impact=None,
                      gauges=[], dem_used=None)
        text = _build(tmp_path, _payload(run=sparse, params={}, solver_params={},
                                         roughness=None))
        assert NOT_RECORDED in text
        import re

        for forbidden in FORBIDDEN_FOR_NULL:
            assert not re.search(rf"(?<![A-Za-z]){re.escape(forbidden)}(?![A-Za-z])", text), (
                f"a missing value rendered as {forbidden!r}")

    def test_a_price_year_is_not_a_quantity(self):
        """Measured: fmt grouped it as 2,024, in the line that exists to be divided out."""
        assert fmt_year(2024) == "2024"
        assert fmt_year(None) == NOT_RECORDED

    def test_a_measured_zero_is_still_zero(self):
        """Zero extreme cells is the flagship's finding, not a missing figure."""
        assert fmt(0) == "0"
        assert fmt(0.0, "MCM", 3) == "0.000 MCM"
        assert fmt(None) == NOT_RECORDED
        assert fmt(float("nan")) == NOT_RECORDED
        assert fmt_duration(0) == "0 s"
        assert fmt_duration(None) == NOT_RECORDED

    def test_volume_balance_absent_says_so_and_present_prints_the_numbers(self, tmp_path):
        without = _build(tmp_path, _payload())
        assert "Volume balance" in without

        balance = {"available": True, "released_mcm": 85.314, "exited_mcm": 82.219,
                   "retained_mcm": 3.09, "retained_fraction": 0.0362,
                   "closure_error": 6.5e-05, "n_members": 6}
        with_balance = _build(tmp_path, _payload(run=_run(volume_balance=balance)))
        assert "85.314" in with_balance and "82.219" in with_balance


class TestHonesty:
    def test_a_synthetic_run_says_so_and_does_not_call_itself_a_result(self, tmp_path):
        text = _build(tmp_path, _payload(run=_run(
            is_synthetic=True, synthetic_note="No solver ran; the wave was painted.")))
        assert "SYNTHETIC" in text
        assert "This document is not a result." in text
        assert "No solver ran; the wave was painted." in text

    def test_an_unverified_regression_is_named(self, tmp_path):
        run = _run()
        run["ensemble"] = {**run["ensemble"], "uses_unverified_regression": True,
                           "unverified_regressions": ["xu_zhang_2009"],
                           "unverified_regression_note": "Over-predicts Teton by 5.5x."}
        text = _build(tmp_path, _payload(run=run))
        assert "xu_zhang_2009" in text
        assert "Over-predicts Teton by 5.5x." in text

    def test_a_boundary_shaped_gauge_is_flagged_by_name(self, tmp_path):
        run = _run()
        run["gauges"][0] = {**run["gauges"][0], "near_boundary": True,
                            "boundary_clearance_km": 3.0}
        lines = honesty_lines(_payload(run=run))
        assert any("Deccan Gymkhana" in line and "domain edge" in line for line in lines)

    def test_a_minority_arrival_note_reaches_the_honesty_page(self, tmp_path):
        run = _run()
        run["gauges"][0] = {**run["gauges"][0],
                            "note": "MINORITY ARRIVAL: 1 of 4 ensemble members reached this gauge."}
        lines = honesty_lines(_payload(run=run))
        assert any("MINORITY ARRIVAL" in line for line in lines)

    def test_unit_costs_travel_with_every_rupee_figure(self, tmp_path):
        text = _build(tmp_path, _payload())
        assert "20,000 INR/m2" in text and "2024 prices" in text
        assert "UNPUBLISHED" in text

    def test_a_withheld_total_names_the_missing_sectors(self, tmp_path):
        run = _run()
        run["impact"]["damage"] = {**run["impact"]["damage"], "total_crore_inr": None,
                                   "total_lower_crore_inr": None, "total_upper_crore_inr": None,
                                   "missing_sectors": ["agricultural"]}
        text = _build(tmp_path, _payload(run=run))
        assert "agricultural" in text
        assert "fabricated" in text

    def test_the_honesty_page_is_page_two_not_an_appendix(self, tmp_path):
        text = _build(tmp_path, _payload(run=_run(is_synthetic=True)))
        assert text.index("What this run does not claim") < text.index("Inputs and provenance")


class TestGaugesAndEngines:
    def test_a_no_arrival_gauge_reads_not_assessed(self, tmp_path):
        text = _build(tmp_path, _payload())
        assert "Not assessed" in text
        assert "It does not mean safe." in text

    def test_delft3d_is_named_only_when_the_binary_ran(self, tmp_path):
        ran = _build(tmp_path, _payload(comparison={
            "delft3d_binary_used": True,
            "delft3d_engine_label": "Delft3D FM (official dflowfm binary)",
            "metrics": {"rmse_m": 0.8, "bias_m": -0.057},
            "gauge_comparison": [], "sph_near_field": {}}))
        assert "Delft3D FM (official dflowfm binary)" in ran

        fell_back = _build(tmp_path, _payload(comparison={
            "delft3d_binary_used": False,
            "delft3d_fallback_reason": "kernel not found"}))
        assert "NOT Delft3D FM" in fell_back
        assert "kernel not found" in fell_back

    def test_validation_is_dated_and_not_claimed_as_this_run(self, tmp_path):
        text = _build(tmp_path, _payload(validation={
            "generated_at": "2026-09-11T20:53:51Z",
            "checks": [{"name": "Lake at rest", "passed": True, "detail": "5.08e-14 m/s"}]}))
        assert "2026-09-11T20:53:51Z" in text
        assert "property of the build, not of this run" in text


def test_a_missing_figure_file_is_skipped_not_faked(tmp_path):
    text = _build(tmp_path, _payload(figures=[{"path": str(tmp_path / "nope.png"),
                                               "caption": "Peak wet extent"}]))
    assert "Figures" in text
    assert "no keyframe imagery on disk" in text


def test_a_corridor_line_without_its_volume_does_not_read_as_a_number(tmp_path):
    """Measured on the flagship: "removing not recorded for this run of closed capacity"."""
    lines = honesty_lines(_payload(params={"condition_corridor_m": 10.0,
                                           "terrain_modified": True}))
    corridor = next(line for line in lines if "TERRAIN WAS MODIFIED" in line)
    assert "removing not recorded" not in corridor
    assert "the volume removed was not recorded" in corridor
