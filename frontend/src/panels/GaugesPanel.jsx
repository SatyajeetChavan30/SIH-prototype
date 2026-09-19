import React from "react";
import { Caveat, Chip, DataTable, Empty } from "../ui/index.jsx";

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
    return <Empty>No downstream corridor is defined for this dam.</Empty>;
  }

  return (
    <div className="jr-page">
      <h3 className="jr-h1">
        Downstream gauges{dam?.name ? ` — ${dam.name}` : ""}
      </h3>
      {!hasRun && (
        <p className="jr-lede">
          Reference corridor. Run or load a simulation to populate arrival times.
        </p>
      )}

      <DataTable className="jr-measure-wide">
        <thead>
          <tr>
            <th>Town</th>
            <th className="num">Distance</th>
            <th className="num">Arrival (median)</th>
            <th className="num">5th–95th</th>
            <th className="num">Peak depth</th>
            <th>Hazard</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((g) => {
            const hazard = hazardClass(g.max_depth_m);
            return (
              <tr key={g.gauge_name}>
                <td>
                  <strong>{g.gauge_name}</strong>
                  {g.river && <span className="muted"> · {g.river}</span>}
                  {g.note && (
                    <Caveat compact className="jr-row-note">{g.note}</Caveat>
                  )}
                </td>
                <td className="num">{fmtKm(g.distance_km)}</td>
                <td className={g.arrival_time_s != null ? "num strong" : "num muted"}>
                  {fmtMin(g.arrival_time_s)}
                </td>
                <td className="num muted">
                  {g.arrival_p05_s != null && g.arrival_p95_s != null
                    ? `${fmtMin(g.arrival_p05_s)} – ${fmtMin(g.arrival_p95_s)}`
                    : "—"}
                </td>
                <td className="num">
                  {g.max_depth_m != null ? `${g.max_depth_m.toFixed(2)} m` : "—"}
                </td>
                <td>
                  {/* Shape from the class, colour from the FD2320 mirror below:
                      hazard colours are data and never live in the stylesheet. */}
                  {hazard && (
                    <Chip style={{ background: hazard.bg, color: hazard.fg }}>
                      {hazard.label}
                    </Chip>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </DataTable>

      {hasRun && rows.every((r) => r.arrival_time_s == null) && (
        <Caveat className="jr-measure jr-mt-12">
          The flood did not reach any gauge within the simulated time. Increase
          the simulated duration, or check that the domain contains the corridor.
        </Caveat>
      )}

      <p className="jr-note jr-measure jr-mt-16">
        Arrival times are the defensible output at 30 m DEM resolution. Point
        depths are indicative only — lead with arrival and inundation extent.
      </p>
    </div>
  );
}

/**
 * FD2320 depth-only bands, mirroring
 * jalraksha.impact.hazard.HazardClassifier.classify_depth_only.
 *
 * That method evaluates HR = depth * (|V| + 0.5) + DF at |V| = 0, which with
 * the default debris factor of 0.5 reduces to HR = 0.5*depth + 0.5. Against
 * the published class boundaries of 0.75 / 1.25 / 2.5 that puts the depth
 * edges at 0.5 / 1.5 / 4.0 m. A gauge reports a depth and no velocity, so the
 * depth-only form is the correct one here — but it UNDER-states hazard
 * wherever the flow is fast.
 *
 * These numbers are duplicated from Python only because the badge renders
 * before any classified raster is available. If they are edited, edit
 * hazard.py first: it is the source of truth, and this file mirrors it.
 */
function hazardClass(depth) {
  if (depth == null) return null;
  if (depth < 0.05) return { label: "dry", bg: "#eee", fg: "#555" };
  if (depth < 0.5) return { label: "low", bg: "#e6f4e6", fg: "#1b5e20" };
  if (depth < 1.5) return { label: "moderate", bg: "#fff8e1", fg: "#7a5b00" };
  if (depth < 4.0) return { label: "significant", bg: "#ffe9d6", fg: "#7a3e00" };
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
