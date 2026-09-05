import React from "react";

/**
 * The headline numbers of the loaded run, above the tabs.
 *
 * WHAT THIS IS NOT
 * ----------------
 * It computes nothing. Every tile is a projection of a field already in the
 * result — first arrival from `gauges`, peak outflow from `ensemble`, the
 * headcount from `population_at_risk`, the engine from `engine` — so it cannot
 * disagree with the panel the number came from. If a tile is ever seen to
 * contradict its tab, the fix belongs in the backend, not here.
 *
 * WHY IT EXISTS
 * -------------
 * All of these already existed, one tab each. A viewer who never left the
 * 2D + 3D tab — which, in a five-minute demo, is most of them — saw none of the
 * numbers the system exists to produce.
 *
 * WHAT IT REFUSES TO DO
 * ---------------------
 * Show a figure that was not computed. "No population figure" is rendered as
 * its own state in the muted style, never as a zero and never as a dash that
 * could be mistaken for one: an invented headcount under a "people at risk"
 * heading is the worst number this project could put on a screen. Same for the
 * engine label — it reads `engine.delft3d_binary_used`, so a run that fell back
 * to the built-in solver can never be labelled Delft3D FM.
 */
export default function RunSummaryBar({ result }) {
  if (!result) return null;

  const gauges = result.gauges || [];
  const arrived = gauges
    .filter((g) => g.arrival_time_s != null)
    .sort((a, b) => a.arrival_time_s - b.arrival_time_s);
  const first = arrived[0];
  const ensemble = result.ensemble || {};
  const par = result.population_at_risk;

  return (
    <div className="kpi-bar">
      <Kpi
        label={first ? `First arrival — ${first.gauge_name}` : "First arrival"}
        value={first ? formatDuration(first.arrival_time_s) : "no gauge reached"}
        tone={first ? "data" : "none"}
        sub={
          first
            ? `${fmt(first.distance_km, 1)} km downstream${
                bandOf(first) ? ` · ${bandOf(first)}` : ""}`
            : "within the simulated time"
        }
      />

      <Kpi
        label="Gauges reached"
        value={gauges.length ? `${arrived.length} / ${gauges.length}` : "—"}
        tone={arrived.length ? "data" : "none"}
        sub={
          // A minority arrival is the ensemble's own caveat and it travels with
          // the gauge row. Surfacing it here matters more than anywhere else:
          // this strip is read first and quoted second.
          first?.note ? "see Gauges tab for the arrival note" : "in the run's corridor"
        }
      />

      <Kpi
        label="Peak breach outflow"
        value={
          ensemble.q_peak_median_m3s != null
            ? `${num(ensemble.q_peak_median_m3s)} m³/s`
            : "not recorded"
        }
        tone={ensemble.q_peak_median_m3s != null ? "data" : "none"}
        sub={
          ensemble.q_peak_p05_m3s != null && ensemble.q_peak_p95_m3s != null
            ? `p05–p95 ${num(ensemble.q_peak_p05_m3s)} – ${num(ensemble.q_peak_p95_m3s)}`
            : "ensemble median"
        }
        // The dam-class caveat outranks the number it qualifies: where it is
        // set, the figure comes from regressions fitted on a different kind of
        // structure. It is read from EITHER carrier — the backend puts it on
        // `ensemble` and the sidebar warning reads it off `hazard_summary`, and
        // a run that has it in one place and not the other must still show it.
        warn={
          ensemble.dam_class_outside_fitted_population ||
          result.hazard_summary?.dam_class_outside_fitted_population
            ? "screening figure — dam class outside fitted population"
            : null
        }
      />

      <Kpi
        label="Population at risk"
        value={
          par?.available
            ? num(par.par?.total_par)
            : par
              ? "no figure"
              : "not computed"
        }
        tone={par?.available ? "data" : "none"}
        sub={
          par?.available
            ? `of ${num(par.total_population_in_domain)} in the domain`
            : par?.reason
              ? "no estimate is substituted"
              : "run with Earth Engine configured"
        }
      />

      <Kpi
        label="Engine"
        tone="text"
        value={engineLabel(result)}
        sub={engineSub(result)}
        warn={result.engine?.fallback_reason || null}
      />
    </div>
  );
}

function Kpi({ label, value, sub, tone, warn }) {
  const valueClass =
    tone === "data" ? "kpi-value kpi-value--data"
      : tone === "none" ? "kpi-value kpi-value--none"
        : tone === "text" ? "kpi-value kpi-value--text"
          : "kpi-value";
  return (
    <div className="kpi" title={warn || undefined}>
      <div className="kpi-label">{label}</div>
      <div className={valueClass}>{value}</div>
      <div className={`kpi-sub${warn ? " kpi-sub--warn" : ""}`}>{warn || sub}</div>
    </div>
  );
}

/**
 * Which engine produced these numbers — the CLAUDE.md naming rule, in one place.
 *
 * `delft3d_binary_used === true` is the only condition under which the words
 * "Delft3D FM" may appear. False means the built-in solver ran, and the label
 * says so; the `fallback_reason` then shows as the caveat line. Anything else
 * (an older run with no engine record) is described by the requested solver
 * alone, which is a statement about what was asked for, not about what ran.
 */
function engineLabel(result) {
  const engine = result.engine;
  if (engine?.delft3d_binary_used === true) return "Delft3D FM";
  if (engine?.delft3d_binary_used === false) return "JalRaksha 2D SWE";
  if (engine?.label) return engine.label;
  return SOLVER_LABELS[result.solver] || result.solver || "—";
}

function engineSub(result) {
  const engine = result.engine;
  if (engine?.delft3d_binary_used === true) return "dflowfm-cli, dimrset 2026.01";
  if (engine?.delft3d_binary_used === false) return "Delft3D-class — NOT Delft3D FM";
  return SOLVER_SUBS[result.solver] || "requested solver";
}

const SOLVER_LABELS = {
  swe: "JalRaksha 2D SWE",
  sph: "JalRaksha 2D SWE + SPH",
  delft3d: "Delft3D FM (requested)",
  both: "SWE + Delft3D FM (requested)",
};

const SOLVER_SUBS = {
  swe: "Delft3D-class — NOT Delft3D FM",
  sph: "far-field SWE, near-field handoff",
  delft3d: "engine not recorded for this run",
  both: "engine not recorded for this run",
};

/** The gauge's own uncertainty band, when the run recorded one. */
function bandOf(gauge) {
  if (gauge.arrival_p05_s == null || gauge.arrival_p95_s == null) return null;
  return `p05–p95 ${formatDuration(gauge.arrival_p05_s)} – ${formatDuration(gauge.arrival_p95_s)}`;
}

function formatDuration(seconds) {
  if (seconds == null) return "—";
  const minutes = seconds / 60;
  if (minutes < 60) return `${minutes.toFixed(1)} min`;
  return `${Math.floor(minutes / 60)}h ${Math.round(minutes % 60)}m`;
}

function num(value) {
  return typeof value === "number" ? Math.round(value).toLocaleString() : "—";
}

function fmt(value, digits) {
  return typeof value === "number" ? value.toFixed(digits) : "—";
}
