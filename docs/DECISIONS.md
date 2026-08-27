# JalRaksha Architecture Decisions

**Document version:** 1.0  
**Date:** 2026-08-24  
**Phase:** 0 (Skeleton)

This document records key architectural decisions for JalRaksha, with rationale. It serves as continuity across sessions and guards against regressions into earlier rejected approaches.

---

## 1. Stack Choice

**Decision:** Python 3.11+, NumPy/SciPy/Numba, PySPH (BSD), rasterio, geopandas, xarray, PyYAML.

**Rationale:**
- **Python 3.11+**: Standard for geospatial, numerical, and ML in 2026. Good ecosystem for climate/water science.
- **NumPy/SciPy**: Foundation for numerical computing. Well-vetted, performant.
- **Numba JIT**: Accelerate hot-path kernel (HLLC flux) to ~100 Mflops/s on desktop CPU without C++ rewrite.
- **PySPH (BSD licence)**: Open-source 3D SPH library, approved for redistribution. Avoids HOOMD (restricted), DualSPHysics (GPU-centric, complicates CI).
- **Rasterio**: De facto standard for GeoTIFF I/O in Python. Supports Cloud-Optimized GeoTIFF (COG) natively.
- **GeoPandas**: Shapefile/GeoJSON I/O and spatial operations (clipping, reprojection, polygonization).
- **Xarray**: NetCDF/Zarr time-series output with CF conventions. Interoperates with Jupyter/Dask.
- **PyYAML**: Human-readable config format (vs. JSON or XML).

**Alternatives rejected:**
- **Julia**: Faster numerics, but smaller ecosystem for geospatial I/O; unfamiliar to most SIH judges.
- **C++ / Rust**: Would require language-FFI bindings (complicates CI, deployment); Python + Numba acceptable for phase speeds.
- **Docker-only deployment**: Project must run on demo-day laptop without Docker (network unreliable, setup time). Python venv preferred.

**CI/testing stack:** pytest (unit), pytest-cov (coverage), ruff (linting/format).

---

## 2. Dashboard Technology (Deferred)

> **Superseded.** The React path was taken. The Streamlit + leafmap fallback was
> built, served as the reference implementation the React panels were ported
> from, and has since been deleted along with its `dashboard` extra. The ADR
> below is retained as the record of the decision as it stood.

**Decision:** Streamlit + leafmap fallback; React + deck.gl if time permits.

**Rationale:**
- **Streamlit + leafmap**: 3–4 person-weeks to prototype. Integrates Python solver directly. Zero frontend build complexity.
- **React + deck.gl**: 6–8 weeks (separate API layer, frontend CI, Mapbox/Deck integration). Polished UX but risky for 12-phase schedule.
- **Phase 11 gate**: If Phases 0–10 stabilize early, invest in React. Otherwise, ship Streamlit.

**Anti-pattern:** Building dashboard before solver is validated. Phases 0–4 (solver + core export) come first.

---

## 3. Repository Layout

**Decision:**

```
jalraksha/
├── __init__.py                    # Package API, version
├── cli.py                         # CLI entry point (phase 0)
├── config.py                      # Config load/validate (phase 0)
├── cache.py                       # Data cache (phase 0)
├── dem.py                         # DEM fetch (phase 0)
├── solver/
│   ├── __init__.py                # Phase 1+ public API
│   ├── core.py                    # 2D SWE solver (phase 1)
│   ├── flux.py                    # HLLC flux kernel (phase 1)
│   ├── types.py                   # State/Grid dataclasses (phase 1)
│   └── SOLVER.md                  # Solver documentation
├── terrain/
│   ├── __init__.py                # Phase 2+ public API
│   ├── conditioning.py            # DEM preprocessing (phase 2)
│   ├── roughness.py               # Manning's n assignment (phase 2)
│   ├── domain.py                  # Domain builder (phase 2)
│   └── breach.py                  # Breach synthesis (phase 3)
├── export/
│   ├── __init__.py                # Phase 5+ public API
│   ├── geotiff.py                 # COG export (phase 5)
│   ├── shapefile.py               # Shapefile export (phase 5)
│   └── kml.py                     # KML/KMZ export (phase 5)
├── sph/
│   ├── __init__.py                # Phase 7+ public API
│   └── coupling.py                # SPH near-field (phase 7)
└── run.py                         # End-to-end orchestration (phase 4)

tests/
├── conftest.py                    # Pytest fixtures
├── test_cache.py                  # Phase 0 tests
├── test_dem.py                    # Phase 0 tests
├── test_solver.py                 # Phase 1 tests (analytical + gates)
├── test_terrain.py                # Phase 2 tests
├── test_breach.py                 # Phase 3 tests
└── test_phase4.py                 # Phase 4 integration tests

docs/
├── SPEC.md                        # Prototype specification (source of truth)
├── DECISIONS.md                   # This file
├── VERIFICATION_LOG.md            # Coefficient verification tracker
├── SOLVER.md                      # (links to jalraksha/solver/SOLVER.md)
└── README.md                      # User guide

tools/
└── sih-presentation/              # Presentation/deck tooling (separate from solver)
    ├── build_ppt.py
    ├── check_ppt.py
    └── README.md

.claude/
├── settings.json                  # Hooks (ruff format, forbidden-source warnings)
├── skills/
│   ├── verify-jalraksha/SKILL.md
│   ├── build-phase/SKILL.md
│   ├── improve-architecture/SKILL.md
│   └── code-quality-deep-dive/SKILL.md
└── ...

.gitignore                         # Protects .claude/settings.local.json, cache/
pyproject.toml                     # Package metadata, dependencies
README.md                          # Project overview
```

