---
name: build-phase
description: Guided executor for a specific build phase (0–17). Specify the phase number, and this skill validates pre-flight checks (DEM cached, breach regression data verified if needed), runs the phase's core build steps, and reports blockers clearly.
disable-model-invocation: true
---

## Overview

The `/build-phase` skill stages the execution of a single phase from the 18-phase build plan specified in AGENTS.md. It:

1. **Pre-flight checks**: Verifies dependencies are available (data cache, prior phase completion)
2. **Executes core build tasks** for the requested phase
3. **Reports blockers**: If a phase cannot start, explains why with actionable remediation steps
4. **Logs completion**: Tracks which phases have finished for downstream dependencies

## Usage

```
/build-phase 0
# Execute Phase 0 (skeleton setup)

/build-phase 1
# Execute Phase 1 (solver core) — must have Phase 0 complete
```

## Phase Reference

| Phase | Name | Critical? | Dependencies | Key Deliverable |
|-------|------|-----------|--------------|-----------------|
| **0** | Skeleton | ★ | None | CLI entry point, data cache system, DEM fetch |
| **1** | Solver core | ★ | Phase 0 | 2D SWE with HLLC, gated on analytical tests |
| **2** | Terrain conditioning | | Phase 1 | DEM interpolation, smoothing, breach location |
| **3** | Breach regressions | | Phase 2 | Peak outflow, failure time (Wahl method) |
| **4** | End-to-end dam-break | ★ | Phases 0–3 | Breach → solver → arrival times + inundation polygons |
| **5** | Export formats | | Phase 4 | Shapefile, KML, Cloud-Optimized GeoTIFF writers |
| **6** | Impact analysis | | Phase 5 | Exposure analysis, building footprints, vulnerability |
| **7** | SPH coupling | | Phase 4 | Near-field 3D SPH handoff (one-way) |
| **8** | Google Earth Engine | | Phase 6 | Land use, population, dynamic data streams |
| **9** | Validation framework | | Phase 7 | Malpasset, Chamoli 2021 benchmarks |
| **10** | Dashboard (React) | | Phase 8 | deck.gl map, time series plots, impact tables |
| **11** | Dashboard | | Phase 8 | React + Vite + Leaflet/Cesium on FastAPI (the Streamlit fallback was built, then removed) |
| **12** | Hardening & docs | | Phase 11 | Error handling, logging, user documentation |
| **13–17** | (Reserved) | | | Future enhancements |

## Pre-Flight Checks

Each phase runs these checks before starting:

- **Phase 0**: No dependencies (can run immediately)
- **Phases 1–4**: Verify prior phase(s) have a `.phase_complete` marker file
- **Phases 5+**: Verify Phase 4 (end-to-end deliverable) is complete
- **DEM-based phases** (2, 3, 4): Verify `./data/dem_copernicus_cache/` exists and has ≥1 GeoTIFF
- **Breach regression phases** (3, 4): Verify unvetted coefficients in `prototype specs.md` are reviewed

## Execution Model

When you invoke `/build-phase <N>`:

1. Codex checks pre-flight conditions
2. If blockers exist, prints actionable remediation (e.g., "Phase 0 must complete first. Run: `/build-phase 0`")
3. If clear, executes the phase's build steps
4. On success, creates `./.phase_N.complete` marker
5. Reports what was built and what comes next

## Minimum Viable Slice

If schedule collapses, prioritize **Phases 0–5 + Phase 7 (reduced)**:
- Phase 0: Skeleton, CLI, caching
- Phase 1: Solver core (analytical tests gate it)
- Phase 2–3: Terrain + breach regressions
- Phase 4: End-to-end pipeline (core deliverable)
- Phase 5: Export to .shp and .kml
- Phase 7: Small SPH near-field run

This yields a working simulation with basic export — defensible for SIH judging.

## Notes

- **Critical phases** (0, 1, 4) must pass their verification gates (Phases 0–1) before downstream phases can start
- **Unvetted coefficients**: Before executing Phase 3 or 4, review `prototype specs.md` and flag any hardcoded values without primary-source citations
- **Demo-day**: Assume offline operation. All data fetches happen during Phase 0 and are cached for Phase 4 demo
- **Licensing**: Verify approved vs forbidden sources before adding new data dependencies (see AGENTS.md)

## Status (Aug 2026)

**Initialized**: Skill scaffold created and registered in `.Codex/skills/build-phase/`
**Dependencies**: Ready to scaffold Phase 0 skeleton
**Next steps**: Implement phase executors
- Phase 0: CLI scaffolding, data cache initialization, DEM fetch setup
- Phase 1: 2D SWE solver core (gated on `/verify-jalraksha analytical`)
- Phase 2–3: Terrain conditioning and breach regressions
- Phase 4: End-to-end pipeline (core deliverable)
- Phases 5+: Export, impact analysis, SPH, dashboard

**Phase completion markers**: `.phase_N.complete` files track build progress for dependency checks
