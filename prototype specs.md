# DOCUMENT 2 — PROTOTYPE BUILD SPECIFICATION

> **Target reader:** an AI coding agent. This document is self-contained — it does not require Document 1.

> **Note on gaps:** this document was originally pasted in as plain text, which stripped its fenced code blocks, formulas, and some URLs. Every such gap is marked inline with `⬚ [block missing from source]`. Fill them from the cited primary sources before implementing the affected module.

---

## 0. Mission and rules of engagement

Build **JalRaksha**, a Python system that:

- Takes a dam location (lat/lon) plus reservoir storage, using only open data
- Computes a breach outflow hydrograph
- Simulates the resulting flood with two solvers — a 3D SPH near-field model and a 2D depth-averaged shallow-water far-field model — and quantitatively compares them
- Estimates loss and damage from open exposure layers
- Cross-checks against satellite-observed flood extent via Google Earth Engine
- Exports `.shp`, `.kml`/`.kmz`, and Cloud-Optimized GeoTIFF
- Presents all of it in a web dashboard

### Hard rules

| Rule | Reason |
| --- | --- |
| No dependency on India-WRIS, ffs.india-water.gov.in, or Bhuvan/CartoDEM | Verified geo-fenced, broken, or login-gated. A demo that touches them fails at the venue. |
| Never claim to be Delft3D. Say "Delft3D-class depth-averaged shallow-water solver, not the Deltares kernel" | Accuracy; overclaiming is fatal to credibility |
| Every empirical coefficient marked ⚠ in this spec must be transcribed from its cited primary source before use | A wrong coefficient produces plausible, silently wrong output |
| Everything must run fully offline from cache after first fetch | Demo-day network cannot be trusted |
| Report inundation envelopes and arrival times as primary outputs; treat point depths as indicative | A 30 m DEM cannot support metre-accurate point depths in a gorge |
| Licence hygiene: prefer Copernicus DEM (free/open) + Google Open Buildings (CC BY 4.0). Avoid FABDEM (CC BY-NC-SA), MERIT (CC BY-NC/ODbL), OSM (ODbL share-alike) in redistributed outputs | The deliverable should be cleanly licensable |

### Scope fence (explicitly authorised)

The engineered dam-break path is **mandatory** and must work end-to-end. The natural river-blockage path is *designed for* — same solver, different breach model — but may ship as a reduced/stub implementation. Do not spend effort generalising to arbitrary hydro-activity types.

---

## 1. Stack

> ⬚ *[stack table missing from source]*

**Fallback decision if time collapses:** drop React, use Streamlit + leafmap. It satisfies deliverable (iii) — a GUI for input and output visualisation — with a fraction of the effort. Document the trade-off rather than shipping a half-built React app.

---

## 2. Repository layout

> ⬚ *[directory-tree block missing from source]*

Build the CLI before the API. Every module must be exercisable as `jalraksha run --scenario tehri` with no web server running. This makes debugging tractable and guarantees a working demo path even if the dashboard breaks.

---

## 3. Data acquisition (M1)

### 3.1 DEM — Copernicus GLO-30, no authentication

Verified public AWS S3, no credentials, Cloud-Optimized GeoTIFF with `Accept-Ranges: bytes` (so windowed reads work without downloading the whole tile):

> ⬚ *[S3 URL pattern block missing from source]*

Verified working example (43.3 MB, covers Tehri):

> ⬚ *[example tile URL missing from source]*

- **Tile naming:** 1° × 1°, lower-left corner
- **Vertical accuracy:** < 4 m at 90% LE
- **Vertical datum:** EGM2008
- **GEE equivalent:** `COPERNICUS/DEM/GLO30_2024_1` (the older `COPERNICUS/DEM/GLO30` is deprecated — do not use)
- Check the **FLM** and **HEM** bands: Copernicus replaced GLO-30's Himalayan SRTM infill with AW3D30, and knowing the source per-pixel matters for the accuracy statement

No-login SRTM alternative (for the ASTER/SRTM option the PS mentions):

> ⬚ *[SRTM source block missing from source]*

⚠ **Datum trap:** EGM2008 vs EGM96 differ by roughly 1 m over India. If DEMs are ever mixed, convert explicitly. A silent 1 m datum offset is a metre of fake flood depth.

### 3.2 Dam registers

Parse once, commit the CSVs:

| Source | URL | Contents |
| --- | --- | --- |
| NRLD 2019 | `https://cwc.gov.in/sites/default/files/nrld-2019.pdf` (6.2 MB) | 5,745 dams; lat/lon, height above lowest foundation, gross/effective storage, reservoir area, type, seismic zone, spillway capacity, purpose, year |
| NRSD 2025 | `http://cwc.gov.in/sites/default/files/NRSD_2025.pdf` (29.9 MB) | Storage in MCM, District |

