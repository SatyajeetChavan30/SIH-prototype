---
name: verify-jalraksha
description: Run the multi-tier validation suite for the JalRaksha solver (analytical tests, correctness gates, optional benchmarks). Use this before committing solver changes or after implementing Phase 1 core components.
---

## Overview

The `/verify-jalraksha` skill executes the complete testing framework specified in AGENTS.md:

1. **Analytical exact-solution tests** (Ritter, Stoker, Thacker)
2. **Blocking correctness gates** (lake-at-rest <0.1% velocity, mass conservation <0.1%)
3. **Dry-bed robustness check** (no NaNs, negative depths, or division errors)
4. **Optional benchmarks** (Malpasset 1959, Chamoli 2021)

## When to Use

- After implementing the 2D SWE solver core (Phase 1)
- Before opening a PR that modifies the flux scheme, reconstruction, or time integrator
- To validate changes to Manning friction or wet/dry treatment
- To gate Phase 1 completion on correctness

## Typical Workflow

```
/verify-jalraksha analytical
# Runs Ritter, Stoker, Thacker only — fast (~30s)

/verify-jalraksha gates
# Runs lake-at-rest, mass conservation, dry-bed — ~1 min

/verify-jalraksha full
# Runs all of the above plus Malpasset benchmark — ~5 min

/verify-jalraksha chamoli
# Runs the Chamoli 2021 comparison (most expensive, most realistic) — ~10 min
```

## What Passes/Fails Means

**Analytical tests (Ritter, Stoker, Thacker):**
- PASS: Max relative L∞ error <1% vs exact solution
- FAIL: Indicates scheme instability or incorrect boundary conditions

**Lake-at-rest:**
- PASS: Max velocity magnitude <0.1% of initial conditions over any bathymetry for 100 timesteps
- FAIL: Hydrostatic pressure term is not balanced; check Audusse reconstruction

**Mass conservation:**
- PASS: Total volume change <0.1% over 1000 timesteps
- FAIL: Flux scheme is leaking mass; check HLLC implementation

**Dry-bed robustness:**
- PASS: No NaNs, negative depths, or runtime errors on dry-bed dam-break (Ritter)
- FAIL: Wet/dry treatment has a singularity; check small-depth guards

**Malpasset & Chamoli:**
- PASS: Arrival times match published benchmarks ±5%
- FAIL: Breach regression or Manning parameterization is off

## Environment Requirements

- Python environment with PySPH, NumPy, Numba, xarray installed
- Test data cached locally (see AGENTS.md "Offline-first design")
- If running Chamoli: requires 2 m pre/post-event DEMs (cached in `./data/chamoli_2021/`)

## Notes

- Analytical tests are **blocking gates** — Phase 1 cannot merge without PASS
- Benchmark runs are **optional for nightly CI** but strongly recommended before final integration
- All tests must use metric CRS (EPSG:32643 for India or equivalent UTM)
- Do not compare against Delft3D directly; use published field benchmarks (Malpasset, Chamoli) instead

## Status (Aug 2026)

**Initialized**: Skill scaffold created and registered in `.Codex/skills/verify-jalraksha/`
**Next steps**: Implement test runner scripts (Phase 1 prerequisite)
- Ritter exact solution test
- Stoker exact solution test
- Thacker oscillation test
- Lake-at-rest verification
- Mass conservation gate
- Dry-bed robustness check
- Optional: Malpasset and Chamoli benchmark harness
