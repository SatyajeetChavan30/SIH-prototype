import React from "react";
import { useSimulationClock } from "../state/SimulationClock.jsx";
import { PLAYBACK_RATES, fmtSimTime, phaseMarkers } from "../playback.js";
import { Button } from "../ui/index.jsx";

/**
 * Playback speed pills and phase markers, under the sidebar scrubber.
 *
 * Speed changes only how often PlaybackDriver advances a frame; 1x is the
 * original 500 ms interval. The markers are read from this run's keyframe
 * manifest (playback.js), so "Peak wet extent" sits where this run's flood
 * actually peaks and each marker carries its own simulated time.
 */
export default function PlaybackRate() {
  const { keyframes, index, playbackRate, setPlaybackRate, seekTo } = useSimulationClock();
  if (!keyframes.length) return null;
  const markers = phaseMarkers(keyframes);

  return (
    <>
      <div className="jr-playback jr-mt-8" role="group" aria-label="Playback speed">
        {PLAYBACK_RATES.map((rate) => (
          <Button
            key={rate}
            size="sm"
            variant={rate === playbackRate ? "primary" : undefined}
            aria-pressed={rate === playbackRate}
            onClick={() => setPlaybackRate(rate)}
          >
            {rate}×
          </Button>
        ))}
      </div>
      {markers.length > 1 && (
        <div className="jr-playback jr-playback--wrap" role="group" aria-label="Jump to phase">
          {markers.map((m) => (
            <Button
              key={m.label}
              size="sm"
              aria-current={m.index === index ? "step" : undefined}
              title={`Frame ${m.index + 1} of ${keyframes.length}`}
              onClick={() => seekTo(m.index)}
            >
              {m.label} · {fmtSimTime(m.time_s)}
            </Button>
          ))}
        </div>
      )}
    </>
  );
}
