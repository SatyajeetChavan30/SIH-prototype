# (PROJECT NAME) — Aazhi slice 2: operations, prediction and reporting

**Paste everything below the line into a session opened at the repo root.**

Two conventions in this document. `(PROJECT NAME)` is the placeholder the product
name goes into — leave it as a placeholder in anything user-facing you write.
Python module paths (`jalraksha/...`, `jalraksha_service`) are identifiers, not
the product name, so they stay exactly as written.

---

## Read before writing any code

1. `CLAUDE.md` — in full. It is the contract, not background.
2. `docs/VERIFICATION_LOG.md` — the live queue of unvetted coefficients. Row 39 is
   the newest. Anything you add starts at row 40.
3. `docs/DECISIONS.md` — §14 (GPU), §15 (desktop), §16 (DualSPHysics), §17
   (label-not-refusal gating for unvetted thresholds).
4. The **original Aazhi feature-integration spec**. Slice 1 built three of its nine
   workstreams: W8 (provenance tab), W1 (evacuation directives), W9 (playback).
   Six are designed and unstarted. **Before creating anything below, check whether
   the spec's W2–W7 already cover that ground and extend those instead of forking a
   second implementation.** Only number something new from W10 onward if the spec
   genuinely has no slot for it. Say in your first message which existing
   workstreams you matched and which are new.

This slice takes the operational, predictive and reporting surfaces from the
reference UI and rebuilds them on data this repo can actually stand behind. It is
not a reskin. Several of the reference screens report quantities we do not have,
and §6 lists those explicitly as things not to build.

---

## 1. Hard rules (these override anything below)

- **No overclaiming.** Every number on screen or in a document traces to a field
  something recorded. A field a run never recorded prints "not recorded for this
  run" — never a blank, never a plausible default. This is the rule
  `ProvenancePanel` already follows; the new surfaces follow it too.
- **Three states, no fourth** (the `gee/sar.py` contract): an observation is
  fetched, or refused with a reason, or absent. There is never a synthesised
  stand-in. This binds the weather fetch exactly as it binds the SAR fetch.
- **Operator-supplied is a state, not a default.** A number typed into the
  dashboard is labelled `OPERATOR_SUPPLIED` in the payload and rendered as such.
  `blockage.py` already refuses a run whose `storage_source` is user-supplied; use
  that precedent whenever an input would otherwise drive a published figure.
- **Unvetted constants are labelled, not hidden.** `# TODO: UNVETTED — source?` in
  the code, a new `docs/VERIFICATION_LOG.md` row, and the flag travelling in the
  payload with a `Caveat` in the UI (DECISIONS §17).
- **No hazard colour in a stylesheet.** Colours come from the run payload or
  `GaugesPanel.hazardClass`. There is no green in the directive palette.
- **Layering holds.** New library modules must not import `jalraksha_service`, and
  `jalraksha.impact` must not import `jalraksha.gee`. Add every new forbidden edge
  to `tests/test_layering.py` in the same commit.
- **Endpoints stay fast while a run solves.** Runs execute in a subprocess for this
  reason; do not do fetches or hypsometry inside a request handler without a cache.

---

## 2. Dam scope — ours, not the reference UI's

Build every screen below for the four sites that have real cached terrain, gauge
geometry and completed runs behind them:

| id | what it is | source of truth |
| :-- | :-- | :-- |
| `khadakwasla` | Khadakwasla Dam, Mutha, Pune — the flagship, run `e2e09ea3` | `jalraksha/presets.py::KHADAKWASLA` |
| `tehri` | Tehri Dam, Bhagirathi, Uttarakhand | `jalraksha/presets.py::TEHRI` |
| `rishi_ganga` | Rishi Ganga / Dhauliganga, Chamoli — real 2021 blockage | `presets.py::RISHI_GANGA` |
| `mutha_temghar` | Mutha below Temghar — **hypothetical**, operator-supplied barrier | `presets.py::MUTHA_TEMGHAR` |

Do **not** add Bhakra, Srisailam, Hirakud, Mettur, Nagarjuna Sagar, Tungabhadra or
Medigadda. We have no cached DEM, no gauge geometry and no verified storage figures
for any of them, so every number on such a page would be hand-typed. Mullaperiyar
stays forbidden (active litigation).

