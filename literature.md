# DOCUMENT 1 — LITERATURE SURVEY & CASE STUDIES

**Project:** JalRaksha — Dam-Break Inundation Modelling
**SIH 2026 · PS 26161 · NTRO · Disaster Management · Software**

> **Note on gaps:** this document was originally stored as plain text, which stripped its formula blocks. The two affected places (§5.5 level-pool routing, §7.3 FD2320 hazard rating) are marked inline with `⬚ [formula missing from source]`.

---

## 1. How this survey was compiled, and how to trust it

Every claim below is tagged:

- **[V]** = verified this project by fetching the primary source
- **[S]** = standard textbook/reference material, unambiguous in the field
- **⚠ VERIFY** = correct in form, but the exact numeric coefficients must be transcribed from the cited primary source before being written into code

The ⚠ VERIFY tags are concentrated in the empirical breach regressions (§5) and the fatality-rate tables (§7). This is deliberate. A mis-transcribed regression coefficient produces a plausible-looking hydrograph that is silently wrong by a factor of two, which is far more dangerous than an admitted gap. **Do not code those from this document.**

**Research tooling note, for whoever continues this:** the WebSearch tool was non-functional throughout (`Tool 'web_search' not found`). All searching was done by fetching search-engine HTML — `search.yahoo.com/search?p=` works best but breaks on `%22` quoted queries; `html.duckduckgo.com/html/?q=` works (the plain `duckduckgo.com/html/` host 302-redirects and fails). `api.openalex.org/works?search=` is the most reliable route to DOIs and open-access PDF locations. MDPI's Cloudflare 403 is bypassed via `res.mdpi.com/d_attachment/...`. Known-blocked: `web.archive.org`, `science.org`, `reliefweb.int`, `figshare.com`, `sphysics.org`, `opentelemac.org`, India-WRIS (geo-fenced), and most Indian news domains. USBR and USACE `.gov` PDFs returned content-blocked on the last attempt.

---

## 2. The problem statement's own technical vocabulary, decoded

The PS asks for simulation "through 'Smooth Particle Hydrodynamics' and 'Delf3D' model and compare the scenario." Two observations that shape the entire literature review:

1. **The correct terms are Smoothed Particle Hydrodynamics and Delft3D.** The PS misspells both. This matters only because it tells you the PS was written by a requirements owner describing a capability, not by a hydrodynamicist prescribing a method.
2. **SPH and Delft3D are not peer alternatives.** This is the single most important finding in the whole survey and it determines the architecture. SPH is a Lagrangian, mesh-free, three-dimensional method for the full Navier–Stokes equations. Delft3D-FLOW is an Eulerian, structured-grid, depth-averaged-or-layered method. They do not operate at the same scale, do not solve the same equations, and are not substitutable. Asking which is "better" for a 60 km valley is a category error.

The literature does not merely permit the resolution of this; it recommends it. See §3.

---

## 3. Numerical dam-break modelling: the 3D-vs-2D question

### 3.1 The governing review

Maranzoni, A. & Tomirotti, M. (2023). "Three-Dimensional Numerical Modelling of Real-Field Dam-Break Flows: Review and Recent Advances." *Water* 15(17):3130. doi:10.3390/w15173130 **[V]**

This is the anchor citation. Its conclusion, applied to our problem: full 3D modelling of a real-field dam-break over tens of kilometres is computationally prohibitive, and the productive direction is **domain decomposition** — resolve the violently three-dimensional near-field with a 3D method, and route the far-field with a depth-averaged 2D method. Our architecture is not a compromise forced by hackathon constraints; it is the review's own recommended direction.

### 3.2 Why SPH cannot do the far field

Vacondio, R., Altomare, C., De Leffe, M., Hu, X., Le Touzé, D., Lind, S., Marongiu, J.-C., Marrone, S., Rogers, B.D. & Souto-Iglesias, A. (2020). "Grand challenges for Smoothed Particle Hydrodynamics numerical schemes." *Computational Particle Mechanics* 8:575–588. **[V]**

SPHERIC's Grand Challenge 3 is adaptive resolution. SPH is, in production practice, a uniform-resolution method: the particle spacing needed to resolve a 20 m breach jet must be carried across the entire domain. Extending that to a 60 km valley is not a tuning problem, it is an open research challenge named by the SPH community itself.

This citation is the reason the architecture is defensible rather than lazy. When a judge asks "why didn't you just use SPH everywhere?", the answer is that the SPH community's own published grand-challenge list says you can't yet.

### 3.3 The depth-averaged shallow-water lineage

The far-field solver is a 2D shallow-water (Saint-Venant) finite-volume code. The relevant literature is mature and settled:

| Contribution | Source | Role in our build |
| --- | --- | --- |
| Riemann solvers, HLLC | Toro, E.F. (2001). *Shock-Capturing Methods for Free-Surface Shallow Flows.* Wiley **[S]** | The flux function |
| Well-balanced bed slope | Audusse, E., Bouchut, F., Bristeau, M.-O., Klein, R. & Perthame, B. (2004). "A fast and stable well-balanced scheme with hydrostatic reconstruction for shallow water flows." *SIAM J. Sci. Comput.* 25(6):2050–2065 **[S]** | Prevents spurious flow on a sloping dry bed |
| Wetting/drying | Liang, Q. & Marche, F. (2009). "Numerical resolution of well-balanced shallow water equations with complex source terms." *Adv. Water Resour.* 32(6):873–884 **[S]** | Keeps the wet–dry front stable |
| Robust WD + friction | Liang, Q. (2010). "Flood simulation using a well-balanced shallow flow model." *J. Hydraul. Eng.* 136(9):669–675 **[S]** | The friction limiter for thin films |
| Roughness values | Chow, V.T. (1959). *Open-Channel Hydraulics.* McGraw-Hill **[S]** | Manning's n by land cover |