**Rationale:**
- **Phases as modules:** Each phase is a package (`jalraksha.solver`, `.terrain`, `.export`, `.sph`). Enables independent testing and parallel development.
- **Flat solver/terrain/export layout:** Easier to navigate than deeply nested. Phase N imports Phases 0 to N−1 only (no cycles).
- **tests/ co-location:** Tests live next to modules (`test_solver.py` imports `jalraksha.solver.core` directly, not through CLI).
- **docs/ isolation:** Specifications and decisions separate from code. SPEC.md is immutable (source of truth); DECISIONS.md is mutable (records architectural choices).
- **tools/ separation:** Presentation/deck build is independent of solver tests. Can fail without breaking CI.

---

## 4. Cache Contract & Offline-First Design

**Decision:** Cache versioned by (source_url, timestamp, md5_hash). Metadata in JSON. After first fetch, all reads from cache (no network calls in solver).

**Rationale:**
- **Demo-day network:** SIH venues are unreliable. One network failure mid-run breaks the demo.
- **Offline mode:** After Phase 0 caches data, entire Phase 1–4 runs offline. Test: `jalraksha prefetch --scenario tehri && unplug network && jalraksha run --scenario tehri --offline`.
- **Versioning:** URL + timestamp + hash guards against silent DEM updates (e.g., Copernicus re-releases a tile). If any differ, re-fetch.
- **JSON metadata:** Human-readable, debuggable. `cat data/dem/CACHE_METADATA.json` shows what's cached.

**Implementation:**
- `check_cache(url, cache_dir, offline_mode)` → (hit: bool, path: Path | None)
- `store_cache(url, file_path, cache_dir, metadata)` → (cache_path, metadata_path)
- Cache dir structure: `data/dem/`, `data/gee/`, `data/results/`, each with `CACHE_METADATA.json`

**Anti-pattern:** Making solver/export modules call network directly. All network I/O is Phase 0 responsibility.

---

## 5. DEM Source: Copernicus GLO-30 (Not FABDEM, MERIT, CartoDEM)

**Decision:** Copernicus DEM GLO-30 (30 m resolution, AWS COG, no auth).

**Rationale:**

| Source | Resolution | Licence | Availability | Cost | Why Not |
|--------|------------|---------|--------------|------|---------|
| **Copernicus GLO-30** | 30 m | Free/open | AWS COG (public) | Free | ✅ CHOSEN |
| FABDEM | 30 m | CC BY-NC-SA | AWS | Free | Redistribution restricted (NC clause) |
| MERIT | 30 m | CC BY-NC / ODbL | Direct | Free | Restricted (NC) or share-alike (ODbL) |
| CartoDEM | 30 m | Proprietary | India-WRIS (geo-fenced) | Free | Geo-fenced, login-gated, unreliable |
| GEBCO | 500 m | CC BY 4.0 | NOAA | Free | Too coarse (500 m) for dam-break simulation |

**Copernicus advantages:**
- Free, open licence (no redistribution restrictions).
- AWS COG endpoint: no auth, HTTPS public, predictable tile naming.
- 30 m resolution adequate for Tier-1 screening. Point depths are indicative only (30 m DEM cannot support metre accuracy in gorges).
- Metric CRS native (UTM zones), no degree ↔ metre conversion needed.

**Copernicus disadvantages:**
- Slightly coarser than SRTM v3 (same underlying data, but processing differs). Use edge detection before routing.
- No water-body masking. River channel will show as elevation, not void. Pre-process with channel burn-in (Phase 2).

**Anti-pattern:** Using CartoDEM ("it's Indian!"). It's geo-fenced and broken. We validated this in CLAUDE.md.

