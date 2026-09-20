"""
The run report, as a Word document (Phase 5 export).

WHAT THIS MODULE IS ALLOWED TO DO
---------------------------------
Print what a run recorded, and say so when it recorded nothing. It computes no
hydraulics, re-derives no coefficient and substitutes no default: every value
here was read from that run's own artifacts by the caller and passed in. A
field the run never wrote renders as ``NOT_RECORDED`` — never 0.0, never a bare
dash, never "TBD". A reader must be able to tell "this run measured zero" from
"nobody measured this", because those are different claims and only one of them
is evidence.

That rule is the whole point of the document. A dossier that drops the honesty
labels is worse than no dossier: it launders them out of the record, and the
labels are the thing no competing screening tool here can match.

LAYERING
--------
Pure library. It imports python-docx and the standard library, and nothing from
``jalraksha_service``, ``jalraksha.gee`` or ``jalraksha.impact`` — the caller
assembles the payload (services/api/jalraksha_service/main.py::generate_report),
which is the same seam ``damage.py`` uses to stay testable with no network.

python-docx is an OPTIONAL dependency (the ``[report]`` extra). Importing this
module without it raises ``ReportUnavailableError`` naming the install command,
so the endpoint answers with that sentence instead of a traceback.
"""

from __future__ import annotations

import datetime as _dt
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

#: The one string a missing value may render as. Same wording as the
#: Provenance tab (frontend/src/provenance.js), so the document and the screen
#: describe an absent field identically.
NOT_RECORDED = "not recorded for this run"

#: Product name, kept in one place so it travels with a rename.
PRODUCT_NAME = "JalRaksha"

_INSTALL_HINT = (
    "python-docx is not installed. Install it with: pip install -e \".[report]\" "
    "(or pip install python-docx)."
)


class ReportUnavailableError(RuntimeError):
    """python-docx is missing, so no document can be written."""


def _docx():
    """Import python-docx, or refuse with the install command."""
    try:
        import docx  # noqa: F401
        from docx import Document  # noqa: F401
        from docx.enum.text import WD_ALIGN_PARAGRAPH  # noqa: F401
        from docx.shared import Inches, Pt, RGBColor  # noqa: F401
    except ImportError as exc:  # pragma: no cover - exercised by the endpoint
        raise ReportUnavailableError(_INSTALL_HINT) from exc
    return docx


# --------------------------------------------------------------------------- #
# Value rendering
# --------------------------------------------------------------------------- #

def fmt(value: Any, unit: str = "", digits: Optional[int] = None) -> str:
    """
    One value as the document prints it.

    None, NaN and an empty string are all "not recorded". A real zero prints as
    zero — a measured zero is a result (the flagship run reaches zero extreme
    cells, which is the finding), and blurring it into "missing" would destroy
    exactly the distinction this module exists to keep.
    """
    if value is None or value == "":
        return NOT_RECORDED
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (int, float)):
        number = float(value)
        if number != number or number in (float("inf"), float("-inf")):
            return NOT_RECORDED
        if digits is None:
            text = f"{int(number):,}" if float(number).is_integer() else f"{number:,.3f}"
        else:
            text = f"{number:,.{digits}f}"
        return f"{text} {unit}".strip()
    if isinstance(value, (list, tuple)):
        return ", ".join(str(v) for v in value) if value else NOT_RECORDED
    return f"{value} {unit}".strip()


def fmt_year(value: Any) -> str:
    """
    A year, ungrouped.

    ``fmt`` groups thousands, which is right for a headcount and wrong for a
    price year: 2024 printed as "2,024" reads as a quantity and undermines the
    very line it appears in, where the unit cost is published so a reader can
    divide it back out.
    """
    if value is None or value == "":
        return NOT_RECORDED
    try:
        return str(int(value))
    except (TypeError, ValueError):
        return str(value)


def fmt_duration(seconds: Any) -> str:
    """Seconds as 'X h Y min (N s)', or not recorded."""
    if seconds is None:
        return NOT_RECORDED
    try:
        total = float(seconds)
    except (TypeError, ValueError):
        return NOT_RECORDED
    if total != total:
        return NOT_RECORDED
    if total < 60:
        return f"{total:.0f} s"
    minutes = total / 60.0
    if minutes < 60:
        return f"{minutes:.0f} min ({total:,.0f} s)"
    return f"{int(minutes // 60)} h {int(round(minutes % 60))} min ({total:,.0f} s)"


