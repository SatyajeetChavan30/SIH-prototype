# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**JalRaksha** (named FloodView until 2026-09-11 — `JALRAKSHA_*` environment variables fall back to `FLOODVIEW_*`, and `data/floodview.db` is adopted by rename on first connection) is a Python system for dam-break inundation modelling and analysis, designed for the Smart India Hackathon 2026 (Problem Statement 26161, NTRO-sponsored). It combines a 2D shallow-water equation (SWE) solver for far-field propagation with 3D Smoothed Particle Hydrodynamics (SPH) for violent near-field dynamics. The system uses exclusively open data (Copernicus DEM, Google Earth Engine, CWC dam registers, ESA WorldCover) and produces outputs in Cloud-Optimized GeoTIFF, Shapefile, and KML/KMZ formats.

## Critical Constraints

**Hard Rules:**

- **18 unvetted coefficients** in the verification queue (breach regressions, Wahl uncertainty bands, fatality-rate tables, depth-damage curves). Flag any coefficient before use with a TODO and a source citation from the literature.md file.
- **Tehri dam** is the demo case (260 m height, 3,540 MCM). **Mullaperiyar is explicitly forbidden** (active Supreme Court litigation).
- **Metric CRS for all solver operations** — never degrees. Cell-centred finite volume on uniform Cartesian grids.
- **No overclaiming — but the Delft3D rule is now CONDITIONAL.** A real Deltares kernel is installed and running (`dflowfm-cli.exe`, dimrset 2026.01, build 1.2.184), so the naming follows the evidence:
  - `delft3d_binary_used == True` → it IS Delft3D FM. Name it, and name the build: **"Delft3D FM (dflowfm-cli, dimrset 2026.01)"**.
  - `delft3d_binary_used == False` → unchanged: **"JalRaksha built-in 2D SWE — Delft3D-class, NOT Delft3D FM"**, plus the reason it fell back.
  The old blanket "never claim to be Delft3D" existed because the project had never run it. Continuing to hedge once it demonstrably runs would be its own inaccuracy. `run_delft3d_simulation` returns the boolean, so the label is always checkable.
- **No overclaiming (unchanged elsewhere)**: never claim rigorous two-way SPH↔SWE coupling — the handoff is one-way only.
- **DEM resolution is 30 m Copernicus GLO-30** — adequate for Tier-1 screening, but point depths are indicative only. Lead with arrival times and inundation envelopes, not absolute flood depths.
- **Offline-first design**: Everything must run from cache after first fetch. Demo-day network reliability is assumed low.

**Licensing:**
- Copernicus DEM (free) and Google Open Buildings (CC BY 4.0) are approved.
- Avoid FABDEM (CC BY-NC-SA), MERIT (CC BY-NC/ODbL), and OSM (ODbL share-alike) in redistributed outputs.

## Build Order & Phases

The build is organized into 18 phases. **Phases 0, 1, and 4 are marked critical (★)**:

1. **Phase 0★**: Skeleton — repo, CLI entry point, data cache system, DEM fetch pipeline
2. **Phase 1★**: Solver core — 2D SWE with HLLC flux, Audusse hydrostatic reconstruction, MUSCL, wet/dry treatment, Manning friction. *Gated on Ritter, lake-at-rest, and mass-conservation tests.*
3. **Phase 2**: Terrain conditioning — DEM interpolation, smoothing, breach location
4. **Phase 3**: Breach regressions — peak outflow, failure time, width/depth regressions (Wahl method, with uncertainty bands)
5. **Phase 4★**: End-to-end dam-break — breach → solver → arrival-time rasters, inundation polygons. *The mandatory core deliverable.*
6. Phases 5–12: Export formats (.shp, .kml, .tif), impact analysis, SPH coupling, GEE integration, validation, dashboard (React + Vite + Leaflet/Cesium, served by FastAPI — the Streamlit + leafmap fallback was built and has since been removed), hardening.
7. **Minimum defensible slice** (if schedule collapses): Phases 0–5 + Phase 7 (reduced) — working simulation with shapefile/KML export and small SPH near-field run.

## Testing Strategy

Multi-tier validation framework:

**Analytical tests (exact solutions):**
- Ritter dry-bed dam-break (1D)
- Stoker wet-bed dam-break (1D)
- Thacker parabolic bowl (2D oscillation)

**Blocking correctness gates:**
- Lake-at-rest: <0.1% velocity over any bathymetry (hydrostatic pressure term must balance exactly)
- Mass conservation: <0.1% total volume loss over 1000 timesteps
- Dry-bed robustness: no NaNs, negative depths, or division errors

**Benchmarks:**
- Malpasset (1959) real-terrain dam-break (France) — comparison vs published arrival-time field measurements
- Chamoli 2021 (India) — the only Indian dam-break with pre- and post-event 2 m DEMs publicly available; published <5% travel-time benchmark (Shugar et al., Science)
- **Delft3D FM cross-check (implemented and passing).** The same Ritter dam-break is run through JalRaksha's solver and through the real Deltares kernel, and both are scored against the exact solution:

  | | RMSE vs exact | depth at dam |
  | :--- | ---: | ---: |
  | JalRaksha 2D SWE | 0.0317 m | 4.532 m |
  | Delft3D FM | 0.0349 m | 4.515 m |
  | exact (4h₀/9) | — | 4.444 m |

  h₀ = 10 m, t = 40 s, Δx = 10 m, frictionless flat bed, scored over the interior (3 boundary cells trimmed each end). Engines agree to 0.0294 m RMSE. Reproduce with `python scripts/validate_against_delft3d.py --case ritter`.

**CI integration:** Lake-at-rest and mass-conservation tests must pass before any PR merge.

## Numerical Solver Conventions

- **Formulation**: Well-balanced, not surface-gradient method
- **Flux scheme**: HLLC with transverse-momentum correction (not HLL)
- **Reconstruction**: MUSCL with Audusse hydrostatic reconstruction
- **JIT compilation**: Use `@njit(parallel=True, fastmath=True)` for the flux kernel only; avoid `fastmath` in integrators to preserve stability
- **Output**: NetCDF or Zarr time series with 60 s snapshots + running-maxima rasters for depth, velocity, arrival time, and shear stress

## Python Environment & Build

- **Setup**: `pyproject.toml` with pip/setuptools
- **Key dependencies**: PySPH (BSD licence), NumPy, Numba (JIT), rasterio, geopandas, xarray
- **Run**: Entry point is CLI-based (no build system yet). Invoke solver via command line with config file
- **Linting**: ruff (auto-format on edit in hooks)

## Literature & Specifications

- **literature.md** (450 lines): Comprehensive technical survey with validated sources, verified open data, and unresolved research gaps flagged
- **prototype specs.md** (414 lines): Detailed 18-item verification queue for unvetted coefficients; refer to this when flagging TODOs

## Architectural Rationale

**Domain decomposition (near-field SPH + far-field 2D SWE)** is chosen over full-3D SPH because:
- Violent near-field (hundreds of metres, tens of seconds) benefits from adaptive resolution in SPH
- Far-field (tens of kilometres, hours) is well-captured by depth-averaged shallow water with much lower cost
- Follows Maranzoni & Tomirotti (2023)'s review recommendation and SPH community best practices

**Tier-1 instrument framing**: JalRaksha is positioned as a rapid screening and prioritisation tool against CWC's own guidelines, not a replacement for Tier-2/3 detailed surveyed studies.

**India-specific validation**: Chamoli 2021 is the only publicly available Indian dam-break event with rigorous pre- and post-event DEMs and published benchmarks.

## Code Style Notes

- Prefer explicit variable names over shorthand (e.g., `depth` not `h`, `velocity_x` not `u`)
- Comment all numerical assumptions (e.g., "Manning's n = 0.03 assumed for concrete spillway")
- Every coefficient must have a source citation in the code
- Use metric units throughout (m, s, m³/s, kg/m³)

## Gotchas & Common Traps

1. **Unvetted coefficients**: Check `prototype specs.md` before hardcoding any breach regression, fatality rate, or depth-damage value. Flag with TODO if source is not primary literature.
2. **DEM artifacts**: 30 m Copernicus GLO-30 has interpolation artifacts near cliffs and water bodies. Pre-process with edge detection before routing.
3. **Coordinate systems**: Always verify metric CRS (EPSG:32643 for India or equivalent UTM). Never mix degrees and metres in the solver.
4. **SPH coupling**: One-way handoff only (SWE → SPH at breach time). No two-way feedback in current scope.
5. **Demo-day network**: Assume offline operation. Cache all data locally on first fetch.
6. **Licensing**: Check `prototype specs.md` for approved vs forbidden data sources.

## Repository layout

Every phase in the build order above is implemented. The tree below is the real
one as of 2026-09-11; it replaces an August "Project Setup Progress" block that
still listed most modules as Phase stubs.

