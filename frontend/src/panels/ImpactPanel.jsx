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
 *   Buildings            GHS-BUILT-S built-up SURFACE over this run's grid.
 *                        Not a building count — no footprint dataset is wired.
 *   Economic damage      that surface and WorldCover cropland, through an
 *                        UNPUBLISHED depth-damage curve on UNVETTED unit
 *                        costs. Per sector, and a sector that could not be
 *                        fetched shows its reason and no figure.
 *
 * A headcount under a "people at risk" headline is the single worst thing in
 * this project to invent, which is why the empty states here are deliberate
 * and prominent rather than hidden.
 */
// Run-specific display override: for the Khadakwasla drain-to-green run,
// the Impact tab shows ONLY the 15-60 min population-at-risk figure, per
// explicit request — not a general panel change, so it is gated on run_id
// rather than applied to every run.
const MEDIUM_URGENCY_ONLY_RUN_ID = "e2e09ea3201d4d42b7a7dbcd5fac4b81";

export default function ImpactPanel({ result }) {
  const par = result?.population_at_risk;
  const hazard = result?.hazard_summary;
  const impact = result?.impact;

  if (!result) {
    return <Empty>Run or load a simulation to see its impact assessment.</Empty>;
  }

  if (result.run_id === MEDIUM_URGENCY_ONLY_RUN_ID) {
    return (
      <div style={S.page}>
        <h3 style={S.h3}>Impact assessment</h3>
        <section style={S.section}>
          <h4 style={S.h4}>Population at risk — 15–60 min warning</h4>
          {par?.available ? (
            <Tile
              label="15–60 min"
              value={num(par.par?.par_medium_urgency_15_60min)}
              emphasis
            />
          ) : (
            <Empty>No population-at-risk figure for this run.</Empty>
          )}
        </section>
      </div>
    );
  }

  return (
    <div style={S.page}>
      <h3 style={S.h3}>Impact assessment</h3>

      <PopulationSection par={par} />
      <FatalitySection par={par} />
      <HazardSection hazard={hazard} />
      <BuildingsSection impact={impact} />
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
          <BackfillNote at={par.backfilled_at} replacesEarlier />
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

function FatalitySection({ par }) {
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

const SECTOR_LABEL = {
  residential: "Residential",
  non_residential: "Non-residential",
  agricultural: "Cropland",
};

function BuildingsSection({ impact }) {
  const built = impact?.exposure_provenance?.built_up;
  return (
    <section style={S.section}>
      <h4 style={S.h4}>Built-up exposure</h4>
      {built ? (
        <>
          <div style={S.row}>
            <Tile
              label="Built-up surface in domain"
              value={`${num(built.total_built_surface_km2)} km²`}
              sub={`${built.source} ${built.epoch}`}
            />
            <Tile
              label="of which non-residential"
              value={`${num(built.total_non_residential_km2)} km²`}
              sub="published band, not an assumed share"
            />
          </div>
          <div style={S.gap}>
            <strong>Surface area, not a building count.</strong>
            <div style={{ marginTop: 4 }}>
              GHS-BUILT-S posts built-up <em>surface</em> in m² per 100 m cell —
              roofprint area, not footprints and not a number of buildings.
              Residential is the published total minus the published
              non-residential band. A count would need Google Open Buildings
              (CC BY 4.0), which is licence-compatible and is not wired into
              this build, so none is shown.
            </div>
          </div>
        </>
      ) : (
        <div style={S.gap}>
          <strong>Not fetched for this run.</strong>
          <div style={{ marginTop: 4 }}>
            GHS-BUILT-S is the asset layer; without it there is no exposure and
            no damage figure. Runs predating this feature have no built-up
            artifact at all.
          </div>
        </div>
      )}
    </section>
  );
}

function DamageSection({ impact }) {
  const damage = impact?.damage;

  if (!damage) {
    return (
      <section style={S.section}>
        <h4 style={S.h4}>Economic damage</h4>
        <div style={S.gap}>
          <strong>Not computed for this run.</strong>
          <div style={{ marginTop: 4 }}>
            No impact artifact was written. Runs that finished before the damage
            estimate existed have none, and no figure is reconstructed for them.
          </div>
        </div>
      </section>
    );
  }

  const sectors = Object.entries(damage.sectors || {});
  const missing = damage.missing_sectors || [];
  const anyAvailable = sectors.some(([, block]) => block.available);

  return (
    <section style={S.section}>
      <h4 style={S.h4}>Economic damage</h4>

      {damage.total_crore_inr != null ? (
        <div style={S.row}>
          <Tile
            label="Total damage"
            value={`₹${num(damage.total_crore_inr)} cr`}
            sub={`₹${num(damage.total_lower_crore_inr)} – ₹${num(damage.total_upper_crore_inr)} cr`}
            emphasis
          />
        </div>
      ) : (
        anyAvailable && (
          <div style={S.warn}>
            <strong>No total.</strong> {missing.map((s) => SECTOR_LABEL[s] || s).join(", ")}{" "}
            could not be fetched, and a total that silently omits a sector reads
            as a complete one. The sectors that were measured are below.
          </div>
        )
      )}

      <div style={{ ...S.row, marginTop: 10 }}>
        {sectors.map(([name, block]) =>
          block.available ? (
            <Tile
              key={name}
              label={SECTOR_LABEL[name] || name}
              value={`₹${num(block.damage_crore_inr)} cr`}
              sub={`${block.exposed_area_km2?.toFixed(3)} km² exposed · ₹${num(
                block.unit_cost_inr_per_m2
              )}/m² (${block.unit_cost_price_year})`}
            />
          ) : (
            <Tile
              key={name}
              label={SECTOR_LABEL[name] || name}
              value="—"
              sub="not measured"
            />
          )
        )}
      </div>

      {sectors
        .filter(([, block]) => !block.available)
        .map(([name, block]) => (
          <div key={name} style={{ ...S.warn, marginTop: 8 }}>
            <strong>{SECTOR_LABEL[name] || name}:</strong> {block.reason}
            <div style={{ marginTop: 4 }}>No estimate is substituted.</div>
          </div>
        ))}

      <div style={S.warnInline}>
        UNVETTED — the depth–damage curve is an unpublished saturating
        exponential, and the unit costs are placeholders at a stated price year,
        echoed above so the figure can be rescaled. An ordering of severity and
        an order of magnitude, not an appraisal.
      </div>
      <div style={S.provenance}>
        Exposure is fetched onto this run's own grid, so it varies with the
        catchment: GHS-BUILT-S built-up surface and ESA WorldCover cropland
        fraction (CC BY 4.0). Cells shallower than{" "}
        {sectors.find(([, b]) => b.available)?.[1]?.depth_threshold_m ?? 0.1} m
        contribute nothing, matching the depth used for the population count
        above. See docs/VERIFICATION_LOG.md rows 10, 35 and 36.
      </div>
      <BackfillNote at={impact.backfilled_at} />
    </section>
  );
}

/**
 * A figure recomputed after its run finished says so.
 *
 * Backfilled population figures REPLACE a wrong number — every headcount
 * written before 2026-09-06 was low by (grid / 100 m)^2, because
 * `reduceResolution(sum)` is area-weighted and returns a mean. Silently
 * swapping the value would leave no way to tell a corrected figure from an
 * original one on a run whose other artifacts still date from the solve.
 */
function BackfillNote({ at, replacesEarlier }) {
  if (!at) return null;
  return (
    <div style={S.provenance}>
      Computed after the run finished ({String(at).slice(0, 10)}) from its own
      stored depth raster — nothing was re-solved.
      {replacesEarlier
        ? " This REPLACES an earlier headcount that was low by (grid ÷ 100 m)²;" +
          " see docs/VERIFICATION_LOG.md row 37."
        : " No damage figure existed for this run before."}
    </div>
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
