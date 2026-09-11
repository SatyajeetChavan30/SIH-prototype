Build a clean, modern, single-page project website for **(PROJECT NAME)**, our Smart India Hackathon 2026 entry. The site's job: in under two minutes of scrolling, show screening judges what we are building, how far we have got, what we have measured, and where to get the code and the detailed document. It should look credible and technical, like a research project page, not a marketing landing page.

---

## 1. Technical requirements

- **Static site only.** React + Vite + Tailwind CSS (or plain HTML/CSS/JS). It must build to static files and deploy for free on GitHub Pages, Netlify or Vercel. No backend, no database, no login, no API keys, no runtime calls to external APIs.
- **One content file.** Put ALL text, numbers, links, statuses and dates in a single file (`src/content.js` or `content.json`) so we can update progress by editing only that file. The project name is one variable there: `PROJECT_NAME = "(PROJECT NAME)"`, used everywhere on the page, in the `<title>` and in meta tags.
- **Placeholders.** Everything written in CAPS inside parentheses, like `(GITHUB REPO URL)`, is a placeholder. Keep it exactly as written in the content file. Do not invent a project name, links or team names.
- **Images.** Create an `/public/images/` folder. Wherever an image slot is described below, show a light-blue placeholder box displaying the caption and the expected filename until we drop the real file in.
- Fully responsive (375 px phone up to wide desktop), semantic HTML, keyboard accessible, visible focus states, alt text on every image, honours `prefers-reduced-motion`.
- Lightweight: charts in Recharts or plain SVG, images lazy-loaded, no heavy animation libraries.
- Include a short `README.md` explaining how to run locally and how to deploy to GitHub Pages (set Vite `base` correctly) and to Netlify.
- Add `<title>(PROJECT NAME) — SIH 2026 · PS 26161</title>`, a meta description, and a simple SVG water-drop favicon.

---

## 2. Visual design — white and light blue

Overall feel: calm, clean, scientific. Lots of white space. Water-inspired but restrained. Light theme only.

**Palette**

| Role | Colour |
| --- | --- |
| Page background | `#FFFFFF` |
| Alternate section background | `#F3F8FD` |
| Light-blue cards, tags, table header | `#E3F0FB` |
| Borders and dividers | `#CFE3F5` |
| Decorative light blue (waves, icons, illustrations — never text) | `#7BB8E8` |
| Primary blue: buttons, links, key numbers | `#1E6FB8` (hover `#185C99`) |
| Headings | `#0B2545` (deep navy) |
| Body text | `#334E68` |
| Muted text, captions | `#5B7083` |
| Status "Done" | text `#17704A` on `#E6F6EE` |
| Status "In progress" | text `#8A5A0B` on `#FDF4E3` |
| Status "Next" | text `#5B7083` on `#EEF2F6` |

- All text must pass WCAG AA contrast. Light blues are for backgrounds and decoration only, never for body text.
- Status badges always carry a text label and a small icon (check, half-circle, arrow), never colour alone.
- Typography: **Inter** from Google Fonts with a system-font fallback. Semibold headings, relaxed line height, tabular numerals for all statistics.
- Components: rounded cards (12–16 px radius), 1 px `#CFE3F5` border, very soft shadow; pill-shaped badges; primary buttons solid `#1E6FB8` with white text, secondary buttons white with a blue outline.
- Hero only: a soft vertical gradient from `#FFFFFF` to `#EAF4FC`, and a subtle light-blue SVG wave divider at its bottom edge.
- Sections alternate between white and `#F3F8FD` backgrounds.
- Do NOT use: stock photos, emojis, dark mode, neon or rainbow gradients, glassmorphism, third-party brand logos.

---

## 3. Page sections, in this order

### Navbar (sticky)
White with a thin bottom border. Left: a small SVG wave/water-drop icon and the text "(PROJECT NAME)". Links: Overview · Problem · How it works · Progress · Results · Next steps · Resources · Team. Highlight the current section while scrolling; smooth-scroll to anchors; collapse to a hamburger menu on mobile. Right side: primary button **"View on GitHub"** → `(GITHUB REPO URL)`.

