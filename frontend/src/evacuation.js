/**
 * Evacuation directives, as the run stored them.
 *
 * The directive for each gauge is computed ONCE, server-side, by
 * jalraksha/impact/evacuation.py and travels in GaugeResult.evacuation with its
 * label, colours and thresholds. Nothing here decides a directive: this file
 * only summarises the stored payloads, so the Gauges and Impact tabs cannot
 * disagree with each other or with the service. FD2320 once had five copies of
 * one table in this repo, and two live ones disagreed on real output.
 *
 * Pure (no React) so `node --test` can pin it.
 */

export const DIRECTIVE_ORDER = ["evacuate", "prepare", "monitor", "no_arrival"];

/** True when this run's gauges carry directives (runs before them do not). */
export function hasDirectives(result) {
  return (result?.gauges || []).some((g) => g.evacuation);
}

/**
 * The Impact tab's summary row.
 *
 * "Reached" counts gauges with an arrival time. They are gauged places — towns,
 * and on some presets TERRAIN-DERIVED thalweg points — not a village census, so
 * the count is never labelled as villages.
 */
export function evacuationSummary(result) {
  const gauges = result?.gauges || [];
  const reached = gauges.filter((g) => g.arrival_time_s != null);
  const depths = reached.map((g) => g.max_depth_m).filter((d) => d != null);
  const counts = Object.fromEntries(DIRECTIVE_ORDER.map((d) => [d, 0]));
  let nearBoundaryCount = 0;
  let minorityCount = 0;
  let thresholds = null;
  let thresholdSource = null;
  for (const g of gauges) {
    const e = g.evacuation;
    if (!e) continue;
    if (e.directive in counts) counts[e.directive] += 1;
    // Only a directive that was computed FROM a depth can be shaped by the
    // boundary or rest on a minority; a gauge the flood never reached was not
    // assessed at all, and flagging it would describe a reading that was never made.
    const assessed = e.directive !== "no_arrival";
    if (assessed && e.near_boundary) nearBoundaryCount += 1;
    if (assessed && e.minority_arrival) minorityCount += 1;
    if (e.thresholds_unvetted && !thresholds) {
      thresholds = e.thresholds || {};
      thresholdSource = e.threshold_source || null;
    }
  }
  return {
    total: gauges.length,
    reached: reached.length,
    meanPeakDepthM: depths.length ? depths.reduce((a, b) => a + b, 0) / depths.length : null,
    depthsCounted: depths.length,
    shortestLeadS: reached.length ? Math.min(...reached.map((g) => g.arrival_time_s)) : null,
    counts,
    nearBoundaryCount,
    minorityCount,
    anyUnvetted: thresholds != null,
    thresholds,
    thresholdSource,
  };
}

/** The unvetted thresholds in words, read from the payload, never restated here. */
export function thresholdText(thresholds) {
  if (!thresholds) return null;
  const parts = [];
  if (thresholds.evacuate_hazard_level) {
    parts.push(`Evacuate at hazard class ${thresholds.evacuate_hazard_level} or above`);
  }
  if (thresholds.lead_time_s != null) {
    parts.push(
      `or at class ${thresholds.hazard_floor ?? "?"} or above when the flood arrives ` +
      `in under ${Math.round(thresholds.lead_time_s / 60)} min`,
    );
  }
  const text = parts.join(", ");
  return thresholds.hazard_scheme ? `${text}. Hazard: ${thresholds.hazard_scheme}.` : `${text}.`;
}