def _get(mapping: Optional[Dict[str, Any]], *path: str) -> Any:
    """Nested lookup that tolerates every level being absent."""
    current: Any = mapping
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


# --------------------------------------------------------------------------- #
# Document primitives
# --------------------------------------------------------------------------- #

def _heading(document, text: str, level: int = 1) -> None:
    document.add_heading(text, level=level)


def _para(document, text: str, *, bold: bool = False, italic: bool = False,
          color: Optional[Tuple[int, int, int]] = None, size_pt: Optional[int] = None):
    from docx.shared import Pt, RGBColor

    paragraph = document.add_paragraph()
    run = paragraph.add_run(text)
    run.bold = bold
    run.italic = italic
    if color is not None:
        run.font.color.rgb = RGBColor(*color)
    if size_pt is not None:
        run.font.size = Pt(size_pt)
    return paragraph


def _bullets(document, lines: Iterable[str]) -> None:
    for line in lines:
        document.add_paragraph(str(line), style="List Bullet")


def _kv_table(document, rows: Sequence[Tuple[str, str]]) -> None:
    """A two-column key/value table. Rows whose value is None are still shown."""
    if not rows:
        return
    table = document.add_table(rows=0, cols=2)
    table.style = "Table Grid"
    for label, value in rows:
        cells = table.add_row().cells
        cells[0].text = str(label)
        cells[1].text = str(value)
    document.add_paragraph()


def _grid_table(document, headers: Sequence[str], rows: Sequence[Sequence[str]]) -> None:
    table = document.add_table(rows=1, cols=len(headers))
    table.style = "Table Grid"
    for index, header in enumerate(headers):
        cell = table.rows[0].cells[index]
        cell.text = str(header)
        for paragraph in cell.paragraphs:
            for run in paragraph.runs:
                run.bold = True
    for row in rows:
        cells = table.add_row().cells
        for index, value in enumerate(row):
            cells[index].text = str(value)
    document.add_paragraph()


def _page_break(document) -> None:
    from docx.enum.text import WD_BREAK

    document.add_paragraph().add_run().add_break(WD_BREAK.PAGE)


# --------------------------------------------------------------------------- #
# Sections
# --------------------------------------------------------------------------- #

def _cover(document, report: Dict[str, Any]) -> None:
    run = report.get("run") or {}
    params = report.get("params") or {}
    solver_params = report.get("solver_params") or {}
    grid = run.get("grid") or {}
    backend = run.get("solver_backend") or {}
    engine = run.get("engine") or {}

    _heading(document, f"{PRODUCT_NAME} — dam-break screening report", level=0)
    _para(document, fmt(run.get("dam_name")), bold=True, size_pt=14)
    if run.get("is_synthetic"):
        _para(document,
              "SYNTHETIC — NOT A REAL SIMULATION. No solver ran for this run; "
              "the flood shown was prescribed. This document is not a result.",
              bold=True, color=(0xB0, 0x00, 0x00))

    _kv_table(document, [
        ("Run id", fmt(run.get("run_id"))),
        ("Generated at", fmt(report.get("generated_at"))),
        ("Scenario", fmt(_get(run, "ensemble", "scenario_type") or params.get("scenario_type"))),
        ("Solver requested", fmt(run.get("solver"))),
        ("Computed on", fmt(backend.get("solver_backend_label"))),
        ("Engine", fmt(engine.get("label") or engine.get("name"))),
        ("Grid", (f"{grid['nx']} x {grid['ny']} cells at {fmt(grid.get('dx'), 'm')}"
                  if grid.get("nx") and grid.get("ny") else NOT_RECORDED)),
        ("CRS", fmt(grid.get("crs"))),
        ("Simulated duration", fmt_duration(solver_params.get("solver_duration_s"))),
        ("Ensemble members",
         (f"{_get(run, 'ensemble', 'num_completed')} of {_get(run, 'ensemble', 'num_ensemble')}"
          if _get(run, "ensemble", "num_ensemble") is not None else NOT_RECORDED)),
        ("Wall clock", fmt_duration(report.get("wall_clock_s"))),
        (f"{PRODUCT_NAME} version", fmt(report.get("version"))),
    ])
    _para(document,
          "Tier-1 screening output over 30 m Copernicus GLO-30 terrain. Read the "
          "arrival times and the inundation envelope; point depths are indicative only.",
          italic=True)


