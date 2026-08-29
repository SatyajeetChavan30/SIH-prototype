import React from "react";
import {
  Bar, BarChart, CartesianGrid, Cell, ErrorBar, Legend, ResponsiveContainer,
  Tooltip, XAxis, YAxis,
} from "recharts";

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

  if (!ensemble) {
    return (
      <Empty>
        No ensemble statistics for this run. They are produced by the SWE
        pipeline; a <code>delft3d</code>-only run has no breach ensemble.
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
    <div style={S.page}>
      <h3 style={S.h3}>Ensemble statistics</h3>

      {ensemble.dam_class_outside_fitted_population && (
        <div style={S.warn}>
          <strong>
            Screening figure only — dam class outside fitted population
            {ensemble.dam_type ? ` (${ensemble.dam_type})` : ""}
          </strong>
          <div style={{ marginTop: 4 }}>{ensemble.dam_class_note}</div>
        </div>
      )}

      <div style={S.row}>
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

      <div style={S.meta}>
        {converged && <span>{converged}</span>}
        {ensemble.regressions_used?.length > 0 && (
          <span>
            {" · "}Regressions:{" "}
            <strong>{ensemble.regressions_used.join(", ")}</strong>
          </span>
        )}
      </div>
      <p style={S.note}>
        The four published regressions disagree with each other by a factor of
        3–4. That inter-method spread is the dominant term in this band and is
        the documented state of the art, not a defect in this implementation —
        which is why the range is quoted rather than a single number.
      </p>

      <h4 style={S.h4}>Arrival time with uncertainty</h4>
      {chartData.length === 0 ? (
        <Empty>
          The flood reached no gauge within the simulated time, so there is no
          arrival band to plot.
        </Empty>
      ) : (
        <div style={{ height: 260 }}>
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={chartData} margin={{ top: 8, right: 16, bottom: 40, left: 8 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#eee" />
              <XAxis
                dataKey="name"
                tick={{ fontSize: 11 }}
                angle={-25}
                textAnchor="end"
                interval={0}
              />
              <YAxis
                tick={{ fontSize: 11 }}
                label={{ value: "minutes", angle: -90, position: "insideLeft", fontSize: 11 }}
              />
              <Tooltip formatter={(v) => `${Number(v).toFixed(1)} min`} />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              <Bar dataKey="median" name="Median arrival" fill="#1565C0">
                <ErrorBar dataKey="err" width={4} strokeWidth={1.5} stroke="#7a3e00" />
                {chartData.map((entry) => (
                  <Cell key={entry.name} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      {gauges.some((g) => g.median == null) && (
        <div style={S.note}>
          Not plotted:{" "}
          {gauges
            .filter((g) => g.median == null)
            .map((g) => `${g.name}${g.note ? ` (${g.note})` : ""}`)
            .join("; ")}
        </div>
      )}

      {ensemble.h_max_stats && (
        <>
          <h4 style={S.h4}>Peak depth across the domain</h4>
          <div style={S.row}>
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
    <div style={S.card}>
      <div style={S.cardTitle}>{title}</div>
      <div style={S.cardValue}>
        {fmt(median)} <span style={S.cardUnit}>{unit}</span>
      </div>
      <div style={S.cardBand}>
        {fmt(p05)} – {fmt(p95)} {unit}
      </div>
      {hint && <div style={S.cardHint}>{hint}</div>}
    </div>
  );
}

function Empty({ children }) {
  return <div style={S.empty}>{children}</div>;
}

const S = {
  page: { padding: 16, overflowY: "auto", height: "100%" },
  h3: { margin: "0 0 12px" },
  h4: { margin: "20px 0 8px", fontSize: 13, color: "#555" },
  row: { display: "flex", gap: 12, flexWrap: "wrap" },
  card: {
    flex: "1 1 220px", border: "1px solid #ddd", borderRadius: 4,
    padding: "10px 12px", background: "#fafafa",
  },
  cardTitle: { fontSize: 11, color: "#666", textTransform: "uppercase", letterSpacing: 0.4 },
  cardValue: { fontSize: 26, fontWeight: 700, marginTop: 4 },
  cardUnit: { fontSize: 13, fontWeight: 400, color: "#666" },
  cardBand: { fontSize: 12, color: "#1565C0", marginTop: 2 },
  cardHint: { fontSize: 10, color: "#888", marginTop: 6 },
  meta: { fontSize: 12, color: "#555", marginTop: 10 },
  note: { fontSize: 11, color: "#777", marginTop: 8, lineHeight: 1.45, maxWidth: 760 },
  warn: {
    padding: "8px 10px", fontSize: 11, border: "2px solid #e65100",
    background: "#fff4e5", borderRadius: 4, color: "#7a3e00", marginBottom: 12,
  },
  empty: { fontSize: 12, color: "#777", padding: "12px 0", maxWidth: 700, lineHeight: 1.5 },
};