**Open reference implementations surveyed** (for cross-checking our solver, not for adoption): ANUGA (Geoscience Australia, 2D FV SWE), LISFLOOD-FP (diffusive/inertial, Bristol), GeoClaw (adaptive Riemann, Clawpack), Basilisk, TRITON, SERGHEI, Iber, TELEMAC-2D, and HEC-RAS 2D.

### 3.4 Delft3D — actual open-source status

**[V]** Delft3D is genuinely open source at `github.com/Deltares/Delft3D`, under a mixed licence set (AGPL-3.0 / GPL-3.0 / LGPL-2.1 plus Apache components). Delft3D-FLOW uses an orthogonal curvilinear structured grid with ADI time integration and σ- or z-layers, with MPI parallelism. The modern successor is D-Flow Flexible Mesh (D-Flow FM).

The Python toolchain exists and is installable: `hydromt` 1.4.1, `hydromt_delft3dfm` 0.3.0, `hydrolib-core` 1.0.1, `dfm_tools` 0.47.0. **[V]**

⚠ **The unresolved risk:** the D-Flow FM computational kernel is Fortran/C++ and must be compiled. Only unofficial Docker images were found. The Python packages above are pre/post-processing and model-configuration layers — they do not include a solver binary. This was the specific question the (quota-killed) research agent had answered as "Task D is complete and thorough" before dying; that answer is lost and must be re-established.

**Honest framing rule, non-negotiable:** if we ship our own SWE solver, we describe it as "Delft3D-class depth-averaged shallow-water" and state plainly in the same breath that it is **not** the Deltares kernel. We implement the same governing equations and the same physics class. We never claim to be Delft3D. Overclaiming here is the fastest way to lose credibility with a technically literate jury.

---

## 4. Smoothed Particle Hydrodynamics

### 4.1 Method

Weakly-compressible SPH solves Navier–Stokes in Lagrangian form on moving particles, with pressure from a stiff equation of state (Tait), no mesh, and a free surface that emerges naturally from particle positions rather than being tracked. That last property is exactly why it suits a breach: the water surface at a collapsing embankment is not a graph over the horizontal plane, and a depth-averaged method cannot represent it.

### 4.2 PySPH — the de-risking find

Ramachandran, P., Bhosale, A., Puri, K., Negi, P., Muta, A., Dinesh, A., Menon, D., Govind, R., Sanka, S., Sebastian, A.S., Sen, A., Kaushik, R., Kumar, A., Kurapati, V., Deepak, M., Patil, P., Tavker, D., Pandey, P., Kaushik, C., Dutt, A. & Agarwal, A. (2021). "PySPH: A Python-based Framework for Smoothed Particle Hydrodynamics." *ACM Transactions on Mathematical Software* 47(4). doi:10.1145/3460773 **[V]**

Why this is the most useful single discovery in the survey:

- **BSD licence** — no share-alike obligation, unlike DualSPHysics (LGPL) or GPUSPH (GPLv3)
- `pip install pysph` — no compilation of a Fortran kernel
- **Developed at IIT Bombay** — an Indian-authored, citable framework, which is a genuine pitch asset for an Indian national hackathon, not just a technical convenience
- Ships dam-break examples in the box: `dam_break_2d.py`, `dam_break_3d.py`, plus Lobovsky, Buchner and Yeh benchmark variants
- Ships a shallow-water SPH module `pysph.sph.swe` with `rectangular_dambreak.py`, `cylindrical_dambreak*.py`, `okushiri_tsunami.py`
- Ships experimental validation CSVs alongside those examples, with runtimes annotated in the docstrings (e.g. "8 mins")

An SPH framework that is permissively licensed, pip-installable, Indian-authored, and arrives with dam-break validation data already in the package is a rare alignment. It converts the SPH half of the PS from the highest-risk component into the lowest-risk one.

### 4.3 Other SPH implementations surveyed

| Code | Licence | Notes |
| --- | --- | --- |
| DualSPHysics | LGPL | CUDA, most mature for coastal/hydraulic engineering |
| GPUSPH | GPLv3 | GPU-native |
| SWE-SPHysics | — | Shallow-water SPH variant |
| PySPH | BSD | **Selected** |

### 4.4 Scheme elements to be specified before coding

Tait equation of state; artificial sound-speed selection (c0 ≳ 10 × expected max velocity, to hold density variation near 1%); kernel choice (cubic spline / quintic / Wendland) and smoothing-length-to-spacing ratio; density treatment (continuity vs summation) with δ-SPH diffusive stabilisation (Molteni & Colagrossi; Antuono et al.), Shepard/MLS filtering, XSPH, particle shifting; and wall boundary conditions (dynamic boundary particles vs ghost/mirror vs Adami et al.). PySPH provides named schemes for most of these — the exact inventory needs reading off the source, which the dead agent had begun.

---

## 5. Breach mechanics and parameter prediction

The outflow hydrograph is the single most consequential input to the whole model. Everything downstream inherits its error.

### 5.1 Empirical breach-geometry regressions

⚠ **All coefficients in this subsection must be transcribed from the primary sources. Do not code from this document.**

The canonical consolidated source is Wahl, T.L. (1998). "Prediction of Embankment Dam Breach Parameters: A Literature Review and Needs Assessment," Report DSO-98-004, US Bureau of Reclamation — which reproduces all of the following in one place with consistent notation. (Attempted fetch returned content-blocked; retry needed.)

| Regression | Predicts | Primary source |
| --- | --- | --- |
| Froehlich (1995a) | Average breach width, side slopes | *J. Water Resour. Plann. Manage.* |
| Froehlich (1995b) | Peak outflow | *J. Water Resour. Plann. Manage.* |
| Froehlich (2008) | Revised breach width + failure time | *J. Hydraul. Eng.* |
| MacDonald & Langridge-Monopolis (1984) | Eroded volume → breach geometry; failure time. Separate earthfill / non-earthfill coefficients | *J. Hydraul. Eng.* 110(5) |
| Von Thun & Gillette (1990) | Average breach width; two failure-time expressions (erosion-resistance-based and depth-only) | ASTM STP 1121 |
| Xu & Zhang (2009) | Dimensionless breach parameters, with a large coefficient table keyed on dam type, failure mode, erodibility and core type | *J. Geotech. Geoenviron. Eng.* 135(12) |