```
jalraksha/                 core library
├── api.py                 rapid analytic estimate (no solver) + legacy HTTP handler
├── cli.py, config.py      CLI entry point and config validation (Phase 0)
├── cache.py, dem.py       DEM tile cache and Copernicus GLO-30 fetch (Phase 0)
├── presets.py             dam and blockage-site presets
├── run.py                 end-to-end dam-break / blockage pipeline (Phase 4)
├── hardening.py           input validation and error types
├── solver/                2D SWE: types, flux (HLLC + Audusse), core, parallel ensemble,
│                          backend (cpu | cuda), flux_cuda / engine_cuda / ensemble_cuda
├── terrain/               conditioning, domain, breach regressions, natural_dam,
│                          blockage (barrier burn), dem_update, roughness
├── export/                geotiff (COG), shapefile, kml, keyframes, xdmf_export,
│                          matlab_export, georef
├── impact/                hazard (FD2320), population (PAR), damage, fatality
├── gee/                   Earth Engine: auth, sar, blockage_detect, terrain_correction,
│                          population (GHSL), built_up, worldcover, grid_fetch
├── delft3d/               Deltares D-Flow FM: setup, dfm_model, runner, ugrid, comparison
├── sph/                   near-field WCSPH: domain, core, coupling, pysph_runner
└── validation/            metrics, benchmarks, delft3d_benchmark, sensitivity

services/api/jalraksha_service/   FastAPI backend: main (routes), tasks (run pipeline),
                                  run_worker (subprocess runs), script_runs, db, schemas
frontend/src/                     React + Vite dashboard: App, api.js, hazard.js,
                                  panels/ (11 tabs and panels), state/SimulationClock
scripts/                          long runs and maintenance (run_blockage, drainage check,
                                  validate_against_delft3d, register/backfill, run_api)
paraview/                         ParaView render pipeline (static, animation, cameras)
tools/                            sih-presentation/ decks, architecture diagrams,
                                  cesium/ terrain tiles, matlab/, paraview/ dataset builders
tests/                            32 test modules + conftest.py
docs/                             validation_findings, dashboard_integration, progress,
                                  DECISIONS, VERIFICATION_LOG, the Technical Reference
                                  Manual; archive/ holds dated status snapshots
```

**Skills** in `.claude/skills/`: `verify-jalraksha`, `build-phase`,
`improve-architecture`, `code-quality-deep-dive`, and `developing-with-streamlit`
— the last is a leftover, since the Streamlit dashboard was removed.
`build-phase` checks `.phase_N.complete` marker files; they are local build
state and have been git-ignored since `94a994e`, so a fresh clone has none.

**Hooks** (`.claude/settings.json`): ruff auto-format on Write/Edit, and a
warning on forbidden data sources before Bash. Note that `pyproject.toml`'s
ruff config lists `W503`, which ruff does not recognise, so ruff currently fails
to load it and the format hook does nothing until that entry is removed.

## Architecture Rules (Deep Modules Principle)

These rules ensure the codebase stays navigable and testable as it grows across 18 phases.

### 1. Module Depth (Functionality vs Interface)
Each module should have **high functionality relative to interface complexity**:
- **Deep**: CLI accepts `jalraksha run --dam tehri`, internally handles DEM fetch, config validation, cache setup (simple interface, lots of work)
- **Shallow**: 3 small functions scattered across 5 files that do nearly the same thing (complex interface, little work)

### 2. Dependency Direction (No Backwards Imports)
Phases build on earlier phases only:
- Phase 0 (`jalraksha.config`, `.cli`, `.cache`, `.dem`) → no dependencies on Phase 1+
- Phase 1 (`jalraksha.solver`) → may depend on Phase 0, but NOT Phases 2+
- Phase 4 (`jalraksha.terrain`, `.breach`) → may depend on Phases 0–3, but NOT Phases 5+
- **Violation**: Phase 1 importing Phase 5 export logic = circular, hard to test

### 3. Layer Isolation (Seams)
Each phase has a clear seam (boundary) with the next:
- **Phase 0 ↔ Phase 1**: CLI passes config to solver; solver returns results
- **Phase 1 ↔ Phase 2**: Solver produces raster; Phase 2 reads raster for terrain conditioning
- **Violating example**: Phase 1 calling Phase 5 GeoTIFF writer directly (no buffer)

### 4. Test Co-Location (Locality)
Tests live next to modules they test:
- `tests/test_cache.py` imports `jalraksha.cache`
- `tests/test_solver.py` imports `jalraksha.solver.core` (NOT through CLI or export)
- **Anti-pattern**: Tests importing from main entry point (forces everything to load)

### 5. Configuration Isolation
Configuration is data, not code:
- Unvetted coefficients live in `jalraksha/config.py` (not hardcoded in solver)
- Manning's n, breach regression params flagged with `# TODO: UNVETTED — source?`
- Each param must have a source citation

### 6. Reusability (SPH Independence)
SPH (Phase 7) must be independent of SWE (Phase 1):
- Phase 7 can import `jalraksha.solver.types.State`, but NOT `jalraksha.export`
- One-way handoff only: SWE produces raster → SPH reads raster (no bidirectional coupling)
- If you remove Phase 5 (export), SPH still works

### 7. Documentation Locality
Each module is self-documenting:
- `jalraksha/cli.py` docstring explains Phase 0 CLI contract
- `jalraksha/solver/__init__.py` lists gating tests (Ritter, Stoker, Thacker)
- `tests/conftest.py` explains fixtures (temp_cache_dir, sample_config)

### 8. Separation of Concerns
Presentation, solver, and export are in separate trees:
- **Solver logic**: `jalraksha/solver/`
- **Export logic**: `jalraksha/export/`
- **Presentation/tooling**: `tools/sih-presentation/`
- SIH deck build can fail without breaking solver tests

### Enforcement
- **CI gate**: Import graph must be acyclic (no Phase 5 importing Phase 0 for a solver thing)
- **Code review**: `/code-quality-deep-dive` checks for layer violations
- **Architecture audit**: `/improve-architecture` surfaces shallow modules before they grow

## Dashboard — every module reaches the browser

Full record: `docs/dashboard_integration.md`. The demo-critical facts:

- **Tabs**: 2D+3D · Gauges · Ensemble · Impact · SPH · Comparison · Validation ·
  Downloads. Panels stay MOUNTED and are hidden with CSS — switching tabs used
  to tear down and rebuild the Cesium viewer and Leaflet map every time.
- **Run picker** (`GET /runs`) loads any completed run instantly. This is the
  offline demo path; it replaced typing a 32-character hex id by hand.
- **Earth Engine is live.** `JALRAKSHA_GEE_PROJECT=sih-prototype-506812`, set in
  `scripts/run_api.py` because `.claude/launch.json` has no env field. Both the
  Sentinel-1 overlay and GHSL population-at-risk depend on it.
  - For Khadakwasla the SAR fetch retrieves a real scene and then REFUSES it
    (precision 0.486 vs JRC, below the 0.5 gate). That is the quality guard
    working, not a bug — say so if it comes up in the demo.
  - No synthetic overlay is ever produced. An earlier spec asked for one; it was
    not built, and `GeoSarResponse`'s "there is no fourth state" rule stands.
- **Validation tab** runs the blocking gates against the live build, mirroring
  the CI tests exactly: lake-at-rest 5.98e-14 m/s, mass conservation 0.000000%,
  Ritter RMSE 0.0317 m (JalRaksha) vs 0.0349 m (Delft3D FM).
- **Delft3D now genuinely runs.** `setup.py`'s NetFile was unreadable by D-Flow
  FM, so the kernel failed at mesh load every time and silently fell back;
  `dfm_model.py` is used instead, and `*_his.nc` is read for real gauge
  arrivals. `solver="delft3d"` used to call `rapid_estimate` and never touch
  the kernel at all.
- **`solver="sph"`** runs the full SWE pipeline AND the near-field handoff. It
  is not an alternative solver: ~600 m over 15 s, and it can never reach a
  downstream gauge.
- **Cesium terrain is configured.** The Ion token lives in
  `frontend/.env.local` (git-ignored — a fresh clone must re-create it, or the
  globe falls back to Cesium's default token with no terrain).
  `vite.config.js` must use `loadEnv`, NOT `process.env` inside `define`: the
  latter reads only the shell environment and, being a text substitution,
  silently overwrites whatever Vite loaded from `.env.local` with empty strings.
- **Runs execute in a SUBPROCESS**, not a thread
  (`services/api/jalraksha_service/run_worker.py`). A dam-break run is CPU-bound
  and holds the GIL — the flux kernels are `@njit` without `nogil=True` — so an
  in-process thread starved uvicorn and `GET /validation` returned nothing after
  120 s. With the subprocess, every endpoint answers in ~0.21 s while a run is
  actively solving. `--broker` still switches to a real Celery worker.
- **Progress is real.** `run_dam_break_ensemble` and `run_ensemble` take a
  `progress_cb`, and a `phase` string travels with the percentage, so the
  dashboard shows "Solving member 12/30" instead of a frozen "running 5%".
- **SPH runs only for `solver="both"`.** It used to run for `delft3d` too, via
  `_run_comparison`, which is what made a Delft3D run take ~20 minutes. It now
  takes **47 seconds**.
- **ParaView uses each dam's own preset** (`vertical_exaggeration`,
  `nominal_depth_m`). These were hardcoded to 1.5 / 25.0 for every dam, which
  rendered Khadakwasla — 1,170 m of relief across 54 km — as a near-flat plate.
  `main.py` is in the `.pvsm` staleness check, so changing those arguments
  invalidates cached states.