**Mandatory cross-check logic.** NRLD's detail sheets contradict its own summary tables. Verified examples: Hirakud appears as both 12.80 m and 60.96 m (60.96 is correct); Tehri's gross-storage cell is blank; Bhakra is 7,551 MCM in NRLD vs 9,868 MCM in NRSD.

Expose disagreements in the dashboard. A tool that flags bad government data is more credible than one that hides it.

**Optional:** Global Dam Watch v1.0 (CC BY 4.0) via GEE community asset `projects/sat-io/open-datasets/GDW/GDW_BARRIERS_V1_0` — 41,145 barriers, HydroSHEDS-harmonised. Note neither GRanD nor GDW is in the official GEE catalogue; Figshare bot-blocks direct download.

### 3.3 Land cover → Manning's n

`ESA/WorldCover/v200` via GEE, or download once and cache. Map class → roughness (Chow 1959 values) *[standard reference]*:

| WorldCover class | Manning's n |
| --- | --- |
| Tree cover | 0.100 |
| Shrubland | 0.050 |
| Grassland | 0.035 |
| Cropland | 0.035 |
| Built-up | 0.050 |
| Bare/sparse | 0.025 |
| Permanent water | 0.030 |
| Herbaceous wetland | 0.045 |
| Snow and ice | 0.025 |

Channel roughness for a Himalayan boulder river: **0.040–0.070**. Make it a config parameter and expose it in the sensitivity analysis — it is one of the two or three parameters that actually move the answer.

### 3.4 Exposure layers (GEE, all verified accessible)

`JRC/GHSL/P2023A/GHS_POP`, `JRC/GHSL/P2023A/GHS_BUILT_C` (10 m; residential classes 11–15, non-residential 21–25 — use this to pick which depth-damage curve applies per pixel), `JRC/GHSL/P2023A/GHS_BUILT_S_10m`, `WorldPop/GP/100m/pop`, `GOOGLE/Research/open-buildings/v3/polygons` (CC BY 4.0), `WRI/GPPD/power_plants`.

### 3.5 Caching contract

> ⬚ *[cache-layout / contract block missing from source]*

Ship a `jalraksha prefetch --scenario tehri` command and run it the night before any demo.

---

## 4. Terrain conditioning (M2)

This module is where most of the honest accuracy work lives.

### 4.1 The four DEM problems, and what to do about each

| Problem | Consequence | Treatment |
| --- | --- | --- |
| GLO-30 is a DSM, not a DTM — it measures rooftops and canopy | Flood is routed over tree tops and buildings | Optionally subtract canopy height; more practically, document it and treat built-up/forest cells with elevated roughness rather than fake bare-earth |
| Water-surface flattening removes channel bathymetry entirely | The river is a flat ribbon; there is no channel to convey low flows | Burn in a synthetic trapezoidal channel using MERIT Hydro's `wth` width band — see §4.2 |
| 30 m cell gives 1–2 cells across a 20–40 m gorge | Point depths are fictional | Report arrival time and inundation envelope as the primary product; label point depths indicative |
| A 30 m cell straddling a 10–15 m embankment averages it away | Spurious overtopping where a real levee exists | Detect and flag; optionally burn known embankment lines |

Write these into the output metadata and the dashboard, not just the report. A tool that states its own error bars is the thing a professional trusts.

### 4.2 Synthetic channel burn-in

> ⬚ *[burn-in algorithm block missing from source]*

Then enforce hydrological connectivity: fill or breach single-cell pits so the solver does not trap water in DEM noise. Prefer breaching over filling in steep terrain — filling flattens gorges.

### 4.3 Domain definition

> ⬚ *[domain-builder block missing from source]*

Always work in a **metric CRS** for the solver. Never run shallow-water on degrees.

**Tehri demo domain:** dam at 30°22′40″N 78°28′40″E → 60 km downstream reaches Haridwar (58.4 km). At 30 m that is roughly 2,000 × 300 cells ≈ 600 k cells — comfortable.

---

## 5. Reservoir E–A–C synthesis (M3)

We have gross storage from the register but no surveyed elevation–area–capacity curve. Derive one from the DEM.

> ⬚ *[numbered derivation steps 1–4 missing from source]*

**Step 4 is the important one.** It turns an uncheckable assumption into a reported, quantified consistency check.

Then invert for routing: given a volume, return the level. Cache as a monotonic spline.