def honesty_lines(report: Dict[str, Any]) -> List[str]:
    """
    Every honesty label this run carries, as sentences.

    Pure and public so the tests can assert on the labels without parsing a
    document: each line here is one thing about the run a reader must not miss.
    """
    run = report.get("run") or {}
    params = report.get("params") or {}
    ensemble = run.get("ensemble") or {}
    impact = run.get("impact") or {}
    par = run.get("population_at_risk") or {}
    lines: List[str] = []

    if run.get("is_synthetic"):
        lines.append(
            "SYNTHETIC RUN — no solver ran. " + fmt(run.get("synthetic_note")))

    if ensemble.get("uses_unverified_regression"):
        names = ", ".join(ensemble.get("unverified_regressions") or []) or NOT_RECORDED
        lines.append(
            f"An UNVERIFIED breach regression contributed members: {names}. "
            + fmt(ensemble.get("unverified_regression_note")))
    if ensemble.get("dam_class_outside_fitted_population"):
        lines.append(
            "The dam class is OUTSIDE the regressions' fitted population. "
            + fmt(ensemble.get("dam_class_note")))

    directives = [g.get("evacuation") for g in (run.get("gauges") or []) if g.get("evacuation")]
    unvetted = next((d for d in directives if d.get("thresholds_unvetted")), None)
    if unvetted:
        lines.append(
            "Evacuation directives use UNVETTED thresholds: "
            f"{fmt(unvetted.get('threshold_source'))}. They order gauges for "
            "attention and are not evacuation orders.")

    if params.get("terrain_modified") or params.get("condition_corridor_m"):
        removed = _get(report, "hazard_series", "corridor_volume_removed_mcm")
        grid = run.get("grid") or {}
        extent = (f"{grid.get('nx')} x {grid.get('ny')} cells at {fmt(grid.get('dx'), 'm')}"
                  if grid.get("nx") else NOT_RECORDED)
        # The removed volume is only meaningful WITH its domain and resolution
        # (CLAUDE.md: quote a corridor figure with both or not at all), and it
        # is usually absent, so the clause is dropped rather than filled with a
        # phrase where a number belongs.
        removed_clause = (
            f", removing {fmt(removed, 'MCM')} of closed capacity on this domain ({extent})"
            if removed is not None else
            f" on this domain ({extent}); the volume removed was not recorded")
        lines.append(
            "TERRAIN WAS MODIFIED — corridor conditioning at "
            f"{fmt(params.get('condition_corridor_m'), 'm')}{removed_clause}. "
            + fmt(params.get("terrain_note")))

    if run.get("dem_update"):
        lines.append(
            "The DEM was CONDITIONED ON AN OBSERVATION, not surveyed: "
            + fmt(_get(run, "dem_update", "not_a_survey")))

    near = [g for g in (run.get("gauges") or []) if g.get("near_boundary")]
    for gauge in near:
        lines.append(
            f"{fmt(gauge.get('gauge_name'))} sits "
            f"{fmt(gauge.get('boundary_clearance_km'), 'km')} from the domain edge; its "
            "depth and arrival are shaped by the outflow boundary as well as by the flood.")

    for gauge in (run.get("gauges") or []):
        note = gauge.get("note") or ""
        if note.startswith("MINORITY ARRIVAL"):
            lines.append(f"{fmt(gauge.get('gauge_name'))}: {note}")

    if par:
        if par.get("available"):
            lines.append(
                "Population at risk comes from "
                f"{fmt(par.get('population_source'))} (epoch {fmt(par.get('population_epoch'))}). "
                "Figures written before the 2026-09-06 aggregation fix are low by the square "
                "of the ratio between the solver grid and 100 m, and were not retroactively "
                "corrected (verification row 37).")
        else:
            lines.append("No population-at-risk figure: " + fmt(par.get("reason")))

    damage = impact.get("damage") or {}
    if damage:
        if damage.get("model_is_published") is False:
            sectors = damage.get("sectors") or {}
            costs = sorted({
                f"{name}: {fmt(block.get('unit_cost_inr_per_m2'))} INR/m2 "
                f"({fmt_year(block.get('unit_cost_price_year'))} prices)"
                for name, block in sectors.items() if block.get("available")
            })
            lines.append(
                "Economic damage uses an UNPUBLISHED depth-damage curve on UNVETTED unit "
                "costs (verification rows 35 and 36). The exposure is measured; the cost per "
                "square metre is not. Unit costs, so a reader can divide them back out — "
                + ("; ".join(costs) if costs else NOT_RECORDED))
        if damage.get("missing_sectors"):
            lines.append(
                "The damage total is WITHHELD because these sectors could not be fetched: "
                + ", ".join(damage["missing_sectors"]))

    return lines


