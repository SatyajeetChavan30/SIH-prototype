import React, { useEffect, useState } from "react";
import { getComparison, resolveApiUrl } from "../api.js";
import { Caveat, DataTable, Empty, Stat } from "../ui/index.jsx";

/**
 * Comparison tab (brief §5.7) — originally ported from the since-removed Streamlit
 * "SPH vs Delft3D-Class SWE Solver Comparison" tab
 * dashboard. No new analysis logic:
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
    return <Empty>Run a simulation first.</Empty>;
  }
  if (error) {
    return <Empty>{`Failed to load comparison: ${error}`}</Empty>;
  }
  if (!data) {
    return <Empty>Loading comparison…</Empty>;
  }

  const metrics = data.metrics?.metrics;
  const gaugeComparison = data.metrics?.gauge_comparison || [];
  const depthMap = data.maps?.find((m) => m.kind === "comparison_depth_map");
  const hydro = data.maps?.find((m) => m.kind === "comparison_hydrograph");
  const nearField = data.metrics?.sph_near_field;
  const sphError = data.metrics?.sph_error;

  // `metrics` is empty when the run produced no SPH half at all. That is a
  // different state from "this run has no comparison", and it gets a different
  // message — the Delft3D-class engine banner is still worth showing.
  const hasComparison = metrics && Object.keys(metrics).length > 0;
  if (!hasComparison && !sphError) {
    return (
      <Empty>No comparison data for this run — submit with solver="both" to compare SPH vs Delft3D-class.</Empty>
    );
  }

  return (
    <div className="jr-page">
      <h3 className="jr-h1">⚖️ SPH vs Delft3D-Class SWE Solver Comparison</h3>

      <EngineBanner
        binaryUsed={data.metrics?.delft3d_binary_used}
        label={data.metrics?.delft3d_engine_label}
        reason={data.metrics?.delft3d_fallback_reason}
      />

      <SphBanner error={sphError} engine={data.metrics?.sph_engine} nearField={nearField} />

      {hasComparison && (
        <div className="jr-row jr-measure-wide jr-mt-12">
          <MetricCard label="Depth Field RMSE" value={`${metrics.rmse_m?.toFixed?.(3) ?? metrics.rmse_m} m`} color="#2196f3" />
          <MetricCard label="Mass Balance Bias" value={`${metrics.bias_m} m`} color="#ff9800" />
          <MetricCard label="Critical Success Index (CSI)" value={metrics.csi} color="#4caf50" />
          <MetricCard label="Inundation Grid Overlap" value={`${metrics.overlap_pct}%`} color="#9c27b0" />
        </div>
      )}

      {nearField && (
        <>
          <h4 className="jr-h2">🌊 Near-Field SPH — what the particle run actually measured</h4>
          <div className="jr-row jr-measure-wide">
            <MetricCard label="Surge front speed" value={fmt(nearField.front_speed_m_s, "m/s")} color="#0288d1" />
            <MetricCard label="Front advance" value={fmt(nearField.front_advance_m, "m")} color="#0288d1" />
            <MetricCard label="Max near-field depth" value={fmt(nearField.max_depth_m, "m")} color="#00796b" />
            <MetricCard label="Max near-field speed" value={fmt(nearField.max_speed_m_s, "m/s")} color="#00796b" />
            <MetricCard label="Fluid particles" value={nearField.n_fluid?.toLocaleString?.() ?? "—"} color="#5e35b1" />
            <MetricCard label="Particle spacing" value={fmt(nearField.particle_spacing_m, "m")} color="#5e35b1" />
          </div>
          <p className="jr-note jr-measure-wide">
            {fmt(nearField.duration_s, "s")} of simulated time over a{" "}
            {fmt(nearField.domain_length_m, "m")} window, computed in{" "}
            {fmt(nearField.wall_clock_s, "s")}. Coupling:{" "}
            <strong>{nearField.coupling}</strong> — the breach discharge and
            reservoir head set the SPH initial condition and nothing returns from
            SPH to the solver side.
          </p>
        </>
      )}

      {hasComparison && depthMap && (
        <>
          <h4 className="jr-h2">🗺️ Rasterised Depth Field Comparison</h4>
          <img className="jr-figure" src={resolveApiUrl(depthMap.path_or_url)} alt="Depth field comparison" />
        </>
      )}

      {hydro && (
        <>
          <h4 className="jr-h2">⏱️ Downstream Hydrograph Overlays</h4>
          <img className="jr-figure" src={resolveApiUrl(hydro.path_or_url)} alt="Hydrograph overlay" />
        </>
      )}

      <h4 className="jr-h2">🔢 Arrival Times at Downstream Gauges</h4>
      <DataTable className="jr-measure-wide">
        <thead>
          <tr>
            {["Gauge", "SPH Arrival (min)", "Delft3D Arrival (min)", "Δ (min)", "Δ (%)", "Distance (km)"].map((h, i) => (
              <th key={h} className={i ? "num" : undefined}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {gaugeComparison.map((row) => (
            <tr key={row.gauge}>
              <td>{row.gauge}</td>
              <td className="num">{row.arrival_SPH_min?.toFixed?.(1) ?? "—"}</td>
              <td className="num">{row.arrival_Delft3D_min?.toFixed?.(1) ?? "—"}</td>
              <td className="num">{row.delta_min ?? "—"}</td>
              <td className="num">{row.delta_pct ?? "—"}</td>
              <td className="num">{row.distance_km ?? "—"}</td>
            </tr>
          ))}
        </tbody>
      </DataTable>

      <Caveat className="jr-measure-wide jr-mt-12">
        ⚠ The <strong>SPH arrival column is empty by construction</strong>, not
        by omission. The near-field particle run covers a few hundred metres over
        tens of seconds; the nearest gauge is 13&nbsp;km downstream, so it cannot
        reach any of them. That is what a one-way near-field/far-field
        decomposition means. This column previously showed numbers generated from
        a celerity formula plus random noise.
      </Caveat>

      {data.metrics?.gauge_arrival_method === "ritter_celerity_estimate" && (
        <Caveat className="jr-measure-wide jr-mt-8">
          ⚠ The Delft3D-side arrival times above are a <strong>Ritter celerity
          estimate</strong> (t = distance ÷ 0.5√(gH)), not readings taken from the
          simulation. The comparison domain is 1.2 km across; the nearest gauge is
          13 km downstream, so the run cannot reach these locations. Treat them as
          an order-of-magnitude screening figure.
        </Caveat>
      )}

      {data.metrics?.sph_engine && (
        <p className="jr-note jr-mt-12">
          SPH engine: <code>{data.metrics.sph_engine}</code>.
        </p>
      )}
    </div>
  );
}

function fmt(value, unit) {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  const n = Number(value);
  return `${n >= 100 ? n.toFixed(0) : n.toFixed(2)} ${unit}`;
}

/**
 * Says whether a real near-field SPH run happened, and if not, why.
 *
 * The SPH half of this tab used to be np.random output — particle positions
 * from np.random.uniform and gauge arrivals from a celerity formula plus
 * Gaussian noise — rendered indistinguishably from solver results. It is now a
 * real SPH run (DualSPHysics, or PySPH where DualSPHysics is not installed), and
 * when neither can run there is NO SPH result and this says so, rather than
 * anything being substituted for it.
 */
