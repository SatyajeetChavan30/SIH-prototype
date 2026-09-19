# (PROJECT NAME) — AI video prompt pack for Google Veo

**What this is:** paste-ready prompts for generating the demo video with **Veo 3.1** (inside Gemini, or inside Flow), in two cuts — a **60-second** teaser and a **3-minute** step-by-step explanation of how the system actually works. A fallback prompt for **Gemini / NotebookLM Video Overview** is at the end, plus one for **Google Vids**.

**Relationship to `docs/Demo_Video_Script_3min.md`:** that file is the *dashboard walkthrough* — a screen recording of the product being driven. This file is the *pipeline explainer* — how the water gets from a satellite to a warning. They are complementary. Where a beat overlaps, this file defers to that script's wording, and both draw on the same locked fact sheet in §4. If you only make one video, make that one; if you want the one that a judge remembers, make this one and cut the dashboard walkthrough into it as the shots marked `[SCREEN]`.

---

## §1 · Read this before you generate a single frame

Eight things about Veo that will otherwise cost you a day.

1. **Veo generates 8-second clips.** Not 60, not 180. Every "cut" below is therefore a **shot list**, and you generate each shot separately and assemble them in an editor. 60 seconds ≈ 8 clips. 3 minutes ≈ 22 clips. In Flow you can chain a clip's last frame into the next ("Extend"), which buys continuity but not a single long take.

2. **Veo cannot render your dashboard.** Ask it for "a flood modelling web dashboard" and you get plausible-looking nonsense: garbled axis labels, invented menus, text that melts. Any beat that shows the real product is a **screen recording you capture yourself** — marked `[SCREEN]` below. Veo's job is everything else: terrain, water, satellites, the valley, the abstractions. Where you may not have a recording, each `[SCREEN]` shot has an `[ALT-VEO]` abstract substitute.

3. **Do not ask Veo for on-screen text.** It will garble it, and it will garble the project name in particular. Every title, lower third, caption and number in this pack is added **in the editor**, not generated. The negative block in §3 tells Veo to leave the frame clean for you.

4. **Generate the voiceover separately.** Veo's native audio is per-clip; across 22 clips you will get 22 different narrator voices. Record the VO in one pass — your own voice, or Gemini TTS / ElevenLabs — and lay it under picture. Ask Veo for **ambience and sound effects only** (every prompt below does), then duck them to about −18 dB under the VO.

5. **Continuity comes from repetition, not from hope.** Paste the **style block in §2 verbatim into every single prompt**, unchanged, including the hex values. Same time of day, same grade, same lens language. In Flow, additionally use *Ingredients to Video* with 2–3 reference stills so the valley looks like the same valley in shot 4 and shot 17.

6. **Generate 3–4 takes per shot and keep the best.** Budget for it. Water, particles and aerial parallax are the shots that most often come back wrong; architecture and interior shots almost always work first time.

7. **Keep dams and people non-identifiable.** Veo footage of a failing dam must not look like a named real dam, and must not show recognisable faces. Every shot below is written that way on purpose. Where water covers inhabited terrain, burn the caption `SIMULATION — NOT A FORECAST` in the editor. This is the same rule the codebase applies to synthetic runs, and a judging panel will notice that you applied it to your own trailer.

8. **Aspect and resolution.** Generate 16:9 at 1080p for the judging submission. If you also want a phone cut, regenerate — do not crop; Veo composes for the ratio you ask for.

---

## §2 · The STYLE BLOCK — paste verbatim into every prompt