## River blockage (landslide dam) and the observation-conditioned DEM update

Half the events PS-26161 names are natural blockages, not dam failures. The
`river_blockage` scenario models one properly; `river_overflow` is still a
screening pulse and says so.

- **A landslide dam has no published storage, so it is measured.**
  `jalraksha/terrain/blockage.py` burns the barrier into the bed, PROVES it spans
  the valley (fill, count `downstream_leak_cells`, widen and retry, refuse after
  8 doublings), and reads an elevation-area-capacity curve straight off the
  result. `breach._synthesize_blockage_ensemble` REFUSES a run whose
  `storage_source` is absent or user-supplied — without that check a dashboard
  slider silently drives the outburst volume again the first time somebody
  refactors, and the output still reads as a modelled result.
- **Costa (1985) is the only active regression** on this path: it is the one
  transcribed equation whose fitting population included natural dams. Walder &
  O'Connor (1997) and Peng & Zhang (2012) are implemented in shape and
  quarantined pending coefficient transcription, exactly as Xu & Zhang is.
  Peng & Zhang needs a deposit VOLUME and WIDTH, which only the burned geometry
  can supply — the two features are coupled, not bolted together.
- **The spread comes from the prediction band.** A dam-break ensemble gets most
  of its spread from four equations disagreeing by 3–4×; with one family there is
  no such term, so members are sampled across `NATURAL_DAM_LOG_CYCLES`. Those
  widths are UNVETTED placeholders chosen only to exceed Wahl's embankment bands.
  Quote the range, never a single discharge.
- **The dam-class flag INVERTS.** An embankment is in-population for a dam break
  and out of it for a landslide-dam outburst. Reporting one sense with the other
  scenario's explanation would be the right warning attached to the wrong reason.
- **"Rebuild the DEM from satellite imagery" is not achievable on this data
  policy, and the code says so where it would be edited.** Stereo pairs are
  geo-fenced or commercial; Earth Engine carries S1 GRD, not SLC. What ships is
  an **observation-conditioned DEM update**: GLO-30 with a barrier burned in,
  written as a new GeoTIFF carrying `JALRAKSHA_NOT_A_SURVEY`. Every product and
  the dashboard banner say it is not photogrammetry.
- **Delta-add, never a reprojection round trip.** Only the CHANGE is reprojected
  back onto the source raster, so every pixel outside the barrier footprint stays
  bit-identical to Copernicus — asserted by a test.
- **Updated DEMs live in `data/dem/updated/`, never the cache root.**
  `cache.get_cached_dem` ends in a sorted glob over `dem_{lat}_{lon}*.tif`;
  `dem_..._blockage.tif` sorts ahead of `..._clipped.tif` and would silently
  become the DEM for every run at that location, dam-break runs included.
  Filenames are content-addressed (barrier geometry + scene id + source DEM MD5)
  — there is no TTL anywhere in this repo and there should not be one.
- **`_resolve_dem` is NOT modified.** `tasks._resolve_dem_for_run` wraps it and
  returns the updated path explicitly; a new file in its search path is exactly
  how the Bhakra-over-a-Pune-tile failure happened.
- **A tile cache hit is not coverage.** Tiles are fetched as WINDOWS but cached
  under the full tile's URL, so the tile fetched for Tehri (lon 79.000–79.105)
  was a confident hit for a Rishi Ganga domain at lon 79.70 and then died inside
  `rasterio.mask` with "Input shapes do not overlap raster". `dem.py` now checks
  the cached bounds and re-fetches the UNION, so a tile only ever grows and no
  earlier domain loses coverage.
- **A square domain needs a clip √2 wider than its radius.** The solver domain is
  a square in UTM, the clip a rectangle in degrees, so the corners fall outside.
  Measured: an 18 km domain on an 18 km clip ran 11.3% on nearest-neighbour fill
  and reported a lake 2.5× too large. Rishi Ganga's 18 km domain is staged from a
  26 km clip, and `test_presets.py` asserts the diagonal.
- **Auto-detection refuses over the Rishi Ganga, and that is a result.**
  `gee/blockage_detect.py` differences a pre-event median against a SINGLE
  post-event scene (a composite would make "rebuilt from the 2021-02-08 scene"
  untrue) and applies `MIN_JRC_PRECISION` to the PRE scene, never to the
  difference — a lake that formed last week is definitionally absent from a
  32-year permanent-water product, so that gate on the difference would reject
  every true positive. Measured live: JRC permanent water covers **0.001%** of
  the Raini window against 0.57% at Tehri and 44.5% at Hirakud, so there is
  nothing to verify a same-day mask against and the detector declines. Do NOT
  widen the threshold. The manual barrier path runs fully offline and is the
  demo's guaranteed floor.
- **Auto-detection's root cause was radar shadow, and the fix is now built —
  but NOT re-measured.** Run against the Baige barrier lakes on the Jinsha River
  (10 Oct and 3 Nov 2018) — a wide channel where JRC maps the river at 0.52%,
  with the lake plainly visible in cloud-free Sentinel-2 and three S1
  acquisitions inside its ten-day life — the detector refused, and not for lack
  of a reference: the pre-event mask classified **63% of the gorge as water**
  (precision 0.0075, recall 0.92) because VV backscatter cannot separate water
  from radar shadow on slopes facing away from the sensor.
  `derive_threshold_from_tiles` was confident while doing it: 17/64 tiles at
  separability 0.732. **Gate 1 was the symptom, not the limit.**

  `jalraksha/gee/terrain_correction.py` implements the documented remedy — the
  local incidence angle from Copernicus GLO-30 and the scene's own geometry,
  with shadow and layover dropped BEFORE any histogram is derived (Small 2011).
  Both `sar._fetch_live` and `blockage_detect._fetch_live` apply it. **This is
  the GEOMETRIC half only**: pixels are masked, not radiometrically flattened to
  gamma-nought, so anything published says "geometry-masked", never
  "terrain-flattened".

  **IT WAS RE-MEASURED, AND IT DOES NOT RESCUE THE DETECTOR. Do not present it
  as the fix.** Over Baige the mask excludes 16.6% of the window and moves Gate 1
  precision from 0.0075 to **0.007** against a 0.5 requirement, while recall
  falls 0.92 to 0.85. Every case still refuses. The reason is in the geometry
  itself: **radar shadow is 0.09% of that window**, so shadow was never numerous
  enough to be the explanation. The mis-classified pixels are on slopes that
  image perfectly well and are merely dark, which is a RADIOMETRIC problem —
  the gamma-nought flattening half, not built, and at 140 false positives per
  true one there is reason to doubt it would suffice either. Full table in
  `docs/validation_findings.md` §9. The masking stays because excluding layover
  is correct on its own terms and any radiometric correction needs the same
  geometry underneath it: a prerequisite that turned out not to be sufficient.

  **`setDefaultProjection` is load-bearing and its absence is invisible.**
  `ImageCollection.mosaic()` returns EPSG:4326 with the IDENTITY transform — one
  degree per pixel, nominal scale 111,319 m — and `ee.Algorithms.Terrain`
  computes slope in its input's own projection. So the first version of this
  module measured slope 0.000° over a Himalayan gorge, classified nothing,
  returned `valid_fraction` of exactly 1.0000, and reported that it had terrain
  corrected the scene. Declaring GLO-30's native 30 m posting gives 30.8° mean /
  66.0° max on the same window. A no-op and a working correction produced nearly
  identical detector output, so the precision figures could not distinguish them
  — only measuring the mask itself could. `test_terrain_correction.py` asserts
  the projection is declared, in both this module and `blockage_detect`.

  Two supporting facts worth keeping. `local_incidence_angle` returns the
  UNSIGNED arccos angle, and arccos is even, so it cannot tell a sensor-facing
  slope from an averted one — a 50° slope facing a 39° look reported +11° where
  the signed answer is −11°, and layover was therefore never detected at all.
  Shadow and layover are classified from the SIGNED range-plane slope
  (`range_slope`) instead. And `blockage_detect` now restricts the pre-event
  median to the post scene's own pass and relative orbit: an ascending and a
  descending pass illuminate opposite valley walls, so differencing across
  tracks puts a shadow-to-lit transition in the "new water" band on every slope
  in the scene.

  Measurements, imagery and the Gate-1-bypass diagnostic remain in
  `docs/validation_findings.md` §9. `scripts/detect_blockage_experiment.py`
  writes ONLY under `data/gee/blockage_experiment/`, never the app's
  `data/gee/blockage/`, because `detect_new_water` writes a
  `blockage_manifest.json` that `_read_cache` would later serve back as a
  genuine observation.
