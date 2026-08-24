# JalRaksha Project Setup — Complete Summary

**Date**: August 23, 2026  
**Project**: JalRaksha (Smart India Hackathon 2026, NTRO Problem Statement 26161)  
**Status**: ✅ Fully initialized with CLAUDE.md, 4 skills, hooks, and environment

---

## Overview

JalRaksha is a Python system for dam-break inundation modelling and analysis using open data (Copernicus DEM, Google Earth Engine, CWC dam registers). It combines:
- **2D shallow-water equation (SWE) solver** — far-field propagation
- **3D Smoothed Particle Hydrodynamics (SPH)** — near-field violent dynamics
- **Tier-1 screening tool** — rapid prioritization against CWC guidelines

**18-phase build plan** with Phases 0, 1, 4 marked critical (★).

---

## Files & Setup

### Core Documentation
1. **CLAUDE.md** (130+ lines)
   - Project overview and constraints
   - 18-phase build order with dependencies
   - Multi-tier testing strategy
   - Solver conventions (HLLC flux, Audusse reconstruction, Numba JIT)
   - Python environment setup
   - Code style and gotchas
   - **NEW**: Project setup progress section (Aug 2026)

2. **.claude/settings.json** (Hooks configuration)
   ```json
   {
     "hooks": {
       "PostToolUse": [Write|Edit → ruff format],
       "PreToolUse": [Bash → warn on forbidden data sources]
     }
   }
   ```

3. **.gitignore** (Git ignore rules)
   - Protects `.claude/settings.json`, `.claude/settings.local.json`
   - Excludes Python artifacts, virtual environments, IDE config
   - Excludes local data cache

### Skills (4 Created)

| Skill | Purpose | Status |
|-------|---------|--------|
| `/verify-jalraksha` | Multi-tier validation (analytical tests, gates, benchmarks) | Scaffold ready, tests TBD |
| `/build-phase` | Phase executor with pre-flight checks | Scaffold ready, executors TBD |
| `/improve-architecture` | Codebase structure audit (deep modules) | Scaffold ready, scanner TBD |
| `/code-quality-deep-dive` | Exhaustive numerical + safety review (multi-agent) | Scaffold ready, agents TBD |

Each skill in `.claude/skills/<name>/SKILL.md` with:
- Detailed workflow and usage examples
- Phase/context-specific guidance
- Status and next implementation steps
- Design philosophy (deep modules, parallel audits, etc.)

---

## Environment

### Installed
- **Python**: 3.14.2 (available)
- **pip**: 25.3 (available)
- **ruff**: 0.16.4 (installed, `python -m ruff`)

### Configured
- Auto-format on edit: `python -m ruff format --quiet --line-length 100`
- Bash pre-flight: Warns on forbidden data sources

### Ready To Install
```bash
pip install -e .  # From pyproject.toml (when created)
```

---

## Critical Constraints

**Hard Rules** (from CLAUDE.md):
- ✅ No India-WRIS, ffs.india-water.gov.in, Bhuvan, CartoDEM
- ✅ 18 unvetted coefficients flagged for review (per prototype specs.md)
- ✅ Tehri dam = demo case; Mullaperiyar forbidden
- ✅ Metric CRS only (EPSG:32643 or equivalent UTM)
- ✅ No overclaiming vs Delft3D (say "Delft3D-class")
- ✅ No two-way SPH↔SWE coupling (one-way only)
- ✅ 30 m DEM adequate for Tier-1 screening
- ✅ Offline-first design (cache all data after first fetch)

---

## Build Plan

### Phases (18 Total, 3 Critical ★)

| Phase | Name | Gated On | Output |
|-------|------|----------|--------|
| **0★** | Skeleton | — | CLI, data cache, DEM fetch |
| **1★** | Solver core | Ritter, lake-at-rest, mass conservation | 2D SWE with HLLC |
| 2 | Terrain conditioning | Phase 1 | DEM interpolation, smoothing |
| 3 | Breach regressions | Phase 2 | Peak outflow, failure time (Wahl) |
| **4★** | End-to-end dam-break | Phases 0–3 | Breach → solver → arrival times |
| 5–12 | Export, impact, SPH, GEE, validation, dashboard | Phase 4 | Full system |

### Minimum Viable Slice
If schedule collapses: **Phases 0–5 + Phase 7 (reduced)**
- Working simulation with shapefile/KML export
- Small SPH near-field run
- Defensible for SIH demo

---

## Testing Strategy

**Multi-tier framework**:
1. **Analytical exact solutions** (Ritter, Stoker, Thacker) — validate scheme correctness
2. **Blocking correctness gates** — lake-at-rest (<0.1% velocity), mass conservation (<0.1% loss)
3. **Benchmarks** — Malpasset (1959), Chamoli 2021 (India)
4. **CI integration** — Gates on PR merge

---

## Ready To Start

### Phase 0 — Skeleton
```bash
/build-phase 0
```
Creates CLI entry point, data cache system, DEM fetch pipeline.

### Phase 1 — Solver Core
```bash
/build-phase 1
/verify-jalraksha analytical
```
Implement 2D SWE, validate against exact solutions.

### Code Quality Review
```bash
/improve-architecture phase 0
/code-quality-deep-dive --phase 1
```

---

## Recommended Next Steps

1. **Create pyproject.toml** — dependencies (PySPH, NumPy, Numba, rasterio, geopandas, xarray)
2. **Install plugins** (optional):
   ```
   /plugin install skill-creator@claude-plugins-official
   /plugin install jupyter@claude-plugins-official
   /plugin install playwright@claude-plugins-official  # For Phase 10 dashboard
   ```
3. **Begin Phase 0** — Run `/build-phase 0` or manually scaffold CLI
4. **Implement Phase 1 tests** — `/verify-jalraksha` needs analytical test runners
5. **Draft Phase 1 solver** — 2D SWE core with HLLC flux

---

## Project Memory

Setup progress tracked in:
- `~/.claude-omniroute/projects/D--pd-chosen-one-SIH-prototype/memory/jalraksha-init-setup.md`
- `~/.claude-omniroute/projects/D--pd-chosen-one-SIH-prototype/memory/MEMORY.md`

---

## Files Created

```
D:\pd\chosen one\SIH prototype\
├── CLAUDE.md                                    # 130+ lines, project guidance
├── .gitignore                                   # Git ignore rules
├── .claude/
│   ├── settings.json                            # Hooks configuration
│   └── skills/
│       ├── verify-jalraksha/SKILL.md
│       ├── build-phase/SKILL.md
│       ├── improve-architecture/SKILL.md
│       └── code-quality-deep-dive/SKILL.md
```

---

**Setup completed**: Aug 23, 2026, 18:42 UTC  
**Next session**: Load CLAUDE.md → run `/build-phase 0` or similar