One thing to fix while you are here: `services/api/jalraksha_service/config.py::DEMO_DAMS`
carries `tehri`, `bhakra`, `idukki` and `hirakud` as a fallback list, and only
`tehri` has a preset behind it. Either delete the three unbacked entries or give
each a `runnable: false` plus the reason, so the new registry cannot present them
as selectable. `presets.py` is the source of truth; the service derives from it,
never the reverse.

---

## 3. Workstreams

### W-REPORT — Word (.docx) simulation report

The deliverable a judge or a district officer takes away. Self-contained, reads
only recorded data, recomputes nothing.

- `jalraksha/export/docx_report.py`; `POST /runs/{run_id}/report` returning an
  `ExportRef` of kind `report_docx`; a button in `panels/DownloadsPanel.jsx`.
- `python-docx` as a new `[report]` extra in `pyproject.toml`. Pure Python, works
  offline.
- **Frozen-build gotcha, prove it don't assume it:** python-docx ships its
  `default.docx` template as package data and PyInstaller's module analysis drops
  it. Add `collect_data_files("docx")` to
  `desktop/backend/jalraksha-backend.spec` and generate a report from the packaged
  exe to prove it, the same way the missing `redis` import was proven.

Document structure, in order:

1. **Cover** — site, run id, scenario, solver and `solver_backend_label`, grid from
   `GridSummary`, domain, member count, wall clock, `EngineInfo` versions,
   generated-at.
2. **Honesty page, second, never an appendix.** `is_synthetic` → a full-width red
   banner and the document does not call itself a result;
   `unverified_regressions` / `unverified_regression_note`; `thresholds_unvetted`;
   `terrain_modified` and `corridor_volume_removed_mcm` with its domain and
   resolution; every `near_boundary` gauge; DEM provenance including any
   `JALRAKSHA_NOT_A_SURVEY` update; the GHSL manifest version behind the PAR
   figure; damage `model_is_published: false` with `unit_cost_inr_per_m2` and
   `unit_cost_price_year` printed so a reader can divide them back out.
3. **Inputs and provenance** — dam config, breach ensemble inputs, DEM path and
   source, roughness field summary (`is_uniform`, `fraction_at_default`).
4. **Results** — volume balance **first** (`released`, `exited_mcm`,
   `retained_fraction`, closure), because a run that exported no water never tested
   drainage whatever its hazard counts say. Then arrival times with p05/p50/p95,
   peak depths, hazard-class counts under the four published FD2320 classes,
   `safe_at_s` / `fully_green_at_s`.
5. **Gauges and evacuation directives** — one table, directives straight from
   `gauge_results.evacuation_json`, `NO_ARRIVAL` rendered as "Not assessed".
6. **Impact** — PAR and damage by sector, each sector's own `available` and
   `reason`, and the total withheld with `missing_sectors` listed when any sector
   failed.
7. **Validation** — the gates as they ran; the Delft3D FM comparison only when
   `delft3d_binary_used` is true, named with its build.
8. **Figures** — embed existing keyframe PNGs and the hazard series from
   `data/keyframes/<run_id>/`. No new rendering pipeline.
9. **Limitations and citations** — Tier-1 screening framing, the 30 m point-depth
   caveat, the one-way SPH handoff, and each coefficient's verification-log row.

Acceptance (`tests/test_docx_report.py`): a synthetic fixture run produces a
document containing the synthetic banner text; a run with
`unverified_regressions` contains that caveat; no null field renders as `0.0`,
`—` alone or `TBD`.

### W-REGISTRY — Dam and basin registry

- `GET /registry` (or extend `GET /dams`), built from `PRESETS` and
  `BLOCKAGE_PRESETS`.
- Readiness is **computed, not asserted**: DEM cached (check the cached bounds the
  way `dem.py` does — a tile cache hit is not coverage), gauge count, completed run
  count from the runs table, whether `frl_m` exists and its `frl_source`. The badge
  is derived from those booleans; a missing DEM reads "DEM not cached", not "ready".
- `panels/RegistryPanel.jsx` using `DataTable`, `Chip`, `Caveat` from
  `frontend/src/ui/`. Selecting a row sets the active site — it does not start a run.
- `mutha_temghar` is badged HYPOTHETICAL from its own `barrier_source`, so the
  registry cannot present it as an observed event.

### W-CATALOG — Data centre / provenance catalogue

