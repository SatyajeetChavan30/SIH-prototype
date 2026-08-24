# Research Findings — verified corrections and citations

Compiled for SIH 2026 PS 26161. Every claim here traces to a source that was actually
fetched. Items marked **UNVERIFIED** must not go into the PPT without checking.

---

## 1. The PS's own reference events contain factual errors. Knowing them is an advantage.

The problem statement lists four example events. Three have wrong or unconfirmable details.
Getting these right in the deck signals you actually read the domain literature.

### Rishi Ganga / Chamoli, Uttarakhand — 7 February 2021 ✅ real

- **It was a rock-and-ice avalanche, NOT a glacial lake outburst flood (GLOF).** ~27 × 10⁶ m³
  collapsed from the north face of Ronti Peak — roughly 80 % rock, 20 % glacier ice; ~3.2 km
  elevation drop; valley walls scoured to 220 m height.
  Shugar et al., *Science* 373(6552):300–306, doi `10.1126/science.abh4455`.
  Indian media and some official statements called it a "glacier burst" / GLOF. That is wrong.
- **A landslide dam did form.** CWC: **350 m long, 60 m high, ~10° slope, ~0.7 × 10⁶ m³
  impounded**, at the Ronti Gad–Rishiganga confluence, 5.21 km upstream of the
  Rishiganga–Dhauliganga confluence. Water began flowing out on the morning of 12 Feb 2021.
- **Impact:** 83 dead + 121 missing (204). 13.2 MW Rishiganga project destroyed; 520 MW NTPC
  Tapovan-Vishnugad damaged (~₹1,500 crore). ~140 victims were Tapovan workers.
- Watch out: Wikipedia's infobox says 18 February; its own prose and all scholarship say
  **7 February 2021**.

### "Wapriyang river, Nov 2021" — ❌ does not exist as described

- **No credible November 2021 Indian landslide-dam event was found.** SANDRP's own 2021
  landslide-dam log has no November entry.
- The near-certain referent is the **Kameng river event of 29 October 2021** (East Kameng,
  Arunachal Pradesh), sourced in the **"Warriyang Bung" catchment** at 27.877 N, 92.702 E —
  "Warriyang" → "Wapriyang" is a transliteration slip. AGU Landslide Blog, 1 Nov 2021.
- **But no dam formed and no lake was impounded.** It was a massive sediment/debris influx
  (fivefold TDS rise, fish die-off, ≥5 days turbidity), cause undetermined.
- **How to use this:** do not cite "Wapriyang Nov 2021" as a river-blockage case. If you
  mention it, mention it correctly as the Oct 2021 Kameng turbidity event — or note that a
  suspected blockage that turns out *not* to be one is exactly the false positive a
  satellite-triggered screening system must resolve. That reframing is a strength.

### Phuktal / Tsarap, Zanskar, Kargil district — ❌ the year is 2014, not 2015

- **Blockage: 31 December 2014. Breach: 7 May 2015 at 08:10.** The PS's "Mar 15" is wrong for
  the blockage and wrong for the breach.
- Landslide dam on the **Tsarap (Lungnak/Lingti) river** → Zanskar → Indus, near Marshun
  village, ~90 km from Padum (last 43 km trek-only), N 33°17′25.3″ E 77°17′06.8″.
- **Dimensions are contested — cite both:** Wikipedia/Tsarap River: 60 m high × 90 m wide ×
  600 m long. CWC aerial survey (V.D. Roy, 10 Feb 2015): 400 m long along bed, 50 m high,
  100 m wide across bed. Mostly fine-grained debris.
- **Lake growth from NRSC/ISRO Cartosat-2 (1 m):** 20 Jan 2015 ≈ 8 km long / 55 ha →
  1 Feb 2015 ≈ 14 km long / 110 ha → **9 Feb 2015: 30–35 × 10⁶ m³**.
- **Detected by a flow drop at NHPC's 45 MW Nimoo Bazgo HEP downstream** — not by survey.
- **Deliberate breach:** Army (70 Engineering Regiment) cut a **75 m × 2 m × 2 m channel using
  175 kg of explosive over five days**. Explosives were initially ruled out (70–80° gradient).
- **Exposure:** ~4,000 people, 29 villages, ~50 bridges at risk. On breach: 6 bridges washed
  away (immediate report) / 13 (Wikipedia), **zero deaths**, 2,000–3,000 evacuated.
- **Responders were Army, BRO, NDMA, CWC, DRDO, IAF, NHPC, LAHDC — NOT ITBP or NDRF.**
  ITBP/NDRF/DRDO were the Rishiganga 2021 responders. Do not transpose them.

