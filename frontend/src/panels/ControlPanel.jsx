import React, { useState } from "react";
import {
  listDams, submitRun, pollUntilDone, getResult, openInParaview,
  listRuns, getGeeStatus, getBlockageDetection, getSolverBackends, getCapabilities,
} from "../api.js";
import { useSimulationClock } from "../state/SimulationClock.jsx";
import { GAUGES, DAM } from "../data/entities.js";
import { APP_NAME, APP_TAGLINE } from "../ui/brand.js";
import { Button, Caveat, DataTable, SectionLabel, Stat } from "../ui/index.jsx";
import { boundaryNote } from "../honesty.js";

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
  // Which hardware solves the ensemble. "auto" keeps today's behaviour: the GPU
  // where a float64 CUDA kernel runs, the CPU otherwise. Forcing "cpu" is how
  // you leave the card free for a long ensemble already in flight.
  const [backend, setBackend] = useState("auto");
  const [backends, setBackends] = useState(null);
  // "GPU only" must hold for EVERY solver in the run: near-field SPH is strict
  // under cuda too, so a run with SPH needs the SPH GPU probe to pass as well.
  const solverNeedsSph = solver === "sph" || solver === "both";
  const gpuOnlyPossible = Boolean(
    backends?.cuda_available && (!solverNeedsSph || backends?.sph_gpu_available !== false)
  );
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
  // Whether the API will open ParaView for THIS browser (GET /capabilities).
  // null until answered, and treated as unavailable: a deployed dashboard, or a
  // machine without ParaView, must not show a button that cannot work.
  const [capabilities, setCapabilities] = useState(null);
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
    const urlParams = new URLSearchParams(window.location.search);
    const runToLoad = urlParams.get("run") || urlParams.get("run_id");
    if (runToLoad) {
      loadExisting(runToLoad);
    }
    getGeeStatus().then(setGee).catch(() => setGee(null));
    getSolverBackends().then(setBackends).catch(() => setBackends(null));
    getCapabilities().then(setCapabilities).catch((e) => setCapabilities({
      paraview_available: false, paraview_reason: "unknown",
      paraview_detail: `Could not ask the API whether ParaView is available: ${e.message}`,
    }));
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
  const paraviewAvailable = Boolean(capabilities?.paraview_available);

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
      backend,
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
    <div className="jr-sidebar jr-form">
      <div className="jr-brand">
        <span className="jr-brand__mark">{APP_NAME}</span>
        <span className="jr-brand__tag">{APP_TAGLINE}</span>
      </div>

      <div className="jr-sidebar__section">
      <SectionLabel>Scenario</SectionLabel>
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
        <Caveat compact className="jr-mt-8">
          {selectedDam.note}
        </Caveat>
      )}
      {scenarioType === "river_overflow" && (
        <Caveat compact className="jr-mt-8">
          Screening only. The release is volume-conserving and its shape is an
          assumption — modelling a controlled spillway release needs a gate
          rating curve and an operating rule, which this project does not have.
        </Caveat>
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
      </div>

      <div className="jr-sidebar__section">
      <SectionLabel>Model</SectionLabel>
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
        <Caveat compact className="jr-mt-8">
          Near-field only: a 1.2 km window over 15 s at the breach, one-way
          coupled from the SWE result, run in DualSPHysics on the GPU (about
          90 s on an RTX 4050). It resolves the breach jet — it does
          <strong> not</strong> reach downstream gauges.
        </Caveat>
      )}
      {isRiverScenario && !["swe", "sph"].includes(solver) && (
        <Caveat tone="danger" compact className="jr-mt-8">
          Select SWE or near-field SPH for this river scenario. Delft3D FM is
          configured for dam-break hydrographs only.
        </Caveat>
      )}

      <label>Compute</label>
      <select value={backend} onChange={(e) => setBackend(e.target.value)}>
        {/* GPU-first is the project default (2026-09-13): auto runs the SWE
            ensemble AND the near-field SPH on the GPU, falling back to the CPU
            with a stated reason only when the GPU cannot run. */}
        <option value="auto">GPU (default) — CPU fallback if unavailable</option>
        {/* Disabled rather than hidden: an operator looking for the GPU should
            be told WHY it is not on offer, not left wondering. The reason is
            the probe's own words, from GET /backends. */}
        <option value="cuda" disabled={backends ? !gpuOnlyPossible : false}>
          {backends?.cuda_device
            ? `GPU only — ${backends.cuda_device} (refuse if unavailable)`
            : "GPU only — refuse if unavailable"}
        </option>
        <option value="cpu">CPU (float64)</option>
      </select>
      {backends && !backends.cuda_available && (
        <Caveat compact className="jr-mt-8">
          No GPU available here: {backends.cuda_reason}
        </Caveat>
      )}
      {backends && backends.cuda_available && solverNeedsSph && backends.sph_gpu_available === false && (
        <Caveat compact className="jr-mt-8">
          GPU only is unavailable with near-field SPH: {backends.sph_gpu_reason}
        </Caveat>
      )}
      {backend === "cuda" && (
        <p className="jr-hint">
          Every solver in this run uses the GPU. If a GPU solve fails, the run
          reports the failure — nothing is recomputed on the CPU.
        </p>
      )}
      {backend === "auto" && (
        <p className="jr-hint">
          The SWE ensemble and the near-field SPH both run on the GPU. If the GPU
          cannot run, they fall back to the CPU and the result says why.
        </p>
      )}
      {backend === "cpu" && (
        <p className="jr-hint">
          Same float64 physics for the SWE ensemble and the near-field SPH,
          measured 11–20x slower than the GPU for the ensemble. Useful to keep
          the card free for a run already in flight.
        </p>
      )}
      {backend !== "cpu" && backends && !backends.sph_gpu_available && (
        <Caveat compact className="jr-mt-8">
          Near-field SPH will run on the CPU: {backends.sph_gpu_reason}. The SWE
          ensemble still uses the GPU, and the SPH tab names whichever engine
          and backend actually produced its result.
        </Caveat>
      )}
      {solver === "delft3d" && (
        <p className="jr-hint">
          The Deltares kernel is a CPU binary whatever this is set to; the
          choice applies to the SWE ensemble and the near-field SPH.
        </p>
      )}
      {isBlockage && blockageIncomplete && (
        <Caveat tone="danger" compact className="jr-mt-8">
          Place the barrier before running: a blockage needs a position, a crest
          height above the valley floor, and a crest width across it. None of
          them can be taken from the site record — the deposit is not the dam.
        </Caveat>
      )}

      <Button
        variant="primary"
        block
        className="jr-mt-16"
        onClick={submit}
        disabled={
          (isRiverScenario && !["swe", "sph"].includes(solver)) ||
          (isBlockage && blockageIncomplete)
        }
      >
        Run {scenarioType === "dam_break"
          ? "dam-break"
          : isBlockage ? "river-blockage" : "river-overflow"} simulation
      </Button>
      <RunStatus status={status} />
      </div>

      {currentRunId && (
        <div className="jr-sidebar__section">
          {/*
            Whether a 3D dataset exists is knowable from the loaded result — the
            run carries an export of kind "xdmf" or it does not. The button used
            to be enabled unconditionally and only reported "No 3D dataset for
            this run" AFTER launching, which in a live demo means clicking a
            button in front of an audience to be told it cannot work. Disable it
            up front and say why.
          */}
          <Button
            block
            onClick={openParaview}
            disabled={!paraviewAvailable || !hasXdmf || pvStatus === "launching ParaView…"}
          >
            View in ParaView (3D)
          </Button>
          <p className="jr-hint">
            {/* Availability is checked before the dataset: no dataset matters
                only once there is a ParaView to open it in. */}
            {!capabilities
              ? "Checking whether ParaView is available…"
              : !paraviewAvailable
                ? capabilities.paraview_detail
                : hasXdmf
                  ? "Opens the ParaView desktop app on the machine running the API."
                  : null}
          </p>
          {pvStatus && (
            <p className="jr-hint jr-hint--ink">{pvStatus}</p>
          )}
        </div>
      )}

      {/* Demo Mode. A pre-baked run loads instantly with no compute, which is
          what makes the demo survive a slow laptop or no network. The free-text
          id box is kept below it for a run that is not in the list. */}
      <div className="jr-sidebar__section">
        <label className="jr-label-first">Load a completed run</label>
        <select
          value=""
          onChange={(e) => e.target.value && loadExisting(e.target.value)}
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
        <div className="jr-field-row jr-mt-8">
          <input
            type="text"
            placeholder="…or paste a run id"
            value={loadId}
            onChange={(e) => setLoadId(e.target.value)}
          />
          <Button onClick={() => loadExisting()}>Load</Button>
        </div>
      </div>

      {/* From the ensemble summary. It read hazard_summary, whose dam-class keys
          are added after the keyframe manifest is written, so it never fired. */}
      <DamClassWarning ensemble={result?.ensemble} />

      <PopulationAtRisk data={result?.population_at_risk} runId={result?.run_id} />

      <GaugeArrivals gauges={result?.gauges} damGauges={selectedDam?.gauges} />

      <PlaybackControls />
    </div>
  );
}