def _honesty_page(document, report: Dict[str, Any]) -> None:
    _page_break(document)
    _heading(document, "What this run does not claim", level=1)
    _para(document,
          "Second page, never an appendix. Every line below is a label the run itself "
          "recorded; none is editorial.", italic=True)
    lines = honesty_lines(report)
    if lines:
        _bullets(document, lines)
    else:
        _para(document,
              "This run raised no run-level honesty flag. The standing limitations in "
              "\"Limitations\" still apply.")


def _inputs(document, report: Dict[str, Any]) -> None:
    run = report.get("run") or {}
    params = report.get("params") or {}
    solver_params = report.get("solver_params") or {}
    ensemble = run.get("ensemble") or {}
    roughness = report.get("roughness") or {}

    _heading(document, "Inputs and provenance", level=1)
    _kv_table(document, [
        ("Dam / site", fmt(params.get("name"))),
        ("Location (lat, lon)",
         (f"{fmt(params.get('lat'))}, {fmt(params.get('lon'))}"
          if params.get("lat") is not None else NOT_RECORDED)),
        ("Dam type", fmt(params.get("dam_type") or ensemble.get("dam_type"))),
        ("Height", fmt(params.get("height_m"), "m")),
        ("Gross storage", fmt(params.get("storage_mm3"), "MCM")),
        ("Breach mode", fmt(params.get("breach_mode"))),
        ("Breach notch cut into the bed", fmt(params.get("notch_breach"))),
        ("Depression fill cap", fmt(params.get("fill_max_depth_m"), "m")),
        ("Corridor conditioning", fmt(params.get("condition_corridor_m"), "m")),
        ("Target resolution", fmt(solver_params.get("target_resolution"), "m")),
        ("DEM used", fmt(run.get("dem_used"))),
    ])

    _heading(document, "Breach ensemble", level=2)
    _kv_table(document, [
        ("Regressions used", fmt(ensemble.get("regressions_used"))),
        ("Peak outflow, median", fmt(ensemble.get("q_peak_median_m3s"), "m3/s", 1)),
        ("Peak outflow, 5th-95th",
         (f"{fmt(ensemble.get('q_peak_p05_m3s'), 'm3/s', 1)} - "
          f"{fmt(ensemble.get('q_peak_p95_m3s'), 'm3/s', 1)}"
          if ensemble.get("q_peak_p05_m3s") is not None else NOT_RECORDED)),
        ("Failure time, median", fmt_duration(ensemble.get("t_fail_median_s"))),
        ("Members converged",
         (f"{ensemble.get('num_completed')} of {ensemble.get('num_ensemble')}"
          if ensemble.get("num_ensemble") is not None else NOT_RECORDED)),
    ])

    _heading(document, "Roughness field", level=2)
    if roughness:
        _kv_table(document, [
            ("Applied", fmt(roughness.get("applied"))),
            ("Uniform", fmt(roughness.get("is_uniform"))),
            ("Fraction at the default n", fmt(roughness.get("fraction_at_default"), "", 3)),
            ("Range", (f"{fmt(roughness.get('min_n'))} - {fmt(roughness.get('max_n'))}"
                       if roughness.get("min_n") is not None else NOT_RECORDED)),
            ("Note", fmt(roughness.get("note"))),
        ])
    else:
        _para(document, f"Roughness field: {NOT_RECORDED}. Runs written before "
                        "2026-09-12 did not record it.")


