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
- **Runs predating this work** have no ensemble statistics, no p05/p95 arrival
  band and no per-gauge peak depth — those fields did not exist when they were
  written, and they render as blanks. New runs are complete.

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
rendered and confirmed correct. Phase 7 (static export, `render_static.py`)
is also done and dam-agnostic. Phases 6, 8, and 9 remain unbuilt — see
`paraview/IMPLEMENTATION_PLAN.md` for the authoritative, per-phase checklist.
