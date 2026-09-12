# JalRaksha Coefficient Verification Log

**Purpose:** Track verification status of every ⚠ coefficient in the system. Ensures no scientific constants are fabricated; every coefficient is traceable to primary literature. This file *is* the queue — the "Spec §17" it was originally extracted from lived in `prototype specs.md`, which is no longer on disk (last tracked at commit `3a83ff1`).

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
| 10 | JRC depth-damage curves (India-specific) | Phase 6 | ⏳ DEFERRED | Locate India-specific curves; transcribe lookup tables. **The seam now exists:** `impact/damage.py::huizinga_2017_damage_fraction` implements the JRC global functions in SHAPE and is quarantined behind `HUIZINGA_2017_VERIFIED = False`, raising `DepthDamageCurveUnverified` — the piecewise-linear tables from EUR 28552 EN are not transcribed and the continental maximum-damage values are not converted to INR at a stated price year. Applying one continent's curve to another shifts a damage figure substantially while still producing a plausible number, which is why the flag is shut. What ships instead is the unpublished saturating exponential of row 36, on the unvetted unit costs of row 35. | Spec §6.2, JRC 2017 *FAO*; Huizinga, de Moel & Szewczyk 2017, EUR 28552 EN | — | — |
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
| 31 | Manning's *n* per ESA WorldCover class | Phase 2 | ❌ TODO | `terrain/roughness.py::MANNING_TABLE_ESA`. **A defect was fixed here, and it was not the values.** Every class in the old table was labelled as the one below it in ESA's legend: 10 as "Shrubland" (it is Tree cover), 40 as "Built area" (Cropland), 50 as "Bare / rock / sand" (Built-up). Built-up land — the roughest class and the one that most shapes an inundation footprint — was therefore assigned n = 0.01, the value for smooth concrete. Class 100 (Moss and lichen) was missing entirely. The legend is now ESA's published one and is exact. The eleven **n values** remain unvetted: they are mid-range transcriptions of Chow (1959) Table 5-6 and Arcement & Schneider (1989) onto a land-cover legend both sources predate, and **no published WorldCover-to-Manning crosswalk is cited**. `test_roughness.py` asserts the ORDERING (built-up > bare, trees > grass, ice < grass) rather than the numbers, so a re-shifted legend fails even if the values are later revised. **`af996b7` (2026-09-12) did not close this row.** It fixed which *field* reaches the solver — both backends were solving every ensemble member with the field's MEAN rather than per-cell, which on a WorldCover-style valley made a smooth channel three times too rough and stopped the flood at 170 cells instead of 308. The eleven values are unchanged and still unvetted; that fix only made them load-bearing for the first time, so the case for transcribing them is now stronger, not weaker. `run_summary.json` carries a `roughness` block reporting `is_uniform` and `fraction_at_default` so a uniform 0.03 cannot pass as land-cover-derived. | Zanaga et al. 2022 doi:10.5281/zenodo.7254221 (legend); Chow 1959 Table 5-6; Arcement & Schneider 1989 USGS WSP 2339 | — | — |
| 32 | Fatality-model attribution and the Jonkman (2008) coefficients | Phase 6 | ❌ TODO | **A model was running under another author's name.** `impact/fatality.py::estimate_loss_of_life_jonkman` documented `F(d,v) = Φ((ln(d·v) − μ)/σ)` and has never computed it; the body is a saturating exponential in the depth-velocity product with four shape constants (0.5, 0.4, 0.02, 0.03) and two caps (0.90, 0.05) that come from nowhere. It is renamed `estimate_loss_of_life_depth_velocity`, returns `model` and `model_is_published: False` so a report cannot misattribute it, and the old name survives as a `DeprecationWarning` alias. The real Jonkman (2008) log-normal is present in SHAPE as `estimate_loss_of_life_jonkman_2008` and **quarantined behind `JONKMAN_2008_VERIFIED = False`**, exactly as `natural_dam.py` quarantines Walder & O'Connor and Peng & Zhang. TODO: transcribe μ and σ per hazard zone, the zone definitions in depth / rise rate / depth-velocity product, and the fitted event population. The six ad-hoc constants above are separately unvetted and should be replaced by the published model rather than fitted. Related: row 11 (DeKay & McClelland, cited in the module docstring for a long time and never implemented — the docstring now says so). | Jonkman, Vrijling & Vrouwenvelder 2008, *Natural Hazards* 46(3):353–389; Jonkman et al. 2008, *JFRM* 1(1):43–56 | — | — |
| 33 | Boundary-contamination threshold (`BOUNDARY_CONTAMINATION_KM`) | Phase 4 | ❌ TODO | `scripts/run_khadakwasla_drainage_check.py::BOUNDARY_CONTAMINATION_KM = 5.0`. A gauge closer than this to a transmissive domain edge has its peak depth and arrival shaped by the outflow condition as well as by the flood, and `_boundary_proximity` flags it so such a depth is not read as a clean measurement. The value is **chosen as a few times the coarsest grid spacing this script runs at (200–800 m), not taken from published guidance**, and no sensitivity study has been done. It exists to make contamination VISIBLE, not to quantify it — a flagged gauge is a caveat, never a correction. Measured in use on run `e2e09ea3` (exit domain, 28 x 26 km at 200 m): Hadapsar and Magarpatta City are both 3.0 km from the east edge and flagged; Loni Kalbhor (−6.5 km) and Baramati (−65.4 km) fall outside the grid entirely and report no arrival for that reason rather than a hydraulic one. TODO: replace with a published guidance distance, or with a measured sensitivity of gauge depth to boundary clearance. | No primary source cited — the value is unfitted | — | — |
| 34 | Corridor-conditioning geometry (`window_m`, `condition_corridor_m`) | Phase 2 | ❌ TODO | `terrain/conditioning.py::height_above_valley_floor(window_m=6000.0)` and the `condition_corridor_m` height passed by the caller (10 m in every run so far). The **mechanism** is structural and not in this row: a per-cell fill cap, infinite inside the corridor mask and the ordinary `fill_max_depth_m` outside it, is what separates conditioning a flow corridor — standard flood-routing practice — from erasing terrain to guarantee drainage, which CLAUDE.md forbids. The two NUMBERS are unvetted. `window_m = 6000.0` is justified only as “wider than the Mutha's floodplain and narrower than the gap to the Western Ghats”: a basin-specific choice with no fitted basis, and a minimum filter is a crude stand-in for a flow-accumulation network. The 10 m corridor height has never been varied. Measured in use, with a surviving log (`data/runs/drain_to_green.log`, exit domain at 200 m): 465 of 1,012 corridor cells raised, max 7.5 m, 44 MCM of closed capacity removed, 58 pits outside the corridor left standing. Three larger figures (1,392 / 1,686 / 1,659 MCM) appear in source docstrings for wider domains and have no surviving artifact — do not quote any corridor figure without its domain and resolution. TODO: vary both numbers and report the sensitivity of altered-cell fraction and removed capacity; consider replacing the minimum filter with a real drainage network. | No primary source — both values chosen, not fitted | — | — |
| 35 | Damage unit costs (`UNIT_RECONSTRUCTION_COST_RESIDENTIAL_INR_PER_M2`, `..._NON_RESIDENTIAL_...`, `CROP_VALUE_INR_PER_M2`, `UNCERTAINTY_FRACTION`) | Phase 6 | ❌ TODO | `impact/damage.py`. Four chosen numbers: ₹20,000/m² residential and ₹25,000/m² non-residential reconstruction cost, ₹12/m² annual cropland output, and a ±30% band. **The exposure term beside them is real** — GHS-BUILT-S built-up surface and WorldCover cropland fetched onto the run's own grid — so these constants are the whole of what is unsourced in a rupee figure, and each is ECHOED IN THE PAYLOAD (`unit_cost_inr_per_m2`, `unit_cost_price_year`, `unit_cost_is_default`) precisely so a reader can divide it back out. A test pins that doubling the constant doubles the figure. Two distinctions matter and are already made in code: a reconstruction cost per m² and an annual crop value per m² are different QUANTITIES and do not share a constant name; and a currency value with no price year is not a value, so each carries 2023. What this row does not yet distinguish is REPAIR versus REPLACEMENT cost, which differ by a factor of several. The ±30% band is a judgement about how far an unpublished curve on an unvetted cost can be trusted, not a propagated uncertainty — nothing here has a published variance to propagate. TODO: CPWD plinth-area rates for the relevant state and building class, or a published Indian flood-damage study quoting cost per m² with its price year and its damage definition; a state agriculture department or ICAR gross-value-of-output figure per hectare, with the share of a season's value lost to one inundation stated separately. | No primary source — all four values chosen, not fitted | — | — |
| 36 | Depth-damage curve rate constants (`_SECTOR_RATE`) | Phase 6 | ❌ TODO | `impact/damage.py::_SECTOR_RATE` — 0.8 / 0.7 / 0.6 for residential / non-residential / agricultural in `r(d) = 1 − exp(−k·d)`. **Shape, not calibration.** The curve is monotonic, bounded in [0,1] and zero at zero depth, and the three constants only order the sectors by how fast damage accrues; no published curve was used and none is claimed. Every result carries `model_is_published: False` and a `model_note`, mirroring row 32's remedy for the fatality model — the point being that a plausible number under a published author's name is worse than an obviously provisional one. The published fallback is present in SHAPE as `huizinga_2017_damage_fraction` and **quarantined behind `HUIZINGA_2017_VERIFIED = False`**, raising `DepthDamageCurveUnverified`, exactly as `fatality.py` quarantines Jonkman (2008). See row 10 for that transcription. TODO: replace the exponential entirely with a transcribed piecewise-linear curve; until then, quote this as an ordering of severity and an order of magnitude, never as an appraisal. | No primary source — the three constants are chosen, not fitted. Fallback: Huizinga, de Moel & Szewczyk 2017, EUR 28552 EN | — | — |
| 37 | Earth Engine aggregation of extensive quantities onto the solver grid | Phase 9 | ✅ FIXED | **`reduceResolution(ee.Reducer.sum())` does not sum — it is area-weighted, so it returns a MEAN.** `gee/population.py` documented this exact hazard at length, switched to `sum()` to avoid it, and produced it anyway: measured over the 480×376 domain at 500 m on 100 m GHSL, it returned **741,659 people where the native-resolution total is 18,543,954** — short by 25.003×, exactly (500 m / 100 m)². Every population-at-risk figure published before this was low by the square of the ratio between the solver grid and 100 m, and **runs completed before this fix carry that error in their `population_at_risk.json`; they are not retroactively corrected.** `ee.Reducer.sum().unweighted()` is not the fix either — it counts every touched source pixel in full and overshoots by 1.49× on the same domain. The correction, in `gee/grid_fetch.py`, is to stop resampling a per-cell count at all: convert it to a density per m² (dividing by `pixelArea()` declared in the SOURCE projection), aggregate as the intensive quantity it then is, and multiply back by the output cell area. Verified against native-resolution totals: population 1.0055, built-up surface 1.0059 — the same residual for both, i.e. clip-boundary handling, not a scale error. Callers now declare `extensive=True/False` rather than choosing a reducer, and `test_gee.py::test_an_extensive_quantity_survives_the_change_of_grid` fetches the same ground at 500 m and 250 m and asserts one total, which the old path failed by exactly 4×. GHSL cache manifests are versioned (`ghsl_manifest_v2.json`) so the pre-fix rasters are never served again. | Earth Engine `reduceResolution` weighting semantics; measured against `reduceRegion` at native scale | 2026-09-06 | Measured live, both products |
| 38 | Member-loop and GPU-ensemble engineering constants (`INJECTION_CFL_RTOL`, `MAX_INJECTION_PASSES`, `VRAM_FRACTION`) | Phase 1 | ❌ TODO | Three chosen numbers introduced by `5fa86b8`. **None is a physical coefficient** — they are engineering tolerances, logged here because the queue's contract is that a chosen number says so, not because a literature value is expected to exist for any of them. `INJECTION_CFL_RTOL = 1e-6` (`solver/parallel.py:104`, mirrored in `ensemble_cuda.py`) is the slack allowed when shrinking the pre-injection timestep until the step is still CFL-valid *after* the breach injection. It is REASONED rather than fitted, and the reasoning is in the source: one part in a million is a Courant number of 0.3000003 against a 0.3 ceiling, while the positivity proof holds to 0.5, so the tolerance is three orders of magnitude inside the margin that matters. `MAX_INJECTION_PASSES = 8` (`parallel.py:94`) caps that loop; measured on the harshest valley case (20,000 m³/s, no breach notch), 4 steps in 2,745 used every pass and still finished within 5e-7 of the limit, so the cap is exercised but not binding — and when it *is* exhausted the function returns `overran=True` rather than pretending. `VRAM_FRACTION = 0.6` (`ensemble_cuda.py:80`) sizes an ensemble chunk against free VRAM; it is chosen with no measurement behind the specific fraction, and its failure mode is benign — a chunk that will not fit falls back to the CPU and says so. **What these replaced is the reason they matter:** the old three-timestep member loop ran the clock up to 2.6% ahead of the integrated physics and over-injected by up to 1.2% on a dry synthetic valley. TODO: record a sensitivity for `VRAM_FRACTION` on a card other than the 6 GB RTX 4050, and confirm `MAX_INJECTION_PASSES` never binds on a blockage release down a 1,200 m-relief gorge, which is the steepest case this project runs. | No primary source — all three chosen for this repository. Reasoning and measurements: `docs/validation_findings.md` §11; `TestMemberTimestep` in `tests/test_parallel.py` | — | — |

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
  - **Superseded by row 31.** The legend these values were attached to was shifted by one class, and the eleven *n* values are now recorded as unvetted transcriptions with no published WorldCover crosswalk. Read row 31, not this list.