def _results(document, report: Dict[str, Any]) -> None:
    run = report.get("run") or {}
    balance = run.get("volume_balance") or _get(report, "hazard_series", "volume_balance")
    verdict = _get(report, "hazard_series", "verdict") or {}
    hazard = run.get("hazard_summary") or {}

    _heading(document, "Results", level=1)

    _heading(document, "Where the water went", level=2)
    _para(document,
          "Read this before any hazard count. The transmissive domain boundary is the only "
          "exit this model has, so a run that exported no water never tested drainage, "
          "whatever its hazard classes say.", italic=True)
    if balance and balance.get("available"):
        _kv_table(document, [
            ("Released", fmt(balance.get("released_mcm"), "MCM", 3)),
            ("Exited the domain", fmt(balance.get("exited_mcm"), "MCM", 3)),
            ("Retained", fmt(balance.get("retained_mcm"), "MCM", 3)),
            ("Retained fraction", fmt(balance.get("retained_fraction"), "", 4)),
            ("Closure error", fmt(balance.get("closure_error"), "", 6)),
            ("Members contributing", fmt(balance.get("n_members"))),
        ])
    elif balance:
        _para(document, "Volume balance unavailable: " + fmt(balance.get("reason")))
    else:
        _para(document,
              f"Volume balance: {NOT_RECORDED}. It is computed per run but was only "
              "persisted from 2026-09-20; earlier runs discarded it when they finished.")

    if verdict:
        _kv_table(document, [
            ("Zero severe and extreme cells at", fmt_duration(verdict.get("safe_at_s"))),
            ("Fully dry at", fmt_duration(verdict.get("fully_green_at_s"))),
        ])

    _heading(document, "Hazard classes, final frame", level=2)
    if hazard:
        rows = []
        for level in ("dry", "low", "moderate", "significant", "extreme"):
            block = hazard.get(level) or {}
            rows.append([level, fmt(block.get("count")), fmt(block.get("percentage"), "%", 3)])
        legacy = hazard.get("severe") or {}
        if legacy:
            rows.append(["severe (retired class, pre-2026-09-11 run)",
                         fmt(legacy.get("count")), fmt(legacy.get("percentage"), "%", 3)])
        _grid_table(document, ["FD2320 class", "cells", "share of domain"], rows)
        _para(document, "Scheme: " + fmt(hazard.get("scheme")) +
                        ", debris factor " + fmt(hazard.get("debris_factor")), italic=True)
    else:
        _para(document, f"Hazard classification: {NOT_RECORDED}.")

    _heading(document, "Peak depth across the domain", level=2)
    stats = _get(run, "ensemble", "h_max_stats") or {}
    _kv_table(document, [
        ("Median member", fmt(stats.get("median"), "m", 2)),
        ("5th percentile", fmt(stats.get("p05"), "m", 2)),
        ("95th percentile", fmt(stats.get("p95"), "m", 2)),
    ])


def _gauges(document, report: Dict[str, Any]) -> None:
    run = report.get("run") or {}
    gauges = run.get("gauges") or []

    _heading(document, "Gauges and evacuation directives", level=1)
    if not gauges:
        _para(document, f"Gauge results: {NOT_RECORDED}.")
        return

    rows = []
    for gauge in gauges:
        directive = gauge.get("evacuation") or {}
        band = (f"{fmt_duration(gauge.get('arrival_p05_s'))} - "
                f"{fmt_duration(gauge.get('arrival_p95_s'))}"
                if gauge.get("arrival_p05_s") is not None else NOT_RECORDED)
        rows.append([
            fmt(gauge.get("gauge_name")),
            fmt(gauge.get("distance_km"), "km", 1),
            fmt_duration(gauge.get("arrival_time_s")),
            band,
            fmt(gauge.get("max_depth_m"), "m", 2),
            fmt(directive.get("hazard_level")),
            fmt(directive.get("label")),
        ])
    _grid_table(document,
                ["Gauge", "Distance", "Arrival (median)", "5th-95th", "Peak depth",
                 "Hazard", "Directive"],
                rows)

    notes = [f"{fmt(g.get('gauge_name'))}: {g['note']}" for g in gauges if g.get("note")]
    if notes:
        _para(document, "Per-gauge notes", bold=True)
        _bullets(document, notes)
    _para(document,
          "\"Not assessed\" means the flood did not reach the gauge within the simulated "
          "time, or the gauge lies outside the solver domain. It does not mean safe.",
          italic=True)


