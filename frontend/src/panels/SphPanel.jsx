import React from "react";
import {
  CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Scatter,
  ScatterChart, Tooltip, XAxis, YAxis, ZAxis,
} from "recharts";

/**
 * Near-field SPH — the violent breach jet, resolved with particles.
 *
 * Scope is stated first and prominently, because this is the panel most likely
 * to be over-read. The SPH window is a few hundred metres over ~15 seconds. It
 * cannot and does not reach a downstream gauge; the runner hardcodes
 * reaches_downstream_gauges = false. It answers a different question from the
 * far-field SWE run — what the flow does AT the breach — and the two are joined
 * by a one-way handoff with no feedback (CLAUDE.md).
 *
 * Two views, both real:
 *   surge front   front_position_m against front_time_s, appended every solver
 *                 step. This is the only genuinely time-resolved SPH output.
 *   particles     the final state. PySPH is configured with intermediate dumps
 *                 disabled, so there is one snapshot, not an animation — and
 *                 the panel says so rather than implying otherwise.
 */
export default function SphPanel({ result }) {
  const sph = result?.sph;

  if (!sph) {
    return (
      <Empty>
        No near-field SPH for this run. Select <strong>+ Near-field SPH</strong>{" "}
        in the solver dropdown — it runs alongside the SWE pipeline rather than
        instead of it.
      </Empty>
    );
  }

  if (!sph.available) {
    return (
      <div style={S.page}>
        <h3 style={S.h3}>Near-field SPH</h3>
        <div style={S.warn}>
          <strong>No SPH result</strong>
          <div style={{ marginTop: 4 }}>{sph.reason}</div>
          <div style={{ marginTop: 4 }}>
            No particles are substituted. This panel previously showed positions
            drawn from a random number generator; it now shows nothing when
            there is nothing.
          </div>
        </div>
      </div>
    );
  }

  const frontRows = (sph.front_time_s || []).map((t, i) => ({
    t,
    position: sph.front_position_m?.[i],
  }));

  const particles = (sph.particles?.x || []).map((x, i) => ({
    x,
    y: sph.particles.y?.[i],
    z: sph.particles.z?.[i],
  }));

  return (
    <div style={S.page}>
      <h3 style={S.h3}>Near-field SPH</h3>

      <div style={S.scope}>
        <strong>Near-field only, one-way coupled.</strong> A{" "}
        {fmt(sph.domain_length_m, 0)} m window simulated for{" "}
        {fmt(sph.duration_s, 0)} s at the breach. It does{" "}
        <strong>not</strong> reach downstream gauges, and nothing returns from
        SPH to the SWE solver — {sph.coupling}.
      </div>

      <div style={S.row}>
        <Tile label="Fluid particles" value={num(sph.n_fluid)}
              sub={`${num(sph.n_boundary)} boundary`} emphasis />
        <Tile label="Particle spacing" value={`${fmt(sph.particle_spacing_m, 2)} m`} />
        <Tile label="Front speed" value={`${fmt(sph.front_speed_m_s, 1)} m/s`} />
        <Tile label="Front advance" value={`${fmt(sph.front_advance_m, 0)} m`} />
        <Tile label="Max depth" value={`${fmt(sph.max_depth_m, 2)} m`} />
        <Tile label="Max speed" value={`${fmt(sph.max_speed_m_s, 1)} m/s`} />
      </div>

      <div style={S.provenance}>
        {sph.engine_label}
        {sph.wall_clock_s != null && ` · ${fmt(sph.wall_clock_s, 1)} s wall clock`}
        {sph.q_peak_m3_s != null &&
          ` · driven by a ${num(sph.q_peak_m3_s)} m³/s breach peak over ` +
          `${fmt(sph.breach_width_m, 0)} m`}
      </div>

      {sph.front_exited_domain && (
        <div style={S.warn}>
          The surge front left the SPH window before the run ended. Front
          positions after that point are particles in free flight past the last
          terrain row, not flow over terrain.
        </div>
      )}

      <h4 style={S.h4}>Surge front advance</h4>
      <p style={S.note}>
        The 99th-percentile downstream position of in-domain particles, recorded
        every solver step. This is the one time-resolved output the near-field
        run produces.
      </p>
      {frontRows.length === 0 ? (
        <Empty>No front history was recorded.</Empty>
      ) : (
        <div style={{ height: 240 }}>
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={frontRows} margin={{ top: 8, right: 24, bottom: 28, left: 8 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#eee" />
              <XAxis dataKey="t" type="number" tick={{ fontSize: 11 }}
                     tickFormatter={(v) => v.toFixed(1)}
                     label={{ value: "time (s)", position: "insideBottom",
                              offset: -14, fontSize: 11 }} />
              <YAxis tick={{ fontSize: 11 }}
                     label={{ value: "front position (m)", angle: -90,
                              position: "insideLeft", fontSize: 11 }} />
              <Tooltip formatter={(v) => `${Number(v).toFixed(1)} m`}
                       labelFormatter={(v) => `t = ${Number(v).toFixed(2)} s`} />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              <Line type="monotone" dataKey="position" name="Surge front"
                    stroke="#1565C0" strokeWidth={2} dot={false}
                    isAnimationActive={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      <h4 style={S.h4}>Particle cloud — final state</h4>
      <p style={S.note}>
        Plan view at t = {fmt(sph.duration_s, 0)} s. This is a single snapshot,
        not an animation: PySPH is run with intermediate dumps disabled, so the
        run produces one particle state rather than a sequence.
        {sph.particles?.stride > 1 &&
          ` Showing ${num(sph.particles.n_plotted)} of ${num(sph.n_fluid)} particles (every ${sph.particles.stride}th) — the full cloud is unreadable at this scale.`}
      </p>
      {particles.length === 0 ? (
        <Empty>No particle positions were returned.</Empty>
      ) : (
        <div style={{ height: 320 }}>
          <ResponsiveContainer width="100%" height="100%">
            <ScatterChart margin={{ top: 8, right: 24, bottom: 28, left: 8 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#eee" />
              <XAxis dataKey="x" type="number" tick={{ fontSize: 11 }}
                     label={{ value: "across flow (m)", position: "insideBottom",
                              offset: -14, fontSize: 11 }} />
              <YAxis dataKey="y" type="number" tick={{ fontSize: 11 }}
                     label={{ value: "downstream (m)", angle: -90,
                              position: "insideLeft", fontSize: 11 }} />
              <ZAxis dataKey="z" range={[6, 6]} />
              <Tooltip cursor={{ strokeDasharray: "3 3" }}
                       formatter={(v) => `${Number(v).toFixed(1)} m`} />
              <Scatter data={particles} fill="#1565C0" fillOpacity={0.45}
                       isAnimationActive={false} />
            </ScatterChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}

function Tile({ label, value, sub, emphasis }) {
  return (
    <div style={{ ...S.tile, ...(emphasis ? S.tileEmphasis : null) }}>
      <div style={S.tileLabel}>{label}</div>
      <div style={{ ...S.tileValue, fontSize: emphasis ? 24 : 19 }}>{value}</div>
      {sub && <div style={S.tileSub}>{sub}</div>}
    </div>
  );
}

function Empty({ children }) {
  return <div style={S.empty}>{children}</div>;
}

function num(v) {
  return typeof v === "number" && isFinite(v) ? Math.round(v).toLocaleString() : "—";
}

function fmt(v, digits) {
  return typeof v === "number" && isFinite(v) ? v.toFixed(digits) : "—";
}

const S = {
  page: { padding: 16, overflowY: "auto", height: "100%" },
  h3: { margin: "0 0 10px" },
  h4: { margin: "22px 0 6px", fontSize: 13, color: "#555" },
  row: { display: "flex", gap: 10, flexWrap: "wrap" },
  scope: { padding: "8px 10px", fontSize: 11, border: "1px solid #1565C0",
           background: "#f3f8fd", borderRadius: 4, color: "#0d47a1",
           marginBottom: 12, maxWidth: 820, lineHeight: 1.5 },
  tile: { flex: "1 1 140px", border: "1px solid #ddd", borderRadius: 4,
          padding: "9px 11px", background: "#fafafa" },
  tileEmphasis: { borderColor: "#1565C0", background: "#f3f8fd" },
  tileLabel: { fontSize: 10, color: "#666", textTransform: "uppercase", letterSpacing: 0.4 },
  tileValue: { fontWeight: 700, marginTop: 3 },
  tileSub: { fontSize: 10, color: "#777", marginTop: 2 },
  provenance: { fontSize: 10, color: "#777", marginTop: 8, lineHeight: 1.45, maxWidth: 820 },
  note: { fontSize: 11, color: "#777", maxWidth: 820, lineHeight: 1.45, marginTop: 0 },
  warn: { marginTop: 10, padding: "8px 10px", fontSize: 11, border: "2px solid #e65100",
          background: "#fff4e5", borderRadius: 4, color: "#7a3e00", maxWidth: 820 },
  empty: { fontSize: 12, color: "#777", padding: 16, maxWidth: 720, lineHeight: 1.5 },
};