- **The two dead gates now execute, and the area floor is PER COMPONENT.**
  `MIN_NEW_WATER_AREA_M2` was declared and never referenced;
  `score_candidate_flatness` — "the strongest filter and it is free" per the
  module docstring — was never invoked. Both run now. The area floor is applied
  to each CONNECTED component (`connectedPixelCount`), not to the window total,
  and that distinction is the whole point: over Baige a garbage mask cleared a
  window-total floor by 900× *precisely because* its mis-classified pixels were
  scattered everywhere, whereas a lake is one patch. Flatness reads GLO-30 from
  inside the Earth Engine call — not the layering violation row 28 feared, since
  an EE asset is another EE image and not a call into `jalraksha.terrain` — and
  both halves decide through one shared `flatness_verdict()` so the tested path
  and the live path cannot drift. With Gate 1 bypassed for diagnosis, flatness
  refused every case by **186× on elevation spread** (933–3,258 m vs 5 m) and
  16× on slope. `MAX_PLAUSIBLE_WATER_FRACTION` is applied here too; it never was.
  The four threshold VALUES remain unvetted — that is row 25, not row 28.
- **Rishi Ganga publishes no crest height or width.** Neither is published for
  the 2021 blockage; both are measurable by differencing Zenodo 4554647 against
  4558692 (verification queue row 26). The preset carries a terrain-derived
  `suggested_barrier_*` at the deepest gorge cell in the domain, labelled as
  terrain-derived so nobody reads it as the surveyed deposit location. Its own
  note corrects the problem statement: Chamoli was a rock-and-ice avalanche, not
  a GLOF, though a blockage did form.
- **Rishi Ganga's corridor names no town.** Published town coordinates for
  Rishiganga and Tapovan sat 1,319 m and 79 m ABOVE the nearest channel — the
  pipeline's own `_no_arrival_reason` caught it and said "a town centre, not a
  riverside gauge" — and snapping to the lowest cell within 2 km
  still left Rishiganga at 2,851 m. Two of them are hill towns genuinely hundreds
  of metres above their rivers, so they answer a different question from the one
  a gauge asks. What ships instead is three DEM-traced thalweg points at stated
  along-channel distances, each labelled TERRAIN-DERIVED. The published HEC-RAS
  figures (Rishiganga 7,908–7,975 m³/s at 19.85 m; Tapovan 5,780–5,957 m³/s at
  18.15 m) become a real validation comparison the moment someone sources
  channel coordinates — that is the strongest evidence this scenario could carry.
- **A minority arrival is labelled as one.** One member in four reached 15 km
  downstream, so the "arrival time" was a single realisation, p05 and p95
  collapsed onto it — a zero-width band that reads as high confidence — and the
  peak depth beside it showed 0.0 m, because the ENSEMBLE MEDIAN of `h_max` there
  is median{0,0,0,d}. Depth now comes from the members that actually arrived, and
  `_minority_arrival_note` says "1 of 4 members" below half.
- **Scale sanity, measured at the Dhauliganga gorge below Tapovan** (1,704 m bed,
  1,200 m of relief): crest 55 / 90 / 120 / 150 m impounds 0.6 / 6.3 / 26.0 /
  60.8 MCM. A 55 m barrier there produces a local surge that reaches no gauge in
  an hour, which is the honest answer for a deposit that size on a reach that
  steep — not a broken run.
- **DEMO-DAY COST WARNING.** Compute scales badly with barrier size on steep
  terrain. The 55 m / 0.6 MCM case solved 4 members in about 15 minutes at 100 m
  over a 36 km box; the 120 m / 26 MCM case was still on its first member after
  the same wall time, with every worker pinned. The CFL limit is doing it: a
  deep release down a 1,200 m-relief gorge reaches velocities that cut the
  timestep to a fraction of a second. Pick a modest barrier or a short
  `solver_duration_s` for a live demo, and pre-compute anything larger — the run
  picker loads a finished run instantly.

- **Runs predating this work** have no ensemble statistics, no p05/p95 arrival
  band and no per-gauge peak depth — those fields did not exist when they were
  written, and they render as blanks. New runs are complete.

## A run can now be durable AND visible at the same time

These were mutually exclusive, and the trade cost real work.

- **Dashboard-submitted runs died with the server.** `_spawn_run_subprocess`
  used a plain `Popen`, so the worker was an ordinary child of uvicorn. Three
  runs were lost that way in one session, hours of compute each, because
  `run_ensemble` returns every member at once and writes nothing per-member.
- **Script-launched runs were invisible.** They survived anything — one outlived
  several API restarts across a 5 h solve — but nothing called `db.create_run`,
  so `GET /runs` could not list them and the dashboard could not load them.

`services/api/jalraksha_service/script_runs.py` closes the second half:
`registered_run(...)` is a context manager giving a script the same lifecycle
`tasks.py` performs. Three things in it are load-bearing and each fails
silently if dropped.

- **`record_worker_pid` before any status write.** The API runs
  `mark_stale_runs_failed()` at startup, which marks every `running` row failed
  unless a LIVE pid is recorded. Register a long run at start without it and the
  next API restart kills the row of a run that is still solving — defeating the
  exact durability scripts exist for.
- **`os.chdir(REPO_ROOT)`.** `DATABASE_URL` and `DATA_DIR` are both RELATIVE.
  A script started elsewhere silently creates a second, empty database.
- **Artifacts go in RUN-ID directories.** `_to_file_url` serves a path only if it
  resolves under `DATA_DIR`, and the frontend resolves each `png_url` as a
  SIBLING of the manifest, so frames and manifest cannot be separated.

**The contract for "listed and playable" is four things, and three of them fail
looking like something else:** status EXACTLY `"done"` (else 409, reads as
"still going"), `export_count > 0` (else silently absent from the picker), a
`keyframe_manifest` export whose file exists under `DATA_DIR` (else the run
lists and shows no imagery), and every gauge row with non-null `gauge_name` and
`distance_km` (else the whole result 500s). `tests/test_script_runs.py` pins all
four.

**`gauge_rows_from_result` and `write_run_summary` are SHARED with `tasks.py`,
not copied.** Two versions would eventually disagree about what a minority
arrival is, and that note is what stops "1 of 4 members arrived" reading as a
confident median.

**On Windows, `DETACHED_PROCESS` is not enough** — it detaches from the console
but NOT from a Job Object, and a harness that runs the API in a job with
kill-on-close takes the worker down with it. Measured: a worker died mid-export
at 92%. `CREATE_BREAKAWAY_FROM_JOB` is what actually escapes, and it fails
outright where the job forbids breakaway, so the dispatcher retries without it
and SAYS so rather than turning "your run died" into "your run never started".
Verified: with the API killed outright, a run reached `done` with 22 exports and
7 gauges while nothing was serving.

Output goes to `data/runs/<run_id>.log` because a detached child has no console
to inherit — better than the old shared API stdout, since it survives the server
and belongs to one run.

`scripts/register_script_run.py` backfills a finished tag-named run without
re-solving. It MOVES the directories rather than copying (two divergent 50-file
trees help nobody) and marks status `done` LAST, so a half-registered run is
never briefly listed as complete — which is what saved the first attempt when it
crashed partway.

## Friction, and a legend that was shifted by one

`terrain/roughness.py` maps ESA WorldCover classes to Manning's *n*. Two
independent defects were live in it at once, and each hid the other.

- **Every class was labelled as the one below it.** 10 was commented
  "Shrubland" (it is Tree cover), 40 "Built area" (Cropland), 50 "Bare / rock /
  sand" (Built-up). So **built-up land — the roughest class, and the one that
  most shapes an inundation footprint — was assigned n = 0.01**, the value for
  smooth concrete, while cropland got the urban value. Class 100 (Moss and
  lichen) was missing entirely. The legend is now ESA's published one.
  `test_roughness.py` asserts the ORDERING (built-up > bare, trees > grass,
  ice < grass) rather than the numbers, so a re-shifted legend fails even after
  the values are revised. The eleven **n values stay UNVETTED** — mid-range
  transcriptions of Chow (1959) Table 5-6 and Arcement & Schneider (1989) onto a
  legend both predate, with no published crosswalk cited. Verification row 31.
- **And nothing read the table anyway.** `assign_manning_from_worldcover`
  ignored its arguments and returned a uniform 0.03;
  `preprocess_dem(manning_table=...)` accepted a table, passed it one level down,
  and dropped it. A caller who built a careful roughness table got a constant,
  silently. The reprojection is real now (NEAREST NEIGHBOUR always — these are
  class codes, and interpolating cropland 40 against built-up 50 gives 45, which
  is not a land cover), and **a `manning_table` passed without a
  `worldcover_path` now RAISES** rather than being ignored.
- **The old signature is why it could not have worked.** It asked for
  `grid_shape`. A shape says how many cells there are and nothing about where
  they are; land cover cannot be placed on a domain without its transform and
  CRS. It takes a `Grid` now.