def _impact(document, report: Dict[str, Any]) -> None:
    run = report.get("run") or {}
    par = run.get("population_at_risk") or {}
    impact = run.get("impact") or {}
    damage = impact.get("damage") or {}

    _heading(document, "Impact", level=1)

    _heading(document, "Population at risk", level=2)
    if not par:
        _para(document, f"Population at risk: {NOT_RECORDED}.")
    elif not par.get("available"):
        _para(document, "No population-at-risk figure: " + fmt(par.get("reason")))
        _para(document, "No estimate is substituted.", italic=True)
    else:
        buckets = par.get("par") or {}
        _kv_table(document, [
            ("Total at risk", fmt(buckets.get("total_par"), "people", 0)),
            ("Under 15 min warning", fmt(buckets.get("par_high_urgency_under_15min"), "people", 0)),
            ("15-60 min", fmt(buckets.get("par_medium_urgency_15_60min"), "people", 0)),
            ("Over 60 min", fmt(buckets.get("par_low_urgency_over_60min"), "people", 0)),
            ("Exposed (cells at or above 0.1 m)",
             fmt(_get(par, "exposure", "total_exposed_population"), "people", 0)),
            ("Population in domain", fmt(par.get("total_population_in_domain"), "people", 0)),
            ("Warning lead time assumed", fmt_duration(par.get("warning_lead_time_s"))),
            ("Source", fmt(par.get("population_source"))),
        ])

    _heading(document, "Economic damage", level=2)
    if not damage:
        _para(document, f"Damage estimate: {NOT_RECORDED}.")
        return
    sectors = damage.get("sectors") or {}
    rows = []
    for name in ("residential", "non_residential", "agricultural"):
        block = sectors.get(name) or {}
        if not block:
            rows.append([name, NOT_RECORDED, NOT_RECORDED, NOT_RECORDED])
        elif block.get("available"):
            rows.append([
                name,
                fmt(block.get("damage_crore_inr"), "crore INR", 1),
                fmt(block.get("exposed_area_km2"), "km2", 3),
                fmt(block.get("unit_cost_inr_per_m2"), "INR/m2", 0)
                + f" ({fmt_year(block.get('unit_cost_price_year'))} prices)",
            ])
        else:
            rows.append([name, "refused - " + fmt(block.get("reason")), NOT_RECORDED, NOT_RECORDED])
    _grid_table(document, ["Sector", "Damage", "Exposed area", "Unit cost"], rows)

    if damage.get("total_crore_inr") is not None:
        _kv_table(document, [
            ("Total", fmt(damage.get("total_crore_inr"), "crore INR", 1)),
            ("Band", (f"{fmt(damage.get('total_lower_crore_inr'), 'crore INR', 1)} - "
                      f"{fmt(damage.get('total_upper_crore_inr'), 'crore INR', 1)}"
                      if damage.get("total_lower_crore_inr") is not None else NOT_RECORDED)),
        ])
    else:
        _para(document,
              "No total is given, because these sectors could not be fetched: "
              + (", ".join(damage.get("missing_sectors") or []) or NOT_RECORDED)
              + ". Totalling with a sector silently zero would publish a fabricated figure.")
    _para(document,
          "The depth-damage curve is UNPUBLISHED (model_is_published: false) and the unit "
          "costs above are UNVETTED placeholders, printed so a reader can divide them back "
          "out. Quote the total as an order of magnitude.", italic=True)


def _validation(document, report: Dict[str, Any]) -> None:
    validation = report.get("validation") or {}
    comparison = report.get("comparison") or {}

    _heading(document, "Validation", level=1)
    checks = validation.get("checks") or []
    if checks:
        _para(document,
              "The blocking gates as they last ran on this machine, at "
              + fmt(validation.get("generated_at"))
              + ". They are a property of the build, not of this run.", italic=True)
        _grid_table(document, ["Check", "Passed", "Detail"],
                    [[fmt(c.get("name")), fmt(c.get("passed")), fmt(c.get("detail"))]
                     for c in checks])
    else:
        _para(document, f"Validation gates: {NOT_RECORDED} on this machine.")

    _heading(document, "Cross-check against Delft3D FM", level=2)
    if comparison.get("delft3d_binary_used"):
        metrics = comparison.get("metrics") or {}
        _para(document, "Engine: " + fmt(comparison.get("delft3d_engine_label")))
        _kv_table(document, [
            ("Depth-field RMSE", fmt(metrics.get("rmse_m"), "m", 3)),
            ("Bias", fmt(metrics.get("bias_m"), "m", 3)),
            ("Gauge arrivals read from", fmt(comparison.get("gauge_arrival_method"))),
        ])
        rows = [[fmt(g.get("gauge")), fmt(g.get("distance_km"), "km", 1),
                 fmt(g.get("arrival_SPH_min"), "min", 1),
                 fmt(g.get("arrival_Delft3D_min"), "min", 1)]
                for g in (comparison.get("gauge_comparison") or [])]
        if rows:
            _grid_table(document, ["Gauge", "Distance", "Near-field SPH", "Delft3D FM"], rows)
        near_field = comparison.get("sph_near_field") or {}
        if near_field:
            _para(document,
                  "Near-field SPH: " + fmt(comparison.get("sph_engine")) + ", "
                  + fmt(near_field.get("n_fluid")) + " fluid particles over "
                  + fmt(near_field.get("domain_length_m"), "m") + " for "
                  + fmt_duration(near_field.get("duration_s"))
                  + ". Coupling: " + fmt(near_field.get("coupling")) + ".")
    elif comparison:
        _para(document,
              f"{PRODUCT_NAME} built-in 2D SWE — Delft3D-class, NOT Delft3D FM. "
              + fmt(comparison.get("delft3d_fallback_reason")))
    else:
        _para(document, "No engine cross-check was run for this run.")


