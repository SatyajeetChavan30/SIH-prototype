import React, { useState } from "react";
import {
  CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip,
  XAxis, YAxis,
} from "recharts";
import { getValidation } from "../api.js";

/**
 * The analytical correctness gates — the answer to "how do we know this
 * animation is not decorative".
 *
 * Three independent kinds of evidence, all run against the live solver rather
 * than read from a file:
 *
 *   Ritter          the exact analytical dam-break solution, with JalRaksha and
 *                   the real Delft3D FM kernel both scored against the same
 *                   curve on a shared axis.
 *   Lake at rest    still water over irregular bathymetry must stay still — the
 *                   C-property, and the test a scheme fails when it manufactures
 *                   currents out of terrain.
 *   Mass conservation   total volume must not drift in a closed domain.
 *
 * Deliberately NOT run on mount. The Ritter cross-check launches the Delft3D
 * kernel, so a tab that auto-ran it would fire a solver on every page load. The
 * server caches the result; the button asks for it.
 */
export default function ValidationPanel() {
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  // Poll rather than hold a request open. The gates run two 1000-step solves
  // plus a real Delft3D kernel launch; the endpoint now starts them on a
  // background thread and answers immediately with status "running", because
  // holding the connection returned nothing after 120 s when a simulation was
  // competing for the machine.
  const run = async (refresh = false) => {
    setBusy(true);
    setError(null);
    try {
      let result = await getValidation(refresh);
      const startedAt = Date.now();
      while (result.status === "running") {
        if (Date.now() - startedAt > 15 * 60 * 1000) {
          throw new Error("Validation did not finish within 15 minutes.");
        }
        await new Promise((r) => setTimeout(r, 2000));
        result = await getValidation(false);
      }
      setData(result);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const ritter = data?.checks?.find((c) => c.series?.x_m);

  return (
    <div style={S.page}>
      <h3 style={S.h3}>Validation</h3>
      <p style={S.lede}>
        These gates run the solver against solutions whose answers are known in
        advance. They are the same checks that block a merge in CI, executed
        here against the running build.
      </p>

      <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 14 }}>
        <button onClick={() => run(false)} disabled={busy}>
          {busy ? "Running the gates…" : data ? "Re-check (cached)" : "Run validation"}
        </button>
        {busy && (
          <span style={S.muted}>
            two 1000-step solves plus a Delft3D kernel run — a minute or two
          </span>
        )}
        {data && (
          <button onClick={() => run(true)} disabled={busy} style={{ fontSize: 12 }}>
            Force re-run
          </button>
        )}
        {data?.cached && <span style={S.muted}>served from cache</span>}
        {data?.generated_at && (
          <span style={S.muted}>· {new Date(data.generated_at).toLocaleString()}</span>
        )}
      </div>

      {error && <div style={S.err}>{error}</div>}

      {!data && !busy && !error && (
        <div style={S.empty}>
          Not run yet. The Ritter cross-check starts the Delft3D FM kernel, so it
          is triggered by the button rather than on page load.
        </div>
      )}

      {data?.checks?.map((c) => (
        <Check key={c.name} check={c} />
      ))}

      {ritter && (
        <>
          <h4 style={S.h4}>Ritter dam-break — depth profile</h4>
          <p style={S.note}>
            One instant of a dry-bed dam-break. The analytical curve is the exact
            solution; the others are what each engine computed. Curves that lie
            on top of each other are the result.
          </p>
          <RitterChart series={ritter.series} />
        </>
      )}
    </div>
  );
}

function Check({ check }) {
  const state = check.error ? "error" : check.passed ? "pass" : "fail";
  const badge = { pass: S.pass, fail: S.fail, error: S.errBadge }[state];
  const label = { pass: "PASS", fail: "FAIL", error: "ERROR" }[state];

  return (
    <div style={S.check}>
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <span style={badge}>{label}</span>
        <strong style={{ fontSize: 13 }}>{check.name}</strong>
      </div>
      <div style={S.detail}>{check.detail || check.error}</div>
      {check.metrics && (
        <div style={S.metrics}>
          {Object.entries(check.metrics)
            .filter(([, v]) => v !== null && v !== undefined)
            .map(([k, v]) => (
              <span key={k} style={S.metric}>
                {k.replace(/_/g, " ")}:{" "}
                <strong>{typeof v === "number" ? fmtNum(v) : String(v)}</strong>
              </span>
            ))}
        </div>
      )}
    </div>
  );
}