---

## 6. Breach and outflow hydrograph (M4)

The most consequential module. Every downstream error inherits from here.

### 6.1 Empirical regressions

> ⬚ *[regression formulae block missing from source]*

**Calibration-range checking is not optional.** Tehri is 260 m high with 3,540 MCM storage. These regressions were fitted mostly on far smaller embankment failures. If Tehri falls outside a regression's range — likely for most — the code must say so and the UI must display it. Then report an ensemble range across methods, never a single confident number.

### 6.2 Peak-outflow cross-checks

Implement Froehlich (1995b), Costa (1985) in all three forms (height / storage / storage × height), Walder & O'Connor (1997), Peng & Zhang (2012), Pierce–Thornton–Abt (2010). ⚠ All coefficients to transcribe.

Use these to sanity-check the physically routed hydrograph of §6.3. If the routed peak sits far outside the empirical envelope, something is wrong — **fail loudly**.

### 6.3 Physically routed outflow — the primary method

> ⬚ *[weir + level-pool routing block missing from source]*

### 6.4 Uncertainty ensemble — do not skip this

> ⬚ *[ensemble construction block missing from source]*

This is the single highest-value credibility feature in the project. A flood map with an uncertainty envelope reads as engineering; a single crisp line reads as a guess.

### 6.5 Natural blockage path (reduced scope, authorised)

> ⬚ *[screening-index block missing from source]*

The screening index is worth implementing even alone: for HADR the first question is "should we worry at all", and that is answerable from geometry in milliseconds.

---

## 7. The 2D shallow-water solver (M5)

This is the far-field workhorse and the component the whole system's credibility rests on. It is also entirely standard, well-documented physics — build it carefully and it will work.

### 7.1 Governing equations

Conservative form, `∂U/∂t + ∂F/∂x + ∂G/∂y = S`:

> ⬚ *[U, F, G, S vector definitions missing from source]*

Symbols and units:

| Symbol | Meaning | Unit |
| --- | --- | --- |
| `h` | water depth | m |
| `u`, `v` | depth-averaged velocity, x and y | m/s |
| `z` | bed elevation | m |
| `g` | 9.81 | m/s² |
| `n` | Manning's roughness | s/m^(1/3) |

Friction slope:

> ⬚ *[friction-slope formula missing from source]*

Solve on a uniform Cartesian grid (the DEM grid), cell-centred finite volume, using **η = h + z** (water-surface elevation) as the reconstructed variable rather than `h` — this is what makes well-balancedness natural.

### 7.2 HLLC flux

For the x-direction interface between left state L and right state R:

> ⬚ *[wave-speed and flux formulae missing from source]*

Reference: Toro (2001), *Shock-Capturing Methods for Free-Surface Shallow Flows*. *[standard]*

That transverse-momentum detail is the one people get wrong; it is the entire difference between HLL and HLLC and it matters for a meandering valley.

### 7.3 Well-balanced bed slope — Audusse hydrostatic reconstruction

> ⬚ *[hydrostatic reconstruction formulae missing from source]*

Reference: Audusse et al. (2004), *SIAM J. Sci. Comput.* 25(6):2050–2065. *[standard]*

This must pass the **lake-at-rest test exactly** — still water over arbitrary bathymetry must generate zero velocity, to machine precision. If it does not, the solver will manufacture spurious flow on every hillside and the entire result is worthless. Make this a blocking test (§14.2).

**Alternative:** the surface-gradient method (Zhou et al. 2001) is simpler but less robust at wet/dry fronts. Prefer Audusse.

### 7.4 MUSCL reconstruction and time stepping

> ⬚ *[limiter and time-integrator block missing from source]*

Reconstruct on **η, not h** — reconstructing `h` directly breaks well-balancedness.

### 7.5 Wetting and drying

> ⬚ *[rules 1–4 missing from source]*

**Rule 4 is the single most common cause of a shallow-water solver blowing up on real terrain.** Implement it from the start, not after the first crash.

Reference: Liang & Marche (2009); Liang (2010). *[standard]*

### 7.6 Time step

> ⬚ *[CFL condition block missing from source]*

### 7.7 Boundary conditions

| Type | Use |
| --- | --- |
| Inflow hydrograph | The breach outflow, imposed at the dam cell(s) — discharge distributed over the breach width, with depth from a critical-flow or normal-depth assumption |
| Transmissive / outflow | Downstream domain edge — zero-gradient extrapolation |
| Reflective wall | Domain sides, and any internal structure |
| Internal structure | Koteshwar dam as a weir/barrier — enables the cascade scenario |