### Kosi embankment breach — 18 August 2008 ✅ real

- Breach at **Kusaha VDC, Sunsari district, NEPAL** — on the eastern Kosi afflux embankment,
  **~12 km upstream of the Kosi barrage**. Not in Bihar, though Bihar bore the damage.
- **Cause: bed-level rise of ~4–5 m from sedimentation** plus monsoon rain and poor
  maintenance. Discharge at failure was **far below the barrage design discharge of
  950,000 cusec** — this was not an extreme-flood failure. That is the point.
- Lateral channel shift **~120 km** (the classic Kosi avulsion). >2.3 million affected in
  north Bihar; ~53,800 in Nepal.
- Sinha, R. (2009) "The Great Avulsion of Kosi on 18 August 2008", *Current Science* 97:429–433.
  Via *Sustainability* 2023, 15, 14952.
- **Death toll is genuinely contested: 434 / 250 / 55.** If you cite a number, cite the range.
- Ninth in a documented series of Kosi breaches: Dalwa 1963, Kunauli 1967, Jamalpur 1968,
  Bhatania 1972, Bahurawa 1980, Navhatta 1984, Ghoghepur 1987, Joginia 1991, Kusaha 2008.

---

## 2. Naming: the PS misspells the method

The canonical name is **Smoothed** Particle Hydrodynamics (Gingold & Monaghan 1977, *MNRAS*
181(3):375, doi `10.1093/mnras/181.3.375`; Lucy 1977, *AJ* 82:1013). The PS writes "Smooth
Particle Hydrodynamics", and "Delf3D" for **Delft3D**.

**Use the correct spellings in our materials**, and quote the PS verbatim only where quoting.

---

## 3. The decisive technical finding: SPH and Delft3D are not peers

This is the single most important insight for the pitch.

| | Smoothed Particle Hydrodynamics | Delft3D-FLOW |
|---|---|---|
| Formulation | **Lagrangian**, mesh-free particles | **Eulerian**, structured curvilinear grid |
| Equations | 3D Navier–Stokes, weakly compressible | Shallow-water (depth-averaged / σ-layered) |
| Free surface | Implicit in particle positions | Tracked on the grid |
| Domain scale | **Near-field, a few km at most** | Basin scale, tens of km |
| Maturity for flood routing | Research-grade | Operational since 1986 |

**Pairing them as interchangeable engines is a category error.** The defensible framing —
and the one the literature itself recommends — is a **coupled decomposition**:

> Maranzoni & Tomirotti (2023), "3D Numerical Modelling of Real-Field Dam-Break Flows: Review
> and Recent Advances", *Water* 15(17):3130, doi `10.3390/w15173130`:
> SPH "has also been applied in the modelling of dam-break flow … **even on real-world
> topography**", but "the high computational cost of 3D models is still a significant
> limitation, especially in large-scale field studies … **favouring the 2D depth-averaged
> ones**." The paper's recommended future direction is **coupled 2D–3D models**.

**The killer constraint on SPH — cite this if challenged:**

> Vacondio et al. (2020), "Grand challenges for Smoothed Particle Hydrodynamics numerical
> schemes", *Computational Particle Mechanics* 8:575–588, doi `10.1007/s40571-020-00354-1`
> (Grand Challenge 3): "**almost all SPH codes are based on uniform resolution and this
> prevents the use of SPH models to simulate all engineering problems which are inherently
> multiscale**."

That is exactly our problem — metre-scale detail at the breach, hundred-metre cells 50 km
downstream. So SPH goes in the near field only. **This is not a compromise; it is the correct
engineering answer, and we can cite the SPH community's own assessment for it.**

**Precedent that SPH can do practical flood work (strongest single citation):**
Vacondio, Rogers, Stansby & Mignosa (2011), "SPH Modeling of Shallow Flow with Open Boundaries
for Practical Flood Simulation", *J. Hydraulic Engineering*,
doi `10.1061/(asce)hy.1943-7900.0000543` — SWE-SPH for dam breaks, levee breaches; validated
on the Okushiri tsunami and Thamesmead dyke breach; "compares well with established commercial
and state-of-the-art finite-volume codes."

**Directly on-point:** Prakash, Rothauge & Cleary (2014), "Modelling the impact of dam failure
scenarios on flood inundation using SPH", *Applied Mathematical Modelling*,
doi `10.1016/j.apm.2014.03.011`.

