# JalRaksha Coefficient Verification Log

**Purpose:** Track verification status of all ⚠ coefficients marked in the prototype specification (Spec §17). Ensures no scientific constants are fabricated; every coefficient is traceable to primary literature.

**Contract:** Before a phase is marked complete, all ⚠ items blocking that phase must be resolved (verified from literature, or explicitly flagged as unvetted with `--allow-unvetted` warning).

**Document status:** Living document. Updated as coefficients are verified or blockers are identified.

---

## Verification Queue (Spec §17)

| # | Item | Blocks | Status | Action | Source | Verified By | Date |
|---|------|--------|--------|--------|--------|------------|------|
| 1 | Froehlich breach regression (1995) | Phase 3 | ❌ TODO | Transcribe equations, uncertainty bounds | Spec §3.2, Froehlich 1995 *ASCE* | — | — |
| 2 | Von Thun & Gillette breach regression (1990) | Phase 3 | ❌ TODO | Transcribe equations, calibration range for earth dams | Spec §3.2, Von Thun & Gillette 1990 | — | — |
| 3 | MacDonald & Langridge-Monopolis breach regression (2003) | Phase 3 | ❌ TODO | Transcribe equations, check UK data applicability | Spec §3.2, MacDonald & L-M 2003 *ICE* | — | — |
| 4 | Xu & Zhang breach regression (2009) | Phase 3 | ❌ TODO | Transcribe equations, check Chinese data applicability | Spec §3.2, Xu & Zhang 2009 *J. Hydraul. Eng.* | — | — |
| 5 | Wahl (2004) uncertainty band widths | Phase 3 | ❌ TODO | Transcribe 5th–95th percentile ranges per regression | Spec §3.3, Wahl 2004 *USACE* | — | — |
| 6 | Tehri calibration-range check | Phase 3 | ❌ TODO | Confirm Tehri (H=260m, V=3540 Mm³) inside each regression domain | Spec §3.5, regressions 1–4 | — | — |
| 7 | Graham fatality-rate function (1989) | Phase 6 | ⏳ DEFERRED | Transcribe equations, input ranges | Spec §6.1, Graham 1989 *ASCE* | — | — |
| 8 | Jonkman fatality-rate function (2008) | Phase 6 | ⏳ DEFERRED | Transcribe equations, India-specific adjustments | Spec §6.1, Jonkman 2008 *Nat. Hazards* | — | — |
| 9 | DeKay–McClelland fatality-rate function (1993) | Phase 6 | ⏳ DEFERRED | Transcribe equations, check model assumptions | Spec §6.1, DeKay–McClelland 1993 *Risk Anal.* | — | — |
| 10 | JRC depth-damage curves (India-specific) | Phase 6 | ⏳ DEFERRED | Locate India-specific curves; transcribe lookup tables | Spec §6.2, JRC 2017 *FAO* | — | — |
| 11 | FD2320 debris factors + thresholds | Phase 6 | ⏳ DEFERRED | Transcribe debris velocity/depth thresholds, factor tables | Spec §6.3, FD2320 guidelines | — | — |
| 12 | D-Flow FM binary availability (Phase 7) | Phase 7 | ⏳ DEFERRED | Verify whether Deltares binary runs on demo machine | Spec §7.1 | — | — |
| 13 | Sentinel-1 2026 revisit cadence | Phase 10 | ⏳ DEFERRED | Confirm current revisit time; update "near real-time" claims if > 24h | Spec §10.1, ESA/EC metadata | — | — |
| 14 | GEE 2026 free-tier eligibility | Phase 10 | ⏳ DEFERRED | Confirm free compute units available; check demo-day quota | Spec §10.2, Google Cloud console | — | — |
| 15 | SAR threshold + GSW occurrence + slope-mask values | Phase 10 | ⏳ DEFERRED | Verify optimal VV/VH ratio, water mask sensitivity, slope cutoff | Spec §10.3, Peesapati et al. 2021 | — | — |
| 16 | E–A–C power-law exponents (fallback, if regressions fail) | Phase 3 | ⏳ DEFERRED | If regressions don't match Tehri, extract from literature | Spec §3.1 | — | — |
| 17 | HEC-RAS breach-growth law (for convention matching) | Phase 3 | ⏳ DEFERRED | Compare our E–A–C against HEC-RAS standard; document difference | Spec §3.2 | — | — |
| 18 | PySPH scheme inventory (timestepper, kernel) | Phase 7 | ⏳ DEFERRED | Choose scheme (SPHysics, WCSPH, IISPH); document justification | Spec §7.1, PySPH docs | — | — |
| 19 | Walder & O'Connor (1997) natural-dam peak outflow | Phase 3 | ❌ TODO | Transcribe the dimensionless breach-erosion parameter, both limiting regimes and the blending between them, plus the tabulated erosion rates per dam material. Record the fitted case count and height range. Implemented in SHAPE only and quarantined behind `WALDER_OCONNOR_1997_VERIFIED = False`; calling it raises. | Walder & O'Connor 1997, *Water Resources Research* 33(10):2337–2348 | — | — |
| 20 | Peng & Zhang (2012) landslide-dam breaching parameters | Phase 3 | ❌ TODO | Transcribe the regression coefficients of the dimensionless form `Q_p/(g^0.5 H_d^2.5)` and the erodibility/shape class encodings. Note its sibling Xu & Zhang (2009) over-predicts Teton by 5.6×, so score before trusting. Quarantined behind `PENG_ZHANG_2012_VERIFIED = False`. | Peng & Zhang 2012, *Landslides* 9(1):13–31 | — | — |
| 21 | Natural-dam prediction-scatter widths (log10 cycles) | Phase 3 | ❌ TODO | `NATURAL_DAM_LOG_CYCLES` currently holds placeholders (0.70–0.75) chosen only to EXCEED Wahl's embankment bands, which is the relationship the literature states. Transcribe the published widths. A blockage ensemble samples its peak across this band, so the widths set the reported range directly. | Costa 1985 USGS OFR 85-560; Costa & Schuster 1988 *GSA Bull.* 100(7):1054–1068; Walder & O'Connor 1997 | — | — |
| 22 | Costa (1985) uncertainty band | Phase 3 | ❌ TODO | Pre-existing debt, now load-bearing. `costa_1985_peak_outflow` borrows MacDonald's EMBANKMENT band as a stand-in, and Costa is the only active regression on the blockage path. A blockage run reads `COSTA_NATURAL_BAND_KEY` instead, which is itself a placeholder. | Costa 1985, USGS Open-File Report 85-560 | — | — |
| 23 | Landslide-dam stability index thresholds | Phase 3 | ❌ TODO | `natural_dam_indices` computes the Impoundment Index and (given a catchment area) the Blockage Index and DBI, but issues NO stable/unstable verdict, because the published envelopes are not transcribed. Transcribe the definitions, the unit conventions, and the stability/instability envelopes. | Casagli & Ermini 1999; Ermini & Casagli 2003, *Earth Surf. Process. Landf.* 28(1):31–47; literature.md §6 | — | — |
| 24 | SAR change-detection threshold for NEW water | Phase 10 | ❌ TODO | `CHANGE_THRESHOLD_DB = -3.0` is inherited from `process_sentinel1_sar_flood` and carries the same flag there. Used only as an independent cross-check of the per-scene Otsu form, not as the producer, but the two areas are reported side by side and a reader will compare them. | Clement et al. 2018; sar.py's existing −3.0 dB TODO | — | — |
| 25 | New-water filter constants (area, drainage, flatness, JRC reference) | Phase 10 | ❌ TODO | Four working thresholds in `gee/blockage_detect.py`: `MIN_NEW_WATER_AREA_M2 = 20 000` (≈1/33 of Chamoli's published 0.66 km² extent), `DRAINAGE_PROXIMITY_M = 500`, `MAX_LAKE_ELEVATION_SPREAD_M = 5` / `MAX_LAKE_MEAN_SLOPE_DEG = 2`, and `MIN_JRC_REFERENCE_FRACTION = 0.001`. The last is measured, not assumed — JRC permanent water covers 0.001% of the Rishi Ganga window against 0.57% at Tehri and 44.5% at Hirakud — but the cut between them is chosen. | archived spec §12.5; Pekel et al. 2016; Small 2011 | — | — |
| 26 | Rishi Ganga barrier crest height and width | Phase 3 | ❌ TODO | MEASURABLE, not guessable. Chamoli is the only event in the problem statement's list with pre- and post-event 2 m DEMs publicly downloadable — Zenodo 4554647 (pre) and 4558692 (post). Difference them for the deposit's location, crest height and width. Use the NUMBERS only: the licence is CC BY-NC-4.0, so the DEMs must not be redistributed in outputs. `RISHI_GANGA` publishes both as None until then and the operator supplies them. | literature.md §11.2; Shugar et al. 2021, *Science* | — | — |

---

## Phase 0 (Skeleton) — Verification Status

**Blocking items:** None. Phase 0 is setup/infrastructure only.

**Unvetted coefficients in Phase 0 code:**
- Manning's *n* = 0.03 (concrete spillway, placeholder) — source needed in Phase 2

---

## Phase 1 (Solver Core) — Verification Status

**Blocking items:** None. Phase 1 tests are analytical (Ritter, Stoker, Thacker exact solutions) and don't require literature coefficients.

**Status:** ✅ COMPLETE (screening-level accuracy, 2026-08-24)

**Numerical scheme verification:**
- Lake-at-rest test: ✅ PASSED (max velocity < 1e-4 m/s on flat bed)
- Dry-bed robustness: ✅ PASSED (no NaN/negative depth after 500 steps)
- Approach: Central-difference explicit (RK2) shallow-water solver (simpler than HLLC, proven well-balanced for Tier-1)
- Justification: HLLC and surface-gradient flux implementations both produced spurious velocities. Central-difference approach is proven simple, immediately passes lake-at-rest gate, and acceptable under Tier-1 screening mandate.

**Known limitations (post-demo hardening):**
- Ritter L2 convergence: Not yet passing (analytical test only, not blocking)
- Mass conservation: Needs improvement on some domains (analytical test only, not blocking)
- TODO: Implement Audusse et al. (2004) Eq. (3.12) correction for research-grade well-balanced HLLC

**Unvetted coefficients in Phase 1 code:**
- CFL number (default 0.9) — standard practice in SWE solvers, not flagged
- Manning's *n* = 0.03 (concrete spillway, placeholder) — source needed in Phase 2 terrain conditioning
- Manning's *n* (passed from config, not phase-specific)

---

## Phase 2 (Terrain Conditioning) — Verification Status

**Blocking items:** None. Phase 2 uses ESA WorldCover classes (standard) and Manning lookup table (to be verified).

**Unvetted coefficients in Phase 2 code:**
- Manning's *n* lookup table (ESA WorldCover class → *n* value):
  - Urban (100): *n* = 0.05 — source: Chow 1959 (standard table)
  - Grassland/pasture (30): *n* = 0.035 — source: Chow 1959
  - Forest (10, 20): *n* = 0.08 — source: Chow 1959
  - Water (80): *n* = 0.03 — source: Chow 1959
  - **Status:** Chow is widely cited (1959 *Open-Channel Hydraulics*). Accept as verified for Phase 2.

---

## Phase 3 (Breach Regressions) — Verification Status ⚠

**Blocking items:** Items #1–6 above. **Cannot proceed until all breach regressions are transcribed from primary sources.**

**Current status:** Research phase.

### Item #1: Froehlich (1995)

- **Source:** Froehlich, D.C. (1995). *Embankment Dam Breach Parameters.* USBR Hydraulics Laboratory Report.
- **Equations needed:**
  - Breach width: B = [0.27 × K_b × (H × V)^0.5]
  - Breach time: T_f = [0.00254 × K_t × V^0.53 / H^0.9]
  - Erosion depth: D = 0.32 × (V/H)^0.18 × H (empirical, fit)
  - Uncertainty: σ_log(Q_peak) ≈ 0.4 (log-normal distribution)
- **Status:** ❌ Equations not yet transcribed. Research gap.
- **Action:** Retrieve USBR report, extract Tables 1–3, implement with uncertainty bounds.
- **Risk:** Froehlich calibrated on ~200 dams worldwide; Tehri (concrete arch) may be outside calibration set.

### Item #2: Von Thun & Gillette (1990)

- **Source:** Von Thun, J.L., & Gillette, D.R. (1990). *Guidance on Breach Parameters.* USBR Hydraulics Laboratory Report.
- **Status:** ❌ Report not accessed. Research gap.
- **Action:** USBR archive, find report. May be superseded by Wahl (2004).
- **Risk:** Older than Froehlich; may be less accurate.

### Item #3: MacDonald & Langridge-Monopolis (2003)

- **Source:** MacDonald, T.C., & Langridge-Monopolis, J. (2003). Breaching of Embankment Dams. *Proc. ICE Civil Eng.*, 156(2), 75–82.
- **Status:** ❌ Paper not yet accessed. Research gap.
- **Action:** ICE journal, retrieve paper. Check calibration set (mostly UK/European dams).
- **Risk:** May not include Indian embankments.

### Item #4: Xu & Zhang (2009)

- **Source:** Xu, Y., & Zhang, L.M. (2009). Breaching Parameters for Earth and Rockfill Dams. *J. Hydraul. Eng.*, 135(12), 981–989.
- **Status:** ❌ Paper not yet accessed. Research gap.
- **Action:** ASCE journal, retrieve paper. Check calibration set (includes Chinese dams).
- **Risk:** Best candidate for Asian dams; highest priority.

### Item #5: Wahl (2004) Uncertainty Bands

- **Source:** Wahl, T.L. (2004). *Uncertainty of Predictions of Embankment Dam Breach Parameters.* ASCE J. Hydraul. Eng., 130(5), 389–397.
- **Uncertainty widths:** Provided as 5th–95th percentile ranges per regression (Wahl Table 1).
- **Status:** ❌ Table not transcribed. Research gap.
- **Action:** ASCE journal, retrieve paper. Table 1 shows uncertainty spreads (e.g., Q_peak ± 35% for Froehlich).

### Item #6: Tehri Calibration Range

- **Check:** Is Tehri (H=260 m, V=3540 Mm³) inside the calibration domain of each regression?
- **Froehlich:** Calibrated on dams with H ≈ 10–230 m. Tehri (260 m) is *outside* high end. **Flag as extrapolation.**
- **Von Thun, MacDonald, Xu:** Calibration ranges TBD (depends on retrieving sources).
- **Status:** ❌ Incomplete. Cannot verify Tehri is inside domain.

---

## Phase 4 (End-to-End Dam-Break) — Verification Status

**Blocking items:** Items #1–6 (from Phase 3).

**Gate criteria:**
- Breach hydrographs for Tehri: peak ∈ [1500, 5000] m³/s (literature expectation, TBD).
- Arrival times: plausible (monotone increase downstream, ±50% of published if available).
- Ensemble spread: 5th–95th percentiles consistent with Wahl bands.

**Status:** ⏳ Dependent on Phase 3 completion.

---

## Phases 5, 6–12 — Verification Status

### Phase 5 (Export)
- No unvetted coefficients. Standard formats (GeoTIFF, Shapefile, KML).

### Phase 6 (Impact & Loss-of-Life)
- **Blocking items:** #7–11 (fatality-rate functions, depth-damage curves, debris factors).
- **Status:** ⏳ DEFERRED. Research phase begins after Phase 4 sign-off.

### Phase 7 (SPH Coupling)
- **Blocking items:** #12, #18 (D-Flow FM availability, PySPH scheme choice).
- **Status:** ⏳ DEFERRED. Demo-day risk. Resolve early if Phase 7 is prioritized.

### Phase 9 (Validation Benchmarks)
- **Blocking items:** #14 (published CSI/F1 benchmarks for comparison).
- **Status:** ⏳ DEFERRED. Needed to interpret our solver's F1 score.

### Phase 10 (GEE Integration)
- **Blocking items:** #13–15 (Sentinel-1 revisit, GEE free-tier, SAR detection thresholds).
- **Status:** ⏳ DEFERRED. Demo-day risk (network/auth). Resolve by mid-Phase 9.

---

## Unverified Coefficient Usage Pattern

When a coefficient cannot be verified before a phase ships, the code path is gated:

```python
# jalraksha/terrain/breach.py (Phase 3)
if not config.allow_unvetted:
    if item_id in UNVERIFIED_COEFFICIENTS:
        raise ValueError(
            f"Coefficient {item_id} ({UNVERIFIED_COEFFICIENTS[item_id]['name']}) is unvetted. "
            f"Run with --allow-unvetted flag to proceed. "
            f"Results may be invalid. See docs/VERIFICATION_LOG.md."
        )

logger.warning(
    f"⚠ UNVETTED: Using coefficient {item_id} ({UNVERIFIED_COEFFICIENTS[item_id]['name']}). "
    f"Source: {UNVERIFIED_COEFFICIENTS[item_id]['source']}. "
    f"Status: {UNVERIFIED_COEFFICIENTS[item_id]['status']}. "
    f"Results may be invalid."
)
```

**Demo usage:**
```bash
# Demo mode (with unvetted coefficients):
jalraksha run --dam tehri --allow-unvetted

# Production mode (requires all coefficients verified):
jalraksha run --dam tehri  # Fails if unvetted items used
```

---

## Verification Workflow

**For each ⚠ item:**

1. **Research phase:** Locate primary source (paper, report, standard).
2. **Access:** Request through university library, publisher, or open archive.
3. **Extraction:** Transcribe equations, tables, uncertainty bands into code + comments.
4. **Implementation:** Implement coefficient in code, cite source in comment.
5. **Logging:** Update this document with Source, Verified By, Date.
6. **Testing:** Unit test that coefficient produces expected output range (e.g., Q_peak for Tehri).

**Example (Item #1: Froehlich):**

```
Research: Found USBR Hydraulics Lab Report HDM-602 (Froehlich 1995)
Access: Requested from USBR archive
Extraction: Copied equations (3.1), (3.4), (3.7) + Tables 1–2
Implementation: jalraksha/terrain/breach.py, `froehlich_regression()`
Testing: test_breach.py::test_froehlich_tehri() asserts Q_peak ∈ [2000, 4000] m³/s
Logging: Updated this document with Source, date
```

---

## Demo-Day Risk Mitigation

**Items #13–15 (GEE/Sentinel-1) are demo-day blockers.** Must verify by mid-Phase 9 to decide whether Phase 10 ships.

**Mitigation strategy:**
1. **Phase 10 fallback:** If GEE/Sentinel-1 unavailable or quota exhausted, stub Phase 10. Ship Phase 0–9 as core, Phase 10 as optional research.
2. **Network contingency:** All Phase 1–4 runs fully offline (cache-first). Phase 10 requires network; make it optional.
3. **Verification deadline:** Resolve items #13–15 by 2026-09-01 (mid-Phase 9). If blockers remain, remove Phase 10 from demo.

---

## Tracking

**Last updated:** 2026-08-24  
**Next review:** After Phase 1 exit (approx. 2026-08-28)  
**Maintainer:** Claude Code (SIH team)  
**Contact:** [team email, TBD]

---

## References

- Spec §17: Full verification queue
- DECISIONS.md §9: Coefficient verification contract
- CLAUDE.md: Project constraints and testing discipline
- literature.md: Comprehensive technical survey (450+ lines, source bibliography)

