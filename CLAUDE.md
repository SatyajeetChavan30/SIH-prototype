# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**JalRaksha** is a Python system for dam-break inundation modelling and analysis, designed for the Smart India Hackathon 2026 (Problem Statement 26161, NTRO-sponsored). It combines a 2D shallow-water equation (SWE) solver for far-field propagation with 3D Smoothed Particle Hydrodynamics (SPH) for violent near-field dynamics. The system uses exclusively open data (Copernicus DEM, Google Earth Engine, CWC dam registers, ESA WorldCover) and produces outputs in Cloud-Optimized GeoTIFF, Shapefile, and KML/KMZ formats.

## Critical Constraints

**Hard Rules:**
- **No India-WRIS, ffs.india-water.gov.in, Bhuvan, or CartoDEM** — these are geo-fenced, broken, or login-gated. All data must come from open sources.
- **18 unvetted coefficients** in the verification queue (breach regressions, Wahl uncertainty bands, fatality-rate tables, depth-damage curves). Flag any coefficient before use with a TODO and a source citation from the literature.md file.
- **Tehri dam** is the demo case (260 m height, 3,540 MCM). **Mullaperiyar is explicitly forbidden** (active Supreme Court litigation).
- **Metric CRS for all solver operations** — never degrees. Cell-centred finite volume on uniform Cartesian grids.
- **No overclaiming**: Never claim to be Delft3D (say "Delft3D-class" instead). Never claim rigorous two-way SPH↔SWE coupling (one-way handoff only).
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
6. Phases 5–12: Export formats (.shp, .kml, .tif), impact analysis, SPH coupling, GEE integration, validation, dashboard (React + deck.gl or fallback Streamlit + leafmap), hardening.
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