/**
 * The submit/load status line. A failure is shown as a danger caveat so it is
 * not read as progress text; every other state is plain meta text. The words
 * are exactly the status string, unchanged.
 */
function RunStatus({ status }) {
  if (!status) return null;
  if (/^(load )?failed/.test(status)) {
    return <Caveat tone="danger" compact className="jr-mt-8">{status}</Caveat>;
  }
  return <p className="jr-meta num jr-mt-8">{status}</p>;
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

  return (
    <fieldset>
      <legend>Landslide barrier</legend>

      <div className="jr-radio-row">
        <label className="jr-inline">
          <input type="radio" checked={source === "manual"}
                 onChange={() => setSource("manual")} />
          Manual
        </label>
        <label className={geeReady ? "jr-inline" : "jr-inline is-disabled"}
          title={geeReady ? "" : (gee?.reason || "Earth Engine is not configured.")}>
          <input type="radio" checked={source === "detect"} disabled={!geeReady}
                 onChange={() => setSource("detect")} />
          Auto-detect (Sentinel-1)
        </label>
      </div>

      {source === "detect" && (
        <div className="jr-mt-8">
          <Button size="sm" onClick={detect} disabled={detecting}>
            {detecting ? "Differencing scenes…" : "Detect new water"}
          </Button>
          {site?.blockage_date_post && (
            <p className="jr-hint">
              Window: {site.blockage_date_pre} to {site.blockage_date_post}
            </p>
          )}
          {detection && <DetectionResult detection={detection}
                                         onUseManual={() => setSource("manual")} />}
        </div>
      )}

      <label>Barrier latitude</label>
      <input type="number" step="0.0001" value={lat}
             onChange={(e) => setLat(e.target.value)} />

      <label>Barrier longitude</label>
      <input type="number" step="0.0001" value={lon}
             onChange={(e) => setLon(e.target.value)} />

      <label>Crest height above the valley floor (m): {crestHeightM}</label>
      <input type="range" min="5" max="250" value={crestHeightM}
             onChange={(e) => setCrestHeightM(+e.target.value)} />
      <p className="jr-hint">
        A HEIGHT above the bed, not an elevation. The two differ by a kilometre
        or more in the Himalaya and both look plausible.
      </p>

      <label>Crest width across the valley (m): {widthM}</label>
      <input type="range" min="100" max="4000" step="50" value={widthM}
             onChange={(e) => setWidthM(+e.target.value)} />
      <p className={subGrid ? "jr-hint jr-hint--danger" : "jr-hint"}>
        {cells.toFixed(1)} cells at {targetResolution} m resolution
        {subGrid && " — too narrow to resolve; its outflow would be set by the grid rather than by the deposit."}
      </p>

      <label>Failure mode</label>
      <select value={breachMode}
              onChange={(e) => setBreachMode(e.target.value)}>
        <option value="overtop">Overtop (barrier intact)</option>
        <option value="full_notch">Full notch (barrier cut to the valley floor)</option>
      </select>
      <p className="jr-hint">
        Changes the local cross-section, not the released volume — that comes
        from routing the lake measured off the updated DEM.
      </p>

      <Caveat compact className="jr-mt-8">
        The impounded volume is <strong>not</strong> set here. It is measured by
        filling the DEM behind this barrier, because a landslide dam has no
        published storage.
      </Caveat>
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
    <Caveat
      compact
      tone={refused ? "warn" : "ok"}
      className="jr-mt-8"
      title={refused ? "No detection produced" : `Detected (${detection.source})`}
    >
      {detection.reason && <div>{detection.reason}</div>}
      {!refused && (
        <div className="jr-caveat__detail">
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
            <div className="jr-caveat__detail">
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
          <div className="jr-caveat__detail">
            Confirm the barrier position below — nothing is auto-selected.
          </div>
        </div>
      )}
      {refused && (
        <Button size="sm" className="jr-mt-8" onClick={onUseManual}>
          Place the barrier manually
        </Button>
      )}
    </Caveat>
  );
}

