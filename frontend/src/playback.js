/**
 * Playback speed and phase markers for the shared SimulationClock.
 *
 * Pure (no React) so `node --test` can pin the two properties that matter:
 * rate 1 reproduces the original 500 ms frame interval exactly, and the phase
 * markers come from THIS run's manifest rather than from hours typed in. A
 * label like "T=12h Wave Peak" on every dam cannot be right for two dams with
 * different travel times; the peak here is wherever this run's wet extent
 * actually peaks.
 */
import { HAZARD_LEVELS, foldLegacyLevels } from "./hazard.js";

/** The interval PlaybackDriver used before speeds existed; rate 1 keeps it. */
export const BASE_FRAME_INTERVAL_MS = 500;

export const PLAYBACK_RATES = [1, 2, 5, 10];

export function frameIntervalMs(rate) {
  const r = Number(rate);
  return BASE_FRAME_INTERVAL_MS / (Number.isFinite(r) && r > 0 ? r : 1);
}

/** Wet cells in one keyframe: every FD2320 wet class, legacy "severe" folded in. */
function wetCells(keyframe) {
  const summary = foldLegacyLevels(keyframe?.hazard_summary);
  if (!summary) return null;
  let total = 0;
  let any = false;
  for (const level of HAZARD_LEVELS) {
    const count = summary[level]?.count;
    if (typeof count === "number") {
      total += count;
      any = true;
    }
  }
  return any ? total : null;
}

/**
 * Markers along the scrubber: [{index, time_s, label}].
 *
 * "Release" at the first frame, "Peak wet extent" at the frame with the most
 * wet cells (omitted when the manifest carries no hazard summaries, rather than
 * guessed), and "Last frame". Times are the manifest's own.
 */
export function phaseMarkers(keyframes) {
  const frames = keyframes || [];
  if (!frames.length) return [];
  const markers = [{ index: 0, time_s: frames[0].time_s ?? 0, label: "Release" }];

  let peakIndex = null;
  let peakCells = -1;
  frames.forEach((kf, i) => {
    const cells = wetCells(kf);
    if (cells != null && cells > peakCells) {
      peakCells = cells;
      peakIndex = i;
    }
  });
  if (peakIndex != null && peakCells > 0 && peakIndex !== 0) {
    markers.push({ index: peakIndex, time_s: frames[peakIndex].time_s ?? null, label: "Peak wet extent" });
  }

  const last = frames.length - 1;
  if (last > 0 && last !== peakIndex) {
    markers.push({ index: last, time_s: frames[last].time_s ?? null, label: "Last frame" });
  }
  return markers;
}

/** "1h 35m" / "12 min" / "40 s", for a marker's time. */
export function fmtSimTime(seconds) {
  if (seconds == null || !Number.isFinite(seconds)) return "—";
  if (seconds < 60) return `${Math.round(seconds)} s`;
  const minutes = seconds / 60;
  return minutes >= 60
    ? `${Math.floor(minutes / 60)}h ${Math.round(minutes % 60)}m`
    : `${Math.round(minutes)} min`;
}