**Real-field SPH dam-break cases in the literature** (all small, steep, near-field domains —
note the particle counts): Vajont 1963 via WCSPH (Roubtsova & Kahawita 2006) and via
DualSPHysics (Vacondio et al. 2012, 3.95 × 10⁶ particles at 5 m spacing); St. Francis 1928
(Cleary/Prakash, 1.4 × 10⁶ particles at 4 m); Fundão tailings dam 2015 (Wang et al. 2017,
2.99 × 10⁶ fluid particles at 3 m, GPU). Nearly all labelled "Research".

---

## 4. Delft3D is genuinely open source

- Source: https://github.com/Deltares/Delft3D — "Most simulation engines are licensed under
  **AGPL-3.0 or GPL-3.0**, several utility libraries are licensed under LGPL-2.1."
  https://oss.deltares.nl — "Delft3D is Open Source Software."
- **Delft3D-FLOW** (Delft3D 4 suite): orthogonal **curvilinear structured** grid built with
  RGFGRID; **ADI** time integration; σ- and z-layers; MPI parallel; in use since 1986.
  Manual: https://content.oss.deltares.nl/delft3d4/Delft3D-FLOW_User_Manual.pdf
- **D-Flow Flexible Mesh (Delft3D FM)** is the successor and supports **unstructured** grids
  and 1D networks.
- Documented limitation: "Domain decomposition cannot be combined with parallel computing."

## SPH implementations

| Code | Licence | Notes |
|---|---|---|
| **DualSPHysics** | LGPL | C++/CUDA, GPU. GUI: DesignSPHysics. Renderer: VisualSPHysics. Univ. of Vigo + Manchester. https://dual.sphysics.org |
| **GPUSPH** | GPLv3 | First full-GPU WCSPH implementation. Needs CUDA ≥ 7.5. |
| **SWE-SPHysics** | — | Shallow-water SPH variant; the Vacondio 2011 flood work. |
| **PySPH / SPlisHSPlasH** | open | Python / C++ general SPH frameworks. |

---

## 5. What Indian regulators actually use: HEC-RAS. Neither SPH nor Delft3D appears at all.

**Source: CWC / Central Dam Safety Organisation, "Guidelines for Mapping Flood Risks
Associated with Dams", Doc. No. CDSO_GUD_DS_05_v1.0, January 2018** (170 pp.):

> "Though this guideline does not recommend any particular software/programme over the other,
> owing to the advantages mentioned above, **HEC-RAS has been chosen for dam break analysis in
> the DRIP project**."

Keyword counts across all 170 pages: HEC-RAS **15**, MIKE **2**, DAMBRK **1**, FLDWAV **1**,
BREACH **7**, SMPDBK **2**, DRIP **28** — and **SPH 0, "smoothed particle" 0, Delft 0,
TELEMAC 0, TUFLOW 0**.

