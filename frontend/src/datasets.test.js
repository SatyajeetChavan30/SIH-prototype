import test from "node:test";
import assert from "node:assert/strict";
import { fmtBytes, hashLabel, summariseDatasets } from "./datasets.js";

const PAYLOAD = {
  data_dir: "D:/data",
  total_bytes: 3000,
  hashing: { status: "running", pending: 2 },
  rows: [
    { name: "tile", family: "dem_copernicus", bytes: 2000, sha256: null,
      redistribution: "approved", superseded: false },
    { name: "ghsl v1", family: "ghsl", bytes: 1000, sha256: null,
      redistribution: "approved", superseded: true },
    { name: "Delft3D FM", family: "engine", bytes: null, sha256: null,
      redistribution: "not redistributed", superseded: false, present: true },
  ],
};

test("families are grouped and sized", () => {
  const summary = summariseDatasets(PAYLOAD);
  assert.equal(summary.families[0].family, "dem_copernicus");
  assert.equal(summary.families[0].bytes, 2000);
  assert.equal(summary.totalBytes, 3000);
  assert.equal(summary.fileCount, 2, "an engine row is not a file");
});

test("a superseded product is listed, not hidden", () => {
  const summary = summariseDatasets(PAYLOAD);
  assert.equal(summary.superseded.length, 1);
  assert.equal(summary.superseded[0].name, "ghsl v1");
});

test("a forbidden licence is surfaced separately", () => {
  const summary = summariseDatasets({
    rows: [{ name: "osm extract", family: "unknown", bytes: 10,
             redistribution: "forbidden", redistribution_reason: "names 'osm'" }],
  });
  assert.equal(summary.forbidden.length, 1);
  assert.match(summary.forbidden[0].redistribution_reason, /osm/);
});

test("an empty catalogue summarises to nothing, not to an error", () => {
  const summary = summariseDatasets(null);
  assert.deepEqual(summary.families, []);
  assert.equal(summary.totalBytes, 0);
});

test("a hash still being computed says so rather than reading as absent", () => {
  const running = hashLabel(PAYLOAD.rows[0], PAYLOAD.hashing);
  assert.equal(running.pending, true);
  assert.equal(running.text, "computing…");

  const done = hashLabel({ bytes: 10, sha256: "abcdef0123456789" }, { status: "done" });
  assert.equal(done.pending, false);
  assert.match(done.text, /^abcdef012345/);

  const engine = hashLabel({ bytes: null }, { status: "done" });
  assert.equal(engine.text, "—");
});

test("byte sizes read naturally", () => {
  assert.equal(fmtBytes(0), "0 B");
  assert.equal(fmtBytes(1024), "1.0 KB");
  assert.equal(fmtBytes(70 * 1024 * 1024), "70 MB");
  assert.equal(fmtBytes(null), "—");
});