Extend W8, do not fork it.

- `GET /datasets`: an inventory of what is on disk — DEM tiles under `data/dem/`
  and `data/dem/updated/`, GEE caches under `data/gee/` with their manifests, the
  Delft3D kernel, the DualSPHysics directory. Per row: name, format, source agency,
  licence, path relative to `DATA_DIR`, bytes, sha256 (reuse `data_packs.py`'s
  hashing), fetched-at from the manifest.
- **A row exists only if the file exists.** Never list an expected-but-absent
  dataset as loaded.
- Pre-fix GHSL v1 rasters are labelled superseded (`ghsl_manifest_v2.json` is the
  live one).
- The licence column is load-bearing: Copernicus DEM, GHSL, ESA WorldCover and
  Google Open Buildings are approved; FABDEM, MERIT and OSM must not appear in
  redistributed outputs.

### W-WEATHER — Weather and overflow predictor

New `jalraksha/hydrology/` package. It must not import solver, export or impact;
add those edges to `tests/test_layering.py`.

- `openmeteo.py` — current, 7-day forecast, last-10-day and ERA5 archive, cached to
  `data/weather/` with `dem.py`'s offline-first contract: a cache hit serves, a
  network failure serves the cache **and says how old it is**, and a miss with no
  network refuses. No synthesised forecast, ever.
- `scs_cn.py` — SCS-CN runoff. The curve-number grid comes from the ESA WorldCover
  raster already fetched by `gee/worldcover.py`, reprojected NEAREST NEIGHBOUR
  (class codes do not interpolate), with AMC I/II/III adjustment. **Every CN value
  is UNVETTED** — build the table in `roughness.py`'s shape, one source citation
  per entry, one new verification row. `tests/test_scs_cn.py` asserts the ORDERING
  (built-up > cropland > forest, and AMC III > II > I) rather than the numbers, so
  a re-shifted legend still fails the test. The legend-shifted-by-one defect in
  `roughness.py` is the precedent: assert order, not values.
- `routing.py` — level-pool (modified Puls) routing: inflow hydrograph → storage →
  spillway outflow → level trajectory. The elevation–area–capacity curve comes from
  the cached DEM by the same hypsometry `terrain/blockage.py` already reads off a
  burned barrier. Spillway rating needs new **optional** preset fields —
  `spillway_crest_m`, `spillway_capacity_m3s`, `gate_count`, each with a
  `*_source` string. Absent means the predictor **refuses**, not defaults.
- `POST /overflow` → inflow and outflow series, level trajectory, freeboard margin.
  `GET /weather` → the raw forecast with its fetched-at.
- The result is a **screening** hydrograph and labels itself one. It does not
  silently become a solver boundary condition; handing it to `POST /runs` is a
  separate explicit action, because a screening pulse driving a 2D run upgrades a
  rough estimate into a map.

### W-BREACHRISK — Breach prediction engine

The single largest fabrication hazard in the reference UI, so read this twice.

- **There is no ML model in this repo and you are not to invent one.** The badge
  reads "PHYSICS — RESERVOIR ROUTING + BREACH REGRESSIONS". An ML path would need
  a published training set, a held-out score and its own verification row.
- `jalraksha/breach_risk.py`, deterministic, consuming `hydrology/routing.py`:
  - **Overtopping**: routed peak level against `crest_m` → freeboard margin in
    metres, with its real sign. This is a genuine number.
  - **Time to breach**: the time the routed level crosses the crest, read off the
    series; `null` when it never crosses. Not an estimate, a crossing.
  - **Piping / seepage**: an operator-supplied scenario knob, labelled
    `OPERATOR_SUPPLIED`. Any onset criterion is unvetted and gated by label.
  - **"Probability" is an ensemble fraction and is named one.** `breach_fraction`
    with `members_n` beside it. With four members the only honest values are 0,
    0.25, 0.5, 0.75, 1.0 and the payload says so. A single deterministic run yields
    0 or 1 — never 4.5%, never 99.9%.
  - **Failure mechanism** is the criterion that actually fired, or "none".
  - **No factor of safety and no structural-stability output.** Sliding and
    overturning need foundation shear parameters this project has never had. Drop
    that card rather than fill it.
