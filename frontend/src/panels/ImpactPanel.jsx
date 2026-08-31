import React from "react";
import {
  Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";

/**
 * Impact assessment — population at risk, loss of life, hazard classes.
 *
 * The governing rule for this panel is that a tile either carries a real number
 * or says why it does not. Nothing here is derived from another estimate to
 * fill a gap:
 *
 *   Population at risk   real GHSL census counts over this run's own grid.
 *                        Absent -> the reason is shown and NO figure appears.
 *   Loss of life         Graham (USBR DSO-99-06) applied to the PAR urgency
 *                        buckets. Shown as a range across warning assumptions,
 *                        never as a single number.
 *   Hazard classes       FD2320 classification of the final keyframe.
 *   Buildings            no data source is integrated. Stated, not estimated.
 *
 * A headcount under a "people at risk" headline is the single worst thing in
 * this project to invent, which is why the empty states here are deliberate
 * and prominent rather than hidden.
 */
export default function ImpactPanel({ result }) {
  const par = result?.population_at_risk;
  const hazard = result?.hazard_summary;
  const impact = result?.impact;

  if (!result) {
    return <Empty>Run or load a simulation to see its impact assessment.</Empty>;
  }

  return (
    <div style={S.page}>
      <h3 style={S.h3}>Impact assessment</h3>

      <PopulationSection par={par} />
      <FatalitySection par={par} impact={impact} />
      <HazardSection hazard={hazard} />
      <BuildingsSection />
      <DamageSection impact={impact} />
    </div>
  );
}

function PopulationSection({ par }) {
  return (
    <section style={S.section}>
      <h4 style={S.h4}>Population at risk</h4>
      {!par ? (
        <Empty>No population artifact was written for this run.</Empty>
      ) : !par.available ? (
        <div style={S.warn}>
          <strong>No population-at-risk figure</strong>
          <div style={{ marginTop: 4 }}>{par.reason}</div>
          <div style={{ marginTop: 4 }}>No estimate is substituted.</div>
        </div>
      ) : (
        <>
          <div style={S.row}>
            <Tile
              label="Total at risk"
              value={num(par.par?.total_par)}
              sub={`of ${num(par.total_population_in_domain)} in the domain`}
              emphasis
            />
            <Tile
              label="< 15 min warning"
              value={num(par.par?.par_high_urgency_under_15min)}
              sub="highest urgency"
            />
            <Tile
              label="15–60 min"
              value={num(par.par?.par_medium_urgency_15_60min)}
            />
            <Tile
              label="> 60 min"
              value={num(par.par?.par_low_urgency_over_60min)}
            />
          </div>
          <div style={S.provenance}>
            {par.population_source}
            {par.population_epoch ? ` · epoch ${par.population_epoch}` : ""} · assumes{" "}
            {Math.round((par.warning_lead_time_s || 0) / 60)} min warning lead time
            {" "}(UNVETTED — shifts people between buckets, not the total)
          </div>
        </>
      )}
    </section>
  );
}

/**
 * Loss of life from the Graham (1999) rate table, joined to the PAR buckets.
 *
 * Graham's table is indexed by warning time and flood severity, and
 * compute_par already bins population into exactly the <15 / 15-60 / >60 min
 * warning bands the table uses — so this is a direct join, not a model.
 * Computed client-side from the published rates so the assumption is visible
 * rather than buried in a service.
 */
const GRAHAM_RATES = {
  // severity: [<15 min, 15-60 min, >60 min]   USBR DSO-99-06
  high: [0.75, 0.2, 0.01],
  medium: [0.15, 0.04, 0.002],
  low: [0.01, 0.002, 0.0002],
};

function FatalitySection({ par, impact }) {
  if (!par?.available) {
    return (
      <section style={S.section}>
        <h4 style={S.h4}>Loss of life</h4>
        <Empty>
          Not computable without a population-at-risk figure — the Graham rate
          table is applied to PAR, so an absent headcount means no fatality
          estimate rather than a substituted one.
        </Empty>
      </section>
    );
  }

  const buckets = [
    par.par?.par_high_urgency_under_15min || 0,
    par.par?.par_medium_urgency_15_60min || 0,
    par.par?.par_low_urgency_over_60min || 0,
  ];
  const bySeverity = Object.entries(GRAHAM_RATES).map(([severity, rates]) => ({
    severity,
    fatalities: buckets.reduce((sum, p, i) => sum + p * rates[i], 0),
  }));
  const lo = Math.min(...bySeverity.map((b) => b.fatalities));
  const hi = Math.max(...bySeverity.map((b) => b.fatalities));

  return (
    <section style={S.section}>
      <h4 style={S.h4}>Loss of life (Graham, USBR DSO-99-06)</h4>
      <div style={S.row}>
        <Tile
          label="Estimated range"
          value={`${num(lo)} – ${num(hi)}`}
          sub="across low / medium / high flood severity"
          emphasis
        />
        {bySeverity.map((b) => (
          <Tile
            key={b.severity}
            label={`${b.severity} severity`}
            value={num(b.fatalities)}
          />
        ))}
      </div>
      {impact?.jonkman != null && (
        <div style={S.provenance}>
          Jonkman method, for comparison: <strong>{num(impact.jonkman)}</strong>
        </div>
      )}
      <div style={S.provenance}>
        A range, never a point value. The severity band is not determined by
        this run — it depends on flood depth, velocity and building type at each
        location — so all three are shown rather than one being chosen.
      </div>
    </section>
  );
}

function HazardSection({ hazard }) {
  if (!hazard) {
    return (
      <section style={S.section}>
        <h4 style={S.h4}>Hazard classification</h4>
        <Empty>No hazard summary — this run produced no keyframes.</Empty>
      </section>
    );
  }

  const levels = ["low", "moderate", "significant", "severe", "extreme"];

  // Share of the FLOODED area, not the whole domain — the same correction the
  // map legend needed. hazard[l].percentage divides by every cell including
  // dry, so on a domain that is 99.5% dry every bar collapses to near zero and
  // the chart implies the flood has no gradient. Recomputed from `count`,
  // which is present in every stored manifest, so older runs render correctly
  // too without changing what summarize() persists.
  const wetCells = levels.reduce((sum, l) => sum + (hazard[l]?.count || 0), 0);
  const rows = levels
    .filter((l) => hazard[l] && hazard[l].count > 0)
    .map((l) => ({
      name: l,
      pct: wetCells ? (hazard[l].count / wetCells) * 100 : 0,
      cells: hazard[l].count,
      color: `rgb(${(hazard[l].color || [128, 128, 128]).join(",")})`,
    }));

  // Severity over the water only. The stored weighted_hazard_index is diluted
  // by the dry majority and reads ~0.002 for a genuinely dangerous flood.
  const weightedWet = wetCells
    ? levels.reduce((sum, l) => sum + (hazard[l]?.weight || 0) * (hazard[l]?.count || 0), 0) / wetCells
    : null;

  return (
    <section style={S.section}>
      <h4 style={S.h4}>Hazard classification (FD2320)</h4>
      <div style={S.row}>
        {weightedWet != null && (
          <Tile
            label="Severity index (over water)"
            value={weightedWet.toFixed(2)}
            sub="0 = shallow, 1 = every flooded cell extreme"
            emphasis
          />
        )}
        <Tile
          label="Flooded cells"
          value={num(wetCells)}
          sub={hazard.total_cells ? `of ${num(hazard.total_cells)} in the domain` : null}
        />
      </div>
      <div style={{ height: 180, marginTop: 10 }}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={rows} margin={{ top: 8, right: 16, bottom: 8, left: 8 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#eee" />
            <XAxis dataKey="name" tick={{ fontSize: 11 }} />
            <YAxis tick={{ fontSize: 11 }}
                   label={{ value: "% of flooded area", angle: -90, position: "insideLeft", fontSize: 11 }} />
            <Tooltip formatter={(v, _n, p) => [`${Number(v).toFixed(1)}% of the flood (${num(p.payload.cells)} cells)`, "area"]} />
            <Bar dataKey="pct">
              {rows.map((r) => (
                <Cell key={r.name} fill={r.color} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </section>
  );
}

function BuildingsSection() {
  return (
    <section style={S.section}>
      <h4 style={S.h4}>Buildings affected</h4>
      <div style={S.gap}>
        <strong>No data source integrated.</strong>
        <div style={{ marginTop: 4 }}>
          No building footprint dataset is wired into this build. Google Open
          Buildings (CC BY 4.0) is licence-compatible and is the intended
          source. A count derived from population density and flooded area
          would be a number invented from another number, so none is shown.
        </div>
      </div>
    </section>
  );
}

function DamageSection({ impact }) {
  if (!impact?.damage) {
    return (
      <section style={S.section}>
        <h4 style={S.h4}>Economic damage</h4>
        <div style={S.gap}>
          <strong>Not computed for this run.</strong>
          <div style={{ marginTop: 4 }}>
            The depth–damage module exists but its asset values are fixed
            constants (125 / 85 / 45 crore per category) rather than anything
            derived from this catchment, so a rupee figure here would carry
            more authority than its inputs support.
          </div>
        </div>
      </section>
    );
  }
  return (
    <section style={S.section}>
      <h4 style={S.h4}>Economic damage</h4>
      <div style={S.row}>
        <Tile label="Estimated damage" value={`₹${num(impact.damage.damage_crore_inr)} cr`}
              sub={impact.damage.uncertainty_applied} emphasis />
      </div>
      <div style={S.warnInline}>
        UNVETTED — asset values are fixed constants, not derived from this
        catchment. Treat as an order of magnitude.
      </div>
    </section>
  );
}

function Tile({ label, value, sub, emphasis }) {
  return (
    <div style={{ ...S.tile, ...(emphasis ? S.tileEmphasis : null) }}>
      <div style={S.tileLabel}>{label}</div>
      <div style={{ ...S.tileValue, fontSize: emphasis ? 26 : 20 }}>{value}</div>
      {sub && <div style={S.tileSub}>{sub}</div>}
    </div>
  );
}

function Empty({ children }) {
  return <div style={S.empty}>{children}</div>;
}

function num(v) {
  if (typeof v !== "number" || !isFinite(v)) return "—";
  if (v > 0 && v < 1) return v.toFixed(2);
  return Math.round(v).toLocaleString();
}

const S = {
  page: { padding: 16, overflowY: "auto", height: "100%" },
  h3: { margin: "0 0 12px" },
  h4: { margin: "0 0 8px", fontSize: 13, color: "#555" },
  section: { marginBottom: 22 },
  row: { display: "flex", gap: 10, flexWrap: "wrap" },
  tile: { flex: "1 1 160px", border: "1px solid #ddd", borderRadius: 4,
          padding: "10px 12px", background: "#fafafa" },
  tileEmphasis: { borderColor: "#1565C0", background: "#f3f8fd" },
  tileLabel: { fontSize: 10, color: "#666", textTransform: "uppercase", letterSpacing: 0.4 },
  tileValue: { fontWeight: 700, marginTop: 4 },
  tileSub: { fontSize: 10, color: "#777", marginTop: 3 },
  provenance: { fontSize: 10, color: "#777", marginTop: 8, lineHeight: 1.45, maxWidth: 760 },
  warn: { padding: "8px 10px", fontSize: 11, border: "2px solid #e65100",
          background: "#fff4e5", borderRadius: 4, color: "#7a3e00" },
  warnInline: { fontSize: 10, color: "#7a3e00", marginTop: 6 },
  gap: { padding: "8px 10px", fontSize: 11, border: "1px dashed #999",
         background: "#fafafa", borderRadius: 4, color: "#555",
         maxWidth: 760, lineHeight: 1.5 },
  empty: { fontSize: 12, color: "#777", padding: "8px 0", maxWidth: 700, lineHeight: 1.5 },
};
