# Deep-Research Prompt — SIH 2026 PS 26161

Copy everything inside the fence below into a research-capable AI (one with live web
search — e.g. Claude with web search, ChatGPT Deep Research, Gemini Deep Research,
or Perplexity Pro). It is self-contained.

---

```
# ROLE

You are a research analyst supporting a student team competing in Smart India Hackathon
(SIH) 2026 on Problem Statement 26161. Your job is to produce a rigorous, decision-ready
research dossier that lets the team (a) win the idea-submission screening round, and
(b) build a working prototype that survives expert technical questioning at the grand finale.

You are NOT writing marketing copy. You are producing verifiable engineering and
competitive intelligence.

# THE PROBLEM STATEMENT (official, verbatim — treat as the source of truth)

Problem Statement ID: 26161
Title: Dam-break inundation modelling via hydrodynamic simulation
Organization: NTRO (National Technical Research Organisation, Government of India)
Category: Software
Idea submission deadline: 20 September 2026

--- BACKGROUND (verbatim) ---
In India, due to natural disaster various natural dam / lake formations were observed which
can be a major reason of flash flood in the lower catchment, for example, natural lake formed
over the Rishi Ganga river of Uttarakhand in Feb 2021, Wapriyang river in Nov 2021, Phuktal
river near Sumdo, J&K in Mar 15, Kosi river in 2008 etc. Devastating flood happened in the
Kashmir valley, Assam in 2014 and many other places over a period of time. Therefore,
simulation modelling for flash flood and scenario generation is important from Humanitarian
Assistance and Disaster Relief (HADR) point of view. Another important aspect is water release
issues from the Dam of major rivers. In the crisis situation, if the dam brakes, how much water
will flow into the river and what are the area it will inundated / impacted need to be estimated.
In order to carry out this work simulation modelling needs to be done for the same. In other way
if any dam break situation happened then what will be the impacted area. Development of a
modelling framework is required which will carry out simulation modelling for the same.

--- DESCRIPTION (verbatim) ---
The above problem statement envisages that a software tool need to be developed which should
automatically carry out the simulation modelling for Dam break analysis and identify the
inundated area due to flash flood in the lower catchment. The modelling framework should be
developed using hydrological data, DEM and satellite imagery of any river. The software/tools
should be capable of carrying out the simulation modelling of water flow in case of dam break
or water release through 'Smooth Particle Hydrodynamics' and 'Delf3D' [sic: Delft3D] model and
compare the scenario.

--- EXPECTED SOLUTION / DELIVERABLES (verbatim) ---
i.   Creation of generalized modelling framework to predict / simulate dam break / river
     blockage analysis providing the necessary inputs on the basis of sudden water surge as
     well as loss and damage analysis using 'Smooth Particle Hydrodynamics model and Delft3D model'.
ii.  Building a customized tool / framework so that it is possible to generate a flood
     inundation simulation scenario using different input datasets.
iii. Developing a Dashboard for providing modelling input and output visualization framework
     (GUI). The program should support the large volume of data. Output should be converted to
     .shp or .Kml file.
iv.  Additionally, developing a framework for near real time flood analysis through Google
     Earth Engine with the help of open source data.
v.   Simulation needs to be done by taking the any river and Dam data (open source) of India
     during the final demonstration of the software.

# CRITICAL CONSTRAINTS ON YOUR RESEARCH

1. The sponsor is NTRO — a technical/geospatial intelligence organisation, NOT the dam-safety
   regulator. The framing the PS itself uses is HADR (Humanitarian Assistance and Disaster
   Relief). Do not assume this is a dam-safety-compliance problem.
2. The PS names two specific models: Smooth Particle Hydrodynamics and Delft3D. It does NOT
   mention HEC-RAS. Research what the PS actually asks for.
3. Scope is BOTH engineered dam break AND natural dam / river blockage (landslide-dammed
   lakes, glacial lake outburst). Several named events (Rishi Ganga, Phuktal) are natural
   blockages, not engineered dam failures.
4. Everything must run on OPEN-SOURCE Indian data and be demonstrated live.

# WHAT TO RESEARCH — answer each numbered section separately

## 1. Sponsor intent — what does NTRO actually want?
- NTRO's mandate, structure, and known technical interests (it is the parent of NCIIPC; it
  operates geospatial/imagery intelligence capabilities). Cite sources.
- Why would a technical intelligence agency, rather than CWC/NDSA/NDMA, commission this?
  Consider: critical-infrastructure risk, HADR planning, assessing terrain where NO ground
  survey or bathymetric survey is available, transboundary/upstream dams and lakes that
  cannot be physically surveyed, and rapid post-event damage assessment from satellite.
- Has NTRO posed related SIH problem statements in past years (2023/2024/2025)? What did
  winning teams build? What does that tell us about how NTRO evaluates?
- Distinguish clearly what is DOCUMENTED about NTRO's interest vs your INFERENCE.

## 2. The named models — feasibility and correct usage
- **Delft3D**: exact licensing and what is genuinely open source (Delft3D 4 suite vs D-Flow
  Flexible Mesh). How is it obtained and built (Windows / Linux / Docker)? Are there prebuilt
  containers? What input files does a dam-break case need? Python tooling (`hydrolib-core`,
  `dfm_tools`, `dfm-tools`, OpenDA)? Published Delft3D dam-break studies to imitate.
  Give a blunt effort estimate in person-days for a first working dam-break run.
- **Smooth Particle Hydrodynamics**: survey DualSPHysics, PySPH, SPlisHSPlasH, GPUSPH, and
  writing a bespoke weakly-compressible SPH. Which is realistically usable in a hackathon
  for a dam-break over real terrain? Document the known numerical stability pitfalls
  (CFL/timestep, tensile instability, particle deficiency at the free surface, kernel choice,
  artificial viscosity vs delta-SPH, boundary condition treatment: dynamic vs ghost particles).
- **Physics honesty**: SPH is a 3D Lagrangian method that is computationally brutal at
  catchment scale; Delft3D-FLOW is a depth-averaged Eulerian shallow-water solver. Explain
  rigorously WHERE each is the right tool — i.e. SPH for the near-field breach / steep,
  highly non-hydrostatic, debris-laden flow; depth-averaged SWE for far-field floodplain
  routing. Find published literature that supports this hybrid/coupled decomposition, and
  any papers that explicitly COMPARE SPH against depth-averaged models for dam break.
  This is the intellectual core of the pitch — find real citations.
- If bespoke depth-averaged SWE is implemented instead of compiling Delft3D, what is the
  defensible framing, and what are the canonical citable numerical schemes? (Look for: Toro's
  HLLC Riemann solver; MUSCL reconstruction; well-balanced bed-slope treatment; Audusse
  hydrostatic reconstruction; Kurganov–Petrova; Liang & Marche wetting/drying.) Name
  well-regarded open-source reference codes: ANUGA, LISFLOOD-FP, GeoClaw, Basilisk, TRITON,
  SERGHEI, Iber, TELEMAC-2D. Which are easiest to actually run and cite?

## 3. Breach hydrograph generation
- The standard empirical breach-parameter regressions with FULL formulas, variable
  definitions, and units: Froehlich (1995, 2008), MacDonald & Langridge-Monopolis (1984),
  Von Thun & Gillette (1990), Xu & Zhang (2009). State each one's applicability limits.
- The breach outflow equation (broad-crested weir formulation) and how reservoir drawdown
  is coupled to it.
- How does breaching of a NATURAL / landslide dam differ physically from an engineered
  embankment? (Costa & Schuster; progressive overtopping erosion; models such as BREACH,
  BRES, DABA.) What parameters can realistically be estimated from satellite + DEM alone?
- Is there any published guidance from Indian agencies (CWC, NDSA, DRIP, NIH Roorkee) on
  breach parameter selection for Indian dams?

## 4. Data — exact sources, licences, and access mechanics
For each, give the precise URL, licence, resolution, whether login/API key is required, and
how to fetch programmatically:
- **DEM**: Copernicus GLO-30, SRTM 30m, ALOS AW3D30, NASADEM, FABDEM, MERIT-DEM, CartoDEM
  (Bhuvan/ISRO). Which is best for an automated no-login pipeline? Which is bare-earth (matters:
  surface DEMs put tree canopy in the channel)? Note that DEMs do NOT include reservoir
  bathymetry — how do practitioners handle the missing underwater volume?
- **Indian dam / reservoir inventory**: India-WRIS (indiawris.gov.in), National Register of
  Large Dams (NRLD/CWC), CWC reservoir storage bulletins, DRIP. What fields are public (height,
  gross storage, crest level, coordinates, spillway capacity)? Is there an API?
- **Global dam databases as fallback**: GRanD, GOODD, GDW (Global Dam Watch), OpenStreetMap.
- **Satellite imagery / flood observation**: Sentinel-1 GRD (SAR — works through cloud, the
  standard for flood mapping), Sentinel-2, Landsat, JRC Global Surface Water, MODIS/VIIRS
  flood products, Bhuvan flood layers, NRSC/ISRO flood hazard atlases.
- **Exposure for loss-and-damage**: WorldPop, GHSL (GHS-POP, GHS-BUILT-S), Meta HRSL,
  OpenStreetMap buildings/roads, Census of India village-level data, critical facilities
  (hospitals, schools) sources for India.
- Which of the above are available as ready-to-use Google Earth Engine assets? Give exact
  GEE dataset IDs.

## 5. Google Earth Engine near-real-time flood analysis
- Current (2026) GEE access model: Cloud project requirement, free non-commercial tier
  eligibility, quotas. Python API (`earthengine-api`, `geemap`) usage patterns.
- The standard Sentinel-1 SAR flood-mapping recipe (UN-SPIDER / GEE community practice):
  pre/post image selection, speckle filtering, thresholding or change detection, permanent-water
  masking with JRC GSW, slope masking with a DEM. Give a working code outline and cite the
  recommended tutorial(s).
- Realistic revisit/latency for Sentinel-1 over India, and what "near real time" honestly means.
- How would OBSERVED flood extent from GEE be used to VALIDATE a simulated extent? Name the
  standard agreement metrics used in flood-model validation literature (Critical Success Index,
  F1/F-statistic, hit rate, false-alarm ratio, Nash–Sutcliffe for hydrographs). Give formulas.

## 6. Validation — the credibility test
The single strongest thing this team can show is that their simulation reproduces a real,
documented historical flood. For each event named in the PS, report what PUBLISHED QUANTITATIVE
data exists that could serve as ground truth — peak discharge (m³/s), lake/reservoir volume,
breach geometry, flood extent area, inundation depths, wave arrival times, and any downloadable
maps/shapefiles:
- Rishi Ganga / Chamoli, Uttarakhand — 7 Feb 2021 (look for the Shugar et al. Science paper and
  the HESS / Landslides / NHESS follow-ups with reconstructed hydrographs)
- Phuktal river landslide dam, Sumdo, Zanskar, J&K — 2015 (ITBP deliberate breach)
- Kosi river embankment breach, Bihar — Aug 2008
- Kashmir valley (Jhelum) — Sep 2014; Assam (Brahmaputra) — 2014
- "Wapriyang river, Nov 2021" — verify this location and spelling; it may be a transliteration
  of a place in Arunachal Pradesh or Tibet. Report what you find, or that you cannot confirm it.
Then RANK these by usability as a hackathon validation target and recommend ONE.
- Also research the classic benchmark cases used to verify dam-break codes: the analytical
  Ritter/Stoker dry-bed dam-break solution, the Malpasset 1959 dam failure (the standard
  real-world validation case, with surveyed wave arrival times), and the EU CADAM / IMPACT
  project test cases. These let the team prove solver correctness independently of terrain.

## 7. Competitive and strategic analysis (SIH-specific)
- What existing software already does this, and what specifically does each NOT do?
  Cover: HEC-RAS 2D, Delft3D, MIKE FLOOD/MIKE 21, TELEMAC-2D, Iber, ANUGA, LISFLOOD-FP,
  FLO-2D, TUFLOW, SMS, GeoClaw, and any Indian/ISRO in-house tools. For each: licence cost,
  expertise required, setup time per dam, whether it automates DEM ingestion, whether it does
  SPH at all, and whether it produces exposure/loss estimates.
- Identify the genuine, defensible white space. Be sceptical and specific: is the real gap
  (a) automation of the whole pipeline from coordinates to map, (b) the SPH-vs-Eulerian
  cross-validation the PS asks for, (c) natural/landslide-dam scenarios which commercial dam
  tools handle poorly, (d) the satellite-observation feedback loop, or (e) the loss-and-damage
  layer? Rank by defensibility.
- What will OTHER SIH teams most likely do on this PS, and what is the most likely failure
  mode of a typical attempt? How does a team differentiate beyond "we made a nicer UI"?
- Research SIH judging: the evaluation criteria/marking scheme at internal screening, national
  screening, and grand finale. What do SIH judges reward and penalise? Find first-hand accounts
  from past SIH winners and mentors/jury members. What gets ideas rejected at screening?

## 8. Hard technical risks — argue against the team
Play devil's advocate. Identify the specific ways this project fails technically, and for each
give a concrete mitigation:
- Numerical instability, CFL violations, and the visible symptoms in a demo (water "teleporting",
  checkerboard oscillations, negative depths, mass non-conservation).
- Computational cost: what grid size and time-step are needed for a realistic reach, and can it
  actually run live on a laptop in minutes? What resolution/domain trade-off makes a live demo
  possible? Is GPU acceleration necessary?
- Missing reservoir bathymetry; DEM vertical error and its effect on inundation extent; surface
  vs bare-earth DEM; DEM voids in Himalayan terrain.
- Manning's roughness parameterisation from land cover, and sensitivity of results to it.
- Sediment/debris: the Rishi Ganga event was a debris flow, not clear water. Does modelling it
  as clear water invalidate the result? What is the honest caveat?
- The ethics and liability of publishing inundation maps that a district officer might act on:
  what disclaimers and uncertainty communication do professional practice and Indian regulation
  require?

## 9. Prior art to learn from
- Published papers/theses that automate dam-break inundation mapping at scale (e.g. national
  screening-level dam-break studies, USACE/FEMA simplified dam-break screening methods,
  "rapid dam break assessment" literature).
- Any open-source project that already couples DEM ingestion → breach hydrograph → 2D solver →
  web map. Find the closest existing thing to what this team proposes and state honestly how
  much of the work is already done somewhere.
- Existing SPH-vs-shallow-water comparison studies for dam break.

# OUTPUT REQUIREMENTS

- Answer sections 1–9 in order, with clear headings.
- Every factual claim gets an inline source URL. If you cannot verify something, write
  "UNVERIFIED" and say what you searched. Do NOT fill gaps with plausible-sounding invention —
  a fabricated statistic that a judge checks will lose this competition outright.
- Give exact numbers, formulas, dataset IDs, and URLs wherever possible, not summaries.
- For every recommendation, state the effort estimate and the main risk.
- End with:
  (a) **Top 5 findings that should change the team's plan**, ranked by impact.
  (b) **A recommended 6-slide idea-submission narrative** matching SIH's template
      (Title / Idea Title / Technical Approach / Feasibility and Viability / Impact and
      Benefits / Research and References).
  (c) **A prioritised build order** for the prototype, marking what is essential for the
      demo vs deferrable.
  (d) **The 10 hardest questions a technical judge would ask**, each with the strongest
      honest answer — and flag any question the team currently cannot answer well.
```

---

## Notes on using this prompt

- **Run it with a tool that has live web search.** Without search it will hallucinate dataset
  IDs and paper citations, which is worse than no answer here.
- **Section 6 (validation) and section 8 (risks) are the highest-value parts.** If the tool
  truncates, re-run those two sections on their own.
- **Verify before you cite.** Anything that lands in the PPT's *Research and References* slide
  should be opened and read, not trusted from a summary. Judges do check.
- Ask for the "Wapriyang river" spelling explicitly — it appears to be a transliteration and
  may not resolve. Not being able to confirm it is a legitimate finding, not a failure.