### 1 — Hero (`#overview`)
- Eyebrow line: **Smart India Hackathon 2026 · Problem Statement 26161 · NTRO · Disaster Management**
- Title: **(PROJECT NAME)**
- Subtitle: *"An open-data framework that simulates dam-break and river-blockage floods, maps who is at risk, and checks its answers against analytical solutions and the Delft3D FM kernel."*
- Status pill: **Working prototype · Last updated (LAST UPDATED DATE)**
- Buttons: **Read the detailed document** → `(DOCUMENT LINK)` (primary) · **Download the framework** → `(GITHUB RELEASE DOWNLOAD URL)` (secondary) · **Watch the demo** → `(DEMO VIDEO LINK)` (text link)
- Image slot beside the text (below it on mobile), shown inside a simple browser-window frame: `images/dashboard-2d3d.png` — caption "Our dashboard: 2D flood map and 3D terrain globe".
- Under the hero, a row of four stat cards, with exactly this wording:
  1. **600** — automated tests passing (4 skipped)
  2. **0.0317 m** — RMSE against the exact Ritter dam-break solution (Delft3D FM: 0.0349 m)
  3. **0.000000 %** — mass-conservation error in the 2D flood solver
  4. **8** — dashboard tabs running on real simulation data

### 2 — The problem (`#problem`)
Two columns (stacked on mobile).

Left text:
> When a dam fails, or a landslide blocks a river and the lake behind it later bursts, authorities need to know quickly where the water will go, when it will arrive and who is in its path. Natural blockages such as the Rishi Ganga (Uttarakhand, February 2021) and the Phuktal (Zanskar, 2014–15) have no surveyed height and no surveyed storage — the lake has to be measured from terrain and satellite data. Problem Statement 26161 asks for a tool that automatically simulates these floods from open DEM and satellite data, uses Smoothed Particle Hydrodynamics and Delft3D and compares them, estimates loss and damage, exports .shp and .kml, shows everything on a dashboard, and uses Google Earth Engine for near-real-time analysis.

Right: a light-blue card titled "Problem Statement 26161" with four rows — Title: *Dam Break Inundation Modelling Using Hydrodynamic Modelling of any River* · Organisation: *NTRO* · Category: *Software* · Theme: *Disaster Management*.

### 3 — How it works (`#how`)
A six-step pipeline: horizontal row of connected cards on desktop, vertical stepper on mobile. Each card has a simple line icon, a title and one or two lines of text:

1. **Open data in** — Copernicus GLO-30 elevation model, Sentinel-1 radar through Google Earth Engine, GHSL population. Cached locally, so the demo runs offline.
2. **Pick a scenario** — Dam break, or river blockage (landslide dam) whose lake volume is measured from the terrain, not typed in.
3. **Breach ensemble** — Published breach formulas (Froehlich; MacDonald & Langridge-Monopolis; Von Thun & Gillette; Costa for natural dams) with Wahl (2004) uncertainty bands, sampled Monte Carlo.
4. **Simulate the flood** — A well-balanced 2D shallow-water solver (HLLC fluxes, hydrostatic reconstruction, Manning friction) for the far field, and SPH (PySPH) for the near field through a one-way handoff.
5. **Compare and validate** — Scored against exact analytical solutions and against the real Delft3D FM kernel.
6. **Impact and export** — FD2320 hazard classes, population at risk, loss-of-life ranges. Exports to Shapefile, KML and GeoTIFF. Everything viewable on the dashboard.

Below it, an **Architecture** block drawn in HTML/SVG (not an image): four stacked horizontal bands in light blue, connected by small downward arrows, each band with a title on the left and chips on the right:

- **Dashboard** — React · Vite · Leaflet 2D map · CesiumJS 3D globe · Recharts
- **API** — FastAPI: start runs, track progress, fetch results and exports
- **Simulation engine** — Python · NumPy · Numba: 2D shallow-water solver · SPH near-field · ensemble engine · validation suite · impact module · export engine
- **Open data** — Copernicus GLO-30 DEM · Sentinel-1 (Google Earth Engine) · JRC Global Surface Water · GHSL population

Then a small highlighted note card, titled **"Honest by design"**: *"Features that cannot be verified with open data refuse to run instead of guessing, and every coefficient still awaiting source verification is labelled as a placeholder in the output."*

### 4 — Progress (`#progress`)
Heading: **Progress against the problem statement**. Sub-heading: *Every deliverable in PS 26161 and where it stands today.*

Above the table, a segmented progress bar labelled **"10 of 12 deliverables working · 2 in progress"** (10 green segments, 2 amber).

Then a table (turning into stacked cards on mobile) with columns: **#** · **Requirement** · **Status** · **What exists today**