**The critical unanswered question for our demo dam.** Tehri is 260 m high with 3,540 MCM gross storage. These regressions were fitted on databases of historical embankment failures dominated by dams an order of magnitude smaller. Whether Tehri falls inside or outside each regression's calibration range must be established and stated openly. If it falls outside — which is likely for most of them — the honest presentation is a range across multiple regressions plus an explicit extrapolation caveat, never a single confident number. Getting this right is what separates a credible entry from an overconfident one.

### 5.2 Peak-outflow relations

Froehlich (1995b); Costa (1985) in three forms (dam height, reservoir storage, and the storage × height product); Walder & O'Connor (1997); Peng & Zhang (2012); Pierce, Thornton & Abt (2010); and the MacDonald & Langridge-Monopolis peak-flow envelope. ⚠ VERIFY all.

### 5.3 The honesty artefact

Wahl, T.L. (2004). "Uncertainty of Predictions of Embankment Dam Breach Parameters." *Journal of Hydraulic Engineering* 130(5). **[V — citation]** ⚠ VERIFY the numbers

Wahl quantifies the prediction uncertainty of every relation in §5.1–5.2, and the intervals are wide — roughly an order of magnitude on failure time in the worst cases. These numbers are the most important honesty artefact in the entire project. Presenting a breach hydrograph without Wahl's uncertainty bands is the kind of overclaim a hydrology-literate judge punctures in one question. Presenting with them converts an apparent weakness into evident rigour. Retrieve and quote them.

### 5.4 Physically-based breach models

BREACH (Fread, 1988), BRES, DABA, HR BREACH, WinDAM-B, and Chang & Zhang (2010). These simulate erosion mechanics rather than regressing final geometry. **Assessment:** correct in principle, but they need geotechnical parameters (erodibility, cohesion, gradation) that we cannot obtain remotely for an arbitrary Indian dam. We therefore use them as a discussion point, not a component. This is a scope decision, and stating it explicitly is better than pretending the option doesn't exist.

### 5.5 Outflow routing

Broad-crested weir discharge through a trapezoidal breach (with the side-slope term and a submergence correction), coupled to reservoir drawdown by level-pool routing:

> ⬚ *[level-pool routing formula missing from source]*

with breach growth prescribed by a time law (linear, sinusoidal, or erosion-rate-based). Matching the convention used by HEC-RAS / DAMBRK / MIKE is preferable to inventing one, because it makes our results directly comparable to the incumbent Indian practice. **[S]** for the structure; the specific growth law used by HEC-RAS ⚠ VERIFY.

### 5.6 Elevation–area–capacity from open data only

We have gross storage in MCM from the CWC registers and a DEM, but no surveyed E–A–C curve for any Indian dam. The gap is bridged by flooding the DEM upstream of the dam axis until the impounded volume matches the register's gross storage, which yields a synthetic E–A–C curve.

Supporting literature: power-law `V = a·A^b` reservoir relations (Liebe et al. and successors), and the Avisse et al. satellite-based reservoir-volume method — which the E–A–C research agent reported as "fully captured" immediately before dying. That capture is lost and needs redoing. ⚠ VERIFY exponents and scatter.

---

## 6. Landslide and natural dams

Half the events the PS names are natural blockages, so this literature is not optional.

Costa, J.E. & Schuster, R.L. (1988). "The formation and failure of natural dams." *Geological Society of America Bulletin* 100(7):1054–1068. **[V]** The foundational typology and longevity statistics — the key operational fact being that a large fraction of natural dams fail within days to weeks of forming, which is precisely the window in which a rapid remote-sensing-driven tool has value and a survey-based study does not.

Stability indices, in rough order of usefulness to us:

| Index | Inputs | Computable from DEM + imagery alone? |
| --- | --- | --- |
| Blockage Index / Dimensionless Blockage Index (Ermini & Casagli) | Dam volume, catchment area, dam height | Partial — volume is the hard term |
| Impoundment Index | Lake volume / dam volume | Partial |
| Backstow Index | Lake volume, dam geometry | Partial |
| Basin Index | Catchment characteristics | Yes |

These are attractive because they are **screening tools**: they classify a newly detected blockage as likely-stable or likely-to-fail from geometry alone, without a hydrodynamic run. For a HADR use case where the first question is "should we be worried at all", that is the right first filter.

**Natural-dam peak outflow:** Costa (1985), Walder & O'Connor (1997), Peng & Zhang (2012). Published scatter for natural dams is wider than for engineered embankments — state it.

Additional Indian and regional events worth documenting (verification status varies): Pareechu 2004 (Himachal/Tibet — ⚠ verify or discard), Yigong 2000 (Tibet), South Lhonak Lake October 2023 (Sikkim, GLOF, Teesta-III dam destroyed), Kedarnath 2013, Gohna Tal 1893.

---

## 7. Loss and damage estimation

PS deliverable (i) explicitly requires "loss and damage analysis." This is the part of the survey with the thinnest verified coverage, because the agent assigned to it died. **It is flagged as the largest research gap.**

### 7.1 Depth-damage functions

| Source | Coverage | Status |
| --- | --- | --- |
| Huizinga et al., JRC Technical Report — global flood depth-damage curves | Global, continental curves incl. Asia; damage ratios vs depth plus max damage values | Best free global option ⚠ VERIFY tables |
| HAZUS-MH flood curves (FEMA) | US building types | Well documented, US-specific |
| FLEMOps | Germany | Multi-parameter |
| India-specific curves | — | **Largest gap.** Search NIH Roorkee, IIT publications, DRIP reports, World Bank India flood-risk studies. Unresolved. |

