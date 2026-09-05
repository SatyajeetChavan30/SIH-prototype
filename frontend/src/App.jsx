import React, { useEffect, useState } from "react";
import ControlPanel, { statusTone } from "./panels/ControlPanel.jsx";
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
import RunSummaryBar from "./panels/RunSummaryBar.jsx";
import { SimulationClockProvider, useSimulationClock } from "./state/SimulationClock.jsx";
import { useTheme } from "./state/theme.js";
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

/**
 * Keyboard control of the tabs and the playback clock.
 *
 * Lives inside SimulationClockProvider because it drives the clock. Typing is
 * excluded by target, not by a focus flag: the run-id box and the barrier
 * coordinate fields both accept space and arrow keys, and a shortcut that eats
 * them would be a data-entry bug that only shows up when someone types a real
 * latitude.
 */
function KeyboardShortcuts({ tabs, setTab }) {
  const { setPlaying, prev, next, keyframes } = useSimulationClock();

  useEffect(() => {
    const onKey = (event) => {
      const el = event.target;
      const typing =
        el instanceof HTMLElement &&
        (el.isContentEditable ||
          ["INPUT", "TEXTAREA", "SELECT"].includes(el.tagName));
      if (typing || event.metaKey || event.ctrlKey || event.altKey) return;

      // Digits pick a tab by its position in the bar as rendered — the SPH tab
      // only exists for runs that produced SPH output, so a fixed mapping would
      // point at a different panel depending on the run.
      if (/^[1-9]$/.test(event.key)) {
        const tab = tabs[Number(event.key) - 1];
        if (tab) {
          event.preventDefault();
          setTab(tab.id);
        }
        return;
      }
      if (!keyframes.length) return;
      if (event.key === " ") {
        event.preventDefault();
        setPlaying((playing) => !playing);
      } else if (event.key === "ArrowLeft") {
        event.preventDefault();
        prev();
      } else if (event.key === "ArrowRight") {
        event.preventDefault();
        next();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [tabs, setTab, setPlaying, prev, next, keyframes.length]);

  return null;
}

/**
 * Light / dark / follow-the-system, as a three-state segmented control.
 *
 * A two-state toggle would have to pick a side for "system", and an operator
 * who has set their OS to dark and then sees a sun icon has no way to tell
 * whether the app is following them or has overridden them.
 */
function ThemeToggle() {
  const { theme, setTheme } = useTheme();
  const options = [
    { id: "light", label: "Light" },
    { id: "dark", label: "Dark" },
    { id: "system", label: "Auto" },
  ];
  return (
    <div className="theme-toggle" role="group" aria-label="Colour theme">
      {options.map((option) => (
        <button
          key={option.id}
          aria-pressed={theme === option.id}
          onClick={() => setTheme(option.id)}
          title={option.id === "system" ? "Follow the operating system" : `${option.label} theme`}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
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
  // Presentation layout. The control panel is 300 px of form that nobody needs
  // while a flood is playing, and on the workspace tab the two views split the
  // width evenly whether or not the presenter is talking about both. Both are
  // view state only — nothing here changes what is rendered, just how much of
  // the window it gets. The map panels observe their own container size
  // (Map2D's ContainerResizeWatcher, Scene3D's ResizeObserver), so a change
  // here re-measures Leaflet and Cesium instead of stretching a stale canvas.
  const [sidebarOpen, setSidebarOpen] = useState(true);
  // Mirrored from the control panel, so a run in progress is still visible
  // after the panel is collapsed.
  const [runStatus, setRunStatus] = useState("idle");
  const [viewMode, setViewMode] = useState("split"); // "split" | "map" | "globe"
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
      <KeyboardShortcuts tabs={tabs} setTab={setTab} />
      <div style={{ display: "flex", height: "100vh", width: "100vw" }}>
        {/*
          Kept MOUNTED when collapsed, hidden with CSS, for the same reason the
          tab panels are: unmounting it would discard the dam selection, the
          slider values and the loaded run list, so re-opening the panel would
          silently reset the form the presenter had already set up.
        */}
        <div hidden={!sidebarOpen} style={{ display: sidebarOpen ? "flex" : "none" }}>
          <ControlPanel onRunLoaded={onRunLoaded} onDamChange={setSelectedDam}
                        onStatusChange={setRunStatus} result={result} />
        </div>
        <div style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0 }}>
          {/*
            A title bar, so the window says what is on screen and which run is
            loaded. The run id was previously visible only as a fragment inside
            the sidebar's status line, which scrolls away — and "which run am I
            looking at" is the first question asked of any figure here.
          */}
          <header className="app-header">
            <div className="brand">
              <span className="brand-name">JalRaksha</span>
              <span className="brand-tag">
                Dam-break &amp; river-blockage screening · Tier-1
              </span>
            </div>
            <div className="header-spacer" />
            {runStatus && runStatus !== "idle" && (
              <span className={`status status--header ${statusTone(runStatus)}`}>
                {runStatus}
              </span>
            )}
            {dam?.name && <span className="header-chip">{dam.name}</span>}
            {runId && <span className="header-chip">run {runId.slice(0, 8)}</span>}
            {/* Only offered where it does something: the split applies to the
                workspace tab, and a control that silently does nothing on the
                other seven tabs is worse than no control. */}
            {tab === "workspace" && (
              <div className="theme-toggle" role="group" aria-label="Workspace layout">
                {[
                  { id: "split", label: "Split" },
                  { id: "map", label: "2D" },
                  { id: "globe", label: "3D" },
                ].map((option) => (
                  <button
                    key={option.id}
                    aria-pressed={viewMode === option.id}
                    onClick={() => setViewMode(option.id)}
                    title={`Show ${option.id === "split" ? "both views" : option.id === "map" ? "the 2D map only" : "the 3D globe only"}`}
                  >
                    {option.label}
                  </button>
                ))}
              </div>
            )}
            <button
              className="header-icon-btn"
              onClick={() => setSidebarOpen((open) => !open)}
              aria-pressed={!sidebarOpen}
              title={sidebarOpen ? "Hide the control panel" : "Show the control panel"}
            >
              {sidebarOpen ? "◧ Hide panel" : "◨ Show panel"}
            </button>
            <ThemeToggle />
          </header>

          {/*
            Headline numbers, derived from the loaded result and nothing else.
            Above the tabs because they are the answer the system exists to
            give, and they used to be one tab each.
          */}
          <RunSummaryBar result={result} />

          {/*
            role="tablist" with aria-selected, NOT `disabled` on the active tab.
            Disabling it greyed out the one tab you were looking at and made the
            current view read as the unavailable one.
          */}
          <div className="tabbar" role="tablist" aria-label="Result views">
            {tabs.map((t, i) => (
              <button
                key={t.id}
                className="tab"
                role="tab"
                aria-selected={tab === t.id}
                onClick={() => setTab(t.id)}
                title={i < 9 ? `${t.label} — press ${i + 1}` : t.label}
              >
                {t.label}
                {t.badge ? <span className="tab-badge">{t.badge}</span> : null}
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
          <div style={{ flex: 1, position: "relative", minHeight: 0, minWidth: 0,
                        background: "var(--surface)" }}>
            <Pane active={tab === "workspace"}>
              {/*
                Both views stay in the grid in every mode — a hidden column is
                a zero-width column, not an unmounted panel. Tearing the Cesium
                Viewer down and back up to change the split would cost seconds
                and lose the camera, which is the same mistake the tabs used to
                make.
              */}
              <div style={{ height: "100%", display: "grid",
                            gridTemplateColumns:
                              viewMode === "map" ? "1fr 0" :
                              viewMode === "globe" ? "0 1fr" : "1fr 1fr",
                            gridTemplateRows: "1fr",
                            minHeight: 0 }}>
                <div style={{ borderRight: viewMode === "split" ? "1px solid var(--border)" : "none",
                              minWidth: 0, minHeight: 0, overflow: "hidden" }}>
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
      role="tabpanel"
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