| # | Requirement | Status | What exists today |
| --- | --- | --- | --- |
| D1 | Dam break and river blockage | Done | Both scenario types run end to end: Khadakwasla dam (dam break) and Rishi Ganga (river blockage) |
| D2 | Smoothed Particle Hydrodynamics | Done | PySPH near-field solver, fed by the 2D solver through a one-way handoff |
| D3 | Delft3D | Done | The real Delft3D FM kernel runs from our pipeline and returns gauge arrival times |
| D4 | Compare the scenarios | In progress | Quantitative comparison complete on the Ritter dam-break benchmark; comparison on real Indian sites underway |
| D5 | DEM, satellite and hydrological inputs | Done | Copernicus GLO-30 DEM, Sentinel-1 radar imagery, dam and reservoir parameters from open sources |
| D6 | Loss and damage | In progress | Population at risk (GHSL), loss-of-life ranges and hazard classes working; building exposure not yet integrated; damage coefficients awaiting source verification |
| D7 | Automatic operation | Done | One request from the dashboard runs terrain, breach, solver, impact and exports with no manual steps |
| D8 | Different input datasets | Done | Any dam by coordinates, height and storage; DEM cached locally with offline fallback |
| D9 | Dashboard for large data | Done | Eight tabs: 2D + 3D · Gauges · Ensemble · Impact · SPH · Comparison · Validation · Downloads |
| D10 | .shp / .kml export | Done | Shapefile, KML and GeoTIFF exports — 25 export files from a single river-blockage run |
| D11 | Google Earth Engine, near real time | Done | Live Sentinel-1 water extent and new-water (blockage) detection, which refuses when open reference data cannot verify the result |
| D12 | Real Indian dam and river | Done | Khadakwasla dam (Pune, Maharashtra) and Rishi Ganga (Chamoli, Uttarakhand), on open data only |

### 5 — Measured results (`#results`)
Heading: **Measured results**. Sub-heading: *Every number here was measured on our code. Computing times are real (wall-clock) time on a 16-core CPU with no GPU — not simulated flood time.*

**Block A — Benchmark against theory and Delft3D FM.** A card with a small horizontal bar chart, "RMSE vs exact solution — lower is better":
- (PROJECT NAME) 2D solver: **0.0317 m**
- Delft3D FM (Deltares kernel): **0.0349 m**

Beside the chart, a mini table "Depth at the dam": (PROJECT NAME) 4.532 m · Delft3D FM 4.515 m · exact solution 4.444 m.
Caption: *"Ritter (1892) dry-bed dam-break: 10 m initial depth, t = 40 s, 10 m grid. The two engines agree with each other to 0.0294 m RMSE."*
Image slot: `images/ritter-validation.png` — caption "Exact solution, (PROJECT NAME) and Delft3D FM on one axis".

**Block B — Solver correctness checks.** Three small stat cards:
- **5.98 × 10⁻¹⁴ m/s** — spurious velocity in the lake-at-rest test (still water stays still)
- **0.000000 %** — mass-conservation error
- **0.127 %** — lake-volume error against the exact V-valley formula, at 30 m cells

**Block C — Real-site simulation runs.** A table with columns: Scenario · Study area · Grid · Simulated time · Ensemble members · Computing time

| Scenario | Study area | Grid | Simulated time | Ensemble members | Computing time |
| --- | --- | --- | --- | --- | --- |
| Khadakwasla dam break, around Pune | 28 × 26 km | 200 m | 30 h | 6 | 46 min |
| Khadakwasla dam break, regional | 240 × 188 km | 500 m | 24 h | 4 | 64 min |
| Khadakwasla dam break, regional | 240 × 188 km | 300 m | 24 h | 4 | 5 h 1 min |

Next to the table, two highlight cards:
- **"96.4 % of the released water drains out"** — *Khadakwasla, 28 × 26 km study area. An earlier build left about 42 % trapped in the valley; we traced it to three terrain and domain problems and fixed them. Drainage on the full regional domain is still being tested.*
- **"Rishi Ganga landslide-dam run"** — *Barrier 110 m high × 1,500 m wide, 100 m grid, 4 h simulated, 4 members. Lake measured from the terrain: 22.18 million m³ over 0.79 km². The flood front reached 5 km downstream at 91.5 min with a peak depth of 11.72 m.*

**Block D — Dashboard gallery.** A 2 × 2 grid (one column on mobile), click to enlarge in a simple lightbox:
- `images/dash-2d3d.png` — "2D flood map and 3D Cesium globe"
- `images/dash-ensemble.png` — "Ensemble: peak-discharge band and breach statistics"
- `images/dash-impact.png` — "Impact: population at risk and hazard classes"
- `images/dash-validation.png` — "Validation: lake at rest, mass conservation, Ritter benchmark"

### 6 — Next steps (`#next`)
Two columns (stacked on mobile).

