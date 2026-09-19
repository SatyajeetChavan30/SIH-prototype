import React from "react";
import {
  Bar, BarChart, CartesianGrid, Cell, ErrorBar, Legend, ResponsiveContainer,
  Tooltip, XAxis, YAxis,
} from "recharts";
import { LEGEND_PROPS, SERIES, TOOLTIP_PROPS } from "../ui/chartTheme.js";
import { Caveat, Empty, Stat } from "../ui/index.jsx";

/**
 * Ensemble statistics — peak outflow, breach formation time, arrival spread.
 *
 * Every number here was computed by run_dam_break_ensemble from the first day
 * and then discarded when the Celery task returned: peak outflow and its
 * 5th–95th band, the breach formation time, which published regressions were
 * used, and how many members actually converged. The dashboard could only ever
 * show a single median arrival time, which presents an ensemble result as if it
 * were a deterministic one.
 *
 * The spread is the point. The four regressions disagree with each other by a
 * factor of 3–4 — that is the documented state of the art, not a defect — so
 * the honest headline is the range, never one number.
 */
export default function EnsemblePanel({ result }) {
  const ensemble = result?.ensemble;

  if (!ensemble && result?.is_synthetic) {
    // A painted wave has no breach ensemble to report. The "predates" message
    // below would send a reader looking for a re-run that cannot exist.
    return (
      <Empty>
        This is a synthetic demo run — no solver ran, so there is no breach
        ensemble and no percentile band to show.
      </Empty>
    );
  }

  if (!ensemble) {
    // Distinguish the two reasons this is empty. The old message blamed the
    // solver unconditionally, which was wrong and misleading for the far more
    // common case: a run created BEFORE these fields existed. The Tehri demo
    // run is exactly that — a complete 21-export SWE run whose ensemble
    // statistics were computed and then discarded, because run_summary.json
    // did not exist yet. Telling the user their solver choice was wrong when
    // the real answer is "this run is old" sends them to fix the wrong thing.
    const isSwe = result?.solver === "swe" || result?.solver === "sph";
    return (
      <Empty>
        {isSwe ? (
          <>
            This run has no ensemble statistics because it predates them being
            recorded — they were computed and discarded before{" "}
            <code>run_summary.json</code> existed. Re-run the same dam to get
            the percentile bands; nothing about the solver has changed.
          </>
        ) : (
          <>
            No ensemble statistics for this run. They come from the SWE breach
            ensemble, and a <code>delft3d</code>-only run does not generate one
            — choose <strong>SWE</strong> or <strong>Both</strong>.
          </>
        )}
      </Empty>
    );
  }

  const q = {
    median: ensemble.q_peak_median_m3s,
    p05: ensemble.q_peak_p05_m3s,
    p95: ensemble.q_peak_p95_m3s,
  };
  const t = {
    median: ensemble.t_fail_median_s,
    p05: ensemble.t_fail_p05_s,
    p95: ensemble.t_fail_p95_s,
  };

  // Arrival-time band per gauge. Gauges with no arrival are kept in the list
  // rather than filtered out — a blank row with its reason is information.
  const gauges = (result?.gauges || []).map((g) => ({
    name: g.gauge_name,
    distance_km: g.distance_km,
    median: g.arrival_time_s == null ? null : g.arrival_time_s / 60,
    lo: g.arrival_p05_s == null ? null : g.arrival_p05_s / 60,
    hi: g.arrival_p95_s == null ? null : g.arrival_p95_s / 60,
    note: g.note,
  }));
  const plottable = gauges.filter((g) => g.median != null);
  const chartData = plottable.map((g) => ({
    name: g.name,
    median: g.median,
    // Recharts ErrorBar wants offsets from the value, not absolute bounds.
    err: [
      g.lo == null ? 0 : Math.max(0, g.median - g.lo),
      g.hi == null ? 0 : Math.max(0, g.hi - g.median),
    ],
  }));

  const converged =
    ensemble.num_completed != null && ensemble.num_ensemble != null
      ? `${ensemble.num_completed} of ${ensemble.num_ensemble} members converged`
      : ensemble.num_samples != null
      ? `${ensemble.num_samples} members`
      : null;

  return (
    <div className="jr-page">
      <h3 className="jr-h1">Ensemble statistics</h3>

      {ensemble.dam_class_outside_fitted_population && (
        <Caveat
          className="jr-measure-wide jr-mb-12"
          title={
            <>
              Screening figure only — dam class outside fitted population
              {ensemble.dam_type ? ` (${ensemble.dam_type})` : ""}
              {ensemble.scenario_type ? ` · ${ensemble.scenario_type.replaceAll("_", " ")}` : ""}
            </>
          }
        >
          <div>{ensemble.dam_class_note}</div>
        </Caveat>
      )}

      {ensemble.uses_unverified_regression && (
        <Caveat
          className="jr-measure-wide jr-mb-12"
          title={`Unverified regression in this ensemble: ${(ensemble.unverified_regressions || []).join(", ")}`}
        >
          <div>
            {ensemble.unverified_regression_note ||
              "A quarantined regression contributed members to this band."}
          </div>
        </Caveat>
      )}

      <div className="jr-row jr-measure-wide">
        <Band
          title="Peak breach outflow"
          unit="m³/s"
          {...q}
          hint="5th–95th percentile across the ensemble"
        />
        <Band
          title="Breach formation time"
          unit="min"
          median={t.median == null ? null : t.median / 60}
          p05={t.p05 == null ? null : t.p05 / 60}
          p95={t.p95 == null ? null : t.p95 / 60}
          hint="Time for the breach to reach its final size"
        />
      </div>

      <p className="jr-meta jr-mt-12">
        {converged && <span>{converged}</span>}
        {ensemble.regressions_used?.length > 0 && (
          <span>
            {" · "}Regressions:{" "}
            <strong>{ensemble.regressions_used.join(", ")}</strong>
          </span>
        )}
        {/* Which hardware ran the members. Taken from the members themselves,
            so a GPU run that fell back to the CPU says CPU, and the reason is
            one hover away. Absent for runs that predate the GPU backend. */}
        {result?.solver_backend?.solver_backend_label && (
          <span title={result.solver_backend.solver_backend_reason || ""}>
            {" · "}Computed on:{" "}
            <strong>{result.solver_backend.solver_backend_label}</strong>
          </span>
        )}
      </p>
      <p className="jr-note jr-measure">
        The four published regressions disagree with each other by a factor of
        3–4. That inter-method spread is the dominant term in this band and is
        the documented state of the art, not a defect in this implementation —
        which is why the range is quoted rather than a single number.
      </p>

      <h4 className="jr-h2">Arrival time with uncertainty</h4>
      {chartData.length === 0 ? (
        <Empty inline>
          The flood reached no gauge within the simulated time, so there is no
          arrival band to plot.
        </Empty>
      ) : (
        <div style={{ height: 260 }}>
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={chartData} margin={{ top: 8, right: 16, bottom: 40, left: 8 }}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis
                dataKey="name"
                angle={-25}
                textAnchor="end"
                interval={0}
              />
              <YAxis
                label={{ value: "minutes", angle: -90, position: "insideLeft" }}
              />
              <Tooltip {...TOOLTIP_PROPS} formatter={(v) => `${Number(v).toFixed(1)} min`} />
              <Legend {...LEGEND_PROPS} />
              <Bar dataKey="median" name="Median arrival" fill={SERIES.jalraksha}>
                <ErrorBar dataKey="err" width={4} strokeWidth={1.5} stroke={SERIES.errorBar} />
                {chartData.map((entry) => (
                  <Cell key={entry.name} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      {plottable.some((g) => g.note) && (
        <p className="jr-note jr-measure">
          Notes on plotted gauges:{" "}
          {plottable
            .filter((g) => g.note)
            .map((g) => `${g.name} (${g.note})`)
            .join("; ")}
        </p>
      )}

      {gauges.some((g) => g.median == null) && (
        <p className="jr-note jr-measure">
          Not plotted:{" "}
          {gauges
            .filter((g) => g.median == null)
            .map((g) => `${g.name}${g.note ? ` (${g.note})` : ""}`)
            .join("; ")}
        </p>
      )}

      {ensemble.h_max_stats && (
        <>
          <h4 className="jr-h2">Peak depth across the domain</h4>
          <div className="jr-row jr-measure-wide">
            <Band
              title="Maximum depth anywhere"
              unit="m"
              median={ensemble.h_max_stats.median}
              p05={ensemble.h_max_stats.p05}
              p95={ensemble.h_max_stats.p95}
              hint="Depth is indicative on a 30 m DEM — lead with arrival times"
            />
          </div>
        </>
      )}
    </div>
  );
}

function Band({ title, unit, median, p05, p95, hint }) {
  const fmt = (v) =>
    v == null
      ? "—"
      : Math.abs(v) >= 1000
      ? Math.round(v).toLocaleString()
      : v.toFixed(v < 10 ? 2 : 1);
  return (
    <Stat
      size="lg"
      label={title}
      value={fmt(median)}
      unit={unit}
      band={`${fmt(p05)} – ${fmt(p95)} ${unit}`}
      hint={hint}
    />
  );
}
