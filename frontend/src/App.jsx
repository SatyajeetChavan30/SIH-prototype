import React, { useEffect, useState } from "react";
import ControlPanel from "./panels/ControlPanel.jsx";
import Map2D from "./panels/Map2D.jsx";
import Scene3D from "./panels/Scene3D.jsx";
import ComparisonPanel from "./panels/ComparisonPanel.jsx";
import DownloadsPanel from "./panels/DownloadsPanel.jsx";
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
  // The whole result, not just the id: the Downloads tab lists result.exports,
  // which is the only place the run's .shp/.kml/.tif products are enumerated.
  const [result, setResult] = useState(null);
  const [tab, setTab] = useState("workspace"); // "workspace" | "downloads" | "comparison"

  const onRunLoaded = (runResult) => {
    setRunId(runResult.run_id);
    setResult(runResult);
    // The keyframe manifest is the single artifact both views consume (§5.3).
    // Its own URL is API-relative ("/files/..."); png_url inside each keyframe
    // is a bare filename (jalraksha/export/keyframes.py) resolved against the
    // manifest's own URL so it stays web-server-agnostic.
    if (runResult.keyframe_manifest_url) {
      const manifestUrl = resolveApiUrl(runResult.keyframe_manifest_url);
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
        <ControlPanel onRunLoaded={onRunLoaded} result={result} />
        <div style={{ flex: 1, display: "flex", flexDirection: "column" }}>
          <div style={{ borderBottom: "1px solid #ddd", padding: "4px 8px" }}>
            <button onClick={() => setTab("workspace")} disabled={tab === "workspace"}>2D + 3D</button>
            <button onClick={() => setTab("downloads")} disabled={tab === "downloads"} style={{ marginLeft: 6 }}>
              Downloads{result?.exports?.length ? ` (${result.exports.length})` : ""}
            </button>
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
          ) : tab === "downloads" ? (
            <DownloadsPanel result={result} />
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
