import React, { useEffect, useState } from "react";
import ControlPanel from "./panels/ControlPanel.jsx";
import Map2D from "./panels/Map2D.jsx";
import Scene3D from "./panels/Scene3D.jsx";
import ComparisonPanel from "./panels/ComparisonPanel.jsx";
import DownloadsPanel from "./panels/DownloadsPanel.jsx";
import GaugesPanel from "./panels/GaugesPanel.jsx";
import EnsemblePanel from "./panels/EnsemblePanel.jsx";
import ImpactPanel from "./panels/ImpactPanel.jsx";
import ValidationPanel from "./panels/ValidationPanel.jsx";
import SphPanel from "./panels/SphPanel.jsx";
import DemUpdateBanner from "./panels/DemUpdateBanner.jsx";
import { SimulationClockProvider, useSimulationClock } from "./state/SimulationClock.jsx";
import { resolveApiUrl } from "./api.js";
import { DAM, GAUGES } from "./data/entities.js";

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
  // The dam currently selected in the control panel, lifted here because BOTH
  // map panels need it. They used to be rendered with no props at all and read
  // the hardcoded Tehri constants, so selecting another dam moved nothing on
  // screen. null means "custom", or /dams has not resolved yet.
  const [selectedDam, setSelectedDam] = useState(null);
  const dam = selectedDam || DAM;
  const gauges = selectedDam ? (selectedDam.gauges || []) : GAUGES;

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

  const tabs = [
    { id: "workspace", label: "2D + 3D" },
    { id: "gauges", label: "Gauges", badge: result?.gauges?.length },
    { id: "ensemble", label: "Ensemble" },
    { id: "impact", label: "Impact" },
    // Only offered once a run has SPH output — an always-present tab that is
    // empty for six runs out of seven reads as a broken feature.
    ...(result?.sph ? [{ id: "sph", label: "SPH" }] : []),
    { id: "comparison", label: "Comparison" },
    { id: "validation", label: "Validation" },
    { id: "downloads", label: "Downloads", badge: result?.exports?.length },
  ];

  return (
    <SimulationClockProvider manifest={manifest}>
      <PlaybackDriver />
      <div style={{ display: "flex", height: "100vh", width: "100vw" }}>
        <ControlPanel onRunLoaded={onRunLoaded} onDamChange={setSelectedDam} result={result} />
        <div style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0 }}>
          <div style={{ borderBottom: "1px solid #ddd", padding: "4px 8px",
                        display: "flex", gap: 6, flexWrap: "wrap" }}>
            {tabs.map((t) => (
              <button key={t.id} onClick={() => setTab(t.id)} disabled={tab === t.id}>
                {t.label}{t.badge ? ` (${t.badge})` : ""}
              </button>
            ))}
          </div>

          {/*
            Above the tab content, not inside a tab: the 3D globe renders the
            MODIFIED terrain on the workspace tab, so the label has to be
            visible wherever the viewer is looking. Renders nothing at all when
            the run's terrain was not touched.
          */}
          <DemUpdateBanner demUpdate={result?.dem_update} />

          {/*
            Panels stay MOUNTED and are hidden with CSS rather than swapped by a
            ternary. The previous arrangement unmounted the inactive branch, so
            every tab click tore down and rebuilt the Cesium Viewer and the
            Leaflet map, re-running the keyframe imagery-layer build loop each
            time. That is seconds of rebuild per click during a live demo, and
            it also discarded the camera position the presenter had just set.

            minHeight/minWidth 0 throughout: these are flex and grid children,
            whose default min-height:auto lets a self-sizing widget (Cesium)
            grow its container without bound.
          */}
          <div style={{ flex: 1, position: "relative", minHeight: 0, minWidth: 0 }}>
            <Pane active={tab === "workspace"}>
              <div style={{ height: "100%", display: "grid",
                            gridTemplateColumns: "1fr 1fr", gridTemplateRows: "1fr",
                            minHeight: 0 }}>
                <div style={{ borderRight: "1px solid #ddd", minWidth: 0, minHeight: 0,
                              overflow: "hidden" }}>
                  <Map2D dam={dam} gauges={gauges} result={result} />
                </div>
                <div style={{ minWidth: 0, minHeight: 0, overflow: "hidden" }}>
                  <Scene3D dam={dam} gauges={gauges} />
                </div>
              </div>
            </Pane>

            <Pane active={tab === "gauges"}>
              <GaugesPanel result={result} dam={selectedDam || dam} />
            </Pane>
            <Pane active={tab === "ensemble"}>
              <EnsemblePanel result={result} />
            </Pane>
            <Pane active={tab === "impact"}>
              <ImpactPanel result={result} />
            </Pane>
            <Pane active={tab === "sph"}>
              <SphPanel result={result} />
            </Pane>
            <Pane active={tab === "comparison"}>
              <ComparisonPanel runId={runId} />
            </Pane>
            <Pane active={tab === "validation"}>
              <ValidationPanel result={result} />
            </Pane>
            <Pane active={tab === "downloads"}>
              <DownloadsPanel result={result} />
            </Pane>
          </div>
        </div>
      </div>
    </SimulationClockProvider>
  );
}

/**
 * One tab body. Hidden with visibility + zero opacity rather than
 * display:none, because Leaflet and Cesium both measure their container on
 * mount and a display:none parent measures zero - which is how a map ends up
 * rendering into a 0x0 canvas and staying blank after it is revealed.
 */
function Pane({ active, children }) {
  return (
    <div
      aria-hidden={!active}
      style={{
        position: "absolute", inset: 0, minHeight: 0, minWidth: 0,
        visibility: active ? "visible" : "hidden",
        pointerEvents: active ? "auto" : "none",
        zIndex: active ? 1 : 0,
        overflow: "hidden",
      }}
    >
      {children}
    </div>
  );
}

export default function App() {
  return <Workspace />;
}
