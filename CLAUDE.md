# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**JalRaksha** is a Python system for dam-break inundation modelling and analysis, designed for the Smart India Hackathon 2026 (Problem Statement 26161, NTRO-sponsored). It combines a 2D shallow-water equation (SWE) solver for far-field propagation with 3D Smoothed Particle Hydrodynamics (SPH) for violent near-field dynamics. The system uses exclusively open data (Copernicus DEM, Google Earth Engine, CWC dam registers, ESA WorldCover) and produces outputs in Cloud-Optimized GeoTIFF, Shapefile, and KML/KMZ formats.

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

## Project Setup Progress (Aug 2026)

### ✅ Completed
- **CLAUDE.md** initialized with full project guidance (500+ lines)
- **4 skills created**:
  - `/verify-jalraksha` — Multi-tier validation (analytical tests, correctness gates, benchmarks)
  - `/build-phase` — Phase executor with dependency tracking
  - `/improve-architecture` — Codebase structure audit (HTML explorer + grilling)
  - `/code-quality-deep-dive` — Exhaustive numerical + safety review
- **Hooks configured** (.claude/settings.json):
  - PostToolUse/Write|Edit → Auto-format with ruff
  - PreToolUse/Bash → Warn on forbidden data sources
- **Environment**:
  - ruff 0.16.4 installed (`python -m ruff`)
  - .gitignore configured
  - Python 3.14.2 available
- **Architecture Improved** (Aug 23, 2026):
  - ✅ Created `jalraksha/` package structure (Phase 0 skeleton + stubs for Phases 1–7)
  - ✅ Implemented Phase 0 modules: config.py, cli.py, cache.py, dem.py
  - ✅ Moved presentation tooling to `tools/sih-presentation/`
  - ✅ Created tests/ directory with conftest.py
  - ✅ Documented deep-module design principles

### 🏗️ Package Structure

```
jalraksha/
├── __init__.py           — Package init (phase boundaries documented)
├── config.py             — Config loading & validation (Phase 0)
├── cli.py                — CLI entry point (Phase 0)
├── cache.py              — Cache management (Phase 0)
├── dem.py                — DEM fetch from Copernicus (Phase 0)
├── solver/
│   ├── __init__.py       — Phase 1+: HLLC, Audusse, analytical tests
│   ├── core.py           — (Phase 1)
│   ├── flux.py           — (Phase 1)
│   └── types.py          — (Phase 1)
├── terrain/
│   ├── __init__.py       — Phase 2+: DEM conditioning, breach regressions
│   ├── conditioning.py   — (Phase 2)
│   └── breach.py         — (Phase 3)
├── export/
│   ├── __init__.py       — Phase 5+: GeoTIFF, Shapefile, KML export
│   ├── geotiff.py        — (Phase 5)
│   ├── shapefile.py      — (Phase 5)
│   └── kml.py            — (Phase 5)
└── sph/
    ├── __init__.py       — Phase 7+: SPH near-field coupling
    └── coupling.py       — (Phase 7)

tests/
├── conftest.py           — Pytest fixtures (temp cache, sample config)
├── test_cache.py         — (Phase 0 tests)
├── test_dem.py           — (Phase 0 tests)
├── test_solver.py        — (Phase 1 tests)
└── test_export.py        — (Phase 5 tests)

tools/
└── sih-presentation/
    ├── build_ppt.py      — SIH deck generation (moved from root)
    ├── check_ppt.py      — Deck validation (moved from root)
    └── README.md         — Presentation tooling docs
```

### 🚀 Ready To Start
- **Phase 0 (Skeleton)**: Run `/build-phase 0`
  - ✅ CLI entry point: `jalraksha run --dam tehri --lat ... --lon ... --height ... --storage ...`
  - ✅ Config validation: `jalraksha validate --config jalraksha.yaml`
  - ✅ Cache management: `jalraksha cache --list` / `--clear`
  - ✅ DEM fetch: Copernicus GLO-30 from public AWS COGs
- **Phase 1 (Solver Core)**: Run `/build-phase 1` then `/verify-jalraksha analytical`
  - 2D SWE implementation (HLLC, Audusse, MUSCL)
  - Analytical test validation

### 📋 Recommended Plugin Installs
```
/plugin install skill-creator@claude-plugins-official
/plugin install jupyter@claude-plugins-official
/plugin install playwright@claude-plugins-official  # For Phase 10 dashboard
```

### 📊 Build Timeline
- **Critical path**: Phases 0 → 1 → 4 (gate on tests at each)
- **Minimum viable**: Phases 0–5 + Phase 7 (reduced) = working sim with export
- **Full scope**: All 18 phases for complete Tier-1/2 system with dashboard
- **Demo-day strategy**: Pre-cache all data after Phase 0, assume offline

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
survives the server restarting. Its 24 h confirmation run has NOT completed, so
the plateau is fixed in mechanism but not yet re-measured.

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
