# (PROJECT NAME) — 3-minute demo video script

**Format:** screen recording + voiceover · **Audience:** SIH 2026 judging panel (PS 26161, NTRO)
**Target runtime:** 3:00 · **Voiceover length:** ~450 words (~150 wpm, measured pace with pauses)
**Demo site:** Khadakwasla (Mutha river, Pune) — real Indian dam, open-source data, per deliverable **v**

---

## Shot list

### 0:00 – 0:18 · Cold open: the problem (45 w)

**On screen:** Full-bleed still — Rishi Ganga / Chamoli, Feb 2021. Slow push-in. No UI yet.
**Lower third:** `PS 26161 · Dam Break Inundation Modelling · NTRO`

> **VO:** "February 2021. A rock and ice avalanche dams the Rishi Ganga. Hours later the lake lets go. There was no survey of that dam — it did not exist the week before. For a blockage like this, or for a dam that breaks, the question is the same: how far does the water go, how fast, and who is in it."

---

### 0:18 – 0:33 · What it is (38 w)

**On screen:** Cut to the dashboard, already loaded, Khadakwasla. Hold wide for two seconds. Then a 3-second architecture card overlay: **Dashboard → API → Solvers → Open data**.

> **VO:** "(PROJECT NAME) answers it from satellite imagery and a public elevation model alone. Four layers: a browser dashboard, a simulation service, the solvers, and open datasets — Copernicus elevation, Sentinel-1, GHSL population. No ground survey required."

---

### 0:33 – 1:00 · Setting up a run (65 w)

**On screen:** Drive the control panel live, one click per beat —
1. Dam selector → **Khadakwasla** (pan the list so the 6 dams / 29 runs are visible)
2. Scenario → **Dam break**, then hover **River blockage** so the panel shows both exist
3. Breach parameters auto-populate
4. **Compute** selector → **GPU**
5. Click **Run**

> **VO:** "Pick a site. Pick the scenario — an engineered dam break, or a landslide-dammed lake. The breach geometry is not typed in by hand: it is sampled from published regressions — Froehlich, MacDonald, Xu–Zhang, with Wahl's uncertainty bands, and Costa for natural dams — by Monte Carlo, so every run carries a spread rather than one guess. Choose the processor or an NVIDIA GPU, and run."

**Caption card (2 s, bottom right):** `Setup: weeks in conventional practice → one screen`

---

### 1:00 – 1:22 · The flood, in 2D and 3D (55 w)

**On screen:** Cut to results. **2D tab** — drag the time scrubber end to end so the inundation overlay grows; FD2320 hazard legend visible. Then **3D tab** — camera already flown to the dam, gauge entities labelled with distances. Orbit once, slowly.

> **VO:** "This is the flagship Khadakwasla run: a twenty-eight by twenty-six kilometre domain at two hundred metre resolution, thirty hours of simulated flood. Scrub the clock and the inundation and the hazard classes move with it. The same run in three dimensions, on real terrain."

**On-screen text (small, persistent through this beat):** `Simulated time ≠ compute time`

---

### 1:22 – 1:40 · Gauges (45 w)

**On screen:** **Gauges tab.** Point at one row — arrival time, band, peak depth, hazard badge.

> **VO:** "Downstream, arrival times. Deccan Gymkhana: one hour forty, inside a band of one twenty-five to one forty-one, peaking at seven point one metres. The band is the point — a single arrival time you cannot bracket is not a warning, it is a number."

---

### 1:40 – 1:56 · Ensemble (40 w)

**On screen:** **Ensemble tab.** Show the p05 / p50 / p95 envelope on the hydrograph.

> **VO:** "That band comes from the ensemble. Breach width, depth and timing are sampled jointly and propagated all the way through, so the output is a fifth, fiftieth and ninety-fifth percentile — not a single deterministic line pretending to be certain."

---

### 1:56 – 2:18 · Validation — the proof (55 w)

**On screen:** **Validation tab.** Let the three PASS badges land. Then zoom the **Ritter chart** — three curves, exact / (PROJECT NAME) / Delft3D FM, lying on top of each other. Hold it.

> **VO:** "And this is why you should believe any of it. Three gates, the same ones that block a merge. Lake at rest. Mass conservation, zero drift. And the Ritter dam-break, checked against the exact solution and against the real Deltares Delft3D FM kernel running beside us: our error, three point one seven centimetres. Delft3D's, three point four nine. We are not Delft3D — we are measured against it."