> **STYLE:** Photoreal cinematic documentary, shot on a large-format digital cinema camera with vintage anamorphic prime lenses, 24 fps motion cadence, shallow depth of field, gentle film grain, soft anamorphic bokeh. Colour grade: cold slate-blue and steel-grey base (#1B2A3A, #4A5C6E), glacier white highlights, and a single warm amber accent (#E8A33D) reserved exclusively for data, instruments and artificial light. Volumetric haze in depth, high dynamic range, restrained contrast. Serious, engineered, unsentimental — the look of a scientific field documentary, not an advertisement. No text of any kind in frame.

---

## §3 · The NEGATIVE BLOCK — append to every prompt

> **NEGATIVE:** no text, no captions, no subtitles, no titles, no watermark, no logos, no signage, no readable labels, no numbers in frame, no user interface, no dialogue, no speech, no voiceover, no narrator, no music, no people facing camera, no recognisable faces, no distorted hands, no cartoon, no anime, no 3D-render plastic look, no stock-footage gloss, no lens flare, no slow-motion unless specified, no aerial drone watermark, no split screen.

*Per-shot exception:* the shots marked `[ALT-VEO]` need abstract interface elements, so for those **remove** `no user interface` from the negative block and keep everything else.

---

## §4 · Locked fact sheet — the video may not deviate from this

Everything the narration is allowed to assert, and everything it is forbidden to.

### Numbers you may use

| Fact | Exact form to say |
| :-- | :-- |
| Flagship run domain | 28 × 26 km at 200 m, 30 hours of **simulated** flood, 6 ensemble members |
| Flagship run wall clock | 2,740 s (46 minutes), 16 CPU cores, no GPU |
| Flagship run volume balance | 85.31 MCM released, 96.4 % exited the domain, closure error 0.007 % |
| Hazard clears | Zero severe and zero extreme cells at 9.44 hours |
| Gauge example | Deccan Gymkhana 1 h 40 m arrival, band 1 h 25 m – 1 h 41 m, peak 7.10 m |
| Ritter cross-check | (PROJECT NAME) RMSE **0.0317 m**; Delft3D FM **0.0349 m**; engines agree to 0.0294 m |
| Delft3D build | Delft3D FM, dflowfm-cli 1.2.184, dimrset 2026.01 |
| Lake at rest | 5.98 × 10⁻¹⁴ m/s |
| Mass conservation | 0.000000 % drift |
| Test suite | 821 tests passing, 7 skipped *(figure of 2026-09-13 — re-run pytest before recording and use the fresh number; an earlier audit said 600, so quote whichever the suite prints on the day)* |
| GPU speed-up | **11.5× on a 30-member ensemble, 455.6 s → 39.7 s, full double precision** — and always adjacent to the fact that it also runs on an ordinary processor |
| Near-field SPH, dashboard run | ~14,000 particles (14,149) |
| Near-field SPH, GPU benchmark | 232,426 particles in 89.4 s on an RTX 4050 laptop GPU — *a benchmark, not the dashboard run; never conflate the two* |
| Breach regressions | Froehlich, MacDonald, Xu–Zhang, with Wahl uncertainty bands; Costa (1985) for natural dams |
| Elevation data | Copernicus GLO-30, 30 m |
| Ensemble output | p05 / p50 / p95 |
| Presets in the picker | 6 dams, 29 runs |

### Sentences that must stay exact

- The SWE → SPH link is a **one-way handoff**. Never "coupled", never "two-way".
- (PROJECT NAME) is **measured against** Delft3D FM. It **is not** Delft3D and does not bundle it.
- Sentinel-1 **GRD change detection** — never "InSAR" (Earth Engine carries no SLC).
- **Observation-conditioned DEM update** — never "photogrammetry", never "rebuilt from imagery".
- **Simulated time** and **compute time** are never mixed in the same breath.
- It is a **Tier-1 rapid screening instrument** under CWC's own framing, not a replacement for a Tier-2/3 surveyed study.
- Lead with **arrival times and inundation envelopes**; point depths on a 30 m DEM are indicative.

### Struck claims — if any of these reaches the edit, the edit is wrong

`56 minutes end-to-end` · `16 hours current practice` · `17× faster` · `100-member ensemble` · `validated against observed satellite flood extents` · `four published breach regressions` · `60 km downstream` · `real-time` · `coupled` / `two-way` · `InSAR` · `photogrammetry` · any rupee damage figure (the unit costs are unvetted placeholders — say *population at risk* and *loss-of-life range*, never crores).

### Sites

Demo case **Tehri** (260 m, 3,540 MCM); flagship run **Khadakwasla** (Mutha, Pune); real blockage case **Rishi Ganga**, Feb 2021. **Mullaperiyar must never appear** — active litigation.

---

## §5 · CUT A — the 60-second teaser (8 Veo shots)

Total 64 s. All eight are pure Veo; no screen recording required. VO lines are ~20 words each, which is 8 seconds at 150 wpm.

---

### A1 · 0:00–0:08 — The reservoir at first light

**VO:** "Every large dam in India holds a question no one can answer quickly: if it let go, who is in the water?"

**On-screen (added in edit):** none. Let it breathe.

> **VEO PROMPT —**
> Extreme wide aerial shot, slow forward dolly at low altitude, drifting towards a vast unnamed concrete gravity dam wedged between two steep forested Himalayan ridges at first light. The reservoir behind it is mirror-still and the colour of slate. Thin mist sits on the water surface; monsoon cloud banks are stacked on the peaks behind. The dam face is anonymous weathered concrete with no markings, no signage, no visible people. Camera holds a steady, almost reverent glide; the dam grows in frame but never fills it. Lighting: pre-dawn blue hour, one narrow shaft of warm sun just breaking over the eastern ridge and catching the water's edge. **AUDIO:** deep low wind across a valley, distant water, a single faint bird call. No music. No speech. **STYLE:** *(paste §2)* **NEGATIVE:** *(paste §3)*

---

### A2 · 0:08–0:16 — Downstream, at river level

**VO:** "Downstream there are towns at river level. The conventional study that answers this takes weeks of setup."

> **VEO PROMPT —**
> Low static wide shot from the riverbank, camera at water height, looking downstream along a braided Himalayan river in a broad valley. In the mid-distance, a small terraced settlement of unremarkable concrete-and-tin buildings sits barely above the channel, no signage, no identifiable branding. Morning haze; a thin plume of cooking smoke. The water in the foreground is shallow, fast and ordinary. Nobody is visible except one distant figure with their back to camera, walking away along the bank. The camera does not move — the stillness is the point. Lighting: flat early-morning overcast with a warm break on the far ridge. **AUDIO:** shallow river over stones, faint distant dog, wind in scrub. No music. No speech. **STYLE:** *(paste §2)* **NEGATIVE:** *(paste §3)*

---

### A3 · 0:16–0:24 — Open data descends

**VO:** "(PROJECT NAME) answers it from open data alone. A public thirty-metre elevation model. Sentinel-1 radar. Census population grids."

**On-screen (edit):** small amber lower-third list appearing in sequence — `Copernicus GLO-30` · `Sentinel-1 GRD` · `ESA WorldCover` · `GHSL`.

> **VEO PROMPT —**
> Orbital view from low Earth orbit looking down at the Indian subcontinent's Himalayan front at night-into-dawn terminator, Earth's curvature and thin atmospheric limb visible at the top of frame. A satellite in silhouette crosses the foreground left to right, its solar panels catching hard sunlight. Below, the terrain resolves progressively into a fine warm-amber elevation mesh that sweeps across the mountains like a wave, replacing photoreal terrain with structured topographic wireframe as it passes. Camera slowly descends toward the surface, the mesh growing denser and more detailed. Lighting: hard directional sunlight from frame left, deep blue earthshadow to the right. **AUDIO:** a low sustained orbital hum, a soft rising synthetic sweep as the mesh passes, faint radio static. No music. No speech. **STYLE:** *(paste §2)* **NEGATIVE:** *(paste §3)*

---

### A4 · 0:24–0:32 — Terrain becomes a solver grid

**VO:** "The valley becomes a metric grid. Every cell carries depth, velocity and friction, and the solver steps them forward."

**On-screen (edit):** `2D shallow-water · HLLC flux · Audusse hydrostatic reconstruction`

> **VEO PROMPT —**
> Aerial top-down-to-oblique shot descending over a steep river valley. The photoreal terrain transforms beneath the camera into a precise regular square computational grid of fine glowing amber lines laid conformally over the real topography, following every ridge and channel. Individual grid cells pulse and illuminate in travelling waves down the valley floor, as if information is propagating cell to cell. The mountains remain photoreal and physical; only the grid is luminous. Camera pushes down the valley axis at a steady speed. Lighting: cold overcast ambient on the rock, with all warmth coming from the grid itself. **AUDIO:** a soft rhythmic electronic tick, one per cell wave, over low valley wind. No music. No speech. **STYLE:** *(paste §2)* **NEGATIVE:** *(paste §3)*

---

### A5 · 0:32–0:40 — The breach

**VO:** "The breach is not typed in. It is sampled from published regressions, so every run carries a spread, not a guess."

> **VEO PROMPT —**
> Medium-wide shot on the downstream face of an unnamed earth-fill embankment dam. A notch opens in the crest and widens — soil and rock sloughing away, a dense brown jet of water accelerating through the gap and fanning out down the spillway channel below. Heavy spray, airborne debris, violent turbulence. Shot at 120 fps and played at half speed so the water reads as mass rather than spray. Camera is locked off on a long lens from the opposite bank, slight handheld micro-movement only, as if a real field camera. No people, no vehicles, no signage. Lighting: hard overcast, flat and grey, water reading brown-ochre against slate. **AUDIO:** a deep building roar, cracking earth, heavy water impact, wind buffeting the microphone. No music. No speech. **STYLE:** *(paste §2)* **NEGATIVE:** *(paste §3)*

---

### A6 · 0:40–0:48 — The near field, particle by particle

**VO:** "At the breach itself, the far-field result hands off one way into a particle simulation of the violent near field."

**On-screen (edit):** `SWE → SPH · one-way handoff`

> **VEO PROMPT —**
> Extreme slow motion macro shot, 1000 fps, of a violent water surge breaking around a rough concrete and boulder obstruction. The water resolves into millions of discrete spherical droplets and particles, each catching light individually, suspended and tumbling in a coherent cloud that still reads as a fluid front. Foreground droplets are sharply lit and out of focus at the very front of frame; the surge front behind is crisp. Camera tracks laterally with the front, very slowly. Lighting: hard raking backlight from frame right rendering each droplet as a bright point against a dark wet rock background, with the cold slate base grade preserved. **AUDIO:** deep sub-bass water impact stretched and slowed, individual droplet impacts, a low resonant hum. No music. No speech. **STYLE:** *(paste §2)* **NEGATIVE:** *(paste §3)*

---

### A7 · 0:48–0:56 — The answer, as a map

**VO:** "What comes out is arrival time and an inundation envelope — with a fifth, fiftieth and ninety-fifth percentile band."

**On-screen (edit):** `p05 / p50 / p95` and `SIMULATION — NOT A FORECAST` bottom-left.

> **VEO PROMPT —**
> High aerial shot, slowly rising, looking down at a real river valley opening onto a plain with a scattered low-rise settlement. A translucent luminous flood envelope grows outward from the top of frame along the river corridor and spreads across the floodplain — rendered as a glowing gradient sheet, amber at the leading edge fading to deep cyan in the deepest zones, hugging the true topography exactly. Concentric thin amber arcs sweep outward ahead of the water like isochrone contours, each one passing and fading. The terrain beneath stays photoreal and visible through the overlay. Camera continues to rise, revealing the full extent. Lighting: high overcast daylight, the overlay providing all saturation. **AUDIO:** a low sustained tone rising slowly in pitch, distant wind, no water sound. No music. No speech. **STYLE:** *(paste §2)* **NEGATIVE:** *(paste §3)*

---

### A8 · 0:56–1:04 — Hold, and card

**VO:** "Open data in. A defensible warning out. Before the water moves."

**On-screen (edit):** end card — `(PROJECT NAME)` / `PS 26161 · NTRO` / `(TEAM NAME)` / repo QR. Fade the picture to 25 % behind it.

> **VEO PROMPT —**
> Slow wide aerial pull-back, retreating from the flooded valley at dusk. The luminous flood overlay fades gradually away over the shot, leaving the real terrain quiet, dark and unmarked. Low cloud moves through the valley. The camera continues to retreat until the whole basin sits small in frame surrounded by ridgelines. Lighting: late dusk, the last cold light on the high ridges, valley floor in deep shadow, a few distant warm amber points of settlement light appearing. **AUDIO:** wind falling away to near silence, one distant low rumble, then quiet. No music. No speech. **STYLE:** *(paste §2)* **NEGATIVE:** *(paste §3)*

---

## §6 · CUT B — the 3-minute step-by-step (12 steps, 22 shots)

This is the one that answers *how does it actually work*. Each step is a numbered chapter; shots are tagged:

- `[VEO]` — generate with Veo from the prompt given.
- `[SCREEN]` — record your own product. An `[ALT-VEO]` abstract substitute is provided for each.
- `[HYBRID]` — Veo plate with your screen recording composited into it in the editor.

Total 176 s of picture + a 4 s end card = 3:00.

---

### STEP 0 · The question — 0:00 to 0:16

#### B1 · 0:00–0:08 · `[VEO]`

**VO:** "February 2021. A rock-and-ice avalanche dams the Rishi Ganga. There was no survey of that dam — it did not exist the week before."

> **VEO PROMPT —**
> Wide static shot of a narrow, extremely steep Himalayan gorge choked with a fresh grey landslide deposit — shattered rock, dirty ice and mud filling the valley floor from wall to wall, raw scar faces on both slopes above where the mass detached. A small dark meltwater lake has ponded behind the deposit, flat and unnaturally still. Fine dust still hanging in the air. Utterly deserted, no equipment, no people, no marks of any kind. Camera is locked off, a very slow push-in only. Lighting: harsh high-altitude overcast, blue-grey, no warmth anywhere except a single thin amber break on the far ridge. **AUDIO:** high thin mountain wind, occasional single rock fall clattering, otherwise oppressive silence. No music. No speech. **STYLE:** *(paste §2)* **NEGATIVE:** *(paste §3)*

#### B2 · 0:08–0:16 · `[VEO]`

**VO:** "For a blockage like that, or a dam that breaks, the question is identical: how far, how fast, and who is in it."

**On-screen (edit):** lower third `PS 26161 · Dam Break Inundation Modelling · NTRO`

> **VEO PROMPT —**
> Slow aerial tracking shot moving downstream along a Himalayan river valley, starting high and descending, passing over a sequence of small riverside settlements clinging to the valley floor and low terraces — plain concrete buildings, footbridges, terraced fields, no signage, no identifiable branding, no visible faces. The camera moves with steady purpose, as if following the path water would take. Morning mist sits in the valley bottom. Lighting: soft early light, the valley floor still in shadow, ridge tops catching warm sun. **AUDIO:** wind of movement, distant river, faint village ambience thinning as the camera passes. No music. No speech. **STYLE:** *(paste §2)* **NEGATIVE:** *(paste §3)*

---

### STEP 1 · Choose the site and the scenario — 0:16 to 0:24

#### B3 · 0:16–0:24 · `[SCREEN]`

**VO:** "Step one. Pick a site from the register, and pick the scenario: an engineered dam break, or a landslide-dammed lake."

**Capture:** the control panel. Open the dam selector so the six presets are visible, choose Khadakwasla, then hover the scenario toggle so *Dam break* and *River blockage* both read. 1920×1080, 30 fps, browser at 100 %, cursor movement slow and deliberate — record it three times and keep the calmest take.

> **`[ALT-VEO]` PROMPT —** *(remove `no user interface` from the negative block)*
> Medium shot in a dark quiet operations room, over the shoulder of a single seated analyst seen only from behind, silhouetted against a large wall display. On the display, an abstract map of an Indian river basin with a handful of glowing amber markers placed along the rivers; one marker enlarges and pulses as it is selected. No readable text anywhere — the interface is pure geometry, contour lines and glowing nodes. Camera slowly pushes in past the analyst's shoulder toward the display. Lighting: room lit only by the cold blue screen glow with a warm amber spill from the map's markers. **AUDIO:** quiet room tone, server hum, a single soft interface click. No music. No speech. **STYLE:** *(paste §2)*

---

### STEP 2 · Pull the open data — 0:24 to 0:40

#### B4 · 0:24–0:32 · `[VEO]`

**VO:** "Step two. Everything the model needs is fetched from open data — and cached, so the second run needs no network at all."

**On-screen (edit):** `Copernicus GLO-30 · Sentinel-1 GRD · ESA WorldCover · GHSL`

> **VEO PROMPT —**
> Orbital shot looking down at the Indian subcontinent from low Earth orbit, the Himalayan arc across the top of frame, thin blue atmospheric limb above it. A radar satellite passes through frame in silhouette, its antenna panel catching hard sun. A faint amber swath sweeps the ground beneath it, and where the swath passes, a neat grid of square data tiles briefly illuminates on the terrain and then settles flat. Camera drifts slowly with the satellite. Lighting: hard raw sunlight from frame right, deep unlit shadow on the left half of the globe. **AUDIO:** a low orbital drone, a periodic soft radar ping, faint static. No music. No speech. **STYLE:** *(paste §2)* **NEGATIVE:** *(paste §3)*

#### B5 · 0:32–0:40 · `[VEO]`

**VO:** "Thirty-metre public elevation. Radar backscatter for blockages — amplitude change detection, not interferometry. Census population grids."

> **VEO PROMPT —**
> Descending aerial shot over a mountain river valley in which the terrain is rendered as a smooth photoreal surface that progressively resolves into finer and finer stepped elevation detail as the camera drops, like an image sharpening — coarse and blocky at altitude, crisp and rugged near the ground. Thin amber contour lines trace themselves onto the slopes as it resolves. The river channel below picks out in darker tone. Camera descent is smooth and continuous with no cuts. Lighting: neutral high overcast so the terrain form reads purely as geometry. **AUDIO:** a rising airy tone as the camera descends, wind increasing, a soft mechanical refresh click as each detail level lands. No music. No speech. **STYLE:** *(paste §2)* **NEGATIVE:** *(paste §3)*

---

### STEP 3 · Build the metric domain and condition the terrain — 0:40 to 0:56

#### B6 · 0:40–0:48 · `[VEO]`

**VO:** "Step three. The terrain is reprojected into metres — never degrees — and cut into a square solver domain biased downstream."

**On-screen (edit):** `EPSG:32643 · cell-centred finite volume`

> **VEO PROMPT —**
> Top-down orthographic aerial view of a river basin. A precise square boundary of thin amber light draws itself onto the landscape corner by corner, snapping into alignment, then slides and re-centres so the river's downstream reach sits well inside it rather than the dam sitting at the middle. Inside the boundary the terrain fills with a fine regular square lattice; outside the boundary the terrain visibly desaturates and dims. Camera is locked perfectly overhead, rotating very slightly. Lighting: flat even top light so the drawing reads as a technical operation. **AUDIO:** precise mechanical snap as each boundary edge lands, a low sustained tone underneath. No music. No speech. **STYLE:** *(paste §2)* **NEGATIVE:** *(paste §3)*

#### B7 · 0:48–0:56 · `[VEO]`

**VO:** "Resampling a channel manufactures pits that trap water forever. Those get filled from the boundary inward — and the fill is capped, and recorded."

**On-screen (edit):** `depression fill seeded from the domain boundary · capped · logged`

> **VEO PROMPT —**
> Close aerial view of a rugged valley floor, low sun raking across it. Small isolated depressions and hollows in the terrain glow faintly amber, one by one, as if being identified. Then a translucent level surface rises from the outer edges of frame inward, flooding only those small hollows to their brim and stopping exactly there — the large valley basin in the centre of frame stays open and unfilled, a deliberate contrast. Camera holds a slow lateral drift across the terrain. Lighting: hard low raking sun so every hollow throws a long shadow before it is filled. **AUDIO:** a soft liquid settle per hollow, a low tone rising and then resolving. No music. No speech. **STYLE:** *(paste §2)* **NEGATIVE:** *(paste §3)*

---

### STEP 4 · Assign friction — 0:56 to 1:04 · *conditional*

> **Include this step only if the run you are showing actually used a land-cover roughness field.** Default pipeline runs use a uniform Manning's n of 0.03, and the run summary records which was used. If your run is uniform, cut B8 and give its 8 seconds to Step 5.

#### B8 · 0:56–1:04 · `[VEO]`

**VO:** "Step four. Land cover sets the roughness — forest, cropland, built-up — because a city slows a flood differently from a field."

> **VEO PROMPT —**
> Aerial oblique shot over a mixed landscape of dense forest, open cropland and a low-rise built-up area along a river. Each land type takes on a distinct flat translucent tint that hugs its true extent exactly — deep teal over forest, pale steel over cropland, warm amber over the built-up area — as though a classification is being painted onto the ground. The boundaries between classes are crisp and follow real field edges, roads and tree lines. Camera tracks slowly forward and slightly down. Lighting: clear neutral daylight, no strong shadow, so classification boundaries stay legible. **AUDIO:** a soft distinct tonal chord for each class as it appears, over light ambient wind. No music. No speech. **STYLE:** *(paste §2)* **NEGATIVE:** *(paste §3)*

---

### STEP 5 · Make the breach, or burn the barrier — 1:04 to 1:20

#### B9 · 1:04–1:12 · `[VEO]`

**VO:** "Step five. Breach geometry is sampled — Froehlich, MacDonald, Xu–Zhang, with Wahl's uncertainty bands — by Monte Carlo, many times over."

**On-screen (edit):** `Froehlich · MacDonald · Xu–Zhang · Wahl bands · Costa (natural dams)`

> **VEO PROMPT —**
> Medium shot on the crest of an unnamed earth-fill embankment dam, seen from slightly above and to the side. A notch opens in the crest — and then the shot ghosts: several translucent overlapping versions of the same notch appear simultaneously at different widths and depths, each faintly amber-edged, layered over one another like long-exposure variants of the same event, before they resolve back into one solid notch. No people, no equipment, no signage. Camera holds nearly static with a very slow push. Lighting: flat overcast, cold, the amber edges of the ghost notches the only warmth. **AUDIO:** low earth movement rumble, a soft multiplied echo as the ghost variants appear, settling into a single tone. No music. No speech. **STYLE:** *(paste §2)* **NEGATIVE:** *(paste §3)*

#### B10 · 1:12–1:20 · `[VEO]`

**VO:** "A landslide dam has no published storage. So the barrier is burned into the terrain, proved to span the valley, and its capacity measured off the result."

**On-screen (edit):** `barrier burn · proof of span · elevation–area–capacity read from the geometry`

> **VEO PROMPT —**
> Aerial oblique shot of a narrow steep gorge. A mass of debris materialises across the channel, building up from the bed until it spans wall to wall — the deposit forms as solid rough rock and mud, not as an effect. Then a thin amber water-level plane rises behind it in discrete steps, each step pausing momentarily and illuminating the wetted area it covers, terracing up the gorge walls like a survey being taken. Camera arcs slowly around the barrier from downstream to upstream. Lighting: cold overcast with deep shadow in the gorge, amber level plane as the only light source in the shadow. **AUDIO:** rock settling and grinding, then a clean measured tone per level step. No music. No speech. **STYLE:** *(paste §2)* **NEGATIVE:** *(paste §3)*

---

### STEP 6 · Solve the far field — 1:20 to 1:36

#### B11 · 1:20–1:28 · `[VEO]`

**VO:** "Step six. A two-dimensional shallow-water solver moves the flood downstream. HLLC flux, Audusse reconstruction, well-balanced, wetting and drying."

**On-screen (edit):** `2D SWE · HLLC + Audusse · MUSCL · Manning friction`

> **VEO PROMPT —**
> Aerial view descending along a river valley in which the terrain carries a fine luminous amber computational lattice conformal to the topography. A wave of illumination propagates cell by cell down the valley, each cell brightening as its neighbour resolves, so the calculation visibly sweeps downstream ahead of any water. Behind the wave a translucent blue-cyan water sheet begins to fill the channel, following the lattice exactly. Camera pushes steadily downstream, keeping pace with the propagation front. Lighting: cold ambient on rock; all warmth from the lattice, all cool saturation from the water. **AUDIO:** a fast rhythmic computational tick building in density, under a rising water rush. No music. No speech. **STYLE:** *(paste §2)* **NEGATIVE:** *(paste §3)*

#### B12 · 1:28–1:36 · `[VEO]`

**VO:** "The flux kernel is compiled to machine code, and will run on an ordinary processor — or on a GPU, eleven and a half times faster, in full double precision."

**On-screen (edit):** `11.5× on a 30-member ensemble · 455.6 s → 39.7 s · full double precision` — and beside it, smaller: `also runs CPU-only`

> **VEO PROMPT —**
> Extreme macro shot across the surface of a modern GPU board inside a workstation, shallow depth of field, chrome and matte black hardware, heat-sink fins receding into bokeh. Waves of warm amber light pulse rapidly across the die and along the board's traces, left to right, far faster than any human rhythm. A cooling fan turns in the deep background out of focus. No visible branding, no logos, no readable markings of any kind on the hardware. Camera glides laterally along the board, very close, very slow. Lighting: single hard cold key from above with warm amber emissive light coming from the board itself. **AUDIO:** high-frequency electronic whine, fan hum, a dense fast digital pulse. No music. No speech. **STYLE:** *(paste §2)* **NEGATIVE:** *(paste §3)*

---

### STEP 7 · Run the ensemble — 1:36 to 1:44

#### B13 · 1:36–1:44 · `[SCREEN]`

**VO:** "Step seven. Members run together and the answer is a band — fifth, fiftieth, ninety-fifth percentile — not one line pretending to be certain."

**Capture:** the Ensemble tab, the p05/p50/p95 envelope on the hydrograph. Let the envelope sit still for a full two seconds before any cursor moves.

> **`[ALT-VEO]` PROMPT —** *(remove `no user interface` from the negative block)*
> Dark empty space. Several translucent luminous curved surfaces, like stacked flood hydrographs rendered as ribbons of light, sweep in from frame left and layer over one another — each slightly offset from the last, in cool cyan — until a denser amber envelope forms around their outer limits and a single bright amber median line resolves through their centre. The ribbons drift gently as if suspended. No axes, no labels, no readable marks. Camera arcs slowly around the stack. Lighting: pure emissive, the ribbons are the only light source, deep black background. **AUDIO:** layered soft tones arriving one per ribbon and resolving into a single sustained chord. No music. No speech. **STYLE:** *(paste §2)*

---

### STEP 8 · Hand off to the near field — 1:44 to 1:52

#### B14 · 1:44–1:52 · `[VEO]`

**VO:** "Step eight. At the breach the shallow-water result hands off — one way only — into a particle simulation of the violent near field."

**On-screen (edit):** `SWE → SPH · one-way handoff · ~14,000 particles`

> **VEO PROMPT —**
> Extreme slow motion, 1000 fps, tracking a violent surge front breaking around rough concrete blocks and boulders immediately below a breach. The water resolves into millions of discrete illuminated spherical particles that still move as one coherent front, tumbling, colliding and separating. Depth of field is razor thin: the front is crisp while foreground droplets bloom out of focus. Camera tracks laterally alongside the front at the same speed, holding it steady in frame. Lighting: hard raking backlight from frame right so each particle reads as a bright point against dark wet rock. **AUDIO:** deeply stretched sub-bass impact, discrete droplet ticks, a low resonant hum. No music. No speech. **STYLE:** *(paste §2)* **NEGATIVE:** *(paste §3)*

---

### STEP 9 · Turn water into consequence — 1:52 to 2:08

#### B15 · 1:52–2:00 · `[SCREEN]`

**VO:** "Step nine. Downstream, arrival times with bands. Deccan Gymkhana: one hour forty, inside one twenty-five to one forty-one, peaking at seven point one metres."

**Capture:** the Gauges tab. Hold on one row so the arrival time, the band, the peak depth and the hazard badge are all legible; move the cursor along the row once, slowly.

> **`[ALT-VEO]` PROMPT —** *(remove `no user interface` from the negative block)*
> Top-down aerial of a river corridor passing through a low-rise urban area. Thin amber arcs sweep outward down the corridor one after another like expanding isochrones, each passing a small glowing marker placed on the riverbank and causing it to pulse once as it arrives. Around each marker a soft translucent uncertainty halo breathes slightly wider and narrower. No readable text or numbers anywhere. Camera holds locked overhead, drifting very slightly downstream. Lighting: flat high daylight on the city, all saturation from the amber arcs. **AUDIO:** a soft distinct chime per marker as each arc reaches it, over low ambient tone. No music. No speech. **STYLE:** *(paste §2)*

#### B16 · 2:00–2:08 · `[VEO]`

**VO:** "Hazard is the published rating — depth times velocity plus a debris factor — and population at risk comes from census grids on the run's own mesh."

**On-screen (edit):** `FD2320 hazard rating · GHSL population on the solver grid`

> **VEO PROMPT —**
> Slowly rising aerial over a low-rise riverside town partially covered by a translucent flood overlay. The overlay is banded into four distinct flat colour zones that follow the terrain exactly — pale steel at the thin outer edge, then teal, then deep blue, then a dense warm amber core along the channel — the bands crisply separated, not a smooth gradient. Beneath them the real rooftops, streets and trees remain visible through the translucency. Camera rises and tilts down progressively to reveal the full banded extent. Lighting: high neutral overcast so the bands read as classification rather than as light. **AUDIO:** a low sustained tone stepping up in pitch once per band, faint distant town ambience. No music. No speech. **STYLE:** *(paste §2)* **NEGATIVE:** *(paste §3)*

---

### STEP 10 · Prove it — 2:08 to 2:24

> This is the beat that wins the room. Do not cut it, and do not shorten the hold on the Ritter chart.

#### B17 · 2:08–2:16 · `[SCREEN]`

**VO:** "Step ten. Three gates, the same ones that block a merge. Lake at rest. Mass conservation, zero drift. And the Ritter dam-break, against the exact solution."

**Capture:** the Validation tab. Let the three PASS badges land on screen with their numbers legible, then hold.

> **`[ALT-VEO]` PROMPT —** *(remove `no user interface` from the negative block)*
> Dark frame. Three tall vertical luminous bars rise from the bottom of frame one after another, each settling to rest and then turning from cold cyan to a steady warm amber as it locks. Fine geometric tick marks run alongside them. Everything is abstract instrumentation — no readable numbers, no words. Camera holds locked with a very slow push in. Lighting: pure emissive on black, with faint atmospheric haze catching the glow. **AUDIO:** a single clean confirming tone per bar, then a sustained low hold. No music. No speech. **STYLE:** *(paste §2)*

#### B18 · 2:16–2:24 · `[SCREEN]`

**VO:** "Checked against the real Deltares Delft3D kernel running beside us. Our error: three point one seven centimetres. Delft3D's: three point four nine."

**Capture:** zoom the Ritter chart so the three curves — exact, (PROJECT NAME), Delft3D FM — sit on top of one another. **Hold this for the full eight seconds with no cursor movement.** It is the single most persuasive frame in the film.

> **`[ALT-VEO]` PROMPT —** *(remove `no user interface` from the negative block)*
> Dark frame. Three luminous curves draw themselves left to right across the frame — one bright amber, one cool cyan, one thin white — and land almost exactly on top of one another, the tiny separations between them visible only as faint fringing. The curves hold steady, breathing very slightly. No axes, no labels, no readable marks. Camera pushes in slowly on the region where the three curves are closest. Lighting: pure emissive on deep black with soft bloom. **AUDIO:** three tones arriving in quick succession and resolving into a single clean unison chord, sustained. No music. No speech. **STYLE:** *(paste §2)*

---

### STEP 11 · Ship it — 2:24 to 2:40

#### B19 · 2:24–2:32 · `[SCREEN]`

**VO:** "Step eleven. Results export as GeoTIFF, shapefile and KML — the formats a district office already knows how to open."

**Capture:** the Downloads tab, with `.tif`, `.shp` and `.kml` actually downloading. Show the browser's download shelf if your setup has one.

> **`[ALT-VEO]` PROMPT —** *(remove `no user interface` from the negative block)*
> Dark frame. Three geometric luminous objects assemble themselves in sequence and settle in a row — a fine amber raster grid plane, a cyan polygon outline, and a thin wireframe globe segment — each forming from scattered points that fly together. They rotate gently in place. No text, no labels, no icons with readable marks. Camera arcs slowly past them. Lighting: pure emissive on black, soft bloom, faint volumetric haze. **AUDIO:** a clean assembling tick per object, then a soft sustained tone. No music. No speech. **STYLE:** *(paste §2)*

#### B20 · 2:32–2:40 · `[HYBRID]`

**VO:** "It installs as one Windows application. Import a data pack once, and it runs with no internet at all — which is the condition it will actually be used in."

**How to build it:** generate the Veo plate below, then composite your own screen recording of the installer splash and the app cold-starting into the laptop screen in the editor (corner-pin / screen replace). If you cannot composite, use the plate alone and put the recording as a full-frame cut immediately after.

> **VEO PROMPT —**
> Medium shot of a rugged field laptop open on a folding table inside a bare district emergency operations room — plain painted walls, a wall map with no readable markings, a window showing heavy rain outside. The laptop screen is a flat uniform mid-grey with no content on it whatsoever. No people in frame. A single desk lamp provides warm light. The room's overhead fluorescent flickers once. Camera slowly pushes in toward the laptop, keeping the screen flat-on and unobstructed and fully in frame. Lighting: cold blue storm light from the window, warm amber desk lamp, deep shadow in the corners. **AUDIO:** heavy rain on a window, a laptop fan spinning up, distant thunder, room tone. No music. No speech. **STYLE:** *(paste §2)* **NEGATIVE:** *(paste §3)* — but **allow** a plain blank grey screen.

---

### STEP 12 · Close — 2:40 to 3:00

#### B21 · 2:40–2:48 · `[VEO]`

**VO:** "It does not replace a surveyed Tier-2 study. It tells you, in an afternoon, which dams deserve one."

> **VEO PROMPT —**
> Very high wide aerial, slowly drifting, over a broad Indian river basin at golden hour — many tributaries, several small impoundments, scattered settlement, agricultural plain. A handful of discrete locations across the basin pulse gently with a warm amber glow, one after another, as if being prioritised — not flooded, just marked. Thin haze softens the far distance. Camera drifts laterally across the basin with no cuts. Lighting: low golden-hour sun from frame left, long soft shadows, warm but restrained, cold slate shadow tones preserved. **AUDIO:** high-altitude wind, very distant ambient ground sound, a single soft tone per location as it marks. No music. No speech. **STYLE:** *(paste §2)* **NEGATIVE:** *(paste §3)*

#### B22 · 2:48–2:56 · `[VEO]`

**VO:** "Open data in. A defensible warning out. Before the water moves."

**On-screen (edit):** hold, then cut to the end card at 2:56.

**End card (2:56–3:00, edit only):** `(PROJECT NAME)` · `PS 26161 · NTRO` · `(TEAM NAME)` · repo QR and progress-site QR.

> **VEO PROMPT —**
> Slow static wide shot, camera locked off, of a calm river at dusk running through a quiet valley, a small settlement visible on the bank with a few warm windows lit. The water is smooth and unremarkable. Nothing happens; the shot simply holds and breathes, mist drifting slowly across the surface. Lighting: deep dusk, cold blue ambient, warm amber points from the settlement windows reflecting on the water. **AUDIO:** gentle river, evening insects, one distant dog, a soft settling wind. No music. No speech. **STYLE:** *(paste §2)* **NEGATIVE:** *(paste §3)*

---

## §7 · Assembly — after Veo hands the clips back

**Voiceover.** Record the whole script in one pass. Cut B is ~450 words at ~150 wpm. If you use TTS, a measured Indian-English male or female voice at 0.95× speed reads better to a panel than the default pace. Never narrate live over a screen recording — the clicks drift.

**Sound.** Veo's per-clip ambience is your sound bed; drop each clip's audio to roughly −18 dB under the VO and cross-fade 12 frames between shots or the ambience will chatter at every cut. Add one continuous low drone across the whole film at −30 dB to glue the clips together — that single sustained layer does more for perceived continuity than anything else you can do in the edit.

**Music.** Optional, and if used, it must stop at Step 10. The validation beat plays better dry.

**Titles and captions.** All text is added here, none of it generated. Use one typeface, one weight, amber `#E8A33D` on a 60 %-opacity slate `#1B2A3A` plate, bottom-left, in and out on a 6-frame fade. Every number on screen must appear verbatim in the §4 fact sheet.

**The mandatory caption.** Any shot where water covers inhabited terrain — A7, B16, and B15 if you use the ALT-VEO — carries `SIMULATION — NOT A FORECAST` in the lower left for the whole shot.

**Grade.** Veo clips will not match exactly. Put one shared grade node across everything: lift the blues in shadow, hold amber in the highlights, and match black level by eye against B18, which should be the deepest black in the film.

**Export.** H.264, 1080p, 30 fps, 12–16 Mbps, AAC 192 kbps. Keep the master project — the progress site's video slot is a CAPS placeholder and will want a re-cut.

**Order of work.** Generate B18's alternative and A7 first. They are the two hardest shots and they set the grade for everything else.

---

## §8 · Fallback — Gemini / NotebookLM **Video Overview**

If you would rather have one narrated explainer generated from your own documents than assemble 22 clips: upload `docs/progress.md`, `docs/validation_findings.md`, `CLAUDE.md` and this file as sources, then paste the block below as the customisation prompt.

> Make a detailed, step-by-step explainer video, about three minutes long, aimed at a technical judging panel for India's Smart India Hackathon (Problem Statement 26161, sponsored by NTRO). The audience is engineers and government evaluators, not a general public. The tone is precise, calm and evidence-led — a scientific field briefing, not a product advertisement. Refer to the system only as "(PROJECT NAME)". Do not invent a name for it.
>
> Structure the narration as twelve numbered steps that follow the actual pipeline in order: (1) the question a dam-break or landslide-dam study has to answer; (2) choosing a site and a scenario — engineered dam break or river blockage; (3) fetching open data — Copernicus GLO-30 thirty-metre elevation, Sentinel-1 GRD radar, ESA WorldCover land cover, GHSL population — all cached so later runs need no network; (4) reprojecting into a metric coordinate system and cutting a solver domain biased downstream; (5) conditioning the terrain, filling resampling pits from the domain boundary inward with the fill capped and logged; (6) sampling breach geometry by Monte Carlo from the Froehlich, MacDonald and Xu–Zhang regressions with Wahl uncertainty bands, and using Costa (1985) for natural dams, where storage is instead measured by burning the barrier into the terrain, proving it spans the valley, and reading an elevation–area–capacity curve off the result; (7) solving the far field with a two-dimensional shallow-water solver using HLLC flux with Audusse hydrostatic reconstruction, MUSCL reconstruction, wetting and drying, and Manning friction; (8) running an ensemble so the output is a fifth, fiftieth and ninety-fifth percentile band; (9) the one-way handoff from the shallow-water result into a Smoothed Particle Hydrodynamics simulation of the violent near field; (10) converting water into consequence — arrival times with bands, FD2320 hazard classification, and population at risk from census grids resampled onto the solver's own mesh; (11) validation; (12) delivery as GeoTIFF, shapefile and KML, and as an offline Windows application.
>
> Spend proportionally more time on step eleven than on any other step. State that the blocking correctness gates are lake-at-rest at 5.98 times ten to the minus fourteen metres per second and mass conservation at zero point zero zero zero zero zero zero percent drift, and that the Ritter dry-bed dam-break is scored against the exact analytical solution and against a real Deltares Delft3D FM kernel, dflowfm-cli build 1.2.184, running alongside: (PROJECT NAME) at 0.0317 metres RMSE, Delft3D FM at 0.0349 metres, the two engines agreeing to 0.0294 metres.
>
> Use the flagship measured run as the worked example: a twenty-eight by twenty-six kilometre domain at two hundred metre resolution, thirty hours of simulated flood, six ensemble members, completing in two thousand seven hundred and forty seconds — forty-six minutes — on sixteen CPU cores with no GPU; 85.31 million cubic metres released, 96.4 percent exiting the domain, closure error 0.007 percent, and zero severe and zero extreme hazard cells remaining at 9.44 hours.
>
> Observe these constraints without exception. Never describe the shallow-water-to-particle link as "coupled" or "two-way" — it is a one-way handoff. Say that the system is measured against Delft3D FM, never that it is Delft3D. Say "Sentinel-1 amplitude change detection", never "InSAR". Say "observation-conditioned DEM update", never "photogrammetry" and never "rebuilt from imagery". Never use the phrase "real-time". Never mix simulated time with compute time in the same sentence. Present the system as a Tier-1 rapid screening instrument under the Central Water Commission's own framing, explicitly not a replacement for a detailed surveyed Tier-2 or Tier-3 study. Lead with arrival times and inundation envelopes rather than absolute flood depths, because the elevation model is thirty metres and point depths are indicative only. Do not state any monetary damage figure — the unit costs are unvetted placeholders — and refer only to population at risk and a loss-of-life range. Never claim the system has been validated against observed satellite flood extents; that has not been run. Never claim a hundred-member ensemble, never claim any speed-up over conventional practice, and never claim a sixty-kilometre downstream reach. Do not mention the Mullaperiyar dam at any point.
>
> For visuals, prefer real terrain, satellite and hydraulic imagery, clean architecture diagrams and the pipeline as a left-to-right flow. Avoid stock imagery of generic disaster or of people in distress. Use a cold slate-blue and grey palette with a single warm amber accent for data and instruments.
>
> End on this: open data in, a defensible warning out, before the water moves.

---

## §9 · Fallback — Google Vids

Same content, slide-shaped. Paste the §8 block, then append:

> Lay this out as twelve scenes, one per step, plus a cold-open scene and an end card. Each scene gets one headline of no more than seven words, at most three supporting lines, and one full-bleed visual. Put the validation numbers on their own scene as a three-row comparison — exact solution, (PROJECT NAME), Delft3D FM — and give that scene twice the duration of any other. The end card reads "(PROJECT NAME) · PS 26161 · (TEAM NAME)" with space for two QR codes. Leave the project name as the literal placeholder text "(PROJECT NAME)" throughout; do not substitute anything for it.

---

## §10 · When Veo gives you something wrong

| Symptom | Fix |
| :-- | :-- |
| Garbled text appears despite the negative block | Add `the frame contains no writing of any kind` as a positive clause, not only a negative. Veo respects positive statements more reliably. |
| Water looks like plastic or gel | Add `real water physics, turbulent, aerated, sediment-laden, heavy` and specify a frame rate — `shot at 120 fps` — which pushes it toward photoreal capture. |
| The valley changes between shots | Generate a single establishing still first, then use it as an *Ingredients to Video* reference on every subsequent shot in that chapter. |
| A human appears and looks uncanny | Add `entirely deserted, no people` — every prompt in this pack already does, but re-roll rather than trying to fix it. |
| The clip invents a narrator | Your prompt lost the `no dialogue, no speech, no voiceover` clause. Re-paste the full negative block. |
| Camera move is too fast and reads as a stock-footage sting | Add `the camera moves slowly and deliberately, almost imperceptibly` and remove any verb like *swoop*, *rush* or *fly*. |
| Amber accent bleeds everywhere | Restate the constraint positively: `warm amber appears only on data, instruments and artificial light; everything natural stays cold slate-blue`. |
| Clips won't cut together | You are probably mixing focal lengths. Lock the whole film to two: a wide for aerials and a long lens for everything on the ground. |

---

*Every figure in this file traces to `docs/validation_findings.md`, `docs/progress.md`, the run records, or the presentation claim audit. Before recording, re-run the test suite and use the count it prints. Before publishing, check the video against §4 once more — the fabricated claims in the struck list have found their way back into a deliverable before.*