**Also in Phase 2, and unvetted — see row 34:** the corridor-conditioning geometry, `window_m = 6000.0` in `height_above_valley_floor` and the `condition_corridor_m` height a caller passes. The per-cell fill cap itself is structural; only these two numbers are in the queue.

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
3. **Verification deadline:** the original deadline was 2026-09-01 (mid-Phase 9)
   and it passed without a decision being recorded. What happened instead is in
   rows 24, 25, 28, 29 and 30 and in `docs/validation_findings.md` §9: the
   Sentinel-1 path was measured against real events, auto-detection refuses in
   gorge terrain, and the terrain-correction remedy was built and **does not
   rescue it**. Phase 10 therefore ships with the manual barrier path as its
   guaranteed floor, which needs no network at all, and with detection's refusal
   presented as a result rather than hidden. Items #13–15 remain deferred.

---

## Tracking

**Last updated:** 2026-09-12  
**Next review:** when a quarantined regression is transcribed (rows 19, 20, 32,
or the row-10/36 depth-damage pair), or when a new chosen constant reaches a
published figure  
**Maintainer:** Claude Code (SIH team)  
**Contact:** [team email, TBD]

---

## References

- `docs/VERIFICATION_LOG.md` (this file): the full verification queue. It used
  to live in `prototype specs.md` §17, which is no longer on disk — last tracked
  at commit `3a83ff1`. Headings elsewhere that say "Spec §17" mean this table.
- DECISIONS.md §9: Coefficient verification contract
- CLAUDE.md: Project constraints and testing discipline
- literature.md: Comprehensive technical survey (450+ lines, source bibliography)

