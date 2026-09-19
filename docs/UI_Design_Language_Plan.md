# UI design language: adopting the andhüman visual system in (PROJECT NAME)

**Status:** phases A–E implemented on branch `ui-overhaul` (2026-09-19), plus a
Phase D2 that surfaces three honesty labels the dashboard never received
(`is_synthetic`, `unverified_regressions`, gauge boundary proximity). Phase F
(landing / phone viewer) is deferred. The product name in the UI is JalRaksha.
See "As built" at the end for where the implementation departs from this plan.
**Written:** 2026-09-19.
**Reference site:** `https://www.andhuman.co/` (andhüman, Geneva — Webflow).
**Audience:** whoever implements the frontend restyle in this checkout.

> Naming: **(PROJECT NAME)** is the product name in prose. Code identifiers and
> paths (`jalraksha/`, `jalraksha_service`, `frontend/src/…`) are literal.

---

## 1. What was actually measured on the reference site

Not a description from memory — these are computed styles read out of the live
page on 2026-09-19 at a 1440×900 viewport.

### 1.1 Typography

| Role | Family | Size / line-height | Weight | Case |
| :--- | :--- | ---: | ---: | :--- |
| Display accent | `ProvidenceSansPro` | 48 / 50.4 | 500 | UPPERCASE |
| Section headline | `SuisseIntl Medium` | 40 / 42 | 500 | sentence |
| Sub-headline | `SuisseIntl` | 32 / 40 | 400 | sentence |
| Link / CTA large | `SuisseIntl` | 24 / 24 | 400 | sentence |
| Muted lede | `SuisseIntl` | 20 / 24 | 400 | sentence, `#999` |
| Body link | `SuisseIntl` | 18 / 25.2 | 400 | sentence |
| Body | `SuisseIntl` | 16 / 22.4 | 400 | sentence |
| List item label | `SuisseIntl Medium` | 16 / 19.2 | 500 | sentence |
| Micro / meta | `SuisseIntl` | 14 / 19.6 | 400 | sentence |
| Eyebrow label | `SuisseIntl Medium` | 12 / 12.6 | 500 | sentence |
| Tag (accent) | `ProvidenceSansPro` | 14 / 14 | 700 | UPPERCASE |

Letter-spacing is `normal` everywhere. The whole system is **two families and
three weights** — the interest comes from size and colour, not from styling.

### 1.2 Colour

| Token | Value | Used for |
| :--- | :--- | :--- |
| ink | `rgb(36,36,36)` `#242424` | all body text, and the inverted panel background |
| page | `#ffffff` | page background |
| surface-1 | `#f9f9f9` (also at 75% alpha over media) | cards, floating bars |
| surface-2 | `#f0f0f0` | idle pill buttons, footer |
| surface-3 | `#e6e6e6` | dividers, hover |
| surface-4 | `#d9d9d9` | **active** pill button |
| muted | `#999999` | ledes, secondary meta |

No pure black, no pure-saturated accent anywhere in the chrome. Colour comes
only from the client work imagery.

### 1.3 Geometry and grid

- **Full bleed** — no `max-width` container anywhere; sections run edge to edge.
- Grids are `3 / 4 / 6` equal columns with an **8 px gutter**; a 2-up
  asymmetric layout runs `1fr 2fr`. Inside a card the grid gutter is **16 px**.
- Radii in use: `1000px` (pills), `14px` (cards / media), `8px`, `4px`.
- Navigation is `position: fixed`, fully **transparent** — no blur, no
  background — with pill buttons at `8px 10px`, 14 px text, the active one a
  step darker.
- Section anatomy, in order: hero media → one-sentence promise → two callout
  links → work grid (3-up cards, label under image) → news strip → methodology
  (3 columns of a linked list) → community banner → footer on `#f0f0f0`.

### 1.4 Motion

GSAP **3.15 core + ScrollTrigger**, loaded as two scripts. No Lenis, no Swiper,
no smooth-scroll hijack. Behaviour is progressive reveal on scroll, autoplay
muted video in the hero, and arrow affordances on links. Page height ≈ 7,500 px
— it is a scroll narrative, not an app.

---

## 2. What we may adopt, and what we may not

**Adopt (a design language, not a copy):** the neutral near-monochrome palette,
the two-family/three-weight type discipline, the 8 px gutter grid, the pill
navigation, the 14 px card radius, the muted-grey secondary text, the
label-under-media card, and restrained scroll reveal.

**Do not take:**

- **Their fonts.** Suisse Intl and Providence Sans Pro are commercially
  licensed and are served from their Webflow CDN. Hot-linking them is both a
  licence breach and a violation of this project's offline-first rule. We
  substitute (see §3.1) and **self-host**.
