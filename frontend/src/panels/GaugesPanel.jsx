import React from "react";

/**
 * Downstream gauge table — the headline output of the whole system.
 *
 * Arrival time is what a dam-break screening tool exists to produce, and until
 * now the dashboard showed only a median in a cramped sidebar. This is the full
 * table: town, distance, arrival with its ensemble band, peak depth, and the
 * hazard class that depth implies.
 *
 * A gauge with no arrival keeps its row. The `note` distinguishes the two
 * reasons a cell is blank — "the flood did not reach here in the simulated
 * time" versus "this gauge is outside the solver domain" — which are completely
 * different statements and were previously both rendered as an em dash.
 */
export default function GaugesPanel({ result, dam }) {
  const gauges = result?.gauges || [];
  const hasRun = gauges.length > 0;

  // Pre-run, show the selected dam's corridor so the panel is never empty.
  const rows = hasRun
    ? gauges
    : (dam?.gauges || []).map((g) => ({
        gauge_name: g.name,
        distance_km: g.distance_km,
        river: g.river,
        note: g.note,
      }));

  if (rows.length === 0) {
    return <div style={S.empty}>No downstream corridor is defined for this dam.</div>;
  }

  return (
    <div style={S.page}>
      <h3 style={S.h3}>
        Downstream gauges{dam?.name ? ` — ${dam.name}` : ""}
      </h3>
      {!hasRun && (
        <div style={S.lede}>
          Reference corridor. Run or load a simulation to populate arrival times.
        </div>
      )}

      <table style={S.table}>
        <thead>
          <tr>
            <Th>Town</Th>
            <Th align="right">Distance</Th>
            <Th align="right">Arrival (median)</Th>
            <Th align="right">5th–95th</Th>
            <Th align="right">Peak depth</Th>
            <Th>Hazard</Th>
          </tr>
        </thead>
        <tbody>
          {rows.map((g) => {
            const hazard = hazardClass(g.max_depth_m);
            return (
              <tr key={g.gauge_name} style={S.tr}>
                <Td>
                  <strong>{g.gauge_name}</strong>
                  {g.river && <span style={S.river}> · {g.river}</span>}
                  {g.note && <div style={S.note}>{g.note}</div>}
                </Td>
                <Td align="right">{fmtKm(g.distance_km)}</Td>
                <Td align="right" strong={g.arrival_time_s != null}>
                  {fmtMin(g.arrival_time_s)}
                </Td>
                <Td align="right" muted>
                  {g.arrival_p05_s != null && g.arrival_p95_s != null
                    ? `${fmtMin(g.arrival_p05_s)} – ${fmtMin(g.arrival_p95_s)}`
                    : "—"}
                </Td>
                <Td align="right">
                  {g.max_depth_m != null ? `${g.max_depth_m.toFixed(2)} m` : "—"}
                </Td>
                <Td>
                  {hazard && (
                    <span style={{ ...S.badge, background: hazard.bg, color: hazard.fg }}>
                      {hazard.label}
                    </span>
                  )}
                </Td>
              </tr>
            );
          })}
        </tbody>
      </table>

      {hasRun && rows.every((r) => r.arrival_time_s == null) && (
        <div style={S.warn}>
          The flood did not reach any gauge within the simulated time. Increase
          the simulated duration, or check that the domain contains the corridor.
        </div>
      )}

      <p style={S.footnote}>
        Arrival times are the defensible output at 30 m DEM resolution. Point
        depths are indicative only — lead with arrival and inundation extent.
      </p>
    </div>
  );
}

/**
 * FD2320 depth bands, matching jalraksha.impact.hazard.HazardClassifier's
 * CODED thresholds (0.1 / 0.5 / 2.0 / 5.0 / 10.0 m). Note that module's
 * docstring lists different numbers from its own implementation; the code is
 * what runs, so the code is what is mirrored here.
 */
function hazardClass(depth) {
  if (depth == null) return null;
  if (depth < 0.1) return { label: "dry", bg: "#eee", fg: "#555" };
  if (depth < 0.5) return { label: "low", bg: "#e6f4e6", fg: "#1b5e20" };
  if (depth < 2.0) return { label: "moderate", bg: "#fff8e1", fg: "#7a5b00" };
  if (depth < 5.0) return { label: "significant", bg: "#ffe9d6", fg: "#7a3e00" };
  if (depth < 10.0) return { label: "severe", bg: "#fdecea", fg: "#7f1d1d" };
  return { label: "extreme", bg: "#f3e5f5", fg: "#4a148c" };
}

function fmtKm(v) {
  return typeof v === "number" ? `${v.toFixed(1)} km` : "—";
}

function fmtMin(seconds) {
  if (seconds == null) return "—";
  const minutes = seconds / 60;
  return minutes >= 60
    ? `${Math.floor(minutes / 60)}h ${Math.round(minutes % 60)}m`
    : `${minutes.toFixed(1)} min`;
}

function Th({ children, align = "left" }) {
  return <th style={{ ...S.th, textAlign: align }}>{children}</th>;
}

function Td({ children, align = "left", strong, muted }) {
  return (
    <td
      style={{
        ...S.td,
        textAlign: align,
        fontWeight: strong ? 700 : 400,
        color: strong ? "#1565C0" : muted ? "#888" : "#222",
      }}
    >
      {children}
    </td>
  );
}

const S = {
  page: { padding: 16, overflowY: "auto", height: "100%" },
  h3: { margin: "0 0 8px" },
  lede: { fontSize: 12, color: "#777", marginBottom: 10 },
  table: { width: "100%", maxWidth: 900, borderCollapse: "collapse", fontSize: 13 },
  th: { fontSize: 10, textTransform: "uppercase", letterSpacing: 0.4, color: "#666",
        borderBottom: "2px solid #ddd", padding: "6px 8px", whiteSpace: "nowrap" },
  td: { padding: "8px", verticalAlign: "top" },
  tr: { borderBottom: "1px solid #f0f0f0" },
  river: { color: "#888", fontWeight: 400, fontSize: 11 },
  note: { fontSize: 10, color: "#7a3e00", marginTop: 3, maxWidth: 320, lineHeight: 1.4 },
  badge: { fontSize: 10, fontWeight: 700, borderRadius: 3, padding: "2px 7px" },
  warn: { marginTop: 12, padding: "8px 10px", fontSize: 11, border: "2px solid #e65100",
          background: "#fff4e5", borderRadius: 4, color: "#7a3e00", maxWidth: 760 },
  footnote: { fontSize: 11, color: "#777", marginTop: 14, maxWidth: 760, lineHeight: 1.45 },
  empty: { padding: 16, fontSize: 12, color: "#777" },
};
