# SIH 2026 — Problem Statement 26161 (Official Text)

> **Source of truth.** Pasted verbatim by the user from the SIH 2026 portal.
> All pitch, PPT, and code decisions must trace back to this file.
> If anything in our materials contradicts this file, this file wins.

| Field | Value |
|---|---|
| **Problem Statement ID** | 26161 |
| **Title** | Dam Break Inundation Modelling Using Hydrodynamic Modelling of any River |
| **Organization** | NTRO — National Technical Research Organisation |
| **Category** | Software (SW) |
| **Theme** | **Disaster Management** ✅ verified — appears in both the PS modal and the table column on sih.gov.in |
| **Dataset Link** (verbatim) | "Open source Remote Sensing data (Sentinel, Landsat or any open source satellite image) and ASTER/ STRM or any other DEM." |
| **Idea submission deadline** | 20 September 2026 |
| **Total SIH 2026 PS** | 226 (54 HW / 172 SW) |
| **Disaster Management theme** | 29 PS total; MoES owns 14, all statistical/ML weather forecasting |
| **Uniqueness** | PS 26161 is the **only** physics-based hydrodynamic-simulation PS and the **only** dam-related PS in all of SIH 2026 |

> **Note on the Dataset Link field.** The PS names ASTER and SRTM, but says "**or any other DEM**".
> We use **Copernicus GLO-30** instead — it is open, no-login, and strictly better than both
> (SRTM is 2000-vintage and void-filled in the Himalaya; ASTER GDEM has known artefacts).
> The PS's own wording explicitly permits this. Say so if asked rather than silently substituting.

---

## Background (verbatim)

In India, due to natural disaster various natural dam / lake formations were observed
which can be a major reason of flash flood in the lower catchment, for example, natural
lake formed over the Rishi Ganga river of Uttarakhand in Feb 2021, Wapriyang river in
Nov 2021, Phuktal river near Sumdo, J&K in Mar 15, Kosi river in 2008 etc. Devastating
flood happened in the Kashmir valley, Assam in 2014 and many other places over a period
of time. Therefore, simulation modelling for flash flood and scenario generation is
important from Humanitarian Assistance and Disaster Relief (HADR) point of view.

Another important aspect is water release issues from the Dam of major rivers. In the
crisis situation, if the dam brakes, how much water will flow into the river and what are
the area it will inundated / impacted need to be estimated. In order to carry out this work
simulation modelling needs to be done for the same. In other way if any dam break
situation happened then what will be the impacted area. Development of a modelling
framework is required which will carry out simulation modelling for the same.

## Description (verbatim)

The above problem statement envisages that a software tool need to be developed which
should automatically carry out the simulation modelling for Dam break analysis and
identify the inundated area due to flash flood in the lower catchment. The modelling
framework should be developed using hydrological data, DEM and satellite imagery of any
river. The software / tools should be capable of carrying out the simulation modelling of
water flow in case of dam break or water release through **'Smooth Particle Hydrodynamics'**
and **'Delft3D'** model and **compare the scenario**.

## Expected Solution / Deliverables (verbatim)

The proposed study aims to illustrate the current problems regarding framework generation
of Humanitarian Assistance and Disaster Relief using simulation modelling related to flood
management as follows:

**i.** Creation of generalized modelling framework to predict / simulate dam break /
river blockage analysis providing the necessary inputs on the basis of sudden water surge
as well as **loss and damage analysis** using 'Smooth Particle Hydrodynamics model and
Delft3D model'.

**ii.** Building a customized tool / framework so that it is possible to generate a flood
inundation simulation scenario using **different input datasets**.

**iii.** Developing a **Dashboard** for providing modelling input and output visualization
framework (GUI). The program should support the **large volume of data**. Output should be
converted to **.shp or .kml** file.

**iv.** Additionally, developing a framework for **near real time flood analysis through
Google Earth Engine** with the help of open source data.

**v.** Simulation needs to be done by taking the **any river and Dam data (open source) of
India** during the final demonstration of the software.

---

## Deliverable → requirement traceability

Every one of these is graded. Nothing here is optional.

| # | Requirement | Non-negotiable implication |
|---|---|---|
| D1 | Dam break **AND river blockage** (landslide-dammed lake) | Two scenario types, not one. Rishi Ganga is a *natural* dam, not an engineered one. |
| D2 | **SPH** model | Lagrangian particle solver. Mesh-free. |
| D3 | **Delft3D** model | Eulerian depth-averaged shallow-water solver. |
| D4 | **Compare** the two scenarios | A quantitative comparison layer is mandatory — this is the PS's own core ask. |
| D5 | Hydrological data + **DEM** + **satellite imagery** | Three input modalities. |
| D6 | **Loss and damage** analysis | Exposure/impact estimation (population, structures, roads). |
| D7 | Automatic operation | "should **automatically** carry out" — minimal manual setup. |
| D8 | Different input datasets | Pluggable DEM/hydrology sources. |
| D9 | Dashboard GUI, large data volumes | Web dashboard, tiled/streamed rendering. |
| D10 | **.shp / .kml** export | GIS interoperability — hard format requirement. |
| D11 | **Google Earth Engine** near-real-time | GEE integration for observed flood extent. |
| D12 | Real Indian dam + river, open-source data, live at finale | No synthetic terrain. Named real site. |

## Reference events named in the PS (validation candidates)

| Event | Date | Type | Why it matters |
|---|---|---|---|
| Rishi Ganga, Uttarakhand | **7 Feb 2021** | Rock/ice avalanche → debris flood; natural lake | Chamoli disaster. **Our headline validation case** — pre/post 2 m DEMs public, published travel times. NOT a GLOF. |
| Wapriyang river | Nov 2021 | Natural lake / blockage | **Does not exist as described.** Near-certain referent is the 29 Oct 2021 Kameng / "Warriyang Bung" sediment event — and **no dam formed**. |
| Phuktal river, Sumdo, J&K | **blocked 31 Dec 2014, breached 7 May 2015** | Landslide-dammed lake | Zanskar/Tsarap. The PS's "Mar 15" is wrong. Breached deliberately by the **Army (70 Engineering Regiment)** — *not* ITBP. |
| Kosi river | 18 Aug 2008 | Embankment breach | Breach at Kusaha, **Nepal**, 12 km above the barrage. Bihar bore the damage. |
| Kashmir valley | Sep 2014 | Riverine flood | Jhelum; heavily imaged. **Rainfall flood — cannot validate a dam-break model.** |
| Assam | 2014 | Riverine flood | Brahmaputra. |

## Framing decision (user-approved)

**Dual-framing, NTRO-led.**

- **Lead** with NTRO's actual interest: HADR scenario generation, natural-dam / river-blockage
  detection and breach simulation from satellite + DEM where **no ground survey exists**,
  and near-real-time monitoring via GEE.
- **Support** with the civil dam-safety impact story (NDSA Emergency Action Plan backlog,
  Dam Safety Act 2021 deadline) as a secondary impact multiplier — never as the headline.

## Framing traps to avoid

- **Do not** pitch "we replace HEC-RAS." The PS never mentions HEC-RAS. The named models
  are SPH and Delft3D. Competing with the wrong tool signals you didn't read the PS.
- **Do not** lead with the NDSA/EAP compliance backlog. NTRO is not the dam-safety regulator.
- **Do not** treat this as engineered-dams-only. Half the named events are natural blockages.
- **Do not** claim to *be* Delft3D if you implement your own solver. State precisely what you
  built and what physics class it belongs to.
