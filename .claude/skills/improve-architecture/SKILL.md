---
name: improve-architecture
description: Surface deepening opportunities in JalRaksha codebase. Identifies shallow modules, tight coupling, and testability friction. Presents candidates as an HTML report, then grills through selected refactoring with domain model updates and ADR generation.
disable-model-invocation: true
---

## Overview

The `/improve-architecture` skill performs structural analysis and proposes **deepening opportunities**: refactors that turn shallow modules into deep ones, improving testability, AI-navigability, and phase independence.

Based on John Ousterhout's *A Philosophy of Software Design* (deep modules principle) and mattpocock/skills `improve-codebase-architecture` pattern.

## Design Vocabulary

- **Module**: Coherent unit of code (package, submodule, or class hierarchy)
- **Depth**: Functionality relative to interface complexity (deep = high ratio)
- **Seam**: Boundary between modules (one adapter = hypothetical, two+ = real)
- **Locality**: Related logic clustered together, not scattered
- **Shallow module**: Interface nearly as complex as implementation (friction point)
- **Deletion test**: Would removing it concentrate complexity (signal for deepening) or just move it?

## Three-Phase Process

### Phase 1: Explore
1. **Scope before scanning** (YAGNI principle):
   - Identify hot spots from git history (`git log --oneline`)
   - Read `CONTEXT.md` (domain glossary) and ADRs first
   - Spawn sub-agent to explore organically for friction:
     - Where does understanding require bouncing between many small modules?
     - Which modules are **shallow** (interface ≈ implementation)?
     - Where are pure functions extracted just for testability but bugs hide in call patterns?
     - Where do tightly-coupled modules leak across seams?
     - Which parts are untested or hard to test?

2. **Apply deletion test**:
   - Would deleting it concentrate complexity? → Signal for deepening
   - Or just move it? → Might not be deep enough

### Phase 2: Present Candidates as HTML Report
1. **Generate interactive HTML**:
   - Write to temp directory: `$TMPDIR/architecture-review-<timestamp>.html`
   - Auto-open (`xdg-open`/`open`/`start`)
   - Tailwind CDN + Mermaid CDN for diagrams

2. **Each candidate card includes**:
   - Files/modules involved
   - Problem statement (why friction)
   - Solution (plain English)
   - Benefits (locality, leverage, test improvements)
   - Before/After diagram (side-by-side)
   - Recommendation strength: `Strong` | `Worth exploring` | `Speculative`

3. **Top recommendation** section highlighting which candidate to tackle first

4. **Conventions**:
   - Use `CONTEXT.md` vocabulary for domain names
   - Use design vocabulary exactly (deep/shallow, seam, locality, etc.)
   - Flag ADR conflicts only when friction warrants revisiting
   - Do NOT propose interfaces yet; ask user which candidate to explore

### Phase 3: Grilling Loop
1. User picks a candidate from HTML report
2. Run **grilling** decision tree:
   - Constraints on refactoring
   - Dependencies that would shift
   - Shape of deepened module
   - Seam details (what becomes public?)
   - Test survival (which existing tests still pass?)

3. Update **CONTEXT.md** (lazily created if missing):
   - New deepened module concept? Add to domain glossary
   - Fuzzy term sharpened? Update vocabulary
   - User rejects with load-bearing reason? Create ADR to prevent re-suggestion

4. Generate ADR if major decision:
   - Decisions crystallize inline as grilling progresses
   - Documentation stays current

## When to Use

- After Phase 0 skeleton is drafted (CLI, data cache entry points defined)
- Before Phase 1 (solver core) to validate module boundaries
- When refactoring between phases to prevent technical debt
- To prepare for the 18-phase delivery schedule
- Proactively after hot-spot commits

## Typical Workflow

```
/improve-architecture explore phase 0
# Scan Phase 0, identify friction, generate HTML report

/improve-architecture grill solver-core
# Deep-dive grilling on solver-core deepening candidate
# Updates CONTEXT.md and generates ADRs as needed

/improve-architecture full
# Full codebase scan with candidates across all phases
```

## Checks for JalRaksha

**Module Structure:**
- Solver core isolated from I/O and CLI logic
- Terrain conditioning in separate module from solver
- Breach regression calculations decoupled from dynamics
- Export logic (GeoTIFF, Shapefile, KML) grouped, not scattered
- SPH and 2D SWE solvers independently importable
- Unvetted coefficients isolatable in config, not embedded in solver

**Dependency Direction (Phase Order):**
- Phase 0 (skeleton) has no Phase 1+ dependencies
- Phase 1 (solver) can depend on Phase 0 but not Phases 2+
- Phase 4 (end-to-end) can depend on Phases 0–3 but not Phases 5+
- Phases build on earlier, never backward

**Layer Violations (Seams):**
- CLI shouldn't call solver internals directly (use interface module)
- Tests shouldn't import from main entry point (import from modules)
- Configuration shouldn't be hardcoded in solver (use config objects)
- Breach model shouldn't depend on export format

**Testability & Locality:**
- Can Phase 1 solver run offline without GEE (Phase 8)?
- Can Phase 7 (SPH) be swapped without modifying Phase 4 (SWE)?
- Are magic numbers (Manning's n, time step, CFL) in a configuration file?
- Are analytical tests co-located with solver modules?

## Output Format (HTML Report)

```html
<!-- Each candidate card includes: -->
<div class="candidate">
  <h3>Deepen solver.flux_kernel (HLLC scheme)</h3>
  <p class="problem">Flux computation scattered across 3 files; tests import internals</p>
  <p class="solution">Move to jalraksha.solver.flux with public interface (state, fluxes)</p>
  <p class="benefits">Locality ↑, testability ↑, SPH coupling ↓ coupling</p>
  <div class="before-after"><!-- Mermaid diagram --></div>
  <span class="strength">Strong</span>
</div>
```

## Key Files Referenced

- `CONTEXT.md` — Domain glossary (lazy-created)
- `docs/adr/` — Architecture Decision Records (generated as needed)
- CLAUDE.md — Phase boundaries and phase dependencies

## Side Effects

All domain model updates and ADR creation happen inline as decisions crystallize during grilling, keeping documentation current.

## Status (Aug 2026)

**Initialized**: Skill scaffold with full workflow
**Inspired by**: mattpocock/skills `improve-codebase-architecture` + John Ousterhout deep modules principle
**Integrated patterns**: 
- Three-phase explore → present → grill workflow
- HTML report generation with Tailwind + Mermaid
- CONTEXT.md domain glossary updates
- ADR generation on major decisions
- Deletion test for shallow module detection

**Next steps**: Implement
- Module scanner (git history, import graph, test co-location)
- HTML report generator with before/after diagrams
- Grilling decision tree CLI
- CONTEXT.md and ADR writers

**Integration**: Works alongside `/code-quality-deep-dive` and `/build-phase` for holistic code health