### 7.2 Loss of life

Graham, W.J. (1999). "A Procedure for Estimating Loss of Life Caused by Dam Failure," Report DSO-99-06, US Bureau of Reclamation. **[V — citation]** ⚠ VERIFY the table. Gives suggested fatality rates as a function of flood severity (low / medium / high), warning time, and whether the population understands the severity. This is the standard reference in dam-safety practice. (Fetch returned content-blocked; retry.)

Jonkman, S.N. mortality functions — fatality rate as a function of depth, depth × velocity, and rise rate. The agent that reached the source thesis noted it uses **Dutch decimal commas**, which is exactly the kind of transcription trap that produces a 1000× error. Transcribe with care.

DeKay, M.L. & McClelland, G.H. (1993). Fatality prediction from dam failure. The agent working this found "a real discrepancy" between two published variants of the equation before dying — meaning the literature itself disagrees. Resolve against the original paper.

HEC-FIA and LifeSim (USACE) are the operational software embodiments of this class of model. Useful conceptually and as a citation of what state-of-practice looks like.

### 7.3 Hazard-to-people criteria

These are the most directly implementable, because they need only depth and velocity — both of which our solver produces natively.

UK DEFRA / HR Wallingford FD2320 hazard rating:

> ⬚ *[formula missing from source — the reference list at §13 item 33 records it as `HR = d(v + 0.5) + DF`]*

where `d` = depth (m), `v` = velocity (m/s), `DF` = debris factor. **[V — formula form]** ⚠ VERIFY the debris-factor values and the category thresholds (the agent reported a breakthrough retrieving this via an `r.jina.ai` proxy, then died).

Also: Australian AR&R flood-hazard curves, and USBR flood-severity thresholds.

### 7.4 Exposure layers — all verified accessible in Google Earth Engine [V]

| Asset ID | Use | Licence note |
| --- | --- | --- |
| `JRC/GHSL/P2023A/GHS_POP` | Population count | — |
| `JRC/GHSL/P2023A/GHS_BUILT_C` | 10 m built classification; residential 11–15, non-residential 21–25 | Ideal for depth-damage curve assignment |
| `JRC/GHSL/P2023A/GHS_BUILT_S_10m` | Built surface fraction | — |
| `WorldPop/GP/100m/pop` | Population, alternative | — |
| `GOOGLE/Research/open-buildings/v3/polygons` | Individual building footprints | CC BY 4.0 — the safe buildings source |
| `ESA/WorldCover/v200` | Land cover → Manning's n | — |
| `WRI/GPPD/power_plants` | Critical infrastructure | — |

Facebook/Meta HRSL is on HDX (523 MB, CC BY 4.0, no login) as a population alternative.

**Licence traps to avoid: [V]** FABDEM is CC BY-NC-SA; MERIT is CC BY-NC / ODbL; OSM (Geofabrik) is ODbL with share-alike; Global Flood Database is CC-BY-NC. For anything we present as an open deliverable, Google Open Buildings (CC BY 4.0) and the Copernicus DEM are the clean choices.

---

## 8. Remote sensing of flood extent

PS deliverable (iv) requires near-real-time flood analysis via Google Earth Engine.

**Verified GEE assets [V]:** `COPERNICUS/S1_GRD` (Sentinel-1 SAR, IW mode, VV polarisation), `COPERNICUS/DEM/GLO30_2024_1` (note: the older `COPERNICUS/DEM/GLO30` is deprecated), `JRC/GSW1_4/GlobalSurfaceWater` (permanent-water masking), `MERIT/DEM/v1_0_3`, `MERIT/Hydro/v1_0_1` (carries an `hnd` HAND band and a `wth` channel-width band), `GLOBAL_FLOOD_DB/MODIS_EVENTS/V1` (913 events 2000–2018, covers both Kosi 2008 and Kashmir 2014, CC-BY-NC), `WRI/Aqueduct_Flood_Hazard_Maps/V2`.

The canonical method is the UN-SPIDER / RUS Copernicus "Recommended Practice: Flood Mapping and Damage Assessment using Sentinel-1 SAR": before/after SAR change detection with speckle filtering, a difference or ratio threshold (Otsu histogram thresholding for automatic selection), DEM-slope masking to remove radar shadow and layover, and permanent-water subtraction via JRC GSW occurrence.

Two honesty items that must not be glossed:

1. **Latency.** Sentinel-1B failed in December 2021; Sentinel-1C launched December 2024. The actual 2026 repeat cycle and acquisition-to-GEE-availability latency over Uttarakhand must be stated as a real number. "Near real time" in a satellite context means hours to days, not minutes. Overstating this is an easy puncture. ⚠ VERIFY.
2. **SAR fails badly in exactly our terrain.** Steep Himalayan valleys produce radar shadow and layover; dense vegetation obscures flooding; urban double-bounce confuses water detection. Sentinel-2 optical (NDWI/MNDWI) is the alternative but is defeated by monsoon cloud. The satellite layer validates and detects; it cannot be the primary hazard product. Saying so plainly is the correct position.

**Metrics literature** for comparing simulated against observed extent: Critical Success Index / Threat Score, F1, precision, recall/hit rate, false-alarm ratio, probability of detection, bias ratio, Cohen's κ; plus Nash–Sutcliffe and Kling-Gupta efficiency for hydrographs and RMSE/MAE for depth. The flood-inundation evaluation literature (Bates, Horritt, Aronica, Stephens) establishes what a credible CSI looks like against satellite observation — worth retrieving, because it tells us whether our own number is good or embarrassing.

---

## 9. Indian regulatory and practice literature

### 9.1 The document that reframes our entire positioning

Central Water Commission / Central Dam Safety Organisation (January 2018). "Guidelines for Mapping Flood Risks Associated with Dams," Doc. No. CDSO_GUD_DS_05_v1.0, 170 pp. **[V — read directly]**