def _figures(document, report: Dict[str, Any]) -> None:
    from docx.shared import Inches

    figures = [f for f in (report.get("figures") or []) if Path(f.get("path", "")).exists()]
    _heading(document, "Figures", level=1)
    if not figures:
        _para(document, f"Figures: {NOT_RECORDED} (no keyframe imagery on disk for this run).")
        return
    for figure in figures:
        try:
            document.add_picture(str(figure["path"]), width=Inches(6.0))
        except Exception as exc:  # a corrupt PNG must not lose the whole document
            _para(document, f"Figure could not be embedded ({type(exc).__name__}).")
            continue
        _para(document, fmt(figure.get("caption")), italic=True, size_pt=9)


def _limitations(document, report: Dict[str, Any]) -> None:
    run = report.get("run") or {}
    _heading(document, "Limitations and citations", level=1)
    _bullets(document, [
        f"{PRODUCT_NAME} is a Tier-1 screening and prioritisation instrument, not a "
        "replacement for a surveyed Tier-2 or Tier-3 study.",
        "Terrain is 30 m Copernicus GLO-30. Arrival times and inundation extent are the "
        "defensible outputs; point depths are indicative only.",
        "The near-field SPH handoff is ONE-WAY (SWE to SPH). There is no two-way coupling.",
        "Hazard classes follow Defra/EA FD2320: HR = depth x (|V| + 0.5) + DF, classed at "
        "0.75 / 1.25 / 2.5. At a gauge only depth is known, so the depth-only reduction is "
        "used and it under-states hazard wherever the flow is fast.",
    ])
    citations = [
        ("Breach regressions", fmt(_get(run, "ensemble", "regressions_used"))),
        ("Manning's n per WorldCover class", "UNVETTED - verification log row 31"),
        ("Boundary-contamination threshold (5 km)", "UNVETTED - row 33"),
        ("Corridor-conditioning geometry", "UNVETTED - row 34"),
        ("Damage unit costs", "UNVETTED - row 35"),
        ("Depth-damage curve constants", "UNPUBLISHED - row 36"),
        ("Earth Engine aggregation of population", "FIXED 2026-09-06 - row 37"),
        ("Evacuation-directive thresholds", "UNVETTED - row 39"),
    ]
    _grid_table(document, ["Quantity", "Status"], [[a, b] for a, b in citations])
    _para(document,
          "Every row above is tracked in docs/VERIFICATION_LOG.md, which is this project's "
          "live queue of coefficients that are used but not yet traced to primary literature.",
          italic=True)


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #

def build_report(report: Dict[str, Any], out_path: Path) -> Path:
    """
    Write the report for one run.

    Args:
        report: The assembled payload. Keys: ``run`` (a RunResult dict),
            ``params`` (the run's dam_config), ``solver_params``, ``roughness``,
            ``comparison``, ``hazard_series``, ``validation``, ``figures``
            ([{path, caption}]), ``wall_clock_s``, ``version``, ``generated_at``.
            Every one of them may be absent; the document then says so.
        out_path: Where to write the .docx.

    Returns:
        ``out_path``.
    """
    _docx()
    from docx import Document

    report = dict(report or {})
    report.setdefault("generated_at", _dt.datetime.now(_dt.timezone.utc).isoformat())

    document = Document()
    _cover(document, report)
    _honesty_page(document, report)
    _page_break(document)
    _inputs(document, report)
    _results(document, report)
    _gauges(document, report)
    _impact(document, report)
    _validation(document, report)
    _figures(document, report)
    _limitations(document, report)

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    document.save(str(out_path))
    return out_path