- **Their brand assets** — the eyes logo, the hero video, the client imagery,
  the "Belonging OS™" naming, the copy.
- **Webflow's stylesheet.** One 200 KB shared CSS file of generated class names
  is not a maintainable base for this repo.
- **Their density.** A brand studio's homepage is 16 px body text on infinite
  whitespace. (PROJECT NAME) is a screening instrument with an ensemble table,
  a gauge list and a 986-line control panel. §3.2 re-scales deliberately.

---

## 3. The proposed token set

### 3.1 Fonts (open, self-hosted, no CDN)

| Reference | Substitute | Why | Delivery |
| :--- | :--- | :--- | :--- |
| SuisseIntl (400/500) | **Inter** | closest open neo-grotesque; has `tabular-nums`, essential for gauge and ensemble columns | `@fontsource-variable/inter` (woff2 in `node_modules`, bundled by Vite) |
| ProvidenceSansPro (700, uppercase) | **Space Grotesk 700** | display accent for eyebrows/tags only | `@fontsource/space-grotesk` |
| — (new need) | **IBM Plex Mono** | run ids, coordinates, RMSE figures, `exited_mcm` | `@fontsource/ibm-plex-mono` |

Subset to Latin; expect ~250–400 KB added to the bundle. This is noise against
a 320 MB installer, and it is the only arrangement that survives demo-day with
no network.

### 3.2 Type scale for the dashboard (re-scaled, not copied)

The current panels run at **10–12 px** inline (`fontSize: 10` appears 24 times
in the five files sampled). That is below the accessible floor and it
photographs badly in the deck. Proposed:

| Token | px / lh | Replaces |
| :--- | :--- | :--- |
| `--fs-display` | 32 / 36 | the 22 px headline numbers |
| `--fs-h1` | 20 / 26 | panel titles |
| `--fs-h2` | 16 / 22 | sub-sections |
| `--fs-body` | 14 / 20 | default text (was 12) |
| `--fs-meta` | 13 / 18 | secondary meta (was 11) |
| `--fs-micro` | 12 / 16 | dense table cells only (was 10) |
| `--fs-eyebrow` | 12 / 12.6, 500, `letter-spacing: .02em` | section labels |

Nothing below 12 px ships. Landing page keeps the reference's 16 px body.

### 3.3 Colour tokens

Chrome tokens follow the reference; **data colour is a separate namespace and
is not part of this design system.**

```
--ink:        #242424    --page:       #ffffff
--surface-1:  #f9f9f9    --surface-2:  #f0f0f0
--surface-3:  #e6e6e6    --surface-4:  #d9d9d9
--muted:      #999999    --line:       #e6e6e6
--caveat-bg:  #fff4e5    --caveat-ink: #7a3e00   (kept from today's banners)
--danger-ink: #b00020    --ok-ink:     #1b5e20
```