### 7.8 Steep-terrain honesty (Himalayan gorge)

The shallow-water assumption (hydrostatic pressure, small bed slope) degrades on slopes above roughly 10%, and the Tehri reach has slopes well beyond that. Options, in order of preference:

1. Document the limitation explicitly and report arrival times and extents rather than precise depths. This is the honest and adequate answer for a Tier-1 screening tool.
2. Apply a bed-slope-corrected pressure term.
3. Restrict quantitative depth claims to reaches below a slope threshold, and mark steeper reaches as "transit only" in the output.

Do **all of 1 and 3**. Do not pretend the issue does not exist — a hydraulics-literate judge will ask, and the prepared answer is impressive.

### 7.9 Performance

Numba-jit the flux loop with `@njit(parallel=True, fastmath=True)`, operating on flat arrays. Target for a 2,000 × 300 grid over 6 hours of simulated time: **minutes, not hours**, on a laptop. If it is slower, profile the flux kernel first — it will be over 80% of the runtime.

**Output:** write depth/velocity snapshots to a NetCDF or Zarr time series at a configurable interval (default 60 s of model time), plus running maxima (`h_max`, `v_max`, `hv_max`, `t_arrival`). The maxima rasters are what the impact and export modules actually consume.

---

## 8. SPH near-field (M6)

### 8.1 Purpose — be precise about this

SPH resolves **the breach region only**: the violently non-hydrostatic, three-dimensional flow where the embankment fails and the jet forms. Domain of order hundreds of metres, simulated time of order tens of seconds to minutes.

It exists to do three things:

1. Independently derive/verify the near-field outflow and jet structure, as a physics-based check on the empirical weir formula
2. Provide the comparison that PS deliverable (i) explicitly requires between SPH and the Delft3D-class model
3. Produce visually compelling 3D output for the demo — a real asset, and legitimately the physics that a depth-averaged model cannot represent

It does **not** route the flood downstream. Say so plainly.

### 8.2 PySPH driver

Scheme configuration:

> ⬚ *[PySPH scheme config block missing from source]*

**Particle-count budget:** keep the near-field domain small enough that the run finishes in minutes. Start from the bundled example's particle count and scale deliberately. Check whether PySPH's OpenCL/CUDA backend works in your environment — if it does, it changes what is feasible.

### 8.3 Particle cloud → raster projection

Needed both for the comparison layer and for the handoff:

> ⬚ *[projection algorithm block missing from source]*

---

## 9. Coupling / handoff (M6→M5)

> ⬚ *[handoff implementation block missing from source]*

Be honest in the code comments and in the writeup: rigorous SPH-to-SWE coupling for real-field dam-break is **not a settled technique** in the literature. We implement a defensible one-way handoff, not a two-way coupling.

**Presentation framing:** "SPH independently derives and verifies the near-field breach outflow and jet structure; the verified hydrograph then drives the depth-averaged far-field routing. Mass is conserved across the handoff to within X%." That is truthful, technically sound, and satisfies the PS's requirement to use both methods and compare them.

---

## 10. Comparison and agreement layer (M7)

PS deliverable (i) requires comparing the two models. This module makes the comparison quantitative rather than visual.

### 10.1 Binary extent agreement

Build a 2×2 contingency table over cells, wet defined as `h > h_threshold` (default 0.1 m — state it, and test sensitivity):

> ⬚ *[contingency table + CSI/F1 formulae missing from source]*

CSI is the standard headline metric in flood-inundation model evaluation because it ignores the vast correctly-dry area `D`, which would otherwise inflate accuracy to meaninglessness. Report CSI and F1 together.

⚠ Retrieve published CSI/F1 values that real flood models achieve against satellite observation, so we know whether our own number is good. Without that context the number is uninterpretable.

### 10.2 Continuous comparisons

> ⬚ *[RMSE / bias / arrival-time metric block missing from source]*

For Chamoli, arrival time is the metric — the published benchmark is travel-time agreement to within 5%.

### 10.3 The comparison deliverable

Produce, automatically, for every run:

| Output | Content |
| --- | --- |
| Comparison table | SPH vs SWE: peak Q, peak depth at named points, arrival times, wetted area, CSI/F1 between the two extents |
| Difference raster | `h_SWE − h_SPH_projected` in the overlap region |
| Hydrograph overlay | Weir+routing Q(t) vs SPH-derived Q(t) at the interface |
| Honest narrative | Where they agree, where they diverge, and why physically (non-hydrostatic near field vs hydrostatic far field) |

That last row is what a jury remembers. A team that can explain *why* two models disagree understands its own system.

