import React, { useState } from "react";
import {
  listDams, submitRun, pollUntilDone, getResult, openInParaview,
  listRuns, getGeeStatus, getBlockageDetection,
} from "../api.js";
import { useSimulationClock } from "../state/SimulationClock.jsx";
import { GAUGES, DAM } from "../data/entities.js";

// Grid resolution every run is submitted at. Named rather than left to the
// API's default because the blockage form has to state, live, how many cells a
// barrier of a given width spans — a barrier narrower than a couple of cells
// has an outflow governed by the mesh instead of by the deposit, and the
// operator should see that before submitting, not as a 422 afterwards.
const TARGET_RESOLUTION_M = 100;

/**
 * Control panel (brief §5.4).
 * Dam selector, height/storage sliders, breach mode, ensemble size, solver
 * toggle, export buttons. On submit it enqueues a run and, once done, loads the
 * keyframe manifest into the shared SimulationClock so both panels animate.
 */
export default function ControlPanel({ onRunLoaded, onDamChange, result }) {
  const clock = useSimulationClock();
  const [dams, setDams] = useState([]);
  // No hardcoded "tehri" default: it disagreed with the backend's own
  // DEFAULT_PRESET_ID ("khadakwasla"), so the panel opened describing one dam
  // while the API considered another canonical. Set from the fetched list.
  const [damId, setDamId] = useState(null);
  const [heightM, setHeightM] = useState(DAM.height_m);
  const [storage, setStorage] = useState(DAM.storage_mm3);
  const [breachMode, setBreachMode] = useState("central");
  const [scenarioType, setScenarioType] = useState("dam_break");
  // Landslide-barrier geometry. None of it can come from the site record: the
  // deposit is not the dam, and a natural dam has no published dimensions.
  // "manual" is the default because it needs no network — the offline path is
  // the demo's guaranteed floor, and auto-detection is a bonus on top of it.
  const [blockageSource, setBlockageSource] = useState("manual");
  const [blockageLat, setBlockageLat] = useState("");
  const [blockageLon, setBlockageLon] = useState("");
  const [blockageCrestM, setBlockageCrestM] = useState(50);
  const [blockageWidthM, setBlockageWidthM] = useState(600);
  const [blockageBreachMode, setBlockageBreachMode] = useState("overtop");
  const [detection, setDetection] = useState(null);
  const [ensemble, setEnsemble] = useState(100);
  const [solver, setSolver] = useState("swe");
  // 180 min, not 30. At 30 minutes the flood covers ~3.7 km and Khadakwasla's
  // nearest gauge is 10.5 km away, so the default guaranteed an empty arrival
  // table and the message "The flood did not reach any gauge within the
  // simulated time" on every single run. A default that cannot produce a
  // result is a bad default.
  const [durationMin, setDurationMin] = useState(180);
  const [status, setStatus] = useState("idle");
  const [loadId, setLoadId] = useState("");
  // The run id was previously only a local const inside submit(), so nothing
  // downstream of a completed run could refer to it. The ParaView button needs
  // it, so both submit() and loadExisting() record it here.
  const [currentRunId, setCurrentRunId] = useState(null);
  const [pvStatus, setPvStatus] = useState("");
  // Demo Mode: completed runs, loadable instantly with no compute. The only
  // way to load a previous run used to be typing a 32-character hex id.
  const [runs, setRuns] = useState([]);
  const [gee, setGee] = useState(null);

  React.useEffect(() => {
    listDams()
      .then((list) => {
        setDams(list);
        if (list.length) selectDam(list[0].id, list);
      })
      .catch(() => setDams([]));
    refreshRuns();
    getGeeStatus().then(setGee).catch(() => setGee(null));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const refreshRuns = () =>
    listRuns(50)
      // Only runs with something to show. A run can be "done" with zero
      // exports (the analytic paths produce no rasters), and offering those in
      // a picker labelled "load results" promises something that is not there.
      .then((all) => setRuns(all.filter((r) => r.status === "done" && r.export_count > 0)))
      .catch(() => setRuns([]));

  /**
   * Adopt a dam: its structural figures AND its downstream corridor.
   *
   * Selecting a dam previously changed only the id posted to /runs. The
   * height/storage sliders stayed on Tehri's 260 m / 3540 MCM, and the map,
   * gauge table and camera presets stayed on the Tehri corridor — so the panel
   * could describe Tehri while running Khadakwasla. (The posted slider values
   * were ignored anyway: RunRequest.to_dam_config re-reads the preset whenever
   * dam_id is set, so they only ever mattered for a custom dam.)
   */
  const selectDam = (id, list = dams) => {
    setDamId(id);
    if (id === "custom") {
      onDamChange?.(null);
      return;
    }
    const dam = list.find((d) => d.id === id);
    if (!dam) return;
    // A preset may publish null height/storage when it has no vetted source;
    // keep the current slider value rather than writing null into a number input.
    if (dam.height_m != null) setHeightM(dam.height_m);
    if (dam.storage_mm3 != null) setStorage(dam.storage_mm3);
    onDamChange?.(dam);
  };

  const selectedDam = dams.find((d) => d.id === damId) || null;

  // Which scenarios this site can model, read from the registry.
  //
  // This used to be `isMuthaRiverScenario = scenarioType !== "dam_break"` and
  // `effectiveDamId = isMuthaRiverScenario ? "khadakwasla" : damId`, which
  // routed EVERY non-dam-break scenario to one dam. That made a dedicated
  // blockage site unreachable from the UI no matter what the backend supported,
  // and the variable name encoded the assumption. Records without the field are
  // pre-existing hand-written dams, which model everything.
  const ALL_SCENARIOS = ["dam_break", "river_blockage", "river_overflow"];
  const scenariosFor = (dam) => dam?.scenario_types || ALL_SCENARIOS;
  const availableScenarios = scenariosFor(selectedDam);
  const isBlockage = scenarioType === "river_blockage";
  const isRiverScenario = scenarioType !== "dam_break";
  const isBlockageSite = selectedDam?.record_type === "blockage";

  // Fall back to a site that CAN model the chosen scenario, rather than to one
  // hardcoded dam. Only fires when the current selection genuinely cannot.
  const fallbackSite = dams.find((d) => scenariosFor(d).includes(scenarioType));
  const effectiveDamId = availableScenarios.includes(scenarioType)
    ? damId
    : fallbackSite?.id || damId;

  // A manual blockage cannot run without its barrier. Checked here so the Run
  // button is disabled with an explanation, rather than round-tripping to a 422.
  const blockageIncomplete =
    isBlockage &&
    blockageSource === "manual" &&
    !(blockageLat !== "" && blockageLon !== "" && blockageCrestM > 0 && blockageWidthM > 0);

  // Seed the barrier position from the site, and RE-seed whenever the site
  // changes. A position the operator typed belongs to the site they typed it
  // for; carrying it across to another river would place the barrier hundreds
  // of kilometres from the terrain being simulated, and the geometry would fail
  // with an out-of-domain error rather than an obvious one.
  //
  // Prefers the site's terrain-derived suggestion over its reach centre: the
  // centre is where the map marker sits, which for a mountain reach can be a
  // ridge, and a barrier seeded on a ridge fails the valley-spanning check.
  const seededSiteRef = React.useRef(null);
  React.useEffect(() => {
    if (!isBlockage || !selectedDam) return;
    if (seededSiteRef.current === selectedDam.id) return;
    seededSiteRef.current = selectedDam.id;
    setBlockageLat(selectedDam.suggested_barrier_lat ?? selectedDam.lat);
    setBlockageLon(selectedDam.suggested_barrier_lon ?? selectedDam.lon);
    if (selectedDam.blockage_crest_height_m) {
      setBlockageCrestM(selectedDam.blockage_crest_height_m);
    }
    if (selectedDam.blockage_width_m) {
      setBlockageWidthM(selectedDam.blockage_width_m);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isBlockage, selectedDam?.id]);
  // loadExisting closes over damId; a ref keeps its comparison current without
  // adding damId to every dependency list that touches it.
  const damIdRef = React.useRef(damId);
  React.useEffect(() => { damIdRef.current = damId; }, [damId]);
  // A run can open in ParaView only if it wrote an XDMF, which only the SWE
  // path does. Read it off the loaded result rather than guessing from solver.
  const hasXdmf = Boolean(result?.exports?.some((e) => e.kind === "xdmf"));

  const submit = async () => {
    setStatus("submitting");
    try {
      await submitInner();
    } catch (e) {
      // submit() had no try/catch, so a rejected submitRun threw into an
      // unhandled promise and the status text stuck on "submitting" forever
      // with no indication anything had gone wrong.
      setStatus(`failed: ${e.message}`);
    }
  };

  const submitInner = async () => {
    // dam_id must be absent for a custom dam: the API's `else` branch (explicit
    // lat/lon/height/storage) is only reachable when dam_id is falsy, so
    // posting the literal "custom" hit its Unknown dam_id path and 422'd.
    const isCustom = !effectiveDamId || effectiveDamId === "custom";
    const runId = (await submitRun({
      dam_id: isCustom ? null : effectiveDamId,
      ...(isCustom ? { lat: DAM.lat, lon: DAM.lon } : {}),
      // A blockage sends no height or storage. Its crest comes from the barrier
      // spec and its impounded volume is measured from the updated DEM; sending
      // a slider value would be exactly the request the API refuses, and for
      // the right reason.
      ...(isBlockage ? {} : { height_m: heightM, storage_mm3: storage }),
      breach_mode: breachMode,
      scenario_type: scenarioType,
      ensemble_size: ensemble,
      solver,
      solver_duration_s: (durationMin || 30) * 60,
      target_resolution: TARGET_RESOLUTION_M,
      ...(isBlockage ? {
        blockage_source: blockageSource,
        blockage_lat: blockageLat === "" ? null : +blockageLat,
        blockage_lon: blockageLon === "" ? null : +blockageLon,
        blockage_crest_height_m: blockageCrestM || null,
        blockage_width_m: blockageWidthM || null,
        blockage_breach_mode: blockageBreachMode,
        blockage_date_pre: selectedDam?.blockage_date_pre || null,
        blockage_date_post: selectedDam?.blockage_date_post || null,
      } : {}),
    })).run_id;
    setStatus(`queued ${runId.slice(0, 8)}`);
    setCurrentRunId(runId);
    setPvStatus("");
    const final = await pollUntilDone(runId, (s) =>
      // The phase matters more than the number. Until the backend reported one,
      // every run showed a frozen "running 5%" for its whole duration, which is
      // indistinguishable from a hang — and that is exactly how it was read.
      setStatus(s.phase
        ? `${s.phase} — ${s.progress_pct?.toFixed(0)}%`
        : `${s.status} ${s.progress_pct?.toFixed(0)}%`));
    if (final.status === "failed") {
      // Show WHY. The reason is persisted now, and a bare "failed" gives the
      // user nothing to act on.
      setStatus(`failed: ${final.error || runId.slice(0, 8)}`);
      return;
    }
    onRunLoaded?.(await getResult(runId));
    setStatus(`done ${runId.slice(0, 8)}`);
    refreshRuns();
  };

  const loadExisting = async (explicitId) => {
    const id = (explicitId || loadId).trim();
    if (!id) return;
    setStatus("loading…");
    try {
      const loaded = await getResult(id);
      onRunLoaded?.(loaded);

      // Adopt the run's dam. Loading a run used to leave the dam selector on
      // whatever was previously chosen, so opening a Khadakwasla run while
      // Tehri was selected gave a Gauges panel headed "Downstream gauges —
      // Tehri Dam" above seven Pune towns, a map still centred on the
      // Bhagirathi, and Tehri's camera presets. Every one of those is wrong for
      // the run on screen.
      const row = runs.find((r) => r.run_id === id);
      const damId = row?.dam_id;
      if (damId && damId !== damIdRef.current) selectDam(damId);

      setCurrentRunId(id);
      setPvStatus("");
      setStatus(`loaded ${id.slice(0, 8)}`);
    } catch (e) {
      setStatus(`load failed: ${e.message}`);
    }
  };

  const openParaview = async () => {
    if (!currentRunId) return;
    setPvStatus("launching ParaView…");
    try {
      const res = await openInParaview(currentRunId);
      // The endpoint reports its operational failures in the body rather than
      // as HTTP errors, so a 200 does not mean it launched.
      setPvStatus(res?.launched ? "ParaView opening…" : res?.detail || "could not launch");
    } catch (e) {
      setPvStatus(e.message);
    }
  };

  return (
    <div style={{ padding: 12, width: 280, overflowY: "auto", borderRight: "1px solid #ddd" }}>
      <h3>JalRaksha</h3>
      <label>Site</label>
      <select value={effectiveDamId || ""}
              onChange={(e) => selectDam(e.target.value)}>
        {dams.map((d) => (
          <option key={d.id} value={d.id}
                  disabled={!scenariosFor(d).includes(scenarioType)}>
            {d.name}{d.record_type === "blockage" ? " (blockage site)" : ""}
          </option>
        ))}
        <option value="custom">Custom</option>
      </select>

      <label>Simulation scenario</label>
      <select
        value={scenarioType}
        onChange={(e) => {
          const next = e.target.value;
          setScenarioType(next);
          // Move to a site that can model the chosen scenario only when the
          // current one cannot. The panel used to pin every non-dam-break
          // scenario to Khadakwasla unconditionally, which made a dedicated
          // blockage site unreachable.
          if (!scenariosFor(selectedDam).includes(next)) {
            const site = dams.find((d) => scenariosFor(d).includes(next));
            if (site) selectDam(site.id);
          }
        }}
      >
        <option value="dam_break"
                disabled={!availableScenarios.includes("dam_break") && !fallbackSite}>
          Dam break
        </option>
        <option value="river_blockage">River blockage (landslide dam)</option>
        <option value="river_overflow">River overflow (screening)</option>
      </select>
      {selectedDam?.note && (
        <div style={{ fontSize: 10, color: "#7a3e00", marginTop: 4, lineHeight: 1.4 }}>
          {selectedDam.note}
        </div>
      )}
      {scenarioType === "river_overflow" && (
        <div style={{ fontSize: 10, color: "#7a3e00", marginTop: 4, lineHeight: 1.4 }}>
          Screening only. The release is volume-conserving and its shape is an
          assumption — modelling a controlled spillway release needs a gate
          rating curve and an operating rule, which this project does not have.
        </div>
      )}

      {!isBlockage && <>
        <label>Height (m): {heightM}</label>
        <input type="range" min="10" max="400" value={heightM}
               onChange={(e) => setHeightM(+e.target.value)} />

        <label>Storage (MCM): {storage}</label>
        <input type="range" min="10" max="20000" value={storage}
               onChange={(e) => setStorage(+e.target.value)} />
      </>}

      {isBlockage && (
        <BlockageControls
          gee={gee}
          site={selectedDam}
          source={blockageSource} setSource={setBlockageSource}
          lat={blockageLat} setLat={setBlockageLat}
          lon={blockageLon} setLon={setBlockageLon}
          crestHeightM={blockageCrestM} setCrestHeightM={setBlockageCrestM}
          widthM={blockageWidthM} setWidthM={setBlockageWidthM}
          breachMode={blockageBreachMode} setBreachMode={setBlockageBreachMode}
          targetResolution={TARGET_RESOLUTION_M}
          detection={detection} setDetection={setDetection}
        />
      )}

      {scenarioType === "dam_break" && <>
        <label>Breach mode</label>
        <select value={breachMode} onChange={(e) => setBreachMode(e.target.value)}>
          <option value="central">Central</option>
          <option value="overtopping">Overtopping</option>
          <option value="piping">Piping</option>
        </select>
      </>}

      <label>Ensemble size: {ensemble}</label>
      <input type="range" min="1" max="10000" value={ensemble}
             onChange={(e) => setEnsemble(+e.target.value)} />

      <label>Simulated time (min):</label>
      <input type="number" min="1" step="1" value={durationMin}
             onChange={(e) => setDurationMin(e.target.value === '' ? '' : +e.target.value)} />

      <label>Solver</label>
      <select value={solver} onChange={(e) => setSolver(e.target.value)}>
        <option value="swe">SWE (screening)</option>
        <option value="delft3d" disabled={isRiverScenario}>Delft3D FM</option>
        <option value="both" disabled={isRiverScenario}>Both (compare)</option>
        <option value="sph">+ Near-field SPH (advanced)</option>
      </select>
      {solver === "sph" && (
        <div style={{ fontSize: 10, color: "#7a3e00", marginTop: 4, lineHeight: 1.4 }}>
          Near-field only: a ~600 m window over 15 s at the breach, one-way
          coupled from the SWE result. It resolves the breach jet — it does
          <strong> not</strong> reach downstream gauges, and it is slow.
        </div>
      )}
      {isRiverScenario && !["swe", "sph"].includes(solver) && (
        <div style={{ fontSize: 10, color: "#b00020", marginTop: 4 }}>
          Select SWE or near-field SPH for this river scenario. Delft3D FM is
          configured for dam-break hydrographs only.
        </div>
      )}
      {isBlockage && blockageIncomplete && (
        <div style={{ fontSize: 10, color: "#b00020", marginTop: 4, lineHeight: 1.4 }}>
          Place the barrier before running: a blockage needs a position, a crest
          height above the valley floor, and a crest width across it. None of
          them can be taken from the site record — the deposit is not the dam.
        </div>
      )}

      <button
        onClick={submit}
        disabled={
          (isRiverScenario && !["swe", "sph"].includes(solver)) ||
          (isBlockage && blockageIncomplete)
        }
        style={{ marginTop: 10 }}
      >
        Run {scenarioType === "dam_break"
          ? "dam-break"
          : isBlockage ? "river-blockage" : "river-overflow"} simulation
      </button>
      <div style={{ marginTop: 8, fontSize: 12 }}>{status}</div>

      {currentRunId && (
        <div style={{ marginTop: 10, paddingTop: 10, borderTop: "1px solid #eee" }}>
          {/*
            Whether a 3D dataset exists is knowable from the loaded result — the
            run carries an export of kind "xdmf" or it does not. The button used
            to be enabled unconditionally and only reported "No 3D dataset for
            this run" AFTER launching, which in a live demo means clicking a
            button in front of an audience to be told it cannot work. Disable it
            up front and say why.
          */}
          <button
            onClick={openParaview}
            disabled={!hasXdmf || pvStatus === "launching ParaView…"}
          >
            View in ParaView (3D)
          </button>
          <div style={{ marginTop: 4, fontSize: 11, color: "#666" }}>
            {hasXdmf
              ? "Opens the ParaView desktop app on the machine running the API."
              : null}
          </div>
          {!hasXdmf && (
            <div style={{ marginTop: 4, fontSize: 11, color: "#7a3e00" }}>
              No 3D dataset for this run. Only <strong>SWE</strong> runs record a
              depth series; <code>delft3d</code> and <code>both</code> produce an
              analytic estimate with nothing to render. Load or start an SWE run
              for this dam.
            </div>
          )}
          {pvStatus && (
            <div style={{ marginTop: 4, fontSize: 11 }}>{pvStatus}</div>
          )}
        </div>
      )}

      {/* Demo Mode. A pre-baked run loads instantly with no compute, which is
          what makes the demo survive a slow laptop or no network. The free-text
          id box is kept below it for a run that is not in the list. */}
      <div style={{ marginTop: 12, paddingTop: 10, borderTop: "1px solid #eee" }}>
        <label>Load a completed run</label>
        <select
          value=""
          onChange={(e) => e.target.value && loadExisting(e.target.value)}
          style={{ width: "100%", fontSize: 12 }}
        >
          <option value="">
            {runs.length ? `${runs.length} available…` : "none available yet"}
          </option>
          {runs.map((r) => (
            <option key={r.run_id} value={r.run_id}>
              {(r.dam_name || r.dam_id || "run")} · {r.solver} · {r.export_count} files
              {r.solver === "swe" || r.solver === "sph" ? " · 3D" : ""}
            </option>
          ))}
        </select>
        <div style={{ marginTop: 6 }}>
          <input
            placeholder="…or paste a run id"
            value={loadId}
            onChange={(e) => setLoadId(e.target.value)}
            style={{ width: "68%", fontSize: 12 }}
          />
          <button onClick={() => loadExisting()} style={{ fontSize: 12 }}>Load</button>
        </div>
      </div>

      <GeeBadge gee={gee} />

      <DamClassWarning hazard={result?.hazard_summary} />

      <PopulationAtRisk data={result?.population_at_risk} />

      <GaugeArrivals gauges={result?.gauges} damGauges={selectedDam?.gauges} />

      <PlaybackControls />
    </div>
  );
}

/**
 * Earth Engine availability, stated plainly.
 *
 * Shown regardless of state, because "the satellite layer is live" and "the
 * satellite layer is not configured" are both things a viewer needs to know
 * before they interpret the map. The reason string is Earth Engine's own
 * message, or this project's text naming the exact missing variable, so it is
 * rendered verbatim rather than mapped to something generic.
 */
/**
 * Where the landslide barrier is and how big it is.
 *
 * Two paths, and the manual one is the default on purpose: it needs no network,
 * no Earth Engine and no cached scene, so it is the demo's guaranteed floor.
 * Auto-detection is additive — over steep Himalayan terrain its quality gates
 * may legitimately refuse, and a refusal is displayed and then handed back to
 * the manual path rather than treated as a failure.
 *
 * Nothing here is auto-selected from a detection. An operator confirming a
 * candidate IS the HADR workflow, and making the confirmation explicit is what
 * keeps a refusal an ordinary outcome instead of an exception.
 */
function BlockageControls({
  gee, site, source, setSource, lat, setLat, lon, setLon,
  crestHeightM, setCrestHeightM, widthM, setWidthM,
  breachMode, setBreachMode, targetResolution, detection, setDetection,
}) {
  const [detecting, setDetecting] = useState(false);
  const geeReady = Boolean(gee?.available);
  const cells = widthM > 0 ? widthM / targetResolution : 0;
  const subGrid = cells < 2;

  const detect = async () => {
    setDetecting(true);
    setDetection(null);
    try {
      setDetection(await getBlockageDetection(site?.id || "rishi_ganga"));
    } catch (e) {
      setDetection({ source: "unavailable", reason: e.message });
    } finally {
      setDetecting(false);
    }
  };

  const label = { fontSize: 11, marginTop: 8, display: "block", color: "#444" };
  const field = { width: "100%", boxSizing: "border-box" };

  return (
    <fieldset style={{
      marginTop: 10, padding: "8px 10px 10px", border: "1px solid #ddd",
      borderRadius: 4,
    }}>
      <legend style={{ fontSize: 11, color: "#555" }}>Landslide barrier</legend>

      <div style={{ display: "flex", gap: 12, fontSize: 11 }}>
        <label style={{ display: "flex", gap: 4, alignItems: "center" }}>
          <input type="radio" checked={source === "manual"}
                 onChange={() => setSource("manual")} />
          Manual
        </label>
        <label style={{
          display: "flex", gap: 4, alignItems: "center",
          color: geeReady ? "inherit" : "#999",
        }}
          title={geeReady ? "" : (gee?.reason || "Earth Engine is not configured.")}>
          <input type="radio" checked={source === "detect"} disabled={!geeReady}
                 onChange={() => setSource("detect")} />
          Auto-detect (Sentinel-1)
        </label>
      </div>

      {source === "detect" && (
        <div style={{ marginTop: 8 }}>
          <button onClick={detect} disabled={detecting} style={{ fontSize: 11 }}>
            {detecting ? "Differencing scenes…" : "Detect new water"}
          </button>
          {site?.blockage_date_post && (
            <div style={{ fontSize: 10, color: "#666", marginTop: 4 }}>
              Window: {site.blockage_date_pre} to {site.blockage_date_post}
            </div>
          )}
          {detection && <DetectionResult detection={detection}
                                         onUseManual={() => setSource("manual")} />}
        </div>
      )}

      <label style={label}>Barrier latitude</label>
      <input style={field} type="number" step="0.0001" value={lat}
             onChange={(e) => setLat(e.target.value)} />

      <label style={label}>Barrier longitude</label>
      <input style={field} type="number" step="0.0001" value={lon}
             onChange={(e) => setLon(e.target.value)} />

      <label style={label}>Crest height above the valley floor (m): {crestHeightM}</label>
      <input type="range" min="5" max="250" value={crestHeightM}
             onChange={(e) => setCrestHeightM(+e.target.value)} />
      <div style={{ fontSize: 10, color: "#666", lineHeight: 1.4 }}>
        A HEIGHT above the bed, not an elevation. The two differ by a kilometre
        or more in the Himalaya and both look plausible.
      </div>

      <label style={label}>Crest width across the valley (m): {widthM}</label>
      <input type="range" min="100" max="4000" step="50" value={widthM}
             onChange={(e) => setWidthM(+e.target.value)} />
      <div style={{
        fontSize: 10, lineHeight: 1.4,
        color: subGrid ? "#b00020" : "#666",
      }}>
        {cells.toFixed(1)} cells at {targetResolution} m resolution
        {subGrid && " — too narrow to resolve; its outflow would be set by the grid rather than by the deposit."}
      </div>

      <label style={label}>Failure mode</label>
      <select style={field} value={breachMode}
              onChange={(e) => setBreachMode(e.target.value)}>
        <option value="overtop">Overtop (barrier intact)</option>
        <option value="full_notch">Full notch (barrier cut to the valley floor)</option>
      </select>
      <div style={{ fontSize: 10, color: "#666", marginTop: 4, lineHeight: 1.4 }}>
        Changes the local cross-section, not the released volume — that comes
        from routing the lake measured off the updated DEM.
      </div>

      <div style={{
        marginTop: 8, fontSize: 10, color: "#7a3e00", lineHeight: 1.4,
      }}>
        The impounded volume is <strong>not</strong> set here. It is measured by
        filling the DEM behind this barrier, because a landslide dam has no
        published storage.
      </div>
    </fieldset>
  );
}

/**
 * What the Sentinel-1 difference found, or why it declined.
 *
 * A refusal is rendered as an ordinary result with its reason verbatim, not as
 * an error. Over the Tehri gorge the equivalent SAR gate measures precision
 * 0.010 against JRC permanent water and correctly refuses; that measurement is
 * itself worth showing, and the manual path is one click away.
 */
function DetectionResult({ detection, onUseManual }) {
  const refused = detection.source === "unavailable";
  return (
    <div style={{
      marginTop: 6, padding: "6px 8px", fontSize: 10, borderRadius: 4,
      border: `1px solid ${refused ? "#e65100" : "#2e7d32"}`,
      background: refused ? "#fff4e5" : "#edf7ed",
      color: refused ? "#7a3e00" : "#1b5e20", lineHeight: 1.45,
    }}>
      <strong>
        {refused ? "No detection produced" : `Detected (${detection.source})`}
      </strong>
      {detection.reason && <div style={{ marginTop: 3 }}>{detection.reason}</div>}
      {!refused && (
        <div style={{ marginTop: 3 }}>
          <div>Post scene: {detection.scene_id_post}</div>
          <div>Acquired: {detection.acquired_at_post}</div>
          <div>
            Thresholds: {detection.threshold_db_pre?.toFixed(1)} /{" "}
            {detection.threshold_db_post?.toFixed(1)} dB (pre / post, per scene)
          </div>
          <div>
            Pre-mask precision vs JRC:{" "}
            {detection.precision_of_pre_mask_vs_jrc?.toFixed(3)}
          </div>
          <div>
            New water: {(detection.new_water_fraction * 100)?.toFixed(2)}% of the
            window, {(detection.fraction_near_drainage * 100)?.toFixed(0)}% of it
            on a watercourse
          </div>
          {detection.largest_component_m2 != null && (
            <div>
              Largest connected patch:{" "}
              {(detection.largest_component_m2 / 1e6).toFixed(2)} km&sup2;
              {detection.lake_mean_slope_deg != null && (
                <> · ground beneath it: {detection.lake_elevation_spread_m?.toFixed(1)} m
                  spread at {detection.lake_mean_slope_deg?.toFixed(1)}&deg; mean slope</>
              )}
            </div>
          )}
          {/*
            The terrain correction is stated, not assumed. A mask derived over a
            window that was 60% radar shadow and one derived over open ground are
            different claims, and the whole reason this detector refused every
            mountain reach was that nothing distinguished them. "Geometry-masked"
            is deliberate wording: shadow and layover pixels are EXCLUDED, not
            radiometrically flattened to gamma-nought, and the label must not
            imply the half that is not built.
          */}
          {detection.terrain_correction && (
            <div style={{ marginTop: 3, opacity: 0.85 }}>
              Geometry-masked (not terrain-flattened):{" "}
              {((detection.geometry_valid_fraction ?? 0) * 100).toFixed(0)}% of the
              window usable —{" "}
              {((detection.geometry_shadow_fraction ?? 0) * 100).toFixed(0)}% radar
              shadow,{" "}
              {((detection.geometry_layover_fraction ?? 0) * 100).toFixed(0)}%
              layover, at {detection.look_azimuth_deg?.toFixed(0)}&deg; look
              azimuth
              {detection.look_azimuth_source === "nominal_from_orbit_pass"
                ? " (nominal for the orbit pass)"
                : " (from the scene)"}
              .
              {detection.orbit_pass && (
                <> Pre and post both on {detection.orbit_pass.toLowerCase()} orbit{" "}
                  {detection.relative_orbit}
                  {detection.pre_scenes_on_track != null &&
                    ` (${detection.pre_scenes_on_track} pre-event scene${
                      detection.pre_scenes_on_track === 1 ? "" : "s"} on that track)`}
                  .</>
              )}
            </div>
          )}
          <div style={{ marginTop: 3 }}>
            Confirm the barrier position below — nothing is auto-selected.
          </div>
        </div>
      )}
      {refused && (
        <button onClick={onUseManual} style={{ marginTop: 5, fontSize: 10 }}>
          Place the barrier manually
        </button>
      )}
    </div>
  );
}

function GeeBadge({ gee }) {
  if (!gee) return null;
  const ok = gee.available;
  return (
    <div style={{
      marginTop: 12, padding: "6px 9px", fontSize: 10, borderRadius: 4,
      border: `1px solid ${ok ? "#2e7d32" : "#e65100"}`,
      background: ok ? "#edf7ed" : "#fff4e5",
      color: ok ? "#1b5e20" : "#7a3e00", lineHeight: 1.4,
    }}>
      <strong>Sentinel-1 / Earth Engine: {ok ? "connected" : "not configured"}</strong>
      <div style={{ marginTop: 3 }}>{gee.reason}</div>
    </div>
  );
}

/**
 * The breach ensemble ran on a dam class its regressions were never fitted on.
 *
 * Shown only when the backend sets the flag. This is deliberately loud: the
 * peak outflow for a masonry gravity dam comes out of four EMBANKMENT
 * regressions, and the existing height-based extrapolation check cannot catch
 * it — a 51 m gravity dam scores well inside the fitted height range while
 * being the wrong kind of structure. A number with no caveat next to it reads
 * as a result.
 */
function DamClassWarning({ hazard }) {
  if (!hazard?.dam_class_outside_fitted_population) return null;
  return (
    <div style={{ marginTop: 12, padding: "8px 10px", fontSize: 11,
                  border: "2px solid #e65100", background: "#fff4e5",
                  borderRadius: 4, color: "#7a3e00" }}>
      <div style={{ fontWeight: 700 }}>
        Screening figure only — dam class outside fitted population
        {hazard.dam_type ? ` (${hazard.dam_type})` : ""}
      </div>
      <div style={{ marginTop: 4 }}>{hazard.dam_class_note}</div>
    </div>
  );
}

/**
 * Arrival time at each downstream gauge — the headline number of the system.
 *
 * The panel used to render the static GAUGES list from data/entities.js:
 * names and distances only, identical before and after a run. The API has
 * carried `RunResult.gauges[].arrival_time_s` since the table was created and
 * nothing read it, so the one number the whole solver exists to produce was
 * never on screen. Before a run is loaded the static list still shows, clearly
 * labelled as such.
 */
function GaugeArrivals({ gauges, damGauges }) {
  const hasRun = Array.isArray(gauges) && gauges.length > 0;
  // Pre-run, show THIS dam's corridor rather than the static Tehri import —
  // the fallback is only for the moment before GET /dams resolves.
  const reference = damGauges?.length ? damGauges : GAUGES;
  const rows = hasRun
    ? gauges
    : reference.map((g) => ({ gauge_name: g.name, distance_km: g.distance_km,
                              arrival_time_s: null, note: g.note }));

  const arrival = (seconds) => {
    if (seconds === null || seconds === undefined) return "—";
    const minutes = seconds / 60;
    return minutes >= 60
      ? `${Math.floor(minutes / 60)}h ${Math.round(minutes % 60)}m`
      : `${minutes.toFixed(1)} min`;
  };

  return (
    <div style={{ marginTop: 12 }}>
      <h4 style={{ marginBottom: 4 }}>
        Gauges {hasRun ? "— arrival time" : ""}
      </h4>
      {!hasRun && (
        <div style={{ fontSize: 11, color: "#777", marginBottom: 4 }}>
          Reference list. Run or load a simulation for arrival times.
        </div>
      )}
      <table style={{ fontSize: 12, width: "100%", borderCollapse: "collapse" }}>
        <tbody>
          {rows.map((row) => (
            <tr key={row.gauge_name} style={{ borderBottom: "1px solid #f0f0f0" }}>
              <td style={{ padding: "3px 0" }}>{row.gauge_name}</td>
              <td style={{ padding: "3px 0", color: "#777", textAlign: "right" }}>
                {row.distance_km?.toFixed?.(1) ?? row.distance_km} km
              </td>
              <td style={{ padding: "3px 0 3px 8px", textAlign: "right",
                           fontWeight: row.arrival_time_s != null ? 700 : 400,
                           color: row.arrival_time_s != null ? "#1565C0" : "#aaa" }}>
                {arrival(row.arrival_time_s)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {hasRun && rows.every((r) => r.arrival_time_s == null) && (
        <div style={{ fontSize: 11, color: "#7a3e00", marginTop: 4 }}>
          The flood did not reach any gauge within the simulated time.
        </div>
      )}
    </div>
  );
}

/**
 * Population at risk, from real GHSL census counts over the run's own grid.
 *
 * This field was null for every run since the table was created — nothing ever
 * computed a population figure. It is shown only when a real population grid
 * was obtained; when Earth Engine is unavailable it says so and shows NO
 * number, because a headcount behind a "people at risk" headline is the worst
 * thing in this project to invent.
 */
export function PopulationAtRisk({ data }) {
  if (!data) return null;

  if (!data.available) {
    return (
      <div style={{ marginTop: 12, padding: "8px 10px", fontSize: 11,
                    border: "2px solid #e65100", background: "#fff4e5",
                    borderRadius: 4, color: "#7a3e00" }}>
        <div style={{ fontWeight: 700 }}>No population-at-risk figure</div>
        <div style={{ marginTop: 4 }}>{data.reason}</div>
        <div style={{ marginTop: 4 }}>No estimate is substituted.</div>
      </div>
    );
  }

  const par = data.par || {};
  const n = (v) => (typeof v === "number" ? Math.round(v).toLocaleString() : "-");

  return (
    <div style={{ marginTop: 12 }}>
      <h4 style={{ marginBottom: 4 }}>Population at risk</h4>
      <div style={{ fontSize: 22, fontWeight: 700 }}>{n(par.total_par)}</div>
      <div style={{ fontSize: 11, color: "#555" }}>
        of {n(data.total_population_in_domain)} in the domain
      </div>
      <ul style={{ fontSize: 11, paddingLeft: 16, marginTop: 6 }}>
        <li>&lt; 15 min warning: <strong>{n(par.par_high_urgency_under_15min)}</strong></li>
        <li>15-60 min: <strong>{n(par.par_medium_urgency_15_60min)}</strong></li>
        <li>&gt; 60 min: <strong>{n(par.par_low_urgency_over_60min)}</strong></li>
      </ul>
      <div style={{ fontSize: 10, color: "#777" }}>
        {data.population_source}
        {data.population_epoch ? ` epoch ${data.population_epoch}` : ""} · assumes{" "}
        {Math.round((data.warning_lead_time_s || 0) / 60)} min warning lead time
      </div>
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