- Handoff: a predicted breach feeds `run.py` through the existing
  `breach_formation_time_s` and ensemble inputs; the "simulate downstream
  consequences" action submits an ordinary `POST /runs`, and provenance records
  that the breach parameters came from the predictor rather than a preset.

### W-SCENARIO — Named scenarios and the state bar

- Scenarios live in `presets.py` as data, per site: normal monsoon spill, design
  flood, PMF-plus-overtopping. Each carries only values that have a source and a
  `scenario_source` string. **Do not label anything a "100-year return period"**
  unless the return period comes from a cited frequency analysis — otherwise the
  label is the rainfall depth itself.
- The compact state bar shows current inputs — storage %, rainfall, AMC class,
  seepage, freeboard margin — each cell reading one named field and showing "—"
  when unset.

### W-SURVEY — Downstream impact and evacuation survey

Extend W1's server-side directives (`jalraksha/impact/evacuation.py`, already
inside `script_runs.gauge_rows_from_result` and already in data packs). Do not
build a second directive path; two would eventually disagree about what a minority
arrival is.

- Per-gauge cards: distance, PAR, predicted depth, arrival time, directive colour
  from the payload.
- **"N of N villages (100%)" is only computable when every gauge has an arrival.**
  With a minority arrival, show `_minority_arrival_note` and read the rate honestly:
  "4 of 7 gauges reached, 2 no arrival, 1 outside the domain".
- PAR from runs predating the GHSL v2 fix carries the 25× undercount. Those runs
  are not retroactively corrected, so show the stored figure with a `Caveat` naming
  the manifest version.
- A `near_boundary` gauge shows the flag on its card, not only in the Gauges tab.

### W-STATE — Reservoir state strip

Last, because it can only be honest once routing and hypsometry exist.

- **We have no live reservoir telemetry feed.** Stage and storage are
  `OPERATOR_SUPPLIED`, and the row says so on the row, not in a footnote.
- What is genuinely live is Open-Meteo rainfall over the catchment — fetched,
  timestamped, and refused with a reason when it cannot be.
- Storage percentage derived from stage via the DEM hypsometric curve is labelled
  `DERIVED_FROM_DEM`, and the pool already baked into GLO-30 (Khadakwasla's is
  580.0 m) is stated as the known floor.
- FRL and crest come from the preset with `frl_source` printed. Where `frl_m` is
  `None`, the card reads "not published for this dam" and shows no value.

---

## 4. Build order

Deliberately not the screenshot order. Self-contained and read-only first, new
physics last:

`W-REPORT → W-REGISTRY → W-CATALOG → W-WEATHER → W-BREACHRISK → W-SCENARIO → W-SURVEY → W-STATE`

Land each one green before starting the next, and say what you measured.

---

## 5. Definition of done

- `pytest` green; `npm test --prefix frontend` green; new frontend logic lives in
  testable `src/*.test.js` helpers, not inside JSX.
- `tests/test_layering.py` extended with every new forbidden edge.
- Every unsourced constant carries `# TODO: UNVETTED — source?` and a new
  `docs/VERIFICATION_LOG.md` row, numbered from 40.
- `docs/DECISIONS.md` gains a section recording the two judgement calls made here:
  no ML in the breach engine, and no structural factor of safety.
- `node desktop/scripts/sync-version.mjs --check` still passes; a packaged build
  produces a working .docx report.
- Every new endpoint answers in well under a second while a run is solving.
- `docs/dashboard_integration.md` updated — it is the record of how each module
  reaches the browser.

---

## 6. Do not build

Each of these appears in the reference UI and each would be a fabricated
credential here:

- A live reservoir telemetry stream. We have no such feed.
- Any "ML" or "AI ensemble" badge with no model behind it.
- A calibrated breach probability, in particular a two-decimal percentage.
- A structural factor of safety, sliding or overturning verdict.
- A synthesised weather, SAR or population observation when a fetch fails —
  refuse with the reason instead.
- Bhakra, Srisailam, Hirakud, Mettur, Nagarjuna Sagar, Tungabhadra, Medigadda, or
  any other dam with no cached terrain behind it. Mullaperiyar stays forbidden.
- The reference UI's numbers as defaults, placeholders or fixture data anywhere in
  this repo.

If a screen cannot be filled with real data, ship it showing why it is empty. An
empty panel that explains itself is worth more to a technical panel than a full
one that cannot be defended.
