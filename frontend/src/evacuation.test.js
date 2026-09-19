import test from "node:test";
import assert from "node:assert/strict";
import { evacuationSummary, hasDirectives, thresholdText } from "./evacuation.js";

const THRESHOLDS = {
  lead_time_s: 7200,
  hazard_floor: "low",
  evacuate_hazard_level: "significant",
  hazard_scheme: "FD2320 depth-only (|V| = 0), debris factor 0.5",
};

function evac(directive, extra = {}) {
  return { directive, thresholds_unvetted: true, thresholds: THRESHOLDS,
           threshold_source: "UNVETTED: chosen for screening", ...extra };
}

const RUN = {
  gauges: [
    { gauge_name: "A", arrival_time_s: 900, max_depth_m: 2.0,
      evacuation: evac("evacuate", { near_boundary: true }) },
    { gauge_name: "B", arrival_time_s: 5000, max_depth_m: 0.3,
      evacuation: evac("evacuate", { minority_arrival: true }) },
    { gauge_name: "C", arrival_time_s: null, max_depth_m: null,
      evacuation: evac("no_arrival") },
  ],
};

test("a run written before directives has none", () => {
  assert.equal(hasDirectives({ gauges: [{ gauge_name: "A", arrival_time_s: 10 }] }), false);
  assert.equal(hasDirectives(null), false);
  assert.equal(hasDirectives(RUN), true);
});

test("reached counts arrivals only; an unreached gauge is not counted as safe", () => {
  const s = evacuationSummary(RUN);
  assert.equal(s.total, 3);
  assert.equal(s.reached, 2);
  assert.equal(s.counts.evacuate, 2);
  assert.equal(s.counts.no_arrival, 1);
  assert.equal(s.counts.monitor, 0);
});

test("mean depth and shortest lead come from reached gauges", () => {
  const s = evacuationSummary(RUN);
  assert.equal(s.meanPeakDepthM, 1.15);
  assert.equal(s.depthsCounted, 2);
  assert.equal(s.shortestLeadS, 900);
});

test("boundary and minority flags are counted", () => {
  const s = evacuationSummary(RUN);
  assert.equal(s.nearBoundaryCount, 1);
  assert.equal(s.minorityCount, 1);
});

test("the unvetted thresholds come from the payload", () => {
  const s = evacuationSummary(RUN);
  assert.equal(s.anyUnvetted, true);
  assert.match(thresholdText(s.thresholds), /significant/);
  assert.match(thresholdText(s.thresholds), /120 min/);
});

test("nothing reached gives null figures, not zeros", () => {
  const s = evacuationSummary({ gauges: [{ gauge_name: "C", arrival_time_s: null }] });
  assert.equal(s.reached, 0);
  assert.equal(s.meanPeakDepthM, null);
  assert.equal(s.shortestLeadS, null);
});

test("a gauge that was not assessed is not flagged as boundary-shaped", () => {
  const s = evacuationSummary({
    gauges: [{ gauge_name: "Edge", arrival_time_s: null,
               evacuation: evac("no_arrival", { near_boundary: true, minority_arrival: true }) }],
  });
  assert.equal(s.nearBoundaryCount, 0);
  assert.equal(s.minorityCount, 0);
});
