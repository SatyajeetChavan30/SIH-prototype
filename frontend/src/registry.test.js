import test from "node:test";
import assert from "node:assert/strict";
import { demLabel, frlLabel, tierBadge } from "./registry.js";

const ROW = {
  id: "khadakwasla",
  tier: "verified_run",
  tier_reason: "46 completed run(s) with exports in this database.",
  dem: { cached: true, covers_domain: true, path: "data/dem/dem_18.44_73.77_clipped.tif" },
  frl: { frl_m: null, crest_m: null, frl_source: "DEM-derived pool surface (UNVETTED)" },
};

test("the badge carries the server's own reason", () => {
  const badge = tierBadge(ROW);
  assert.equal(badge.label, "Verified run");
  assert.match(badge.reason, /46 completed/);
});

test("an unknown tier is not silently treated as ready", () => {
  assert.equal(tierBadge({ tier: "something_new" }).label, "Unknown");
  assert.equal(tierBadge(null).label, "Unknown");
});

test("a staged DEM that misses the domain does not read as cached", () => {
  const row = { ...ROW, dem: { cached: true, covers_domain: false, reason: "corners" } };
  const label = demLabel(row);
  assert.equal(label.ok, false);
  assert.match(label.text, /does not cover/);
});

test("no DEM says so", () => {
  assert.equal(demLabel({ dem: { cached: false, reason: "DEM not cached" } }).ok, false);
  assert.match(demLabel({}).text, /not cached/);
});

test("an unpublished FRL shows its source, not a number", () => {
  const label = frlLabel(ROW);
  assert.equal(label.value, null);
  assert.equal(label.text, "not published for this dam");
  assert.match(label.source, /UNVETTED/);
});

test("a published FRL shows the level and the crest", () => {
  const label = frlLabel({ frl: { frl_m: 830, crest_m: 839.5, frl_source: "preset literal" } });
  assert.match(label.text, /830 m/);
  assert.match(label.text, /crest 839.5 m/);
});
