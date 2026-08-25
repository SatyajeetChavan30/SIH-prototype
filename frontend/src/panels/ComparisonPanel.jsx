import React, { useEffect, useState } from "react";
import { getComparison, resolveApiUrl } from "../api.js";

/**
 * Comparison tab (brief §5.7) — direct port of the existing Streamlit
 * "SPH vs Delft3D-Class SWE Solver Comparison" tab
 * (jalraksha/dashboard/app.py, ~line 553) to React. No new analysis logic:
 * metrics, the gauge arrival table, and the two comparison images all come
 * from GET /runs/{run_id}/comparison, which the worker populates only for
 * solver="both" runs (services/api/jalraksha_service/tasks.py::_run_comparison).
 */
export default function ComparisonPanel({ runId }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!runId) return;
    setData(null);
    setError(null);
    getComparison(runId)
      .then(setData)
      .catch((e) => setError(String(e)));
  }, [runId]);

  if (!runId) {
    return <Empty text="Run a simulation first." />;
  }
  if (error) {
    return <Empty text={`Failed to load comparison: ${error}`} />;
  }
  if (!data) {
    return <Empty text="Loading comparison…" />;
  }

  const metrics = data.metrics?.metrics;
  const gaugeComparison = data.metrics?.gauge_comparison || [];
  const depthMap = data.maps?.find((m) => m.kind === "comparison_depth_map");
  const hydro = data.maps?.find((m) => m.kind === "comparison_hydrograph");

  if (!metrics) {
    return (
      <Empty text='No comparison data for this run — submit with solver="both" to compare SPH vs Delft3D-class.' />
    );
  }

  return (
    <div style={{ padding: 16, overflowY: "auto", flex: 1 }}>
      <h3>⚖️ SPH vs Delft3D-Class SWE Solver Comparison</h3>

      <div style={{ display: "flex", gap: 12, flexWrap: "wrap", margin: "12px 0" }}>
        <MetricCard label="Depth Field RMSE" value={`${metrics.rmse_m?.toFixed?.(3) ?? metrics.rmse_m} m`} color="#2196f3" />
        <MetricCard label="Mass Balance Bias" value={`${metrics.bias_m} m`} color="#ff9800" />
        <MetricCard label="Critical Success Index (CSI)" value={metrics.csi} color="#4caf50" />
        <MetricCard label="Inundation Grid Overlap" value={`${metrics.overlap_pct}%`} color="#9c27b0" />
      </div>

      {depthMap && (
        <>
          <h4>🗺️ Rasterised Depth Field Comparison</h4>
          <img src={resolveApiUrl(depthMap.path_or_url)} alt="Depth field comparison" style={{ maxWidth: "100%" }} />
        </>
      )}

      {hydro && (
        <>
          <h4>⏱️ Downstream Hydrograph Overlays</h4>
          <img src={resolveApiUrl(hydro.path_or_url)} alt="Hydrograph overlay" style={{ maxWidth: "100%" }} />
        </>
      )}

      <h4>🔢 Arrival Times at Downstream Gauges</h4>
      <table style={{ borderCollapse: "collapse", width: "100%" }}>
        <thead>
          <tr>
            {["Gauge", "SPH Arrival (min)", "Delft3D Arrival (min)", "Δ (min)", "Δ (%)", "Distance (km)"].map((h) => (
              <th key={h} style={{ textAlign: "left", borderBottom: "1px solid #ccc", padding: 4 }}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {gaugeComparison.map((row) => (
            <tr key={row.gauge}>
              <td style={{ padding: 4 }}>{row.gauge}</td>
              <td style={{ padding: 4 }}>{row.arrival_SPH_min?.toFixed?.(1) ?? "—"}</td>
              <td style={{ padding: 4 }}>{row.arrival_Delft3D_min?.toFixed?.(1) ?? "—"}</td>
              <td style={{ padding: 4 }}>{row.delta_min ?? "—"}</td>
              <td style={{ padding: 4 }}>{row.delta_pct ?? "—"}</td>
              <td style={{ padding: 4 }}>{row.distance_km ?? "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <p style={{ fontSize: 12, marginTop: 12, color: "#555" }}>
        Solver engine state: running <code>{data.metrics.delft3d_engine_label}</code> with fallback to the
        offline SWE kernel. SPH engine: <code>{data.metrics.sph_engine}</code>.
      </p>
    </div>
  );
}

function MetricCard({ label, value, color }) {
  return (
    <div style={{ borderLeft: `4px solid ${color}`, padding: "8px 12px", minWidth: 160 }}>
      <div style={{ fontSize: 12, opacity: 0.8 }}>{label}</div>
      <div style={{ fontSize: 22, fontWeight: 700 }}>{value}</div>
    </div>
  );
}

function Empty({ text }) {
  return <div style={{ padding: 24, color: "#777" }}>{text}</div>;
}
