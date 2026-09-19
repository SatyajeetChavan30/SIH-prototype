import test from "node:test";
import assert from "node:assert/strict";
import {
  BASE_FRAME_INTERVAL_MS, PLAYBACK_RATES, fmtSimTime, frameIntervalMs, phaseMarkers,
} from "./playback.js";

function frame(time_s, wet) {
  return {
    time_s,
    hazard_summary: wet == null ? undefined : { low: { count: wet }, extreme: { count: 0 } },
  };
}

test("rate 1 reproduces the original 500 ms interval exactly", () => {
  assert.equal(BASE_FRAME_INTERVAL_MS, 500);
  assert.equal(frameIntervalMs(1), 500);
  assert.equal(PLAYBACK_RATES[0], 1);
});

test("faster rates shorten the interval; nonsense falls back to rate 1", () => {
  assert.equal(frameIntervalMs(2), 250);
  assert.equal(frameIntervalMs(10), 50);
  assert.equal(frameIntervalMs(0), 500);
  assert.equal(frameIntervalMs(undefined), 500);
});

test("an empty manifest has no markers", () => {
  assert.deepEqual(phaseMarkers([]), []);
  assert.deepEqual(phaseMarkers(undefined), []);
});

test("the peak marker follows each run's own wet extent", () => {
  const early = [frame(0, 1), frame(600, 50), frame(1200, 20), frame(1800, 5)];
  const late = [frame(0, 1), frame(600, 5), frame(1200, 20), frame(1800, 50), frame(2400, 3)];
  const peak = (frames) => phaseMarkers(frames).find((m) => m.label === "Peak wet extent");
  assert.equal(peak(early).time_s, 600);
  assert.equal(peak(late).time_s, 1800);
});

test("no hazard summaries means no peak marker, not a guessed one", () => {
  const markers = phaseMarkers([frame(0), frame(600), frame(1200)]);
  assert.deepEqual(markers.map((m) => m.label), ["Release", "Last frame"]);
});

test("legacy 'severe' cells count toward the wet extent", () => {
  const frames = [
    frame(0, 1),
    { time_s: 600, hazard_summary: { low: { count: 1 }, severe: { count: 90 } } },
    frame(1200, 30),
  ];
  assert.equal(phaseMarkers(frames).find((m) => m.label === "Peak wet extent").time_s, 600);
});

test("a peak on the last frame is not listed twice", () => {
  const markers = phaseMarkers([frame(0, 1), frame(600, 5), frame(1200, 9)]);
  assert.deepEqual(markers.map((m) => m.label), ["Release", "Peak wet extent"]);
});

test("simulation times read naturally", () => {
  assert.equal(fmtSimTime(40), "40 s");
  assert.equal(fmtSimTime(720), "12 min");
  assert.equal(fmtSimTime(5700), "1h 35m");
});