- **A uniform field is still the default, and says so.**
  `manning_field_summary` reports `is_uniform` and `fraction_at_default`,
  because a uniform field wearing a land-cover-derived name is the exact failure
  this module shipped with. `gee/worldcover.py` fetches the raster (ESA
  WorldCover v200, CC BY 4.0 — approved) with the same three-states-no-fourth
  refusal contract as `sar.py`.

## FD2320 had five definitions in this repo, and two live ones disagreed

Full record: `docs/validation_findings.md` §10. `jalraksha/impact/hazard.py`
declares itself "the SINGLE source of truth for hazard classification" and was
neither single nor self-consistent — a depth-band table in the code one full
class COARSER than the docstring above it, the published continuous rating in
the same file reachable only from tests, a fourth table inlined in
`export/shapefile.py`, and a fifth in the frontend's gauge badge.

- **Velocity could only ever REDUCE hazard.** The band table tested
  `velocity <= max_velocity` as one term of an AND with the depth window, so a
  cell exceeding a band's ceiling fell OUT of that band without being promoted.
  A flow **3 m deep at 8 m/s matched no band and was reported DRY.** Latent —
  `classify()` had no non-test caller — but it was the velocity-aware path.
- **Two live tables disagreed on real output.** A cell 1.5 m deep was *moderate*
  on the dashboard and *high* in the exported shapefile, both labelled FD2320.
- **One definition now, and it is the published one.**
  `HR = depth * (|V| + 0.5) + DF`, classed at 0.75 / 1.25 / 2.5.
  `HazardClassifier` computes it; `export_hazard_classification_polygons` calls
  the same classifier instead of its own masks; the gauge badge mirrors the
  depth-only reduction (`HR = 0.5d + DF`, edges at **0.5 / 1.5 / 4.0 m**).
- **`severe` is retired.** FD2320 publishes FOUR wet categories and no boundary
  that would split extreme. Inventing one is what `natural_dam.py`'s own policy
  forbids. `hazard_summary`, the shapefile class names (`medium`/`high` →
  `moderate`/`significant`) and the frontend level lists all follow.
- **The debris factor is a categorical input, not a constant.** The trailing
  `+ 0.5` was hardcoded; DF is published as 0 / 0.5 / 1.0 by land use. It is a
  named parameter now, defaulting to 0.5 and echoed in every summary payload.
  Land cover is deliberately NOT consulted to choose it — that mapping belongs
  beside the WorldCover legend and does not exist.
- **`hazard_weights` stays UNVETTED.** FD2320 publishes classes, not a weighting
  between them, and `weighted_hazard_index` reaches the payload.
- Every hazard class count written down before this change — the tables in the
  drainage section above, `docs/validation_findings.md` §8, and
  `hazard_series.json` for existing runs — is not reproducible and is **not
  retroactively reclassified**, the same precedent as the 25× population
  undercount. `run_khadakwasla_drainage_check.py` folds an old run's `severe`
  count into `extreme` so a stored series still reads.

## `PopulationEstimator` returned zero people, always

`jalraksha/impact/population.py`'s settlement-type estimator was deleted rather
than repaired. Its lookup keys were the strings `"village"`/`"town"`/`"city"`
while the settlement grid it documented — and the one its own synthesiser
produced — held integers 0/1/2, so the membership test could never fire and the
density array stayed all zeros on every input it could be given. Two more
defects sat in the same call: the PAR denominator re-hardcoded a 200 m cell,
discarding the caller's resolution (the exact bug its own docstring claimed to
have fixed), and the exposure loop summed four NESTED depth thresholds, counting
a 2 m-deep cell four times. It had no caller outside its own tests, and
`tasks.py` already uses `compute_par` / `compute_population_exposure`.

Separately, `compute_par` gated on `arrival_time_grid > 0`, which silently
dropped every cell wet at exactly t = 0 — the breach cell and its neighbours,
i.e. the population with the LEAST warning of anyone in the domain. `isfinite()`
is what rejects the never-wet `inf` sentinel; the bound is `>= 0`.

## Three smaller defects closed in the same pass

- **An all-nodata DEM produced a silently all-NaN bed.**
  `conditioning.interpolate_dem_to_grid` took its fill value from `np.nanmean`,
  which returns NaN over an all-NaN array (a warning, not an error). That NaN
  became the interpolator's `fill_value` AND the replacement in the closing
  `np.nan_to_num`, so the sanitiser replaced NaN with NaN. It now averages the
  finite cells and RAISES when none are finite — the older fallback substituted
  a literal 100.0 m flat bed, which runs to completion and produces a
  plausible-looking wrong map. The bare `except Exception` around the
  interpolator is gone with it, so a genuine interpolation failure surfaces
  instead of becoming a flat bed.
- **`sph/coupling.py` divided by an unguarded breach width.** `u = Q/(h·w)` had
  a guard on `h` and `Q` and none on `w`, a plain default parameter — while the
  identical relation in `pysph_runner.py` was guarded. Both factors are guarded
  now, and `extract_sph_free_surface` validates `grid_res_m > 0` (a negative
  value returned an empty (0,0) grid with no error).
- **`XU_ZHANG_2009_VERIFIED` gated nothing.** The function never read the flag,
  and `synthesize_breach_ensemble` took `regression_families` verbatim, so
  `regression_families=["xu_zhang"]` produced a full ensemble from a model that
  over-predicts Teton by 5.5× on its own back-check, indistinguishable from a
  verified one. The function still RETURNS a value — a documented decision so
  direct callers do not break — so the gate lives at the ensemble:
  `REGRESSION_FAMILY_ALIASES` refuses an unknown name (the dispatch used to fall
  through to Froehlich, so a typo silently changed the equation) and
  `UnverifiedRegressionError` refuses a quarantined one without
  `allow_unverified_regressions=True`. `ensemble_statistics` now carries
  `unverified_regressions` up to the payload the way `dam_class_note` does.

## A fatality model was running under another author's name

`impact/fatality.py::estimate_loss_of_life_jonkman` documented
`F(d,v) = Φ((ln(d·v) − μ)/σ)` — Jonkman's log-normal — and has never computed
it. The body is a saturating exponential in the depth-velocity product with four
shape constants and two caps that come from nowhere.

- It is renamed **`estimate_loss_of_life_depth_velocity`**, and returns `model`
  and `model_is_published: False` so a report cannot misattribute it by reading
  the key it arrived under. The old name survives as a `DeprecationWarning`
  alias, because renaming a public function is not worth breaking callers over.
- The real model is present in SHAPE as `estimate_loss_of_life_jonkman_2008` and
  **quarantined behind `JONKMAN_2008_VERIFIED = False`**, exactly as
  `natural_dam.py` quarantines Walder & O'Connor and Peng & Zhang. Each hazard
  zone has its own (μ, σ); applying the wrong pair changes a casualty estimate
  by an order of magnitude while still producing a plausible number.
- **DeKay & McClelland (1993) is absent.** It was cited in the module docstring
  for a long time and never implemented (verification row 11). The docstring now
  says so. Quote Graham (1999) for a defensible figure; the depth-velocity form
  is an ordering of cells by hazard, not a casualty count. Verification row 32.

## Flood water must be able to leave the domain

A 24 h Khadakwasla run once peaked at t ~ 17,876 s and then never receded — 46
cells stuck at SEVERE for the last 7.5 simulated hours, ~42% of released volume
permanently trapped. None of it was hydraulics. Three defaults now exist because
of it, and turning any of them off brings the plateau back. Full measurement in
`docs/validation_findings.md` §8.

- **`notch_breach=True` — a failed dam must have an actual gap.**
  `inject_breach_hydrograph` only ADDS depth at one cell: a source term with no
  momentum direction, on a bed where the DEM's intact crest still stands. Water
  spreading back upstream lands in the real reservoir bowl and sits there.
  `run.py::_notch_breach_into_bed` lowers the bed to the dam-height invert
  (crest minus `height_m` — the one breach-geometry number every member carries,
  and what Froehlich / Von Thun assume for a full-depth breach), clamped never to
  dig below the local terrain floor just outside the footprint, so it can only
  open a path to terrain that already exists. `height_m` is a fixed ensemble
  input, so there is ONE notch shared by every member, like the terrain itself.
- **`fill_max_depth_m=3.0` — fills resampling noise, NOT real basins.** Bilinear
  downsampling of a narrow channel manufactures local minima that exist only in
  the resampled raster, and the solver's own water pools in them forever. The
  fill is a priority-flood seeded from the DOMAIN BOUNDARY — the transmissive
  boundary is the only place water can actually exit, so it is the only valid
  sea level — with the raise per cell then CAPPED. A one-metre pit fills
  completely; a reservoir bowl keeps standing at nearly its original depth. Do
  not raise this to "guarantee drainage": erasing genuine terrain hides the
  defect behind a nicer graph.
- **`domain_margins_km` — a dam-centred square is the wrong shape.** A 54 km box
  on Khadakwasla spends half its cells on the Western Ghats and the Arabian Sea
  while the flood runs east down the Mutha to the Bhima. The asymmetric extent
  (`load_dem_as_grid(margins_km=...)`, `RunRequest.domain_margins_km`) biases the
  domain downstream. It is a PER-REQUEST override — `presets.py` still gives
  every default Khadakwasla run, dashboard demo included, the same 27 km
  dam-centred square. The cached DEM was widened to 240 x 188 km as a superset,
  so nothing that worked before stopped working.