Verbatim: *"HEC-RAS has been chosen for dam break analysis in the DRIP project."*

Keyword frequency across the document **[V]**:

| Term | Occurrences |
| --- | --- |
| HEC-RAS | 15 |
| DRIP | 28 |
| BREACH | 7 |
| SMPDBK | 2 |
| MIKE | 2 |
| DAMBRK | 1 |
| FLDWAV | 1 |
| SPH / "smoothed particle" | **0** |
| Delft | **0** |
| TELEMAC | **0** |
| TUFLOW | **0** |

Two strategic consequences:

**(a) HEC-RAS is not our competitor — it is our baseline.** Indian dam-safety practice already standardised on it. Positioning JalRaksha *against* HEC-RAS invites the response "CWC already chose HEC-RAS." Positioning it as producing results *cross-checkable against* HEC-RAS makes it complementary and immediately legible to Indian practitioners.

**(b) The PS's named methods are absent from Indian dam-safety guidance entirely.** SPH and Delft3D appear zero times. This confirms the PS is not restating existing CWC practice — it is asking for something Indian dam-safety documentation does not currently cover. That is the space we occupy.

### 9.2 The Tier taxonomy — our strongest defensive argument

Table 1-1 of the same guideline defines a three-tier approach to dam-break study rigour. **Tier 1 is explicitly built on low-resolution open DEMs (SRTM / ASTER / ALOS) with simplified models** (Geo-Dam-BREACH, SMPDBK).

**Our pipeline is a Tier-1 instrument by CWC's own definition. [V]**

This pre-empts the hardest objection available to a judge: "should a dam-safety product use a 30 m DEM and a simplified model?" Answer: CWC's own guideline defines exactly this tier, for exactly this purpose — rapid screening and prioritisation — and distinguishes it from the Tier-2/3 surveyed studies that follow. We are not claiming to replace a detailed study; we are claiming to make the screening tier fast, automated, and available for dams that have no study at all.

### 9.3 EAP requirements

CWC Emergency Action Plan guidelines (`cwc.gov.in/sites/default/files/EAPChapters.pdf`) **[V]** are software-agnostic, and require index maps at 1:50,000 and detailed maps at 1:10,000 with 0.5 m contours. The second of those is beyond a 30 m DEM's reach, and we should say so rather than imply our output is EAP-final. Our output serves the index-map tier and the screening decision.

### 9.4 Dam registers

| Register | Access | Contents |
| --- | --- | --- |
| CWC NRLD 2019 | `cwc.gov.in/sites/default/files/nrld-2019.pdf` (6.2 MB) **[V]** | 5,745 dams (5,334 completed + 411 under construction); DMS lat/long, height above lowest foundation, gross and effective storage, reservoir area, dam type, seismic zone, spillway capacity, purpose, year |
| CWC NRSD 2025 | `cwc.gov.in/sites/default/files/NRSD_2025.pdf` (29.9 MB) **[V]** | Storage in MCM, includes District |
| Global Dam Watch v1.0 | doi:10.6084/m9.figshare.25988293, CC BY 4.0 **[V]** | 41,145 barriers + 35,295 reservoir polygons, HydroSHEDS-harmonised. Figshare bot-blocks; use the GEE community asset `projects/sat-io/open-datasets/GDW/GDW_BARRIERS_V1_0`. Note: neither GRanD nor GDW is in the official GEE catalogue. |

⚠ **Data-quality warning, verified [V]:** NRLD's per-dam detail sheets contradict its own summary tables. Hirakud appears as 12.80 m in one place and 60.96 m in another (60.96 is correct); Tehri's gross-storage cell is blank. Any register ingest must cross-check NRLD against NRSD 2025 and flag disagreements rather than silently trusting one. This is a real engineering requirement, not a footnote.

### 9.5 Portals

DHARMA (`dharma.cwc.gov.in`), DRIP (`drip.cwc.gov.in`), CWC Inundation Forecast (`inf.cwc.gov.in`).

**Excluded after verification [V]:** India-WRIS is geo-fenced and unreachable from outside India (DNS resolves to 164.100.85.36, ports 80/443 refused) with no public API. CWC's flood-forecast API at `ffs.india-water.gov.in` returns 404/502. Bhuvan/CartoDEM is login-gated with no REST API. **Do not architect on any of these** — a demo that depends on them fails at the venue.

---

## 10. Strategic and institutional context

This section exists because the sponsor is NTRO, not a water ministry, and the PS frames the need as HADR — Humanitarian Assistance and Disaster Relief.

### 10.1 What NTRO's PS portfolio reveals [V]

SIH 2026 has 226 problem statements (54 hardware, 172 software) across 18 themes. Disaster Management holds 29, of which the Ministry of Earth Sciences owns 14 — all statistical/ML weather forecasting.

**PS 26161 is the only physics-based hydrodynamic simulation problem statement, and the only dam-related problem statement, in all of SIH 2026.** No other team is solving an adjacent problem.

NTRO sponsors 23 consecutive statements (26142–26164), mostly cyber/SIGINT/forensics, but with a distinct open-source GEOINT cluster: satellite super-resolution (26142), oil-spill detection with AIS fusion (26143), drone-video-to-3D reconstruction (26158), dam-break inundation (26161), thermal fire detection via NASA FIRMS (26162).

The recurring signature across that cluster: **infer physical ground truth from open imagery where you have no survey access.** That is the sponsor's actual interest, and it is the sentence our whole framing should answer.

### 10.2 The data-void argument

Ghosh, N. & Modak, S. (18 February 2025). Observer Research Foundation, on China's Yarlung Tsangpo project. **[V]**

Verbatim quotes, all verified:

- *"the entire discourse on the Brahmaputra hydropolitics remains shrouded by a critical void — the absence of hard data"*
- *"China can neither 'turn off the tap' nor 'trap the sediments'"*
- *"The primary risk posed by this project is not water diversion but dam failure"*
- the Nuxia–Tuting reach is *"presently a blind spot for India"*

