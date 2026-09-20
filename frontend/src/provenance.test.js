import test from "node:test";
import assert from "node:assert/strict";
import { NOT_RECORDED, provenanceSections } from "./provenance.js";

// The shape of a run written before most provenance fields existed: the
// shipped database still holds runs like this and the tab must render them.
const OLD_RUN = { run_id: "abc123", dam_name: "Khadakwasla Dam", exports: [], gauges: [] };

function allRows(result) {
  return provenanceSections(result).flatMap((s) => s.rows);
}

test("no result gives no sections", () => {
  assert.deepEqual(provenanceSections(null), []);
});

test("an old run never renders a blank value", () => {
  for (const r of allRows(OLD_RUN)) {
    assert.ok(typeof r.value === "string" && r.value.length > 0, `${r.label} is blank`);
    assert.ok(r.path, `${r.label} names no source field`);
  }
});

test("a field the run did not record says so", () => {
  const backend = allRows(OLD_RUN).find((r) => r.path === "solver_backend.solver_backend_label");
  assert.equal(backend.value, NOT_RECORDED);
  assert.equal(backend.missing, true);
});

test("a recorded field is shown and not flagged missing", () => {
  const rows = allRows({
    ...OLD_RUN,
    solver_backend: { solver_backend_label: "GPU (CUDA, RTX 4050, float64)" },
  });
  const backend = rows.find((r) => r.path === "solver_backend.solver_backend_label");
  assert.equal(backend.value, "GPU (CUDA, RTX 4050, float64)");
  assert.equal(backend.missing, false);
});

test("a false flag is a value, not a missing field", () => {
  const rows = allRows({ ...OLD_RUN, is_synthetic: false });
  const synthetic = rows.find((r) => r.path === "is_synthetic");
  assert.equal(synthetic.value, "no");
  assert.equal(synthetic.missing, false);
});

test("a synthetic run carries a danger caveat", () => {
  const run = provenanceSections({ ...OLD_RUN, is_synthetic: true, synthetic_note: "painted" })
    .find((s) => s.id === "run");
  assert.equal(run.caveats[0].tone, "danger");
  assert.equal(run.caveats[0].body, "painted");
});

test("an unverified regression carries a caveat naming it", () => {
  const breach = provenanceSections({
    ...OLD_RUN,
    ensemble: { uses_unverified_regression: true, unverified_regressions: ["xu_zhang"] },
  }).find((s) => s.id === "ensemble");
  assert.ok(breach.caveats.some((c) => c.title.includes("xu_zhang")));
});

test("boundary-shaped and minority gauges are counted and labelled", () => {
  const gauges = provenanceSections({
    ...OLD_RUN,
    gauges: [
      { gauge_name: "A", near_boundary: true },
      { gauge_name: "B", note: "MINORITY ARRIVAL: 1 of 4 ensemble members reached this gauge." },
      { gauge_name: "C" },
    ],
  }).find((s) => s.id === "gauges");
  assert.equal(gauges.rows.find((r) => r.path === "gauges[].near_boundary").value, "1");
  assert.equal(gauges.rows.find((r) => r.path === "gauges[].note").value, "1");
  assert.equal(gauges.caveats.length, 2);
});

test("a Delft3D fallback is named only on a run that asked for Delft3D", () => {
  const engine = { delft3d_binary_used: false, fallback_reason: "kernel missing" };
  const asked = provenanceSections({ ...OLD_RUN, solver: "delft3d", engine })
    .find((s) => s.id === "compute");
  const notAsked = provenanceSections({ ...OLD_RUN, solver: "swe", engine })
    .find((s) => s.id === "compute");
  assert.match(asked.caveats[0].title, /NOT Delft3D FM/);
  assert.equal(notAsked.caveats.length, 0);
});

test("an absent dem_update is a real 'no' only when the DEM block was recorded", () => {
  const find = (result) => allRows(result).find((r) => r.path === "dem_update");
  assert.equal(find(OLD_RUN).value, NOT_RECORDED);
  assert.equal(find({ ...OLD_RUN, dem_used: "/files/dem/x.tif" }).value, "no");
  assert.equal(find({ ...OLD_RUN, dem_used: "/files/dem/x.tif", dem_update: {} }).value, "yes");
});

test("a refusal row appears only where population was refused", () => {
  const has = (par) => allRows({ ...OLD_RUN, population_at_risk: par })
    .some((r) => r.path === "population_at_risk.reason");
  assert.equal(has({ available: true, population_source: "GHSL" }), false);
  assert.equal(has({ available: false, reason: "no Earth Engine" }), true);
});

test("a refused exposure sector shows its reason, not 'not recorded'", () => {
  const cropland = allRows({
    ...OLD_RUN,
    impact: {
      exposure_provenance: {},
      damage: {
        model_is_published: false,
        missing_sectors: ["agricultural"],
        sectors: { agricultural: { available: false, reason: "no WorldCover grid" } },
      },
    },
  }).find((r) => r.path === "impact.exposure_provenance.cropland");
  assert.equal(cropland.value, "refused — no WorldCover grid");
});

test("a fallback reason row appears only where something fell back", () => {
  const has = (engine) => allRows({ ...OLD_RUN, engine })
    .some((r) => r.path === "engine.fallback_reason");
  assert.equal(has({ delft3d_binary_used: true, label: "Delft3D FM" }), false);
  assert.equal(has({ delft3d_binary_used: false, fallback_reason: "kernel missing" }), true);
});