**The FD2320 hazard colours keep coming from the run payload**, exactly as
`frontend/src/hazard.js` already states ("Colours come from the payload, not
from here"). No token file may define a hazard colour; a restyle that quietly
re-maps `moderate`/`significant`/`extreme` would put the dashboard back into
the five-definitions state §10 of `validation_findings.md` closed.

### 3.4 Geometry and motion tokens

```
--r-pill: 999px   --r-card: 14px   --r-control: 8px   --r-chip: 4px
--gutter: 8px     --pad-card: 16px --pad-panel: 16px
--dur-fast: 120ms --dur: 180ms     --ease: cubic-bezier(.2,.6,.2,1)
```

Dashboard transitions never exceed 180 ms and never animate a map, globe or
chart container. All motion sits behind `@media (prefers-reduced-motion)`.

---

## 4. Where the CSS goes — the repo currently has none

Measured in the sampled files: **0 `className` attributes, 139 inline `style=`
objects, 29 distinct hard-coded hex values, no stylesheet other than
`leaflet/dist/leaflet.css`** imported in `main.jsx`. So this is not a restyle of
an existing system; it is introducing one.

```
frontend/src/styles/
  tokens.css      the custom properties in §3 — values only, no selectors
  base.css        :root, body, scoped resets, font-face imports
  ui.css          the component classes in §5
```

Four rules that keep this from breaking the two things that are hard to debug:

1. **Every selector is scoped under `.jr` on the app root.** Cesium injects its
   own widget DOM and Leaflet its own controls; a bare `button {}` or `input {}`
   reset reaches the Leaflet zoom control and the Cesium toolbar. Never write an
   unscoped element selector.
2. **Inline styles keep working during the migration.** A panel is converted in
   one commit or not at all; there is no half-state where a class and an inline
   rule fight, because the inline rule always wins and the result looks random.
3. **No CSS-in-JS, no Tailwind, no PostCSS plugin.** Vite handles plain CSS
   imports; adding a pipeline means touching `desktop/backend`'s frozen build
   and `windows-installer.yml` for no gain.
4. **Fonts are imported in `main.jsx`** alongside `leaflet.css`, for the same
   stated reason that import exists: the CDN version broke offline.

---

## 5. Component inventory

New primitives in `frontend/src/ui/` — small, presentational, no data fetching:

| Component | Class | Replaces (today) |
| :--- | :--- | :--- |
| `<Shell>` / `<TopBar>` | `.jr-topbar` | `App.jsx`'s `borderBottom: 1px solid #ddd` div |
| `<TabPill>` | `.jr-pill` | bare `<button disabled={active}>` |
| `<Card>` | `.jr-card` | ad-hoc bordered divs in every panel |
| `<SectionLabel>` | `.jr-eyebrow` | 10–11 px bold inline text |
| `<Stat>` | `.jr-stat` | the 22 px headline numbers |
| `<DataTable>` | `.jr-table` | hand-rolled `<table>` styling, per panel |
| `<Chip>` | `.jr-chip` | the badge counts on Gauges / Downloads |
| `<Caveat>` | `.jr-caveat` | the `#fff4e5`/`#7a3e00` banner styling repeated inline |

**`<Caveat>` is a correctness component, not decoration.** It carries the
synthetic-run label, the `JALRAKSHA_NOT_A_SURVEY` DEM banner, the
`dam_class_note`, `unverified_regressions`, the minority-arrival note, the
boundary-proximity flag and the Tier-1 framing. Its contrast is fixed at ≥ 4.5:1
and it may never be rendered muted, collapsed by default, or below
`--fs-meta`. `Web_Publish_Spec.md` §11.4 already makes the same demand of the
phone viewer; this keeps one rule for all three surfaces.

---

## 6. Surface-by-surface

| Surface | Treatment |
| :--- | :--- |
| **Dashboard** (`frontend/`) | Tokens + primitives. Pill tab bar, card surfaces, quiet dividers, Inter with tabular figures. Density preserved — this is the instrument. |
| **Desktop app** (`desktop/`) | Inherits automatically; it serves the same Vite build from the loopback static server. No Electron change. |
| **Landing / mobile viewer** | The place the reference language belongs in full: full-bleed hero, 8 px-gutter card grid, 48 px uppercase accents, GSAP ScrollTrigger reveals. Applies to the static viewer in `Web_Publish_Spec.md` §10 and to any public site. |

---

## 7. Phases

Each phase is independently shippable and ends with a check that would actually
fail if the phase were wrong.

**A — Foundation (no visible change).** Add the three stylesheets and the
self-hosted fonts; set `body` background, colour and family; scope everything
under `.jr`.
*Gate:* `npm run build` succeeds; the 2D map, the Cesium globe and the Leaflet
zoom control look byte-identical to a before screenshot; a grep of `dist/` finds
no external font or CSS URL (same shape as `build.mjs`'s existing Cesium-token
check).

**B — Shell.** `App.jsx` top bar → pill tabs, fixed header, 8 px gutters.
*Gate:* `Pane`'s visibility/opacity mechanism is untouched — panels stay mounted
and Cesium is not rebuilt on tab switch. Verify by switching tabs mid-playback
and confirming the camera position survives.

**C — Primitives.** Build the eight components above with no panel wired to
them yet, plus a throwaway preview route.
*Gate:* `<Caveat>` renders every one of the honesty labels listed in §5 at full
contrast.

**D — Panel migration, one panel per commit.** Order: `DownloadsPanel` (185
lines) → `GaugesPanel` (177) → `ValidationPanel` (352) → `EnsemblePanel` →
`ImpactPanel` → `SphPanel` → `ComparisonPanel` → `Map2D`/`Scene3D` chrome only →
**`ControlPanel` last** (986 lines, 78 inline style objects).
*Gate per commit:* no behavioural diff; the panel's numbers, units and labels
are unchanged; screenshot at **1366×768** (the demo laptop) shows no clipped
control and no new scrollbar in the sidebar.

**E — Charts.** Theme `recharts` to the tokens: `--muted` axes, `--line` grids,
`--ink` labels, tabular figures.
*Gate:* hazard series still take their colours from the payload; the Validation
tab still reads 5.98e-14 m/s, 0.000000%, 0.0317 m vs 0.0349 m.

**F — Landing / mobile viewer.** The full scroll treatment; GSAP + ScrollTrigger
bundled from npm, never the CDN; everything degrades to a static page under
`prefers-reduced-motion` and with JS disabled.
*Gate:* the page renders all mandatory caveats with motion disabled.

Rough effort: A 0.5 d · B 0.5 d · C 1 d · D 3–4 d · E 0.5 d · F 2–3 d.

---

## 8. Risks and traps

1. **Global resets reaching Leaflet and Cesium.** The single most likely way to
   break the demo. Scope under `.jr`; never style `button`, `input`, `canvas` or
   `.leaflet-*` globally.
2. **Fonts over the network.** A `@import url(fonts.googleapis.com)` would look
   fine in dev and render fallback metrics on demo day. Self-host, and keep the
   `dist/` grep in the gate.
3. **Density regression.** 10 px → 14 px body is a ~30% vertical growth in the
   sidebar. `ControlPanel` is fixed-width; check 1366×768 before, not after,
   converting it.
4. **Softening the honesty labels.** A neutral grey design system makes warnings
   look like chrome. The `<Caveat>` contract in §5 exists because this repo has
   already paid for the opposite (`make_synthetic_demo_run.py` is labelled three
   times over precisely so no single omission unlabels it).
5. **Hazard colours drifting into the token file.** See §3.3.
6. **Desktop installer checks.** `build.mjs` fails the build if the Cesium token
   leaks into the output; adding assets must not trip it, and must not add a
   path long enough to matter against the measured 129-char deepest bundled
   path.
7. **The reference is light-only.** The map and globe viewports are visually
   dark. Decide once: **light chrome, dark viewports**, and do not attempt a
   dark mode in this pass.
8. **Scroll motion in an instrument.** ScrollTrigger belongs on the landing page.
   In the dashboard it would fight the simulation clock and the map.

---

## 9. Out of scope

Dark mode · any change to panel data, units or thresholds · restructuring tabs ·
i18n · replacing recharts, Leaflet or Cesium · touching `jalraksha/` Python ·
copying any andhüman asset, image or copy line.

---

## 10. Open questions for the owner

1. Does the landing treatment (Phase F) target the static phone viewer in
   `Web_Publish_Spec.md`, a separate public site, or both?
2. Is adding three `@fontsource` packages acceptable, or should fonts be
   committed as woff2 files under `frontend/public/`?
3. Phase D is the bulk of the work. Convert all eight panels, or only the four
   the demo actually walks through?

---

## 11. As built (2026-09-19)

Owner decisions: dashboard only (A–E), `@fontsource` npm packages, all panels
migrated, "JalRaksha" in the top bar, and D2 added to the scope.

Where the implementation departs from the plan above, and why:

1. **Secondary text is `#666`, not `#999`.** `#999` on white is 2.85:1 — below
   WCAG AA even for large text. `--ink-2: #666` (5.7:1) carries every secondary
   label; `--muted: #999` is kept for rules, icons and disabled states.
2. **`.jr` scoping alone does not protect the maps.** Leaflet and Cesium render
   inside the app root, so `.jr a` still outranks `.leaflet-bar a`. Element
   rules in `base.css` exclude `.leaflet-container` / `.cesium-viewer` subtrees
   and are wrapped in `:where()` so they carry zero specificity (without that,
   the exclusion made them outrank the component classes).
3. **Tokens are on `:root`, not `.jr`.** Custom properties style nothing, so
   they cannot leak; `body` needs them for its background.
4. **Caveat has four tones** (warn, danger, ok, info), collapsing five
   amber-ink variants, three reds, a green and a blue that were each defined
   inline. All ≥ 7:1 at 13 px.
5. **Chart legends moved to the top.** At the bottom they collided with the
   x-axis labels in the Validation and SPH charts.
6. **The sidebar is 300 px** (from 280) with a fixed flex basis; measured at
   1366×768 with no horizontal overflow and nothing below 12 px.
7. **Primitives live in one module**, `src/ui/index.jsx`, plus `brand.js`,
   `chartTheme.js` and a dev-only `Preview.jsx` (`?ui-preview`).
8. **§5's `<Caveat>` list included three labels no payload carried.** Phase D2
   added them to `RunResult` / `EnsembleSummary` / gauge rows and rendered them.

Verification, measured: panes are not remounted by a tab round trip (same
`.leaflet-container` and `.cesium-viewer` nodes, unchanged Leaflet pane
transform); every font loads from `/assets/` with no external request; the
Validation tab still reads mass drift 0.000000% and Ritter RMSE 0.0317 m vs
0.0349 m; Impact bars keep the payload's class colours.