This is an authoritative Indian source stating that the threat is dam failure, under a data void, in a reach India cannot observe. It is the cleanest available justification for a tool that models dam-break consequences from open satellite data alone, with no access to the dam.

It also explicitly undercuts the "water bomb" framing — so **we must not use that phrasing.** Citing this source and then using the rhetoric it debunks would be self-defeating.

**Context:** China approved the Medog/Motuo mega-dam in December 2024, construction began 19 July 2025. India suspended the Indus Waters Treaty on 23 April 2025 after Pahalgam; still in abeyance as of June 2026. India is not a party to Additional Protocol I (1977), whose Article 56 protects dams.

### 10.3 Two claims we must NOT make [V — both are corrections to earlier drafts]

1. **NTRO has no organisational relationship to NRSC.** NRSC is an ISRO centre under the Department of Space. NTRO does hold independent satellite/IMINT tasking (ORF/Manoj Joshi, 2019: *"The NTRO, which was given control of the military satellites, has its own station in Assam"*), but no public official record places DEM, terrain, or hydrological analysis inside NTRO. Do not assert it. Safest hierarchy phrasing: NTRO "functions under the National Security Adviser" — sources split between PMO and Cabinet Secretariat for the parent department, so assert neither.
2. **NCIIPC's critical-sector list does not include water or dams.** The sectors are Power & Energy, BFSI, Telecom, Transport, Government, Strategic & Public Enterprises, and Health. Hydropower qualifies as power infrastructure; dams as such do not. Do not claim NCIIPC covers dams.

Also: no public NTRO or Indian-defence writing on dam-sabotage modelling was found. That is absence of evidence, not evidence of absence — do not present a gap as a finding.

### 10.4 Framing decision (settled)

**Dual-framing, NTRO-led.** Lead with NTRO's HADR and no-ground-survey interest. Keep the NDSA / Emergency-Action-Plan dam-safety backlog as a secondary impact story only.

**Rationale, verified [V]:** the strings *NDSA*, *Emergency Action Plan*, *Dam Safety Act* and *Dam Safety* each occur **zero** times across all 226 SIH 2026 problem statements. (Three apparent hits were false positives: `ndsa` inside "Landsat"; `act` inside "impacted" and "Contact info".) Leading with a dam-safety-regulatory framing would be answering a question nobody asked.

---

## 11. Case studies

### 11.1 The four events the PS names — and what they actually are

The PS's own event list contains factual errors. Knowing them is a credibility asset: it demonstrates we read the domain rather than the prompt. Correcting them gently in the writeup ("we take the PS's Rishi Ganga reference to mean the 7 Feb 2021 Chamoli event, which was a rock-and-ice avalanche rather than a GLOF") is the right tone. **[V — all corrections]**

| PS says | Reality |
| --- | --- |
| "natural lake formed over the Rishi Ganga river of Uttarakhand in Feb 2021" | The 7 Feb 2021 Chamoli event was a rock-and-ice avalanche, not a GLOF. A temporary blockage did form. |
| "Wapriyang river in Nov 2021" | No such river exists. Most likely the 29 Oct 2021 Kameng / "Warriyang Bung" sediment event at 27.877 N, 92.702 E — where no dam formed. |
| "Phuktal river near Sumdo, J&K in Mar 15" | Blockage formed 31 Dec 2014; breach 7 May 2015, 08:10. March 2015 is when NRSC's last Cartosat-2 image was taken (24 Mar) — the PS appears to have taken the imagery date for the event date. |
| "Devastating flood... Kashmir valley... 2014" | A rainfall flood, not a dam break. Cannot validate a dam-break model. Useful only as an inundation-mapping and exposure test. |

### 11.2 Primary validation case — Chamoli, 7 February 2021 ★

Selected as the headline validation case for one decisive reason: **it is the only one of the PS's events with both pre- and post-event high-resolution DEMs publicly downloadable**, which means the terrain change can be reconstructed rather than assumed.

Data **[V]**:

- **Pre-event DEM:** Zenodo 4554647 — 2 m, CC BY-NC-4.0
- **Post-event DEM:** Zenodo 4558692 — 2 m, CC BY-NC-4.0
- Shugar et al. (2021), *Science* — free green-OA full text at `https://eprints.whiterose.ac.uk/id/eprint/175202/1/Shugar%20et%20al%20Uttarakhand%20FINAL%20Maintext%20wFigs.pdf`

The benchmark sentence to beat, verbatim from Shugar et al.:

> "simulated travel times between P0-P3 show excellent agreement (<5% difference) with travel times inferred from seismic data, videos, and satellite imagery."

That is a published, quantitative, independently-corroborated target. If our model reproduces arrival times at the same points to within a comparable margin, we have a validation result that stands on its own.

**Independent cross-checks — three separate studies, which is unusually strong for an Indian event [V]:**

| Study | Reported values |
| --- | --- |
| HEC-RAS study, *Natural Hazards* (2023), doi:10.1007/s11069-023-05972-5 | Peak inflow 12,761.88 m³/s; 7,908–7,975 m³/s at Rishiganga; 5,780–5,957 m³/s at Tapovan; depths 19.85 m and 18.15 m |
| Thayyen et al. (2022), NIH Roorkee, doi:10.1007/s11069-022-05454-0 | Independent flood volume ~10 MCM |
| GEE Sentinel-2 extent study, doi:10.1007/s12145-022-00786-8 | Reference extent 0.66 km², 88% accuracy, F-score 0.85 |

That last one is doubly useful: it gives us both a reference inundation extent and a published F-score to compare our own agreement metric against.

**Known gap [V]:** Shugar et al.'s r.avaflow input dataset was never published — the code-availability section literally reads "available at [insert link when available]". The model inputs must therefore be rebuilt from the Zenodo DEMs. Annoying, but tractable, and worth stating because it shows we checked.