**Long runs belong in `scripts/`, not `POST /runs`.** An API-submitted run
executes in a subprocess spawned by the server and dies with it — three runs
were lost that way in one session, each discarding hours of compute, because
`run_ensemble` returns every member at once and writes nothing per-member.
`scripts/run_khadakwasla_drainage_check.py` calls the same pipeline directly and
survives the server restarting. **Its confirmation runs have now completed — see
the next section, which supersedes the "not yet re-measured" status this
paragraph used to carry.**

## The plateau was VOLUME-limited, and the flood now drains

Five confirmation runs later, the mechanism fixes of the previous section were
necessary and not sufficient, and the reason was not the one being looked for.

**Three runs on the wide domain all plateaued identically.** Read them from
`data/keyframes/<run_id>/hazard_series.json`. Every per-class count in this
section PREDATES the FD2320 unification below and is not reproducible by a new
run — the `sev` column names a class that no longer exists. The hydraulics are
untouched, so wet extent, `exited_mcm`, `retained_fraction`, arrival times and
the recession shape all stand; only the class labelling changed.

| run | domain | Δx | duration | members | wall clock | final low/mod/sig/sev/ext | wet severity | `exited_mcm` |
| :--- | :--- | ---: | ---: | ---: | ---: | :--- | ---: | ---: |
| `48f7ac59` | full 40/200/94/94 | 500 m | 24 h | 4 | 3,867 s | 6/21/39/26/1 | 0.518 | −8.5e−14 |
| `1d3d3c45` | full 40/200/94/94 | 300 m | 24 h | 4 | 18,047 s | 11/45/98/58/15 | 0.551 | −4.4e−13 |
| `e5485691` | mid 12/105/45/45 | 500 m | 48 h | 2 | 827 s | 62/21/39/25/1 | 0.358 | +2.7e−13 |

**`exited_mcm` is ZERO in all three, and that is the whole finding.** The
transmissive domain boundary is the only exit this model has — no infiltration,
no evaporation, no seepage, and `flux.py` zeroes velocity below `H_DRY_DEFAULT`
while LEAVING DEPTH IN PLACE. So a run that exported no water never tested
drainage at all, whatever its hazard counts say, and `safe_at_s: null` on such a
run describes a pond with nowhere to go rather than a failed recession. Read
`exited_mcm` and `retained_fraction` FIRST; they are in the verdict now, and the
script prints a WARNING when `exited_mcm <= 1e-6`.

The front is **volume-limited, not domain-limited**: 85.3 MCM fills the
reachable channel and runs out at east 23.5 km / north 15 km, against a boundary
40 km away. "Give it more runway" therefore cannot work, which is why the wider
domain and the finer grid both changed nothing.

**So the boundary was moved INSIDE the front.** `DOMAINS["exit"]` (8/20/8/18 km,
a 28 × 26 km box) puts the east edge 3.5 km inside the measured 23.5 km front.
Run `e2e09ea3201d4d42b7a7dbcd5fac4b81` (`khadakwasla_drain_to_green`, 200 m,
30 h, 6 members, `solver="both"`, corridor-conditioned 10 m, 2,740 s wall clock):

    released 85.314 MCM · exited 82.219 MCM (96.4%) · retained 3.090 MCM (3.6%)
    closure 0.007% · safe_at 33,977.7 s (9.44 h) · final sev 0, ext 0

against a pre-fix baseline of ~42% retained and 46 cells stuck SEVERE. **The
hazard reaches zero SEVERE and zero EXTREME at 9.44 h.** `fully_green_at_s` is
still null: 154 low + 46 moderate + 1 significant cell remain wet at 30 h.
(Those class names are the pre-unification ones; re-running this case today
would report the same water under the four published FD2320 classes.)

**Say what that run is, because it clips the study area on purpose.** It answers
"when does the flood clear a 28 × 26 km area around Pune", NOT "the water ceased
to exist" — 82 MCM left through the eastern edge and is downstream, unmodelled.
It also changed four things at once against the plateaued runs (domain,
conditioning, resolution, duration), so only the volume balance is cleanly
attributable: 96.4% exited against 0.0%. Two gauges then sit 3.0 km from that
edge — Hadapsar and Magarpatta City — and `_boundary_proximity` flags them, at an
UNVETTED `BOUNDARY_CONTAMINATION_KM = 5.0` chosen as a few times the coarsest
grid spacing, not from published guidance. Their depths are shaped by the
outflow condition and are not clean measurements. Loni Kalbhor (−6.5 km) and
Baramati (−65.4 km) fall outside the box entirely and report no arrival for that
reason, not for a hydraulic one.

## Corridor conditioning — opt-in, and it produces MODIFIED TERRAIN

`condition_corridor_m` threads `run.py` → `terrain/domain.py::build_domain` →
`conditioning.py::load_dem_as_grid` → `fill_depressions(corridor_mask=...)`.
Default **0 (off)**; off, a run is byte-identical to before, which
`test_no_mask_is_byte_identical_to_before` pins.

- **The mask is what makes it defensible.** `height_above_valley_floor` is a
  6 km minimum filter (wider than the Mutha's floodplain, narrower than the gap
  to the Western Ghats), and cells within `condition_corridor_m` of that floor
  get an INFINITE fill cap while every upland basin keeps the ordinary
  `fill_max_depth_m`. Conditioning a flow corridor is standard flood-routing
  practice; erasing terrain to guarantee drainage is what the previous section
  forbids. The mask is the entire difference, and `window_m = 6000.0` is an
  UNVETTED basin-specific choice.
- **Measured, with provenance, on the exit domain** (28 × 26 km at 200 m, in
  `data/runs/drain_to_green.log`): 465 of 1,012 corridor cells raised, max 7.5 m,
  **44 MCM of closed capacity removed**, 58 pits OUTSIDE the corridor left
  standing. Larger figures appear in source docstrings for other domains
  (1,392 MCM, 1,686 MCM, 1,659 MCM) — those were measured on the 117 × 90 km and
  wider domains, are not interchangeable with this one, and none of them has a
  surviving log. Quote a corridor figure with its domain and resolution or not at
  all.
- **It improves recession and it is not drainage.** `e5485691` conditioned at
  10 m still exported zero water. Only moving the boundary did that.
- **A conditioned run says so everywhere:** `corridor_conditioned` and
  `corridor_volume_removed_mcm` in the fill stats, `[CORRIDOR-CONDITIONED n m]`
  in the run label, and `terrain_modified` / `terrain_note` in `dam_config`.

## `mutha_temghar` is HYPOTHETICAL, and both blockage sites have now run

`rishi_ganga` models a REAL 2021 blockage whose geometry is merely unmeasured.
**`mutha_temghar` models nothing that happened.** No landslide dam has been
recorded on that reach of the Mutha; crest and width are entirely
operator-supplied, and its `barrier_source` says so in the wire payload, so the
dashboard cannot present it as an observed event. The preset carries **no
`event_date` and no detection window**, deliberately — offering detect dates
would invite the Sentinel-1 detector to hunt for a barrier that never existed.

Two constraints shape every result from it, and both are in the preset note.
**Headroom:** the bed is 617 m here and Temghar's toe about 700 m, so a crest
above roughly 80 m backs water into Temghar's own pool and the hypsometric fill
starts counting an existing reservoir as impounded volume — 45 m is the default
for that reason. **The reservoir downstream:** the release enters Khadakwasla
(85.31 MCM gross, pool baked into GLO-30 at 580.0 m) at about 26 km, so
**attenuation is the expected result**, and whether Pune sees anything depends on
a freeboard this model does not set.

Measured runs, both via `scripts/run_blockage.py`:

| run | site | barrier | Δx / duration / members | impounded (MEASURED off the burn) | result |
| :--- | :--- | :--- | :--- | ---: | :--- |
| `afabb054` | mutha_temghar | 45 m crest, 1,600 m requested | 150 m / 6 h / 4 | 39.110 MCM over 2.542 km², surface 664.2 m | **no arrival at any of six gauges**, 100% retained |
| `a221473f` | rishi_ganga | 110 m crest, 1,500 m | 100 m / 4 h / 4 | 22.177 MCM over 0.790 km², surface 1816.8 m | +5 km arrives 91.5 min, peak 11.72 m; +10.5 and +15.1 km no arrival |

Mutha's no-arrival is the expected attenuation, not a broken run — say that
rather than showing an empty map without explanation.

**The preset's own width estimate was wrong, and the burn caught it.**
`MUTHA_TEMGHAR`'s note says the barrier must be 1,400–1,900 m wide to span the
valley. `burn_barrier` widened the requested 1,600 m to a `width_m_final` of
**7,200 m** before `downstream_leak_cells` reached zero (5,215 cells modified).
The proof-of-span loop is doing exactly the job it exists for; the note's figure
is a terrain estimate and should be corrected or labelled when someone touches
that preset.