---

## 11. Loss and damage (M8)

### 11.1 Hazard classification — implement this first, it needs only h and v

> ⬚ *[hazard-class thresholds block missing from source]*

### 11.2 Structural damage

> ⬚ *[depth-damage curve block missing from source]*

### 11.3 Population at risk and loss of life

> ⬚ *[PAR / fatality-rate block missing from source]*

**Presentation rule:** loss-of-life estimates carry order-of-magnitude uncertainty at best. Present them as ranges with the warning-time dependence made explicit — because warning time is the one variable a decision-maker can actually change, and showing how fatalities drop with warning time is the most useful thing this module can say.

### 11.4 Critical infrastructure

Intersect the inundation envelope with: `WRI/GPPD/power_plants`; roads and bridges; hospitals and schools; the Koteshwar dam (cascade). Report counts and names, plus time-to-inundation for each.

For OSM-derived features, remember ODbL share-alike — use for analysis, be careful about redistribution.

---

## 12. GEE near-real-time observation (M9)

Satisfies PS deliverable (iv).

### 12.1 Access — resolve this early, it can kill the demo

⚠ **VERIFY before relying on it:** the 2026 Google Earth Engine registration and pricing position — whether free noncommercial/research/academic access still exists and what qualifies; whether a Google Cloud Project is required and whether billing must be enabled; and the signup latency (instant vs days of review).

Build the mitigation regardless of the answer: pre-export every GEE product needed for the demo to local GeoTIFF, and make the GEE module **read from cache by default**. The dashboard must show satellite comparison with the network unplugged.

### 12.2 Sentinel-1 SAR flood mapping

> ⬚ *[SAR change-detection recipe block missing from source]*

Also implement **Otsu automatic thresholding** on the difference histogram — a hard-coded threshold will not transfer between scenes.

### 12.3 The two honesty constraints

**Latency.** ⚠ Establish and state the real number: Sentinel-1B failed in December 2021, Sentinel-1C launched December 2024, so the 2026 repeat cycle over Uttarakhand must be verified (6-day vs 12-day), as must the acquisition-to-GEE-availability lag. "Near real time" for SAR means hours to days. Print the actual observed latency in the dashboard next to every satellite product. Never let the UI imply minutes.

**Terrain failure modes.** SAR flood mapping degrades badly in exactly our setting: radar shadow and layover in steep valleys, vegetation obscuring flooding, urban double-bounce confusion. Sentinel-2 optical (NDWI/MNDWI) is the alternative but monsoon cloud defeats it.

Therefore: the satellite layer **detects and validates**; it is not the primary hazard product. Encode that in the UI's wording.

### 12.4 Optical fallback

> ⬚ *[NDWI/MNDWI fallback block missing from source]*

### 12.5 Blockage detection (natural-dam path)

Detect a new water body — a forming landslide-dammed lake — by differencing current surface water against JRC GSW permanent water, filtering by size and by proximity to the drainage network, then estimating lake volume from the DEM. Feeding that into the screening indices of §6.5 gives a genuine end-to-end "detect, screen, and if needed simulate" capability, which is precisely the HADR workflow.

---

## 13. Export and dashboard

### 13.1 Vector export (.shp)

> ⬚ *[polygonisation / schema block missing from source]*

Also export: the maximum inundation envelope (single polygon), arrival-time contours, and the hazard classification.

### 13.2 KML/KMZ — including the time-animated flood wave

> ⬚ *[KML TimeSpan generation block missing from source]*

This is a high-value, low-cost demo feature: a Google Earth file the viewer can scrub through to watch the wave advance.

Also export a ground-overlay KMZ of the depth raster as a coloured PNG for the simplest possible visual.

### 13.3 COG and tiling

> ⬚ *[COG creation options block missing from source]*

For serving: **pre-generated XYZ PNG tiles** are the most demo-robust option (no server logic, works offline from disk). TiTiler/rio-tiler dynamic tiling is more elegant but is another moving part. Choose pre-generated tiles for the demo and mention dynamic tiling as the production path.

### 13.4 Dashboard (deliverable iii)

Minimum feature set:

| Panel | Function |
| --- | --- |
| Input | Dam selection — map click or register search; scenario parameters (breach method, failure mode, downstream extent, grid resolution); run button |
| Progress | Live job progress with stage labels (fetching DEM → conditioning → breach → SPH → SWE → impact → export) |
| Map | Basemap + terrain; animated flood depth over time with a time slider; hazard classification; exposure overlays; arrival-time isochrones |
| Comparison | SPH vs SWE side-by-side or swipe, with the metrics table from §10.3 |
| Impact | PAR, buildings affected, infrastructure hit, loss-of-life range with warning-time sensitivity |
| Satellite | GEE-observed extent vs simulated, with CSI/F1 and the observation timestamp and latency shown |
| Uncertainty | The ensemble envelope from §6.4 — min/median/max |
| Data quality | Register disagreements, DEM limitations, calibration-range warnings. A visible panel, not a footnote. |
| Export | Download .shp, .kml/.kmz, COG, PDF report |

**Job streaming:** WebSocket for progress (`fastapi.WebSocket`), or SSE if simpler. Polling is acceptable for a prototype — do not over-engineer.

**Honest fallback:** if React + deck.gl is consuming the schedule, switch to Streamlit + leafmap. It delivers every row above with far less work. Deliverable (iii) asks for a GUI that supports large data and exports .shp/.kml — it does not ask for a bespoke React app.

---

## 14. Testing and validation

### 14.1 Analytical tests — build these before anything else

> ⬚ *[Ritter exact-solution block missing from source]*

`h(0,t) = 4h₀/9` is the single best five-second sanity check on a shallow-water dam-break solver. If your code does not produce **0.444·h₀** at the dam site, stop and fix it before doing anything else.

Also implement:

- **Stoker** wet-bed solution with the shock (requires numerically solving a transcendental equation for shock speed — use `scipy.optimize.brentq`)
- **Thacker (1981)** oscillating parabolic bowl — the standard test for wetting/drying and well-balancedness together
- **Dam-break with friction** (Dressler / Whitham / Chanson) if a usable closed form can be sourced ⚠

### 14.2 Blocking correctness tests

These must pass before any result is shown to anyone:

| Test | Criterion |
| --- | --- |
| Lake at rest | Still water over arbitrary bathymetry generates zero velocity to machine precision. If this fails, every result is invalid. |
| Mass conservation | Total volume = initial + inflow − outflow, to <0.1% over the run |
| Ritter | L2 error against the exact solution decreasing at the expected order under grid refinement |
| Dry-bed robustness | No NaN, no negative depth, on a domain with steep dry terrain |
| Thin-film stability | Friction limiter prevents unbounded acceleration in shallow water |

Wire these into CI. **A solver without a passing lake-at-rest test is not a solver.**

### 14.3 Benchmark and real-event validation

**Malpasset (1959)** — the standard real-terrain dam-break benchmark, with surveyed wave arrival times. Validates the solver on real topography.

**Chamoli, 7 February 2021** — end-to-end validation against a published Indian event:

| Item | Value / source |
| --- | --- |
| Pre-event DEM | Zenodo 4554647, 2 m, CC BY-NC-4.0 |
| Post-event DEM | Zenodo 4558692, 2 m, CC BY-NC-4.0 |
| Benchmark to beat | Shugar et al. (2021), *Science*: "simulated travel times between P0-P3 show excellent agreement (<5% difference) with travel times inferred from seismic data, videos, and satellite imagery" — green OA at `eprints.whiterose.ac.uk/id/eprint/175202/` |
| Cross-check 1 | HEC-RAS study, *Nat. Hazards* 2023, doi 10.1007/s11069-023-05972-5: peak inflow 12,761.88 m³/s; 7,908–7,975 m³/s at Rishiganga; 5,780–5,957 m³/s at Tapovan; depths 19.85 m / 18.15 m |
| Cross-check 2 | Thayyen et al. 2022, doi 10.1007/s11069-022-05454-0: flood volume ~10 MCM |
| Cross-check 3 | Sentinel-2 extent, doi 10.1007/s12145-022-00786-8: 0.66 km², 88% accuracy, F-score 0.85 |

⚠ **Note:** Shugar et al.'s r.avaflow input dataset was never published — the code-availability section literally reads "available at [insert link when available]". Rebuild inputs from the Zenodo DEMs.

Three independent studies to compare against is unusually strong for an Indian event. Use all three.

### 14.4 Demo scenario — Tehri

