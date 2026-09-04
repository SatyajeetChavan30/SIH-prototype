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
| 25 | New-water filter constants (area, drainage, flatness, JRC reference) | Phase 10 | ❌ TODO | Four working thresholds in `gee/blockage_detect.py`: `MIN_NEW_WATER_AREA_M2 = 20 000` (≈1/33 of Chamoli's published 0.66 km² extent), `DRAINAGE_PROXIMITY_M = 500`, `MAX_LAKE_ELEVATION_SPREAD_M = 5` / `MAX_LAKE_MEAN_SLOPE_DEG = 2`, and `MIN_JRC_REFERENCE_FRACTION = 0.001`. The last is measured, not assumed — JRC permanent water covers 0.001% of the Rishi Ganga window against 0.57% at Tehri and 44.5% at Hirakud — but the cut between them is chosen. **Now exercised against real events** (`docs/validation_findings.md` §9, `scripts/detect_blockage_experiment.py`): over Baige and Rishi Ganga the drainage gate refuses at 10–16% against its 80% requirement and the flatness gate refuses by 186× on spread (933–3,258 m vs 5 m) and 16× on slope (31–36° vs 2°), so both are far from their thresholds and neither value is currently load-bearing; the area floor is exceeded by 900× on a garbage mask and does nothing. `MIN_JRC_REFERENCE_FRACTION` correctly separates Rishi Ganga (0.0008%/0.0134%) from Baige (0.518%/0.260%) at both window sizes. | archived spec §12.5; Pekel et al. 2016; Small 2011 | — | — |
| 28 | Two gates that were documented but never executed | Phase 10 | ✅ WIRED IN, thresholds still TODO | **Both now run.** `MIN_NEW_WATER_AREA_M2` is applied PER CONNECTED COMPONENT (`connectedPixelCount`, eight-connected, capped at Earth Engine's 1024-pixel `maxSize`), not to the window total — this row's own measurement is why: over Baige a garbage mask cleared a window-total floor by 900× *because* its mis-classified pixels were scattered everywhere, whereas a lake is one patch. Saturation at the cap can only under-state a component, so it can only make the gate stricter. `score_candidate_flatness` is invoked through an Earth Engine twin that reads Copernicus GLO-30 (`COPERNICUS/DEM/GLO30`) inside the same call; that is **not** the layering violation this row feared, because an Earth Engine asset is another EE image, not a call into `jalraksha.terrain`. Both halves decide through one shared `flatness_verdict()`, so the tested path and the live path cannot drift. `MAX_PLAUSIBLE_WATER_FRACTION` is also applied now (row 29 noted `blockage_detect` never did). **What remains TODO is the four threshold VALUES themselves** — they are row 25, unchanged and still unvetted; this row was about the wiring. | This repository's own measurement; Small 2011 for the terrain-correction alternative | 2026-09-04 | Wired; values remain row 25 |
| 29 | VV thresholding cannot separate water from radar shadow in a gorge | Phase 10 | ⚠ REMEDY BUILT AND MEASURED — IT DOES NOT WORK | The documented remedy is now implemented (`jalraksha/gee/terrain_correction.py`: local incidence angle from Copernicus GLO-30 and the scene's own geometry, shadow and layover excluded before any histogram, applied in both `sar._fetch_live` and `blockage_detect._fetch_live`) and **re-measured against `scripts/detect_blockage_experiment.py` on 2026-09-04. It does not rescue the detector.** Over Baige the mask excludes 16.6% of the window and Gate 1 precision moves 0.0075 → **0.007** against a 0.5 requirement, with recall falling 0.92 → 0.85; all six cases still refuse. **The original diagnosis was wrong in its emphasis: radar shadow is 0.09% of that window**, never numerous enough to explain a 63%-water mask. The false positives are on geometrically imageable slopes that are simply dark, which is radiometric — the gamma-nought flattening half of Small (2011), not built, and at 140 false positives per true one there is reason to doubt it suffices either. The masking is KEPT: excluding layover is correct independently, and any radiometric correction needs the same geometry beneath it. Closing this row now means either demonstrating a construction that reaches 0.5 precision in a gorge or recording that open-data VV auto-detection over mountain terrain is not achievable and removing the path. Full table: `docs/validation_findings.md` §9. | Small 2011, *IEEE TGRS* 49(10):3081–3093; this repository's own measurement | 2026-09-04 | Built, measured, insufficient |
| 26 | Rishi Ganga barrier crest height and width | Phase 3 | ❌ TODO | MEASURABLE, not guessable. Chamoli is the only event in the problem statement's list with pre- and post-event 2 m DEMs publicly downloadable — Zenodo 4554647 (pre) and 4558692 (post). Difference them for the deposit's location, crest height and width. Use the NUMBERS only: the licence is CC BY-NC-4.0, so the DEMs must not be redistributed in outputs. `RISHI_GANGA` publishes both as None until then and the operator supplies them. | literature.md §11.2; Shugar et al. 2021, *Science* | — | — |
| 27 | DEM drainage-conditioning thresholds (`fill_max_depth_m`, breach-notch footprint) | Phase 2 | ❌ TODO | Two chosen numbers, neither from literature. `fill_max_depth_m = 3.0` m (`terrain/conditioning.py::fill_depressions`) is the cap on the raise applied per cell; it separates bilinear-resampling pits from genuine basins, and the separation is asserted by test but the value itself is picked, not fitted. `footprint_radius = 1` in `run.py::_notch_breach_into_bed` stands in for breach WIDTH (~2–3 cells, i.e. a few hundred metres at 200–300 m resolution) because no per-member width is available; a real width would come from the Froehlich / Von Thun geometry the ensemble already samples. The notch INVERT is not in this row — it is crest minus `height_m`, which is the full-depth breach those regressions assume. Both defaults are documented in `docs/validation_findings.md` §8 with the failure that motivated them. | Chosen for this repository; no primary source. Related: Wahl 2004 (row 5), Von Thun & Gillette 1990 (row 2) | — | — |
| 30 | Radar-geometry mask thresholds (`GEOMETRY_MARGIN_DEG`, `MIN_VALID_GEOMETRY_FRACTION`) | Phase 10 | ❌ TODO | Two chosen numbers in `gee/terrain_correction.py`. The shadow limit (LIA ≥ 90°) and the layover limit (≤ 0°) are **definitions, not thresholds**, and are not in this row. `GEOMETRY_MARGIN_DEG = 5.0` is held back from both, chosen against Copernicus GLO-30's stated ~4 m vertical accuracy, which at 30 m posting is several degrees of slope error on rough terrain; Small (2011) prescribes no margin because it works from an illuminated-area integral rather than a per-pixel angle test. `MIN_VALID_GEOMETRY_FRACTION = 0.35` is the point below which a window refuses rather than thresholding what survives — the surviving pixels being valley floors and sensor-facing slopes only, a biased sample then applied scene-wide. Neither is fitted. Measured in use: at Baige the margin's exclusions are 16.5% layover against 0.09% shadow, and `MIN_VALID_GEOMETRY_FRACTION` has not yet refused any real window (0.83 and 0.85 valid at the two cases tested), so neither value is currently load-bearing. The nominal headings (348°/192° ascending/descending) are NOT in this row: they follow from Sentinel-1's published 98.18° orbit inclination and right-looking geometry, and the scene's own `platform_heading` is preferred whenever present. | Small 2011, *IEEE TGRS* 49(10):3081–3093; Copernicus DEM product spec; ESA Sentinel-1 Product Definition | — | — |
| 31 | Manning's *n* per ESA WorldCover class | Phase 2 | ❌ TODO | `terrain/roughness.py::MANNING_TABLE_ESA`. **A defect was fixed here, and it was not the values.** Every class in the old table was labelled as the one below it in ESA's legend: 10 as "Shrubland" (it is Tree cover), 40 as "Built area" (Cropland), 50 as "Bare / rock / sand" (Built-up). Built-up land — the roughest class and the one that most shapes an inundation footprint — was therefore assigned n = 0.01, the value for smooth concrete. Class 100 (Moss and lichen) was missing entirely. The legend is now ESA's published one and is exact. The eleven **n values** remain unvetted: they are mid-range transcriptions of Chow (1959) Table 5-6 and Arcement & Schneider (1989) onto a land-cover legend both sources predate, and **no published WorldCover-to-Manning crosswalk is cited**. `test_roughness.py` asserts the ORDERING (built-up > bare, trees > grass, ice < grass) rather than the numbers, so a re-shifted legend fails even if the values are later revised. | Zanaga et al. 2022 doi:10.5281/zenodo.7254221 (legend); Chow 1959 Table 5-6; Arcement & Schneider 1989 USGS WSP 2339 | — | — |
| 32 | Fatality-model attribution and the Jonkman (2008) coefficients | Phase 6 | ❌ TODO | **A model was running under another author's name.** `impact/fatality.py::estimate_loss_of_life_jonkman` documented `F(d,v) = Φ((ln(d·v) − μ)/σ)` and has never computed it; the body is a saturating exponential in the depth-velocity product with four shape constants (0.5, 0.4, 0.02, 0.03) and two caps (0.90, 0.05) that come from nowhere. It is renamed `estimate_loss_of_life_depth_velocity`, returns `model` and `model_is_published: False` so a report cannot misattribute it, and the old name survives as a `DeprecationWarning` alias. The real Jonkman (2008) log-normal is present in SHAPE as `estimate_loss_of_life_jonkman_2008` and **quarantined behind `JONKMAN_2008_VERIFIED = False`**, exactly as `natural_dam.py` quarantines Walder & O'Connor and Peng & Zhang. TODO: transcribe μ and σ per hazard zone, the zone definitions in depth / rise rate / depth-velocity product, and the fitted event population. The six ad-hoc constants above are separately unvetted and should be replaced by the published model rather than fitted. Related: row 11 (DeKay & McClelland, cited in the module docstring for a long time and never implemented — the docstring now says so). | Jonkman, Vrijling & Vrouwenvelder 2008, *Natural Hazards* 46(3):353–389; Jonkman et al. 2008, *JFRM* 1(1):43–56 | — | — |

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

