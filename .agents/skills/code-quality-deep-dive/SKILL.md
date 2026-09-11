---
name: code-quality-deep-dive
description: Comprehensive code quality review of JalRaksha solver code. Checks correctness (numerical stability, flux schemes, boundary conditions), performance (Numba JIT efficiency, memory access patterns), safety (division by zero, NaN propagation, dry-bed handling), and compliance (unvetted coefficients, metric CRS, licensing).
disable-model-invocation: true
---

## Overview

The `/code-quality-deep-dive` skill performs an exhaustive review of code changes, focusing on the rigorous numerical and safety requirements of a dam-break solver:

1. **Correctness** — Flux schemes, reconstruction, boundary conditions, time integration
2. **Performance** — Numba JIT compilation, memory layout, vectorization
3. **Safety** — Division by zero, NaN/Inf handling, dry-bed robustness
4. **Compliance** — Unvetted coefficients flagged, metric CRS verified, licensing declared
5. **Testing** — Analytical test coverage, benchmark integration

## When to Use

- Before merging Phase 1 (solver core) changes
- After modifying the HLLC flux scheme or Audusse reconstruction
- When adding new coefficients or parameters (breach regression, Manning's n, etc.)
- Before committing changes that touch the wet/dry transition or friction term
- On any PR touching numerical code (not just formatting/docs)

## Usage

```
/code-quality-deep-dive --phase 1
# Deep review of Phase 1 (solver) code

/code-quality-deep-dive --file src/solver/flux.py
# Review a specific module in detail

/code-quality-deep-dive --pr-branch my-hllc-fix
# Review all changes on a branch before PR

/code-quality-deep-dive --quick
# Fast pass: checks only critical safety gates (dry-bed, NaN, negatives)
```

## Checklist

### Correctness (Numerical Physics)
- [ ] Flux scheme matches stated method (HLLC with transverse-momentum correction, not HLL)
- [ ] Reconstruction is Audusse hydrostatic, not surface-gradient
- [ ] Slope limiters are MUSCL (not minmod or van Leer unless documented)
- [ ] Boundary conditions: inflow/outflow/wall correctly applied
- [ ] Time integration preserves CFL stability (explicit: CFL ≤ 1, implicit: verified by tests)
- [ ] Source terms (friction, bed slope) use correct signs
- [ ] Manning's n units are correct (s/m^(1/3), not inverted)
- [ ] All operations use **metric CRS** (never degrees or mixed units)

### Performance (Numba JIT)
- [ ] Flux kernel decorated with `@njit(parallel=True, fastmath=True)`
- [ ] No Python objects in inner loops (all arrays, scalars, tuples)
- [ ] Memory access is row-major (Fortran order for large arrays) or verified cache-friendly
- [ ] No type mismatches that trigger slow path (all float64 or consistent precision)
- [ ] Integrator avoids `fastmath=True` to preserve stability

### Safety (Robustness)
- [ ] Division by zero guards: `depth < 1e-6` before computing velocity `u = momentum / depth`
- [ ] NaN checks: after each computed velocity, check `~np.isnan(u)` or use safe divide
- [ ] Negative depths rejected: `depth = np.maximum(depth, 0)` after update
- [ ] Dry-bed robustness: test passes Ritter dry-bed without crashes
- [ ] Friction term bounded: Manning's n ≥ 0, no infinite friction
- [ ] Eigenvalue safeguards: wave speeds clamped to prevent supercritical errors

### Compliance & Documentation
- [ ] All coefficients have source citations (e.g., "Manning's n = 0.03 per Chow 1959, p. 123")
- [ ] Unvetted coefficients flagged with `# TODO: UNVETTED` + source requirement (per AGENTS.md)
- [ ] Coordinate system declared: "All operations in EPSG:32643 metric UTM"
- [ ] Data licensing noted if used: "Copernicus DEM (free), Google Buildings (CC BY 4.0)"
- [ ] No hard-coded paths to India-WRIS, Bhuvan, or CartoDEM

### Testing Coverage
- [ ] Analytical test (Ritter, Stoker, or Thacker) covers modified code path
- [ ] Lake-at-rest test passes if solver touches hydrostatic term
- [ ] Mass conservation test passes if code modifies flux or time step
- [ ] Dry-bed robustness passes if code touches depth checks or velocity
- [ ] Benchmark (Malpasset or Chamoli) re-runs if breach or Manning parameters change

## Critical Failures (Automatic Block)

Any of these blocks the PR:
- **Negative depth after update** → NaN propagation risk
- **Division by zero without guard** → Crash or Inf
- **fastmath=True in integrator** → Loss of precision, instability
- **Unvetted coefficient without TODO** → Verification gate failure
- **Non-metric CRS detected** → Wrong scale, incorrect results
- **Ritter or lake-at-rest test fails** → Core solver broken

## Output Format

```
PHASE 1 SOLVER CODE REVIEW
==========================

✓ Correctness: HLLC scheme verified, Audusse reconstruction correct
✓ Performance: Numba JIT is tight, memory layout optimal
✗ Safety: CRITICAL — Division by zero on line 42 (depth check missing)
✗ Compliance: Unvetted coefficient "Manning's n = 0.03" flagged without source

Blocking Issues:
  1. Line 42: u = momentum / depth  [guard: if depth < 1e-6]
  2. Line 108: FLAG TODO: Manning's n from Chow (1959)?

Passing Tests:
  ✓ Ritter dry-bed (L∞ error 0.8%)
  ✗ Lake-at-rest (velocity drift 0.15%) → Check hydrostatic term

Recommendation: Fix division guard and flag Manning source before merge.
```

## Notes

- This is a **blocking review** for Phase 1–4 changes (solver core, end-to-end)
- Optional but encouraged for Phases 5+ (export, GEE, dashboard)
- Reuses verification tests from `/verify-jalraksha`
- Focuses on numerical rigor — style/formatting are handled by ruff hook

## Design Philosophy & Patterns

Based on cursor/plugins "Thermos" approach:
- **Deep security/correctness audits** with harsh quality standards
- **Parallel subagents** for independent module analysis
- **Thermos orchestration** to coordinate findings and report

Applied to JalRaksha:
- Solver correctness (flux schemes, boundary conditions, time integration)
- Performance profiling (Numba JIT efficiency, memory patterns)
- Safety gates (NaN propagation, division by zero, dry-bed robustness)
- Compliance checks (unvetted coefficients, metric CRS, licensing)

## Status (Aug 2026)

**Initialized**: Skill scaffold created and registered in `.Codex/skills/code-quality-deep-dive/`
**Inspired by**: cursor/plugins Thermos deep-audit pattern
**Next steps**: Implement multi-agent review harness
- Parallel agents for correctness, performance, safety, compliance
- Aggregate findings with severity ranking (critical block → warning → info)
- Auto-gate Phase 1–4 PRs on critical findings
- Generate structured review report (markdown + JSON)

**Integration**: Blocks Phase 1–4 PRs; optional for Phases 5+
**Related**: Works with `/verify-jalraksha` (uses test results) and `/improve-architecture` (structural health)
