import React, { useEffect, useState } from "react";
import ControlPanel from "./panels/ControlPanel.jsx";
import Map2D from "./panels/Map2D.jsx";
import Scene3D from "./panels/Scene3D.jsx";
import ComparisonPanel from "./panels/ComparisonPanel.jsx";
import { SimulationClockProvider, useSimulationClock } from "./state/SimulationClock.jsx";
import { resolveApiUrl } from "./api.js";

function PlaybackDriver() {
  // Auto-advance the shared clock while playing (drives both panels).
  const { playing, next, keyframes } = useSimulationClock();
  useEffect(() => {
    if (!playing || !keyframes.length) return;
    const id = setInterval(next, 500);
    return () => clearInterval(id);
  }, [playing, next, keyframes.length]);
  return null;
}

function Workspace() {
  const [manifest, setManifest] = useState({ keyframes: [] });
  const [runId, setRunId] = useState(null);
  const [tab, setTab] = useState("workspace"); // "workspace" | "comparison"

  const onRunLoaded = (result) => {
    setRunId(result.run_id);
    // The keyframe manifest is the single artifact both views consume (§5.3).
    // Its own URL is API-relative ("/files/..."); png_url inside each keyframe
    // is a bare filename (jalraksha/export/keyframes.py) resolved against the
    // manifest's own URL so it stays web-server-agnostic.
    if (result.keyframe_manifest_url) {
      const manifestUrl = resolveApiUrl(result.keyframe_manifest_url);
      fetch(manifestUrl)
        .then((r) => r.json())
        .then((m) => ({
          ...m,
          keyframes: (m.keyframes || []).map((kf) => ({
            ...kf,
            png_url: new URL(kf.png_url, manifestUrl).href,
          })),
        }))
        .then(setManifest)
        .catch(() => setManifest({ keyframes: [] }));
    }
  };

  return (
    <SimulationClockProvider manifest={manifest}>
      <PlaybackDriver />
      <div style={{ display: "flex", height: "100vh", width: "100vw" }}>
        <ControlPanel onRunLoaded={onRunLoaded} />
        <div style={{ flex: 1, display: "flex", flexDirection: "column" }}>
          <div style={{ borderBottom: "1px solid #ddd", padding: "4px 8px" }}>
            <button onClick={() => setTab("workspace")} disabled={tab === "workspace"}>2D + 3D</button>
            <button onClick={() => setTab("comparison")} disabled={tab === "comparison"} style={{ marginLeft: 6 }}>
              Comparison
            </button>
          </div>
          {tab === "workspace" ? (
            <div style={{ flex: 1, display: "grid", gridTemplateColumns: "1fr 1fr", gridTemplateRows: "1fr" }}>
              <div style={{ borderRight: "1px solid #ddd" }}>
                <Map2D />
              </div>
              <div>
                <Scene3D />
              </div>
            </div>
          ) : (
            <ComparisonPanel runId={runId} />
          )}
        </div>
      </div>
    </SimulationClockProvider>
  );
}

export default function App() {
  return <Workspace />;
}
