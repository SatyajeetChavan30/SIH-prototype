import React, { useState } from "react";
import { listDams, submitRun, pollUntilDone, getResult } from "../api.js";
import { useSimulationClock } from "../state/SimulationClock.jsx";
import { GAUGES, DAM } from "../data/entities.js";

/**
 * Control panel — ports the Streamlit sidebar 1:1 (brief §5.4).
 * Dam selector, height/storage sliders, breach mode, ensemble size, solver
 * toggle, export buttons. On submit it enqueues a run and, once done, loads the
 * keyframe manifest into the shared SimulationClock so both panels animate.
 */
export default function ControlPanel({ onRunLoaded }) {
  const clock = useSimulationClock();
  const [dams, setDams] = useState([]);
  const [damId, setDamId] = useState("tehri");
  const [heightM, setHeightM] = useState(DAM.height_m);
  const [storage, setStorage] = useState(DAM.storage_mm3);
  const [breachMode, setBreachMode] = useState("central");
  const [ensemble, setEnsemble] = useState(100);
  const [solver, setSolver] = useState("swe");
  const [durationMin, setDurationMin] = useState(30);
  const [status, setStatus] = useState("idle");
  const [loadId, setLoadId] = useState("");

  React.useEffect(() => {
    listDams().then(setDams).catch(() => setDams([]));
  }, []);

  const submit = async () => {
    setStatus("submitting");
    const runId = (await submitRun({
      dam_id: damId,
      height_m: heightM,
      storage_mm3: storage,
      breach_mode: breachMode,
      ensemble_size: ensemble,
      solver,
      solver_duration_s: durationMin * 60,
    })).run_id;
    setStatus(`queued ${runId.slice(0, 8)}`);
    await pollUntilDone(runId, (s) => setStatus(`${s.status} ${s.progress_pct?.toFixed(0)}%`));
    onRunLoaded?.(await getResult(runId));
    setStatus(`done ${runId.slice(0, 8)}`);
  };

  const loadExisting = async () => {
    const id = loadId.trim();
    if (!id) return;
    setStatus("loading…");
    try {
      onRunLoaded?.(await getResult(id));
      setStatus(`loaded ${id.slice(0, 8)}`);
    } catch (e) {
      setStatus(`load failed: ${e.message}`);
    }
  };

  return (
    <div style={{ padding: 12, width: 280, overflowY: "auto", borderRight: "1px solid #ddd" }}>
      <h3>JalRaksha</h3>
      <label>Dam</label>
      <select value={damId} onChange={(e) => setDamId(e.target.value)}>
        {dams.map((d) => (
          <option key={d.id} value={d.id}>{d.name}</option>
        ))}
        <option value="custom">Custom</option>
      </select>

      <label>Height (m): {heightM}</label>
      <input type="range" min="10" max="400" value={heightM}
             onChange={(e) => setHeightM(+e.target.value)} />

      <label>Storage (MCM): {storage}</label>
      <input type="range" min="10" max="20000" value={storage}
             onChange={(e) => setStorage(+e.target.value)} />

      <label>Breach mode</label>
      <select value={breachMode} onChange={(e) => setBreachMode(e.target.value)}>
        <option value="central">Central</option>
        <option value="overtopping">Overtopping</option>
        <option value="piping">Piping</option>
      </select>

      <label>Ensemble size: {ensemble}</label>
      <input type="range" min="1" max="10000" value={ensemble}
             onChange={(e) => setEnsemble(+e.target.value)} />

      <label>Simulated time: {durationMin} min</label>
      <input type="range" min="5" max="180" step="5" value={durationMin}
             onChange={(e) => setDurationMin(+e.target.value)} />

      <label>Solver</label>
      <select value={solver} onChange={(e) => setSolver(e.target.value)}>
        <option value="swe">SWE (screening)</option>
        <option value="delft3d">Delft3D FM</option>
        <option value="both">Both (compare)</option>
      </select>

      <button onClick={submit} style={{ marginTop: 10 }}>Run simulation</button>
      <div style={{ marginTop: 8, fontSize: 12 }}>{status}</div>

      {/* Load a previously-completed run without re-simulating — survives a
          page refresh and lets a demo start from a pre-baked run. */}
      <div style={{ marginTop: 8 }}>
        <input
          placeholder="Load run id…"
          value={loadId}
          onChange={(e) => setLoadId(e.target.value)}
          style={{ width: "70%", fontSize: 12 }}
        />
        <button onClick={loadExisting} style={{ fontSize: 12 }}>Load</button>
      </div>

      <h4>Gauges</h4>
      <ul style={{ fontSize: 12, paddingLeft: 16 }}>
        {GAUGES.map((g) => (
          <li key={g.name}>{g.name} — {g.distance_km} km</li>
        ))}
      </ul>

      <PlaybackControls />
    </div>
  );
}

function PlaybackControls() {
  const { keyframes, index, playing, setPlaying, prev, next, seekTo } = useSimulationClock();
  if (!keyframes.length) return null;
  return (
    <div style={{ marginTop: 12 }}>
      <h4>Playback</h4>
      <button onClick={() => setPlaying((p) => !p)}>{playing ? "Pause" : "Play"}</button>
      <button onClick={prev}>◀</button>
      <button onClick={next}>▶</button>
      <input type="range" min="0" max={keyframes.length - 1} value={index}
             onChange={(e) => seekTo(+e.target.value)} style={{ width: "100%" }} />
      <div style={{ fontSize: 12 }}>
        t = {keyframes[index]?.time_s?.toFixed(0)} s ({index + 1}/{keyframes.length})
      </div>
    </div>
  );
}