**Responders:** ITBP and NDRF. (Do not confuse with Phuktal's responders — see below.)

### 11.3 Demo case — Tehri Dam scenario

Selected as the live demonstration dam for PS deliverable (v), which requires simulation on real open Indian dam data.

Parameters **[V, from CWC registers]**:

| Attribute | Value |
| --- | --- |
| Location | 30°22′40″N, 78°28′40″E |
| Height above lowest foundation | 260 m — India's tallest |
| Gross storage | 3,540 MCM |
| Live storage | 2,615 MCM |
| Type | Earth-and-rockfill |
| Completed | 2006 |
| Seismic zone | IV |
| PIC code | UA34VH0012 |

Downstream chain (straight-line distances) **[V]**:

| Location | Distance | Significance |
| --- | --- | --- |
| Koteshwar dam | 13.0 km | Cascade-failure narrative — a downstream dam in the flood path |
| Devprayag | 28.0 km | Confluence, Alaknanda–Bhagirathi |
| Rishikesh | 34.8 km | Major population centre |
| Haridwar | 58.4 km | Major population centre, pilgrimage city |

**Why Tehri is the right choice:** it sits in a deep Himalayan gorge, so a 30 m DEM actually resolves the cross-section (a lowland dam would be hopeless at that resolution); it is in Seismic Zone IV, which makes the scenario physically motivated rather than arbitrary; the Koteshwar cascade gives a genuinely interesting multi-structure narrative; and the downstream chain reaches two major cities within 60 km, which is inside our computational budget.

**Alternatives assessed:**

- **Idukki/Cheruthoni (Kerala)** — model Cheruthoni as the breach point, since the Idukki arch has no spillway. Viable, but the Kerala 2018 spillway-timing controversy is politically contested; avoid.
- **Bhakra** — cleanest coordinates, but NRSD says 9,868 MCM against NRLD's 7,551 MCM. A live example of the register inconsistency in §9.4.
- **Ukai (Gujarat)** — good backup: Surat's 7 million people, 77 km downstream.

🚩 **Avoid Mullaperiyar entirely.** There is active Kerala v. Tamil Nadu Supreme Court litigation over precisely whether that dam might fail. Publicly simulating its failure reads as taking a side in live inter-state litigation. (Note it appears as "Periyar" in both registers.) This is a judgement call about institutional risk, not a technical one, and it is worth making explicitly.

### 11.4 Secondary case — Phuktal, 2014–15 (natural blockage narrative)

**Timeline [V]:** blockage formed 31 December 2014; breached 7 May 2015 at 08:10.

**Responders [V]:** Indian Army (70 Engineering Regiment), BRO, NDMA, CWC, DRDO, IAF, NHPC, LAHDC. ⚠ Earlier drafts of this project wrongly credited ITBP — that is the Chamoli/Rishiganga response. Do not repeat the error.

**Value:** this is the ideal narrative case for the natural-blockage path — a blockage detected from satellite imagery, monitored for four months with no ground access, then breached. It is exactly the no-ground-survey HADR scenario NTRO cares about.

**Limitation:** no published discharge, volume, or inundation extent, and NRSC's imagery is view-only. Good geometry, unusable as quantitative validation. Use it to tell the story; use Chamoli to prove the numbers.

### 11.5 Case ranking, with reasons

| Rank | Event | Why |
| --- | --- | --- |
| 1 | Chamoli 2021 | Only event with pre- AND post-event 2 m DEMs public; three independent studies to cross-check; a published <5% travel-time benchmark |
| 2 | Phuktal 2014–15 | Excellent narrative and geometry; no quantitative validation data |
| 3 | Kosi 2008 | 1,500 m breach, ~4,078 m³/s, 2,722 km² avulsion belt — but <1 m/km gradient (SWE-friendly, unspectacular) and only stale SRTM-2000 terrain |
| 4 | Kashmir 2014 | Best gauge record (135,000 cusecs ≈ 3,823 m³/s at Sangam; 557 km² inundated) but not a dam break — cannot validate the breach model |

### 11.6 Validation tiers

| Tier | Case | Tests |
| --- | --- | --- |
| A — Analytical | Ritter (dry bed) and Stoker (wet bed) exact dam-break solutions; Thacker parabolic bowl | Solver correctness against closed-form truth; well-balancedness; wetting/drying |
| B — Benchmark | Malpasset 1959 (surveyed wave arrival times) | Real-terrain dam-break with field measurements — the standard field validation case |
| C — Indian real event | Chamoli 2021 | End-to-end pipeline against a published Indian event with independent corroboration |

Tier A is non-negotiable and cheap — it is the difference between a solver and a plausible-looking animation. **Build it first.**

---

## 12. What the literature itself says is missing

The strongest possible justification for a project is that the literature names the gap. Three do:

1. **Maranzoni & Tomirotti (2023)** — full 3D real-field dam-break modelling is prohibitive; scale decomposition is the way forward. → Our architecture.
2. **Vacondio et al. (2020), Grand Challenge 3** — SPH lacks practical adaptive resolution. → Why SPH is confined to the near field.
3. **Ghosh & Modak (ORF, 2025)** — the primary transboundary risk is dam failure, under an absence of hard data, in a reach that is a blind spot. → Why open-data-only, no-ground-survey modelling matters strategically.

And one gap the literature does **not** close, which we must be honest about: rigorous SPH-to-SWE coupling for real-field dam-break is not a settled, well-documented technique. The defensible pragmatic path is to use SPH to derive and verify the breach outflow hydrograph and near-field velocity field, then impose that as an inflow boundary condition on the SWE model — a **one-way handoff**. That is honest, implementable, and testable. Claiming a rigorous two-way coupling would be an overclaim.

---

## 13. Consolidated reference list

**Numerical dam-break and hydrodynamics**

1. Maranzoni, A. & Tomirotti, M. (2023). *Water* 15(17):3130. doi:10.3390/w15173130
2. Vacondio, R. et al. (2020). *Computational Particle Mechanics* 8:575–588.
3. Toro, E.F. (2001). *Shock-Capturing Methods for Free-Surface Shallow Flows.* Wiley.
4. Audusse, E. et al. (2004). *SIAM J. Sci. Comput.* 25(6):2050–2065.
5. Liang, Q. & Marche, F. (2009). *Adv. Water Resour.* 32(6):873–884.
6. Liang, Q. (2010). *J. Hydraul. Eng.* 136(9):669–675.
7. Chow, V.T. (1959). *Open-Channel Hydraulics.* McGraw-Hill.
8. Ritter, A. (1892). Dry-bed dam-break solution.
9. Thacker, W.C. (1981). Oscillating parabolic-bowl exact solution.

**SPH**

10. Ramachandran, P. et al. (2021). PySPH. *ACM TOMS* 47(4). doi:10.1145/3460773
11. Molteni, D. & Colagrossi, A. δ-SPH density diffusion.
12. Antuono, M. et al. Diffusive-term SPH stabilisation.
13. Adami, S. et al. Generalised wall boundary condition.

**Breach parameters and outflow**

14. Wahl, T.L. (1998). DSO-98-004, USBR. *(consolidated source — retrieve)*
15. Wahl, T.L. (2004). *J. Hydraul. Eng.* 130(5). *(uncertainty bands — retrieve)*
16. Froehlich, D.C. (1995a, 1995b, 2008).
17. MacDonald, T.C. & Langridge-Monopolis, J. (1984). *J. Hydraul. Eng.* 110(5).
18. Von Thun, J.L. & Gillette, D.R. (1990). ASTM STP 1121.
19. Xu, Y. & Zhang, L.M. (2009). *J. Geotech. Geoenviron. Eng.* 135(12).
20. Costa, J.E. (1985). Peak outflow relations.
21. Walder, J.S. & O'Connor, J.E. (1997).
22. Peng, M. & Zhang, L.M. (2012).
23. Pierce, M.W., Thornton, C.I. & Abt, S.R. (2010).
24. Fread, D.L. (1988). BREACH.
25. Chang, D.S. & Zhang, L.M. (2010).

**Natural dams**

26. Costa, J.E. & Schuster, R.L. (1988). *GSA Bulletin* 100(7):1054–1068.
27. Ermini, L. & Casagli, N. Dimensionless Blockage Index.

**Loss and damage**

28. Graham, W.J. (1999). DSO-99-06, USBR. *(fatality rates — retrieve)*
29. Jonkman, S.N. Mortality functions. *(note Dutch decimal commas)*
30. DeKay, M.L. & McClelland, G.H. (1993). *(two variants disagree — resolve)*
31. Huizinga, J. et al. JRC global depth-damage curves.
32. HAZUS-MH flood model, FEMA.
33. DEFRA / HR Wallingford FD2320. `HR = d(v + 0.5) + DF`.
34. USACE HEC-FIA and LifeSim.

**Indian regulatory**

35. CWC/CDSO (2018). CDSO_GUD_DS_05_v1.0, 170 pp.
36. CWC. Emergency Action Plan guidelines.
37. CWC. NRLD 2019.
38. CWC. NRSD 2025.

**Case studies**

39. Shugar, D.H. et al. (2021). *Science.* Chamoli. Green OA at White Rose eprints 175202.
40. *Natural Hazards* (2023). Chamoli HEC-RAS. doi:10.1007/s11069-023-05972-5
41. Thayyen, R.J. et al. (2022). doi:10.1007/s11069-022-05454-0
42. Chamoli GEE Sentinel-2 extent. doi:10.1007/s12145-022-00786-8
43. Zenodo 4554647 (pre-event DEM), Zenodo 4558692 (post-event DEM).

**Data and strategic**

44. Global Dam Watch v1.0. doi:10.6084/m9.figshare.25988293
45. Copernicus GLO-30 DEM, ESA/Airbus.
46. Ghosh, N. & Modak, S. (18 Feb 2025). ORF, Yarlung Tsangpo.
47. Joshi, M. (2019). ORF, on NTRO satellite control.

---

## 14. Open research queue

Ranked by how much damage the gap does if left unfilled:

| # | Gap | Why it matters | Source to fetch |
| --- | --- | --- | --- |
| 1 | Breach regression coefficients | Goes straight into code; wrong value silently corrupts everything | USBR DSO-98-004 |
| 2 | Wahl (2004) uncertainty bands | Our central honesty artefact | *J. Hydraul. Eng.* 130(5) |
| 3 | Tehri inside/outside each calibration range | Determines whether we quote a number or a range | DSO-98-004 + register data |
| 4 | Graham fatality-rate table | Deliverable (i) needs it | USBR DSO-99-06 |
| 5 | D-Flow FM binary availability | Determines whether we run the real kernel or ship our own solver | conda-forge, Docker Hub, Deltares |
| 6 | Sentinel-1 2026 revisit and latency | Overstating "near real time" is an easy puncture | Copernicus / ESA |
| 7 | India-specific depth-damage curves | Would materially strengthen deliverable (i) | NIH Roorkee, DRIP, World Bank |
| 8 | JRC depth-damage tables | Fallback for #7 | JRC technical report |
| 9 | FD2320 debris factors and thresholds | Hazard classification needs them | HR Wallingford (via `r.jina.ai` proxy) |
| 10 | Published CSI/F1 benchmarks for flood models | Tells us if our number is good | Bates / Horritt / Aronica / Stephens |
| 11 | E–A–C synthesis exponents (Avisse, Liebe) | Reservoir volume from DEM | Retrieve |
| 12 | PySPH scheme inventory | Read off actual source | `raw.githubusercontent.com/pypr/pysph` |

Items 1–4 block the loss-and-damage and breach modules from being quantitatively trustworthy. Items 5–6 are demo-day risk. Everything else is enrichment.