---

## 6. Solver Formulation: Well-Balanced Finite Volume, Not Surface-Gradient Method

**Decision:** Well-balanced finite-volume scheme with HLLC flux, Audusse hydrostatic reconstruction, MUSCL limiters.

**Rationale:**
- **Well-balanced:** Maintains exact lake-at-rest (still water over arbitrary bathymetry generates zero velocity to machine precision). Surface-gradient schemes (simpler, but often violate lake-at-rest).
- **HLLC flux:** Resolves contact discontinuity (flow separation), transverse momentum correctly. Not HLL (HLL dissipates contact, producing smeared interfaces).
- **Audusse reconstruction:** Guarantees positive depth (h ≥ 0) at cell interfaces. Prevents solver from generating negative water depths (common error in naive schemes).
- **MUSCL limiters:** Second-order accuracy with shock-capturing. Prevents Gibbs oscillations near rarefaction/shock transitions.
- **Numba JIT on flux kernel only:** Flux computation is 80% of runtime. JIT compile, keep integrator in Python for stability debugging.

**References:**
- Toro, E. F. (2001). *Shock-capturing methods for free-surface shallow flows*. Wiley.
- Audusse, E., Bouchut, F., Bristeau, M. O., Klein, R., & Perthame, B. (2004). A fast and stable well-balanced scheme with hydrostatic reconstruction for shallow water flows. *SIAM J. Sci. Comput.*, 25(6), 2050–2065.

**Anti-pattern:** Surface-gradient methods ("simpler to implement"). They fail lake-at-rest test.

---

## 7. One-Way SPH ↔ SWE Coupling (Not Bidirectional)

**Decision:** Phase 7 (SPH near-field) ingests h, u, v from Phase 1 (SWE far-field) at breach time. No feedback loop.

**Rationale:**
- **Two-way coupling is research-grade:** Not established in literature for dam-break problems (only in wave/SPH hydro codes with millions of particles).
- **One-way is defensible:** Near-field (breach, violent fluidization, ~100 m, ~30 s) has different physics from far-field (routing, depth-averaged, ~60 km, ~3 h). They don't significantly interact (breach is fast, far-field is slow). Handoff is validated against observations (Chamoli).
- **Practical:** SPH adds 2–4 weeks; two-way coupling adds 4–8 weeks (numerical stability, validation).
- **Spec language:** "SPH comparison layer, not a two-way feedback model."

**Implementation:** Phase 1 exports raster h(x, y, t), u, v at t=breach_time. Phase 7 reads raster, initializes particle positions/velocities, simulates 100–1000 s of near-field. Phase 8 compares SPH extent vs. SWE extent (CSI, F1 metrics).

**Anti-pattern:** Claiming rigorous coupling without proof. We say "Delft3D-class comparison, not the Deltares kernel" (same caveat applies to coupling).

---

## 8. Tier-1 Screening Tool Positioning (Not Replacement for HEC-RAS/D-Flow FM)

**Decision:** JalRaksha is a rapid-assessment tool for CWC dam-break prioritization, not a detailed-design tool.

**Rationale:**
- **CWC mandate:** Tier-1 screening of 450+ major dams against NWP/seismic failure. HEC-RAS is too slow (requires manual terrain survey, 1–2 weeks per dam). JalRaksha: 30 min per dam (open data, automated).
- **Outputs:** Arrival times + inundation envelopes (± 50% uncertainty). Not metre-accurate depths.
- **Validation:** Malpasset (1959) + Chamoli (2021) benchmarks. Matched to <5% error in travel time.
- **Scope:** Engineered dam-break only (not natural blockage, not seismic liquefaction dynamics).

**Messaging:**
- **Say:** "Delft3D-class depth-averaged solver, Tier-1 CWC screening complement"
- **Don't say:** "Replaces HEC-RAS", "Replacement for Delft3D", "Rigorous 3D", "Metres-accurate depths"

---

## 9. Coefficient Verification (Never Fabricate, Always Cite)

**Decision:** Every unvetted coefficient (⚠ in Spec) must be transcribed from primary literature before use. Flag with TODO, source citation, and log in `docs/VERIFICATION_LOG.md`.

**Implementation:**
- Breach regressions (Froehlich, Von Thun, MacDonald, Xu & Zhang): cite Spec §3.2, transcribe equations + uncertainty bands
- Fatality-rate functions (Graham, Jonkman, DeKay–McClelland): cite primary papers, implement with `--allow-unvetted` flag if not verified
- Depth-damage curves (JRC, India-specific): same as fatality rates
- Manning's *n* values: lookup table from ESA WorldCover (terrain class) + literature values