| Attribute | Value (CWC registers) |
| --- | --- |
| Coordinates | 30°22′40″N, 78°28′40″E |
| Height above lowest foundation | 260 m (India's tallest) |
| Gross storage | 3,540 MCM |
| Live storage | 2,615 MCM |
| Type | Earth-and-rockfill |
| Completed | 2006 |
| Seismic zone | IV |
| PIC | UA34VH0012 |

**Downstream reporting points:** Koteshwar dam 13.0 km (cascade), Devprayag 28.0 km, Rishikesh 34.8 km, Haridwar 58.4 km.

🚩 **Do not use Mullaperiyar** (listed as "Periyar" in both registers). Active Kerala v. Tamil Nadu Supreme Court litigation concerns precisely whether that dam might fail; publicly simulating its failure reads as taking a side in live litigation. Backups: Ukai (Surat, 7 M people, 77 km downstream) or Idukki/Cheruthoni (model Cheruthoni as the breach point — the Idukki arch has no spillway).

---

## 15. Build order

Each phase has an exit criterion. **Do not start a phase before its predecessor's criterion is met.**

| Phase | Work | Exit criterion |
| --- | --- | --- |
| 0. Skeleton | Repo, config, CLI, data cache, DEM fetch | `jalraksha fetch-dem --lat 30.378 --lon 78.478` writes a clipped GeoTIFF |
| 1. Solver core ★ | 2D SWE: HLLC, Audusse, MUSCL, wet/dry, friction, CFL | Ritter matches to 2nd order; lake-at-rest exact; mass conserved <0.1% |
| 2. Terrain | Conditioning, channel burn-in, domain builder, roughness from land cover | Tehri 60 km domain builds and the solver runs on it without NaN |
| 3. Breach | E–A–C synthesis, regressions, weir + level-pool, ensemble | Hydrograph for Tehri; peak inside the empirical envelope; calibration-range flags emitted |
| 4. End-to-end dam break ★ | Wire breach → solver → h_max/v_max/t_arrival rasters | Tehri run produces plausible arrival times at all four downstream points. **This is the mandatory core deliverable.** |
| 5. Export | .shp, .kml/.kmz incl. time-animated, COG | Files open correctly in QGIS and Google Earth |
| 6. Impact | Hazard classes, depth-damage, PAR, infrastructure | Impact table for the Tehri run with counts (currency optional) |
| 7. SPH | PySPH: reproduce bundled example → real breach geometry → projection | Bundled `dam_break_3d` reproduced against its CSV; then breach run produces a projected raster |
| 8. Comparison | Metrics, handoff validation, comparison outputs | CSI/F1/RMSE table + difference raster + hydrograph overlay |
| 9. Validation | Malpasset; Chamoli end-to-end | Arrival times within a stated margin of the published <5% benchmark |
| 10. GEE | Auth, SAR flood mapping, cache-first design | Chamoli observed extent retrieved and compared; works offline from cache |
| 11. Dashboard | API, jobs, frontend | Full run driven from the browser, all panels populated |
| 12. Hardening | Offline mode, prefetch, report PDF, docs | Full demo runs with the network cable unplugged |

★ = the two phases that matter most. Phase 1 is the foundation; if it is wrong, everything above it is decoration. Phase 4 is the mandatory deliverable.

If time collapses, the **minimum defensible slice** is Phases 0–5 plus 7 reduced — a working dam-break simulation on a real Indian dam with real open data, exported to .shp/.kml, plus a small SPH near-field run to satisfy the two-model comparison requirement. That is a genuine answer to the PS. A half-built dashboard over a broken solver is not.

---

## 16. Deliverable traceability

| PS deliverable | Modules | Evidence at demo |
| --- | --- | --- |
| (i) Generalised framework for dam-break/river-blockage with sudden water surge + loss and damage, using SPH and Delft3D-class models | M3, M4, M5, M6, M7, M8 | Tehri run with both solvers, quantitative comparison table, impact report. Natural-blockage path present (reduced scope). |
| (ii) Customised tool generating scenarios from different input datasets | M1, M2, config/scenarios | Three scenario YAMLs (Tehri, Chamoli, Phuktal) run through the same pipeline; DEM/resolution/roughness/breach-method all swappable |
| (iii) Dashboard GUI, large-volume data, .shp/.kml output | M13, export/ | Browser-driven run; COG tiling for large rasters; .shp opens in QGIS, .kmz animates in Google Earth |
| (iv) Near-real-time flood analysis via GEE with open data | M9 | Sentinel-1 observed extent vs simulated, with CSI/F1 and a stated real latency |
| (v) Simulation on real open Indian river and dam data at final demo | `tehri.yaml` + CWC registers + Copernicus DEM | Live Tehri run; every input open-licensed and sourced |

---

## 17. Verification queue — must be closed before these numbers are trusted

| # | Item | Blocks | Source |
| --- | --- | --- | --- |
| 1 | Breach regression coefficients (Froehlich, MacDonald & Langridge-Monopolis, Von Thun & Gillette, Xu & Zhang) | M4 quantitative validity | USBR DSO-98-004 |
| 2 | Wahl (2004) uncertainty band widths | M4 uncertainty ensemble | *J. Hydraul. Eng.* 130(5) |
| 3 | Whether Tehri (260 m, 3,540 MCM) is inside each calibration range | Whether we quote a number or a range | DSO-98-004 + registers |
| 4 | Graham fatality-rate table | M8 loss of life | USBR DSO-99-06 |
| 5 | Jonkman mortality functions (Dutch decimal commas) | M8 loss of life | Source thesis |
| 6 | DeKay & McClelland — two variants disagree | M8 loss of life | Original paper |
| 7 | JRC depth-damage curves + India max-damage values | M8 damage | JRC technical report |
| 8 | India-specific depth-damage curves | M8 quality | NIH Roorkee / DRIP / World Bank |
| 9 | FD2320 debris factors + category thresholds | M8 hazard classes | HR Wallingford (try r.jina.ai proxy) |
| 10 | D-Flow FM binary availability without compiling | Whether we run the real kernel | conda-forge, Docker Hub, Deltares |
| 11 | Sentinel-1 2026 revisit + GEE latency | M9 honest "near real time" claim | Copernicus / ESA |
| 12 | GEE 2026 free-tier eligibility | Demo viability | Google |
| 13 | SAR threshold + GSW occurrence + slope-mask values | M9 correctness | UN-SPIDER recommended practice |
| 14 | Published CSI/F1 benchmarks for flood models | Interpreting our own score | Bates / Horritt / Aronica / Stephens |
| 15 | E–A–C power-law exponents (Liebe, Avisse) | M3 fallback | Retrieve |
| 16 | HEC-RAS breach-growth law | M4 convention matching | HEC-RAS reference manual |
| 17 | PySPH scheme inventory | M6 configuration | `raw.githubusercontent.com/pypr/pysph` |

Items 1–6 gate quantitative trustworthiness. Items 10–12 are demo-day risk. The code must not silently use a placeholder for any of them — every unverified constant should raise a loud warning or refuse to run without an explicit `--allow-unverified` flag.

---

## 18. Anti-goals

Do not do these things:

| Anti-goal | Why |
| --- | --- |
| Claim to be Delft3D | We are not the Deltares kernel. Say "Delft3D-class." |
| Claim rigorous two-way SPH↔SWE coupling | Not established in the literature. We do a validated one-way handoff. |
| Present point depths as accurate | A 30 m DSM in a gorge cannot support that. Lead with arrival times and envelopes. |
| Present a single breach hydrograph | Report the ensemble. Wahl's uncertainty is the point. |
| Depend on India-WRIS / ffs.india-water.gov.in / Bhuvan | Verified unreachable, broken, or login-gated. |
| Use "water bomb" rhetoric | The best strategic source available (ORF, Ghosh & Modak, Feb 2025) explicitly debunks it. Citing them and then using it is self-defeating. |
| Simulate Mullaperiyar | Active Supreme Court litigation over exactly that question. |
| Claim NTRO does DEM/terrain/hydrological analysis | No public record supports it. NTRO also has no organisational relationship to NRSC (an ISRO centre). |
| Claim NCIIPC covers dams | Its sectors are Power & Energy, BFSI, Telecom, Transport, Government, Strategic & Public Enterprises, Health. Hydropower counts as power; dams as such do not. |
| Position against HEC-RAS | CWC already chose it for DRIP. We are a Tier-1 screening complement that cross-checks against it. |
| Generalise to all hydro-activity types | Explicitly out of scope. The dam-break path must work; that is the requirement. |
| Ship without the lake-at-rest test passing | Every downstream result would be invalid. |

---

## 19. The strongest defensive argument, for the record

CWC/CDSO's *Guidelines for Mapping Flood Risks Associated with Dams* (CDSO_GUD_DS_05_v1.0, January 2018), Table 1-1, defines a three-tier approach in which **Tier 1 is explicitly built on low-resolution open DEMs (SRTM/ASTER/ALOS) with simplified models.**

**JalRaksha is a Tier-1 instrument by CWC's own definition.**

This pre-empts the hardest available objection — "should a dam-safety product use a 30 m DEM and a simplified model?" We are not claiming to replace a Tier-2/3 surveyed study. We are making the screening tier automated, fast, and available for the many dams that have no study at all, **from data that requires no ground access.**

That last clause is the sponsor's actual interest. NTRO's SIH 2026 portfolio has a consistent signature across its GEOINT cluster — satellite super-resolution, oil-spill and AIS fusion, drone-video-to-3D, thermal fire detection, and this: infer physical ground truth from open imagery where you have no survey access.