Left — **Recently completed**, a vertical timeline, newest first:
- **11 Sep 2026** — Hazard classes unified on the published FD2320 scheme.
- **06 Sep 2026** — Khadakwasla flood now drains: 96.4 % of released water leaves the study area.
- **06 Sep 2026** — River-blockage runs completed, including Rishi Ganga.
- **03 Sep 2026** — River-blockage scenario and observation-conditioned DEM update added; 600 tests passing.
- **29 Aug 2026** — Dashboard fully integrated: eight tabs on real data, Google Earth Engine live, Delft3D FM running from the dashboard.

Right — **What we're working on next**, a checklist with "Next" badges:
- Re-run the drainage case with one change at a time, to measure what each fix contributed.
- Benchmark Rishi Ganga against published results.
- Verify damage and loss-of-life coefficients against primary sources, and add building exposure.
- Add two more natural-dam breach formulas (Walder & O'Connor 1997; Peng & Zhang 2012).
- Test drainage on the full regional domain.
- Rehearse the full judge walkthrough and pre-compute one clean demo run per site.

### 7 — Tech stack
Grouped rows of text-only chips (no logos):
- **Simulation:** Python 3.11 · NumPy · Numba · PySPH · rasterio / GDAL
- **Backend:** FastAPI · Celery · Redis · Docker Compose
- **Frontend:** React · Vite · Leaflet · CesiumJS · Recharts
- **Validation and 3D post-processing:** Delft3D FM · ParaView
- **Open data:** Copernicus GLO-30 · Sentinel-1 · Google Earth Engine · JRC Global Surface Water · GHSL

### 8 — Resources (`#resources`)
Heading: **Code, documents and downloads**. Four large cards in a grid, each with an icon, one line of text and a button:
- **Source code** — "Browse the full framework on GitHub." → `(GITHUB REPO URL)`
- **Download the framework** — "Latest release as a ZIP, with setup steps in the README." → `(GITHUB RELEASE DOWNLOAD URL)`
- **Detailed document** — "Architecture, methods, validation and known limits." → `(DOCUMENT LINK)`
- **Presentation** — "Our SIH 2026 idea submission deck." → `(PPT LINK)`

Below the cards, a **"Run it yourself"** code block with a copy button:

```
git clone (GITHUB REPO URL)
cd (REPO FOLDER NAME)
pip install -e .[dev,viz]
python scripts/run_api.py
npm install --prefix frontend
npm run dev --prefix frontend
```

Small note under it: *"Needs Python 3.11+ and GDAL. Full Windows and Linux setup is in the README."*

### 9 — Team (`#team`)
Heading: **Team (TEAM NAME)**, sub-line **(COLLEGE NAME)**. Six cards in a grid, each with a light-blue circle showing initials, **(MEMBER NAME)** and **(ROLE)**. One optional card for **(MENTOR NAME)**.

### Footer
Light-blue top border. Three lines:
- "(PROJECT NAME) · Smart India Hackathon 2026 · Problem Statement 26161 · MIT License"
- "Built only on open data: Copernicus, Sentinel-1, JRC Global Surface Water, GHSL."
- Small muted disclaimer: *"(PROJECT NAME) is a rapid screening tool. Its outputs are indicative flood extents and arrival times, not a substitute for detailed engineering studies."*

Repeat the GitHub, document and download links, plus "Last updated (LAST UPDATED DATE)".

---

## 4. Content rules — follow strictly

- Use only the facts and numbers written in this prompt. Do not invent statistics, percentages, speed-ups, user counts, testimonials, quotes, awards, partner or sponsor logos.
- Every computing time must stay next to its study area, grid size, simulated time and ensemble size.
- Simulated time (how long the flood lasts in the model) and computing time (how long the computer takes) are different. Never mix them, and never write "real-time forecast" or "X-minute forecast".
- The link from the 2D solver to SPH is a **one-way handoff**. Never call it "coupled" or "two-way".
- Never say the project *is* Delft3D. Say it is "validated against the Delft3D FM kernel".
- Do not claim validation against observed satellite flood maps, and do not mention InSAR or photogrammetry.
- Keep "(PROJECT NAME)" and every other CAPS placeholder exactly as written.
- Tone: plain, confident, precise, short sentences. No hype words ("revolutionary", "cutting-edge", "AI-powered", "game-changing", "world-class").

---

## 5. Subtle interactions (optional)

- Stat numbers count up once when they scroll into view (turned off under reduced motion).
- Sections fade in gently on scroll (150–250 ms).
- Copy button on the code block, with a brief "Copied" confirmation.
- A small "Back to top" button after the first screen.