export function SphBanner({ error, engine, nearField }) {
  if (!error && !engine) return null;
  const ok = !error;
  return (
    <Caveat
      role="status"
      tone={ok ? "ok" : "warn"}
      className="jr-measure-wide jr-mt-12"
      title={ok
        ? "✅ Near-field SPH: real particle simulation"
        : "⚠️ No near-field SPH result for this run"}
    >
      <div>
        {ok ? (
          <>
            Weakly Compressible SPH over this dam&rsquo;s own Copernicus
            terrain, driven by the Phase&nbsp;3 breach hydrograph
            {nearField?.n_fluid ? ` (${nearField.n_fluid.toLocaleString()} fluid particles)` : ""}.
          </>
        ) : (
          <>Nothing has been substituted for it. Reason: {error}</>
        )}
      </div>
    </Caveat>
  );
}

/**
 * States, unmissably, which engine produced the numbers on this tab.
 *
 * The previous version of this was a grey sentence at the bottom of the page
 * reading "running <label> with fallback to the offline SWE kernel" — which
 * described both cases at once and so distinguished neither. Since the worker
 * hardcoded force_fallback=True, it was ALWAYS the fallback, and a reader had
 * no way to know. `delft3d_binary_used` is now an explicit boolean from
 * runner.run_delft3d_simulation, so this renders one state or the other.
 *
 * Per CLAUDE.md the built-in solver is "Delft3D-class" — it solves the same
 * depth-averaged 2D Saint-Venant equations — and is never called Delft3D.
 */
export function EngineBanner({ binaryUsed, label, reason }) {
  const ok = binaryUsed === true;
  return (
    <Caveat
      role="status"
      tone={ok ? "ok" : "warn"}
      className="jr-measure-wide jr-mt-12"
      title={ok
        ? "✅ Engine: Delft3D FM (official dflowfm binary)"
        : "⚠️ Delft3D FM was NOT used — these numbers come from JalRaksha's own solver"}
    >
      <div>
        {ok ? (
          <>The official Deltares D-Flow FM engine produced the depth field below.</>
        ) : (
          <>
            Computed by the <strong>JalRaksha built-in 2D SWE solver</strong>, which
            solves the same depth-averaged Saint-Venant equations as Delft3D FM and
            is therefore <em>Delft3D-class</em> — but it is <strong>not Delft3D</strong>{" "}
            and must not be reported as such.
          </>
        )}
      </div>
      {!ok && reason && (
        <div className="jr-caveat__detail">
          Reason: {reason}
        </div>
      )}
      {label && (
        <div className="jr-caveat__detail">
          Engine label: <code>{label}</code>
        </div>
      )}
    </Caveat>
  );
}

function MetricCard({ label, value, color }) {
  return <Stat label={label} value={value} accent={color} />;
}
