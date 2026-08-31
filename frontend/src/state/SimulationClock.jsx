import React, { createContext, useContext, useMemo, useState, useCallback } from "react";

/**
 * SimulationClock — shared playback state above BOTH the 2D and 3D panels.
 *
 * This is the single most important frontend architectural decision in the
 * integration brief (§5.4): scrubbing/playing in one panel must drive the other.
 * One Clock instance lives at the app root; both panels subscribe to it.
 *
 * State:
 *   keyframes : manifest keyframe list [{time_s, png_url, bounds, hazard_summary}]
 *   index     : current keyframe index
 *   playing   : auto-advance on/off
 *   speed     : seconds of wall-clock per simulation second (playback rate)
 */
const SimulationClockContext = createContext(null);

export function SimulationClockProvider({ manifest, children }) {
  const keyframes = manifest?.keyframes || [];
  const [index, setIndex] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(60); // 60 sim-seconds per wall-second

  const current = keyframes[index] || null;

  const seekTo = useCallback(
    (i) => setIndex(Math.max(0, Math.min(keyframes.length - 1, i))),
    [keyframes.length]
  );
  const next = useCallback(() => seekTo(index + 1), [index, seekTo]);
  const prev = useCallback(() => seekTo(index - 1), [index, seekTo]);

  const value = useMemo(
    () => ({
      keyframes,
      index,
      current,
      playing,
      speed,
      setPlaying,
      setSpeed,
      seekTo,
      next,
      prev,
      // Cesium's Clock uses JulianDate; expose current sim time in seconds.
      currentTimeS: current ? current.time_s : 0,
    }),
    [keyframes, index, current, playing, speed]
  );

  return (
    <SimulationClockContext.Provider value={value}>
      {children}
    </SimulationClockContext.Provider>
  );
}

export function useSimulationClock() {
  const ctx = useContext(SimulationClockContext);
  if (!ctx) throw new Error("useSimulationClock must be used inside SimulationClockProvider");
  return ctx;
}