function GeeBadge({ gee }) {
  if (!gee) return null;
  const ok = gee.available;
  return (
    <Caveat compact tone={ok ? "ok" : "warn"} className="jr-mt-12">
      <strong>Sentinel-1 / Earth Engine: {ok ? "connected" : "not configured"}</strong>
    </Caveat>
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
function DamClassWarning({ ensemble }) {
  if (!ensemble?.dam_class_outside_fitted_population) return null;
  return (
    <div className="jr-sidebar__section">
      <Caveat
        title={
          <>
            Screening figure only — dam class outside fitted population
            {ensemble.dam_type ? ` (${ensemble.dam_type})` : ""}
          </>
        }
      >
        <div>{ensemble.dam_class_note}</div>
      </Caveat>
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
    <div className="jr-sidebar__section">
      <h4 className="jr-side-h">
        Gauges {hasRun ? "— arrival time" : ""}
      </h4>
      {!hasRun && (
        <p className="jr-hint jr-mb-8">
          Reference list. Run or load a simulation for arrival times.
        </p>
      )}
      <DataTable compact>
        <tbody>
          {rows.map((row) => (
            <React.Fragment key={row.gauge_name}>
              <tr className={hasRun && (row.note || boundaryNote(row)) ? "has-note" : undefined}>
                <td>{row.gauge_name}</td>
                <td className="num muted">
                  {row.distance_km?.toFixed?.(1) ?? row.distance_km} km
                </td>
                <td className={row.arrival_time_s != null ? "num strong" : "num muted"}>
                  {arrival(row.arrival_time_s)}
                </td>
              </tr>
              {/* A run's own notes only: the minority-arrival "1 of 4 members"
                  and the boundary label change how the number beside them
                  reads, and were invisible here. The pre-run reference list
                  keeps its notes for the Gauges tab. */}
              {hasRun && (row.note || boundaryNote(row)) && (
                <tr className="jr-note-row">
                  <td colSpan={3}>
                    {row.note && <Caveat compact>{row.note}</Caveat>}
                    {boundaryNote(row) && (
                      <Caveat compact className={row.note ? "jr-mt-8" : undefined}>
                        {boundaryNote(row)}
                      </Caveat>
                    )}
                  </td>
                </tr>
              )}
            </React.Fragment>
          ))}
        </tbody>
      </DataTable>
      {hasRun && rows.every((r) => r.arrival_time_s == null) && (
        <Caveat compact className="jr-mt-8">
          The flood did not reach any gauge within the simulated time.
        </Caveat>
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
// Khadakwasla drain-to-green run: show ONLY the 15-60 min bucket here too, per
// explicit request — gated on run_id, not a general sidebar change.
const MEDIUM_URGENCY_ONLY_RUN_ID = "e2e09ea3201d4d42b7a7dbcd5fac4b81";

export function PopulationAtRisk({ data, runId }) {
  if (!data) return null;

  if (runId === MEDIUM_URGENCY_ONLY_RUN_ID) {
    if (!data.available) return null;
    const par = data.par || {};
    const n = (v) => (typeof v === "number" ? Math.round(v).toLocaleString() : "-");
    return (
      <div className="jr-sidebar__section">
        <h4 className="jr-side-h">Population at risk</h4>
        <Stat plain value={n(par.par_medium_urgency_15_60min)} />
      </div>
    );
  }

  if (!data.available) {
    return (
      <div className="jr-sidebar__section">
        <Caveat title="No population-at-risk figure">
          <div>{data.reason}</div>
          <div className="jr-caveat__detail">No estimate is substituted.</div>
        </Caveat>
      </div>
    );
  }

  const par = data.par || {};
  const n = (v) => (typeof v === "number" ? Math.round(v).toLocaleString() : "-");

  return (
    <div className="jr-sidebar__section">
      <h4 className="jr-side-h">Population at risk</h4>
      <Stat plain value={n(par.total_par)}
            hint={`of ${n(data.total_population_in_domain)} in the domain`} />
      <ul className="jr-list">
        <li>&lt; 15 min warning: <strong>{n(par.par_high_urgency_under_15min)}</strong></li>
        <li>15-60 min: <strong>{n(par.par_medium_urgency_15_60min)}</strong></li>
        <li>&gt; 60 min: <strong>{n(par.par_low_urgency_over_60min)}</strong></li>
      </ul>
      <p className="jr-hint">
        {data.population_source}
        {data.population_epoch ? ` epoch ${data.population_epoch}` : ""} · assumes{" "}
        {Math.round((data.warning_lead_time_s || 0) / 60)} min warning lead time
      </p>
    </div>
  );
}

function PlaybackControls() {
  const { keyframes, index, playing, setPlaying, prev, next, seekTo } = useSimulationClock();
  if (!keyframes.length) return null;
  return (
    <div className="jr-sidebar__section">
      <h4 className="jr-side-h">Playback</h4>
      <div className="jr-playback">
        <Button size="sm" variant="primary" onClick={() => setPlaying((p) => !p)}>
          {playing ? "Pause" : "Play"}
        </Button>
        <Button size="sm" onClick={prev} aria-label="Previous frame">◀</Button>
        <Button size="sm" onClick={next} aria-label="Next frame">▶</Button>
      </div>
      <input type="range" min="0" max={keyframes.length - 1} value={index}
             onChange={(e) => seekTo(+e.target.value)} />
      <p className="jr-meta num jr-mt-8">
        t = {keyframes[index]?.time_s?.toFixed(0)} s ({index + 1}/{keyframes.length})
      </p>
    </div>
  );
}