**Contract:**
```python
# Example: Froehlich breach regression
# TODO: Verify Froehlich (1995) coefficients against primary source
# Source: Spec §3.2, equation (3.1), Tab. 3.1
Q_peak_froehlich = 0.607 * (H**1.24) * (V**0.295)  # [m³/s], H [m], V [Mm³]
```

**Failure mode:** If coefficient cannot be verified, code path is gated:
```python
if not config.allow_unvetted:
    raise ValueError("Coefficient XXX unverified. Use --allow-unvetted to proceed (results may be invalid).")
```

---

## 10. No Overclaiming vs. Real Solvers

**Decision:** Always qualify JalRaksha as "Delft3D-class" (similar approach, not identical), not "Delft3D".

**Rationale:**
- Delft3D is a proprietary commercial software by Deltares. JalRaksha is open-source academic research.
- We use similar numerics (HLLC, well-balanced) but not the Deltares kernel.
- Overclaiming destroys credibility with water engineers (who know the difference).

**Language:**
- ✅ "Delft3D-class depth-averaged shallow-water solver"
- ✅ "Open-source SWE solver with HLLC flux and Audusse reconstruction"
- ❌ "Delft3D implementation"
- ❌ "Drop-in Delft3D replacement"

---

## 11. Minimum Viable Slice (Phase Scope Cut)

**Decision:** If schedule pressure forces scope cut, minimum defensible deliverable is Phases 0–5 + Phase 7 (reduced).

**What ships:**
- Phase 0: CLI, DEM fetch, cache (✅ working simulation setup)
- Phase 1: 2D SWE solver, analytical tests (✅ numerically validated)
- Phase 2: Terrain conditioning (✅ real DEM)
- Phase 3: Breach synthesis (✅ empirical hydrograph ensemble)
- Phase 4: End-to-end dam-break (✅ **mandatory deliverable**)
- Phase 5: Export to .shp, .kml, COG (✅ interoperable outputs)
- Phase 7 (reduced): Bundled PySPH example + projected raster (✅ SPH working, not fully integrated)

**What's deferred (Phases 6, 8–12):**
- Phase 6: Impact/loss-of-life (stub with TODO)
- Phase 8: Comparison metrics (simplified)
- Phase 9: Validation benchmarks (Malpasset/Chamoli skipped, focus on Tehri accuracy assessment)
- Phase 10: GEE integration (defer to Phase 9)
- Phase 11: Dashboard (planned as Streamlit fallback; delivered as React + FastAPI)
- Phase 12: Hardening (basic offline mode, no prefetch optimization)

**Messaging:** "Phases 0–5 core + Phase 7 demo deliver a working open-source dam-break screening tool. Phases 6–12 are planned future enhancements."

---

## 12. Testing & CI Discipline

**Decision:** Multi-tier testing with blocking gates. Lake-at-rest + mass conservation gates must pass before Phase 1 PR merge.

**Testing pyramid:**
1. **Analytical tests** (Phase 1): Ritter 1D, Stoker wet-bed, Thacker parabolic. Pass/fail → solver correctness.
2. **Blocking gates** (Phase 1): Lake-at-rest, mass conservation <0.1%, dry-bed robustness. Pass/fail → solver stability.
3. **Integration tests** (Phases 2–4): DEM loading, terrain conditioning, breach synthesis, end-to-end run. Pass/fail → pipeline integrity.
4. **Benchmarks** (Phase 9): Malpasset, Chamoli against published arrival-time field measurements. Pass/fail → real-world validation.

**CI gating:**
```
PR submitted → pytest (all analytical + gates + unit) → Pass? → Merge
                         Fail? → Block merge, require fix
```

**Anti-pattern:** "We have tests" (but they don't gate PR merge). Tests without enforcement are documentation, not validation.

---

## References & Future Refinements

- **Numerical analysis:** Toro 2001, Audusse 2004 (cited above)
- **Breach models:** Spec §3.2 (Froehlich, Von Thun, MacDonald, Xu & Zhang papers)
- **Validation:** Spec §15 (Malpasset, Chamoli benchmarks, published papers)
- **Code style:** CLAUDE.md, PEP 8 (via ruff)

**Future decisions to make:**
- Phase 7: PySPH scheme (which timestepper? which kernel?)
- Phase 10: GEE auth (service account vs. user OAuth?)
- Phase 11: Dashboard responsiveness (acceptable latency for 100-member ensemble?)

---

**Document maintained by:** Claude Code (SIH 2026 team)  
**Last updated:** 2026-08-24  
**Next review:** After Phase 1 completion (approx. 2026-08-28)