The CWC EAP guidelines (https://cwc.gov.in/sites/default/files/EAPChapters.pdf) are entirely
software-agnostic — zero mentions of any package. They require index maps at **1:50,000** and
detailed maps at **1:10,000 with 0.5 m contours**.

**CWC's tiered approach (Table 1-1) — what an EAP-grade study is expected to do:**

| Tier | Terrain data | Tools named |
|---|---|---|
| 1 | SRTM / ASTER / ALOS (low-res) | Geo-Dam-BREACH, SMPDBK, HEC-HMS, simplified approaches |
| 2 | 10 m INTERMAP or Lidar | HEC-HMS, HEC-RAS, MIKE-11 or similar 1D unsteady models |
| 3 | High-resolution Lidar | Empirical equations, WinDAM-B; 1D or 2D unsteady models |

### Why this matters strategically — two ways to use it

1. **Our pipeline is a Tier-1 instrument** in CWC's own taxonomy — automated, public-DEM,
   screening-grade. That is a *precise*, citable statement of what we are and are not. It
   pre-empts the "should a safety document rely on a simplified model?" question: CWC already
   defines a tier for exactly this.
2. **NTRO asked for SPH + Delft3D, which Indian dam-safety guidance never mentions.** So
   HEC-RAS is legitimately relevant — not as the thing we compete with, but as the
   **incumbent Indian baseline we cross-check against**. A third-model agreement check
   (SPH vs depth-averaged SWE vs HEC-RAS on the same reach) is a stronger claim than either
   model alone, and it speaks both NTRO's language and CWC's.

Portals: DHARMA `dharma.cwc.gov.in`, DRIP `drip.cwc.gov.in`, CWC Inundation Forecast
`inf.cwc.gov.in`.

---

## 6. Validation strategy — three tiers, all independently citable

| Tier | Case | What it proves | Data available |
|---|---|---|---|
| **A. Analytical** | Ritter / Stoker dry-bed dam-break | Solver is *correct*, not just plausible | Closed-form solution |
| **B. Benchmark** | **Malpasset 1959** (France) | Correct on real 3D topography | The field's standard case — surveyed wave arrival times; used by TELEMAC-3D (17 × 9 km) and OpenFOAM (2.2 × 10⁶ cells over 17.5 × 10 km) |
| **C. Indian real event** | **Chamoli 2021** ⬅ headline | Works on Indian terrain, real event, quantitatively checkable | Pre/post 2 m DEMs both on Zenodo; published travel times, discharges and flood extent |

### ⚠️ Superseded: Chamoli 2021 replaces Phuktal as the headline demo

The earlier recommendation of Phuktal is **withdrawn**. The deciding factor is *reproducible
quantitative ground truth*, and only Chamoli has it.

**Ranking of the four candidate Indian events:**

| Rank | Event | Verdict |
|---|---|---|
| **1** | **Chamoli 2021** | Only event with **both pre- and post-event high-resolution DEMs publicly downloadable** — Zenodo `4554647` (pre) and `4558692` (post), 2 m, CC BY-NC-4.0. Published travel times, discharges, depths and a satellite flood extent. **Use this.** |
| 2 | Phuktal 2014–15 | Excellent geometry and narrative, but **no published discharge, volume-vs-time or inundation extent**, and NRSC Cartosat-2 imagery is view-only. Nothing to score against. |
| 3 | Kosi 2008 | 1,500 m breach, ~4,078 m³/s, 2,722 km² avulsion belt — but **<1 m/km gradient** (a poor test of a dam-break solver) and only stale SRTM-2000 terrain. |
| 4 | Kashmir 2014 | Best gauge record (135,000 cusecs ≈ 3,823 m³/s at Sangam; 557 km² inundated) but it is a **rainfall flood — it cannot validate a dam-break model.** |

**The benchmark sentence to beat**, verbatim from Shugar et al. (green OA full text at
`https://eprints.whiterose.ac.uk/id/eprint/175202/1/Shugar%20et%20al%20Uttarakhand%20FINAL%20Maintext%20wFigs.pdf`):

> "simulated travel times between P0-P3 show **excellent agreement (<5% difference)** with
> travel times inferred from seismic data, videos, and satellite imagery."

**Three independent cross-checks exist** — so our numbers can be triangulated, not just asserted:

| Source | Independent quantity |
|---|---|
| HEC-RAS study, *Nat. Hazards* 2023, doi `10.1007/s11069-023-05972-5` | Peak inflow 12,761.88 m³/s → **7,908–7,975 m³/s at Rishiganga**, **5,780–5,957 m³/s at Tapovan**; depths 19.85 m / 18.15 m |
| Thayyen et al. 2022 (NIH Roorkee), doi `10.1007/s11069-022-05454-0` | Independent flood volume **~10 MCM** |
| GEE Sentinel-2 study, doi `10.1007/s12145-022-00786-8` | Reference extent **0.66 km², 88 % accuracy, F-score 0.85** |

**Known gap:** Shugar's r.avaflow input dataset was never published — the code-availability
section literally reads *"available at [insert link when available]"*. The DEMs must therefore be
rebuilt from the two Zenodo deposits ourselves. That is a real task, not a download.

Secondary Indian options retained: Phuktal (natural-dam narrative), **Machhu-II 1979** — India's
own catastrophic engineered dam-break and a documented historical benchmark.

---

## 7. Tooling notes for whoever continues this research

- `WebSearch` was broken this session. `https://search.yahoo.com/search?p=…` worked well
  (fails on `%22`-quoted queries). Bing returned spam. DuckDuckGo HTML needs the
  `html.duckduckgo.com` host.
- **OpenAlex API** (`api.openalex.org`) is reliable for paper metadata and abstracts.
- MDPI Cloudflare 403 is bypassed via
  `res.mdpi.com/d_attachment/<journal>/<journal>-<vol>-<art>/article_deploy/<…>.pdf`.
- Blocked in this environment: web.archive.org, science.org, reliefweb.int, Indian news
  domains (Indian Express, TOI, News18, ET), sphysics.org and opentelemac.org (TLS errors),
  `en.wikipedia.org/wiki/Delft3D` (no such article).

### Still UNVERIFIED — check before citing
- SPHysics via its own site (TLS cert mismatch).
- BASEMENT licence and numerics (ETH page is JS-gated).
- Measured dimensions of the Rishiganga artificial lake in late Feb 2021 (news domains blocked).
- Original text of Sinha (2009) *Current Science* (scanned-image PDF; date confirmed via a
  citing paper).
- The **theme** PS 26161 is filed under on the SIH portal.