**A `solver="both"` comparison can still fail, and Tehri's does.**
`data/runs/flashflood.log`, run `37e1e713`: *"Impounding 3540.0 MCM over
9.72 km2 requires a mean depth of 364.2 m, which exceeds the dam height of
260.0 m."* The detected pool is too small for the published storage, so
`_impound_reservoir` refuses to build an initial condition. The far-field SWE run
completed and exported 18 products regardless — the comparison is recorded as
not written, not raised — but Tehri has no Delft3D cross-check on that path until
the pool detection or the storage figure is reconciled.

## `scripts/make_synthetic_demo_run.py` is NOT a simulation

No solver runs. It paints a prescribed wave onto the real Copernicus DEM so the
band follows the actual Mutha → Mula-Mutha → Bhima valley and looks plausible on
a basemap. It exists because the real runs stop at ~26 km and, before the exit
domain, never receded.

It is labelled **three times over, so no single omission unlabels it**: the run
picker name begins "SYNTHETIC DEMO"; the caption is BURNED INTO every keyframe
PNG, so a screenshot taken out of the dashboard still carries it; and both
`run_summary.json` and `params_json` carry `is_synthetic: true`. That mirrors
`demo_synthetic.py`'s mandatory red ParaView banner and `gee/sar.py`'s refusal to
synthesize an observation at all. A fabricated run that looks like a result is
the single failure mode those conventions exist to prevent.

Now that `e2e09ea3` exists, prefer it: it is a real solve that reaches zero
severe cells. Reach for the synthetic asset only for the long-reach picture the
solver still cannot produce.

## Damage estimation, and a 25x undercount found while building it

PS-26161 deliverable (i) asks for "loss and damage analysis" and nothing reached
a user. `impact/damage.py` existed but had **zero call sites outside tests**,
and `main.py` had been reading an export of kind `"impact"` that **nothing has
ever written** — `RunResult.impact` was null for all 40 runs in the shipped
database, so `ImpactPanel`'s populated damage branch was dead code behind a gap
notice.

- **A fabricated credential was deleted, not relabelled.** The old
  `DepthDamageAnalyzer` attributed its coefficients to "Graham (2009), a
  comprehensive study for the Uttarakhand region" with r² of 0.82 / 0.79 / 0.75.
  No such study is in `literature.md`; the only Graham there is the **1999 USBR
  report on FATALITY rates**, a different quantity. A goodness-of-fit statistic
  for a fit that was never performed is a fabricated credential. Gone with it:
  three asset baselines (125 / 85 / 45 crore) identical for every dam in the
  country, an assumed 450 persons/km², and two hardcoded 200 m cell areas that
  ignored the run's real resolution.
- **Exposure now comes from the catchment.** Damage is
  `ratio(depth) x exposure x unit_cost`. Exposure is **GHS-BUILT-S built-up
  SURFACE** (`gee/built_up.py`, m² per cell) plus **WorldCover cropland
  fraction**, both fetched onto the solver's own grid. The residential /
  non-residential split is `built_surface` minus `built_surface_nres` — **two
  published bands, not a ratio somebody picked**. Both fetches keep the
  three-states-no-fourth contract, and `built_up.py` has **no `allow_synthetic`
  parameter at all**, following `blockage_detect` rather than `population.py`.
- **The curve says it is unpublished and the cost says it is unvetted.**
  `compute_depth_damage` is a saturating exponential with three unsourced rate
  constants; every result carries `model_is_published: False`. The unit costs
  are placeholders **echoed in the payload** (`unit_cost_inr_per_m2`,
  `unit_cost_price_year`) so a reader can divide them back out — a test pins
  that doubling the constant doubles the figure. Huizinga (2017) is present in
  SHAPE and quarantined behind `HUIZINGA_2017_VERIFIED = False`, exactly as
  `fatality.py` holds Jonkman (2008). Verification rows 35 and 36; row 10 now
  points at the quarantine.
- **THREE STATES PER SECTOR, NOT PER PAYLOAD.** Built-up can be available while
  cropland is not. Refusing the whole payload would suppress a good buildings
  figure; totalling with agriculture silently zero would publish a fabricated
  number that reads as "no agricultural damage". So each sector carries its own
  `available` and `reason`, and **the total is withheld entirely unless every
  sector succeeded**, beside a `missing_sectors` list.
- **`jalraksha.impact` must not import `jalraksha.gee`** (Phase 6 importing
  Phase 9). `tasks.py` fetches and passes arrays in, the same seam
  `_population_at_risk` already used. That is also what keeps `damage.py`
  testable with no network.
- **`impact_exports` is SHARED with `script_runs.py`, not copied**, and it
  covers PAR as well. The script path wrote **neither** artifact, which is why
  the flagship `e2e09ea3` run lists with an empty Impact tab.

**And the reason to read `exposure_provenance` before any rupee figure:
`reduceResolution(ee.Reducer.sum())` DOES NOT SUM.** Earth Engine weights each
contributing pixel by the fraction of the OUTPUT pixel it covers and those
weights sum to one, so a weighted sum is arithmetically a **mean**.
`gee/population.py` documented this exact hazard at length, switched to `sum()`
to avoid it, and produced it anyway: over the 480x376 domain at 500 m it
returned **741,659 people against a native-resolution total of 18,543,954** —
short by **25.003x**, precisely (500/100)². Every population-at-risk figure this
project published before now was low by the square of the ratio between the
solver grid and 100 m, and **runs finished before the fix keep that error in
their `population_at_risk.json`** — they are not retroactively corrected.

`sum().unweighted()` is not the fix (it overshoots 1.49x). The correction in
`gee/grid_fetch.py` is to stop resampling a per-cell count at all: convert to a
density per m² dividing by `pixelArea()` **declared in the SOURCE projection**,
aggregate as the intensive quantity it then is, and multiply back by the output
cell area. Against native totals: population 1.0055, built-up 1.0059 — the same
residual for both, so clip-boundary handling, not scale. Callers now declare
`extensive=True/False` instead of choosing a reducer, GHSL manifests are
versioned (`ghsl_manifest_v2.json`) so pre-fix rasters are never served again,
and `test_an_extensive_quantity_survives_the_change_of_grid` fetches the same
ground at 500 m and 250 m and asserts one total — which the old path failed by
exactly 4x. Verification row 37.

**Two Earth Engine limits are worth not rediscovering.** WorldCover is 10 m and
the solver runs at 100-500 m: in one hop EE wants 3,081 source pixels per output
pixel against a default of 1,024, and raising the cap trips the other limit —
*"Reprojection output too large (27412x20470 pixels)"* — because the whole
domain then has to be materialised at 10 m. `stage_scale_m` aggregates through
a middle scale, and it must stage **in the SOURCE CRS**: staging into UTM still
forces that 10 m materialisation, measured identically at 50, 100 and 200 m,
which is what shows the stage scale was never the problem. Both hops are means
over the same quantity, so splitting them approximates nothing — 100 m and
200 m staging return the same cropland area to the last decimal.

**Measured, Khadakwasla run `858d7690` (480x376 at 500 m, 119 wet cells):**
791.07 km² built-up in domain (native-resolution truth 786.42, +0.6%), 24.54 km²
non-residential, 23,933 km² cropland. Flooded exposure 5.43 km² residential,
0.151 km² non-residential, 2.15 km² cropland, giving ₹8,482 / ₹283 / ₹2.1 crore
and a total of **₹8,767 crore (band 6,137-11,397)**. Quote it as an order of
magnitude — the exposure is measured, the cost per m² is not.

## Two small operational facts

`scripts/run_api.py` honours `$PORT` (an explicit `--port` still wins) and
`.claude/launch.json` uses `autoPort`, so a second checkout or a parallel session
no longer collides on 8000.

`scripts/register_script_run.py` emits the `GridSummary` field names
(`nx`/`ny`/`dx`/`dy`/`x0`/`y0`/`crs`); the old `resolution_m` key rendered the
panel as a row of blanks. `x0`/`y0` stay **null rather than guessed** — the UTM
origin was never recorded, and a wrong one georeferences every downloaded raster
incorrectly, which is worse than an absent one.

## GPU backend — float64 CUDA on the RTX 4050, CPU kept as the reference

Full record: `docs/validation_findings.md` §11 and `docs/DECISIONS.md` §14. The
old "a float64 GPU port would be slower" line in `parallel.py` and PERF-6 was an
estimate, and measurement replaced it.

- **One switch.** `SWESolver` and `run_ensemble` take `backend="auto" | "cuda" |
  "cpu"`, and `JALRAKSHA_SOLVER_BACKEND` overrides `auto`. `auto` uses the GPU
  when a float64 CUDA kernel compiles and runs (probed once per process),
  otherwise the CPU, and records why. An explicit `cuda` request that cannot
  run RAISES. It never quietly runs on the CPU, because every timing and every
  provenance label would then be false.