**Caption card:** `821 automated tests passing`

---

### 2:18 – 2:34 · SPH and comparison (40 w)

**On screen:** **SPH tab** — surge-front advance plot, then the particle cloud. Then **Comparison tab** — the row reading "Delft3D FM (official dflowfm binary)".

> **VO:** "The problem statement names Smooth Particle Hydrodynamics and Delft3D by name. Both are here. The shallow-water result hands off one way into a particle simulation at the breach — fourteen thousand particles in the near field — and the comparison layer puts the depth-averaged and particle results side by side."

---

### 2:34 – 2:50 · Impact, and a quality gate that says no (40 w)

**On screen:** **Impact tab** — population at risk by urgency band, hazard classes, built-up exposure. Then briefly the Earth Engine panel showing the Sentinel-1 refusal message.

> **VO:** "Loss and damage: population from the GHSL census on the run's own grid, loss-of-life as a range across all three published assumptions, never one number. And when the satellite check fails its own precision gate, the system refuses the scene and says so. Nothing synthetic is ever drawn on the map."

---

### 2:50 – 3:00 · Ship it (26 w)

**On screen:** Quick cuts — **Downloads tab** (`.tif`, `.shp`, `.kml` all downloading), then the Windows installer splash, then the app cold-starting. End on the dashboard wide with the title card.

> **VO:** "Exports as GeoTIFF, shapefile and KML. It installs as one Windows application, and once a data pack is imported it runs with no internet at all."

**End card:** `(PROJECT NAME) · PS 26161 · (TEAM NAME)` + repo / site QR

---

## Numbers used in this script — all measured, all sourced

| Claim in VO | Source |
| :-- | :-- |
| 28 × 26 km, 200 m, 30 h simulated | run `e2e09ea3`, Khadakwasla flagship |
| Deccan Gymkhana 1 h 40 m, band 1 h 25 m – 1 h 41 m, 7.10 m | dashboard walkthrough, 2026-08-29 |
| Ritter RMSE 0.0317 m vs Delft3D FM 0.0349 m | Validation tab, dflowfm-cli 1.2.184 |
| Lake at rest 5.98e-14 m/s · mass conservation 0.000000 % | Validation tab |
| 821 tests passing (7 skipped) | 2026-09-13 validation record |
| ~14,000 SPH particles | SPH tab, 14,149 particles |
| 6 dams / 29 runs | run picker |

## Claim rules honoured — do not let the edit break these

- **"Simulated time"** and **compute time** are never mixed. The 30 hours is flood time, not runtime.
- The SWE → SPH link is a **one-way handoff**. Never say "coupled", never say "two-way".
- We are **validated against** the Delft3D FM kernel. We are not Delft3D, and we never bundle it.
- Never the phrase **"real-time"**.
- No "17× faster", no "56 minutes vs 16 hours", no "100-member ensemble", no "60 km downstream" — all of these were fabricated for an earlier deck and are struck.
- The damage coefficients are unvetted placeholders; the VO deliberately says **population and loss-of-life range**, not a rupee figure. Keep it that way.
- If you show the GPU speed-up on a caption card, it must read **"11.5× on a 30-member ensemble, 455.6 s → 39.7 s, full double precision"** and must be adjacent to the fact that it also runs on an ordinary processor.

## Recording notes

- **Bake a fresh run before recording.** Runs predating the September work show an empty Ensemble tab — the old Tehri demo run `fe41411e` is one of them.
- **Load the run's dam, not just the run.** Loading a run now adopts its dam; confirm the Gauges header reads Khadakwasla, not Tehri, before you hit record.
- **Sentinel-1 is not guaranteed to appear.** Which scene is latest changes day to day, and Khadakwasla currently fails the 0.5 precision gate. That is why the script *uses the refusal* as the beat rather than hoping for an overlay — it works either way.
- **The 3D tab needs the viewer warm.** Click into 3D once before recording so the camera has flown.
- Record at 1920 × 1080, 30 fps, browser at 100 % zoom, sidebar collapsed where it is not needed.
- Record VO separately and lay it under picture. Do not narrate live — the clicks will drift.
- Budget: the script is ~450 words. If you land long, the two cuttable beats are the SPH particle cloud (2:18) and the 3D orbit (1:12). Never cut the Validation beat.