function RitterChart({ series }) {
  const rows = (series.x_m || []).map((x, i) => ({
    x,
    analytical: series.analytical_m?.[i],
    jalraksha: series.jalraksha_m?.[i],
    delft3d: series.delft3d_m?.[i],
  }));
  const hasDelft3d = Array.isArray(series.delft3d_m);

  return (
    <div style={{ height: 320 }}>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={rows} margin={{ top: 8, right: 24, bottom: 28, left: 8 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#eee" />
          <XAxis
            dataKey="x"
            type="number"
            tick={{ fontSize: 11 }}
            tickFormatter={(v) => `${Math.round(v)}`}
            label={{ value: "distance along channel (m)", position: "insideBottom",
                     offset: -14, fontSize: 11 }}
          />
          <YAxis
            tick={{ fontSize: 11 }}
            label={{ value: "depth (m)", angle: -90, position: "insideLeft", fontSize: 11 }}
          />
          <Tooltip formatter={(v) => (v == null ? "—" : `${Number(v).toFixed(3)} m`)} />
          <Legend wrapperStyle={{ fontSize: 11 }} />
          {/* Analytical drawn thickest and first so the engines overlay it. */}
          <Line type="monotone" dataKey="analytical" name="Exact (Ritter)"
                stroke="#111" strokeWidth={2.5} dot={false} isAnimationActive={false} />
          <Line type="monotone" dataKey="jalraksha" name="JalRaksha 2D SWE"
                stroke="#1565C0" strokeWidth={1.6} dot={false} isAnimationActive={false} />
          {hasDelft3d && (
            <Line type="monotone" dataKey="delft3d" name="Delft3D FM"
                  stroke="#e65100" strokeWidth={1.6} strokeDasharray="5 3"
                  dot={false} isAnimationActive={false} />
          )}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

function fmtNum(v) {
  if (v === 0) return "0";
  const abs = Math.abs(v);
  if (abs < 1e-4 || abs >= 1e6) return v.toExponential(2);
  return abs >= 100 ? v.toFixed(1) : v.toFixed(4).replace(/0+$/, "").replace(/\.$/, "");
}

const S = {
  page: { padding: 16, overflowY: "auto", height: "100%" },
  h3: { margin: "0 0 6px" },
  h4: { margin: "22px 0 6px", fontSize: 13, color: "#555" },
  lede: { fontSize: 12, color: "#555", maxWidth: 760, lineHeight: 1.5, marginTop: 0 },
  note: { fontSize: 11, color: "#777", maxWidth: 760, lineHeight: 1.45 },
  muted: { fontSize: 11, color: "#888" },
  check: { border: "1px solid #ddd", borderRadius: 4, padding: "10px 12px", marginBottom: 8 },
  detail: { fontSize: 12, color: "#444", marginTop: 6, lineHeight: 1.45 },
  metrics: { display: "flex", flexWrap: "wrap", gap: 12, marginTop: 8 },
  metric: { fontSize: 10, color: "#666" },
  pass: { background: "#edf7ed", color: "#1b5e20", border: "1px solid #2e7d32",
          borderRadius: 3, padding: "1px 7px", fontSize: 11, fontWeight: 700 },
  fail: { background: "#fdecea", color: "#7f1d1d", border: "1px solid #c62828",
          borderRadius: 3, padding: "1px 7px", fontSize: 11, fontWeight: 700 },
  errBadge: { background: "#fff4e5", color: "#7a3e00", border: "1px solid #e65100",
              borderRadius: 3, padding: "1px 7px", fontSize: 11, fontWeight: 700 },
  err: { padding: "8px 10px", fontSize: 12, border: "2px solid #c62828",
         background: "#fdecea", borderRadius: 4, color: "#7f1d1d", marginBottom: 12 },
  empty: { fontSize: 12, color: "#777", padding: "12px 0", maxWidth: 700, lineHeight: 1.5 },
};