- **Measured: 11–20× faster**, float64 on both, with identical step counts.
  One member at 376 × 480 went from 72.4 s to 5.74 s (12.6×), one member at
  600 × 600 from 136.4 s to 6.72 s (20.3×), and a 30-member ensemble from
  455.6 s on the CPU process pool to 39.7 s (11.5×). The speed-up grows with
  grid size, because 376 × 480 does not fill the GPU.
- **Install:** `pip install -e ".[gpu]"`, which is numba-cuda[cu12] plus pyopencl.
  numba-cuda ships NVVM and NVRTC as pip wheels, so only the NVIDIA driver is
  needed, not the CUDA toolkit. That missing NVVM was the whole reason CUDA
  "did not work" here before. Kernels use `cache=True`, so editing
  `flux_cuda.py` or `ensemble_cuda.py` costs a few seconds of recompilation on
  the next run.
- **Single physics source.** The `_impl` functions in `solver/flux.py`
  (minmod, Audusse, HLLC, friction, the per-cell CFL term) are compiled twice,
  with `njit` and with `cuda.jit(device=True)`. Edit an `_impl` function and
  both backends follow. Four pieces are MIRRORED rather than shared (MUSCL edge
  extrapolation, tendency assembly, the RK stages, Kurganov–Petrova recovery),
  and `tests/test_solver_cuda.py` pins them against the CPU.
- **Not bit-identical, and that is expected.** NVVM contracts `a*b + c` into an
  FMA and numba-cuda has no switch to stop it. Backends differ at about 1e-15.
  Never write `array_equal` between backends, and never "fix" the difference
  with fastmath: `flux.py` explains why fastmath breaks the C-property.
- **The GPU passes the gates on its own.** `tests/test_solver.py` runs every
  test on both backends through an autouse fixture. GPU `step()` uploads and
  downloads every call, so those tests are slower on the GPU (Thacker: 17.7 s
  against 3.1 s). `run()` and the ensemble keep state on the device.
- **Provenance travels with every result.** Each member dict carries
  `solver_backend`, `solver_backend_label`, `solver_backend_reason` and
  `solver_device`. These flow to run.py's `solver_backend`, `run_summary.json`,
  `RunResult.solver_backend`, the Ensemble tab's "Computed on" line, and the
  Validation tab's metrics.
- **The batched ensemble is a SECOND implementation of the member loop**
  (`ensemble_cuda.py`: per-member dt and t_sim, an `active` mask, snapshots
  captured on the device). `tests/test_parallel.py::TestGpuEnsemble` binds it
  to `run_ensemble_member`. Change one without the other and that test fails,
  which is its purpose.
- **One timestep per member step** (fixed 2026-09-12).
  `inject_with_one_timestep` on the CPU and `choose_injection_step` on the GPU
  shrink the pre-injection CFL dt until the step is CFL-valid after the
  injection, to within `INJECTION_CFL_RTOL` = 1e-6. The injection, the step
  and the clock then all use that dt. The
  old three-dt loop ran the clock 1.8–2.6% ahead of the physics on a dry
  synthetic valley. It changed nothing measurable on Khadakwasla, where the
  shrink fires once in about 75,000 steps. `TestMemberTimestep` pins
  clock = physics time and CFL validity.
- **Ensemble members use the per-cell Manning field** (fixed 2026-09-12). Both
  backends used to solve every member with the field's MEAN. On a
  WorldCover-style valley that made a smooth channel three times too rough, and
  the flood reached 170 cells instead of 308. Current pipeline runs are
  unaffected, because `build_domain` still supplies a uniform field
  (dam_config `manning_n`, default 0.03). `run_summary.json` now carries
  `roughness`, describing the field the members were actually solved with.
- **CPU pool workers are pinned to `backend="cpu"`**, because 16 worker
  processes each opening a CUDA context on a 6 GB card would fail. Ensemble
  chunks are sized to 60% of FREE VRAM (`ensemble_cuda.VRAM_FRACTION`); a
  member at 376 × 480 takes about 35 MB. A second concurrent run that runs out
  of memory falls back to the CPU and says so.
- **Near-field SPH stays on the CPU on Python 3.14.** PySPH's OpenCL path is
  wired in (`--opencl --use-double`, with `PYOPENCL_CTX` set to the NVIDIA
  platform because the AMD gfx1103 iGPU is also an OpenCL platform). But
  compyle 0.9.1, which generates PySPH's GPU kernels, uses `ast.Str`, which
  Python 3.14 removed. `resolve_sph_backend` detects that from compyle's
  source, and `JALRAKSHA_SPH_BACKEND=auto|opencl|cpu` controls the choice.
  Whether a newer compyle or Python 3.13 would run it is UNTESTED.

## ParaView Visualization Pipeline — Model/Effort Routing

The ParaView sub-project (`paraview/`, `tools/paraview/`) builds a DEM →
XDMF+HDF5 → ParaView pipeline visualizing dam-break floods for two presets
(`jalraksha/presets.py`): **Khadakwasla** (Mutha Basin, Pune — default) and
**Tehri** (Bhagirathi Basin, Uttarakhand). Its own phase numbering follows
`paraview/*.md`'s spec Section 17, not the table below — the **Phase**
column here is a work-routing label from planning, not a phase number; the
**Maps to** column gives the actual Section 17 phase so the two schemes
don't get confused.

| Phase (table label) | Maps to (spec Section 17) | Task / Objective | Model | Effort | Token Strategy |
| :--- | :--- | :--- | :--- | :--- | :--- |
| Phase 3 Finish | Phase 3 (static water) | Visual sign-off on `phase3_reservoir.png` & update `paraview/IMPLEMENTATION_PLAN.md` | Haiku 4.5 | Low | Use Haiku for plain text markdown check-offs to conserve credits. |
| Phase 2 Planning | Phase 4 (time-varying data) | Design XDMF+HDF5 schema, wave equations, and solver contract | Opus 5 | High | Front-load reasoning in 1 comprehensive prompt to avoid back-and-forth loops. |
| Phase 2 Execution | Phase 4 (time-varying data) | Write `demo_synthetic.py` & `xdmf_export.py` HDF5 serialization code | Sonnet 5 | Medium–High | Pass the exact specification from Opus directly to Sonnet 5 for clean single-pass code output. |
| Phase 5 | Phase 6 (scientific overlays) | Scientific overlays (`Annotate Time`, synthetic flag warning, fixed depth legends, velocity glyphs) | Sonnet 5 | Medium | Combine all filter node logic into a single script request to minimize context window overhead. |
| Phase 6 | Phase 7 (static export) | Set up `camera_presets.py` and fix `render_static.py` pre-render auto-reset issue | Sonnet 5 | Medium | Use Sonnet 5 for routine API script bug fixes and parameter matrix definitions. |
| Phase 7 Planning | Phase 8 (video export) | Frame interpolation sequence design & FFmpeg H.264 pipe strategy | Opus 5 | Medium–High | Map out execution steps and error-handling constraints before requesting code. |
| Phase 7 Execution | Phase 8 (video export) | Implement `render_animation.py` (`SaveAnimation()`) & FFmpeg wrapper script | Sonnet 5 | High | Delegate heavy Python file generation to Sonnet 5. |
| Phase 8 | Phase 9 (optimization) | Grid resolution decimation (30m/60m/120m) & ParaView interactive LOD tuning | Sonnet 5 | Low–Medium | Simple array resampling and property setting updates. |
| Phase 9 | — (new, not in Section 17) | Create unified CLI orchestrator `main.py` (`argparse` setup) | Haiku 4.5 | Low | Haiku handles standard CLI boilerplate with minimal token cost. |

As of this writing: Phase 3 (static water) sign-off is done for both dams —
`paraview/artifacts/phase3_reservoir.png` (Tehri) and
`paraview/artifacts/phase3_khadakwasla_reservoir.png` (Khadakwasla) are both
rendered and confirmed correct. Phase 7 (static export, `render_static.py`) is
done and dam-agnostic. **Phase 8 (video export) is now built** —
`paraview/render_animation.py`, artifacts `flood_simulation.mp4` (synthetic) and
`tehri_flood.mp4` (real solver). Phase 9's Python-side decimation was already in
place upstream and its interactive-GUI LOD half is deliberately not built.
`paraview/IMPLEMENTATION_PLAN.md` is the authoritative per-phase checklist.

**Two things about the video path are worth not rediscovering.** `PlayMode =
"Sequence"` moves the animation clock smoothly, but a READER does not
interpolate in time — asked for a moment between two stored steps it returns the
nearer one — so 60 frames over 30 timesteps came back as 30 byte-identical
PAIRS. ParaView's own `TemporalInterpolator` is the fix, so Section 18's ban on
hand-written frame interpolation still holds. And `frames == timesteps` is NOT
a safe case: Sequence resamples onto EVENLY spaced times while solver timesteps
are unevenly spaced under adaptive CFL, so 30 frames from 30 steps still
collided at index 14/15 and skipped another step. Interpolation therefore
defaults ON at every frame count. `tests/test_paraview_animation.py` hashes
frames rather than checking that files exist, which is the only way either
defect is visible — both produced a complete, playable, wrong video.
