# Prompt — sync the (PROJECT NAME) progress website to current project state

Paste everything below the rule into a fresh agent session that can read **both** folders.
Unlike `Progress_Update_Prompt.md`, this one is self-driving: the agent works out what changed
instead of being handed a filled block.

---

You are updating the public progress website for (PROJECT NAME), our Smart India Hackathon 2026
entry for Problem Statement **26161** — *"Dam Break Inundation Modelling Using Hydrodynamic
Modelling of any River"* (NTRO, Software, Disaster Management). The screening deadline is
**20 September 2026**, so the site has to be accurate rather than impressive.

## The two folders

| | Path |
| --- | --- |
| **Engine repo** (source of truth — read only) | `D:\pd\chosen one\SIH prototype` |
| **Site repo** (what you edit) | `D:\pd\chosen one\sih prototype progress` |

The site is React + Vite + Tailwind CSS v4, static build, white and light-blue theme.
**All copy, numbers, links, dates and team details live in one file: `src/content.js`.**

## Your job

The site was last synced on **14 September 2026** and already reflects everything through that
date — the GPU backend, the Windows installer, 821 tests, the "Three ways to run it" section, the
Compute performance block and the packaged-app stats are all in. Do **not** re-apply those.

Find what has changed in the engine repo *since* that sync, apply it to `src/content.js`, and fix
anything on the site that no longer matches the repo. If nothing has changed, say so plainly and
change nothing except what the placeholder section below asks for — a no-op is an acceptable
answer and is far better than inventing an update.

## Step 1 — Build a fact ledger before you touch the site

Read these, in this order, and write down every measured figure with the file and line it came
from:

- `docs/progress.md` — the running progress log
- `docs/validation_findings.md` — validation and benchmark results (**changed after the last site
  sync; read it closely**)
- `docs/Progress_Update_2026-09-14.md` — what the last sync applied, so you can tell new from old
- `docs/VERIFICATION_LOG.md` — open verification items; item **#14** (published CSI/F1 benchmarks
  against observed satellite flood extents) is still open and still blocks any "validated against
  real floods" claim
- `docs/PS-26161-official.md` — the twelve deliverables, for the progress table
- `README.md` and `desktop/README.md` — current capability and packaging claims
- `docs/DECISIONS.md`, `docs/Demo_Video_Script_3min.md` — recent decisions and current framing
- the current test-suite count (run it if you have a shell; otherwise take it from the repo docs
  and say which file you took it from)

**Sources you must not treat as measurements:**

- `BUILD_STATUS.md` states Phase targets, not results. Never quote it as an achievement.
- `CLAUDE.md` is a working brief, not a record of what has been measured.
- The engine `README.md` still says **"100-member breach hydrograph ensembles"** and still calls
  SWE/SPH **"coupled"**. Both contradict our claim audit. Do **not** carry either onto the site —
  flag them in your report as repo bugs to fix before the repo goes public.

Ledger rules:

- A figure earns a place only if you can point to the line in a project file that states it. If
  two files disagree, report the contradiction; do not pick one.
- Every simulation figure carries its **study area, grid size, simulated duration and ensemble
  member count**. A speed-up carries its grid size and member count.
- **Computing time is wall-clock time. Simulated flood time is a different quantity.** Never let
  one stand in for the other, and never write "real-time forecast" or "3-minute forecast".
- Leave out design targets, planned features, and anything not yet measured.

## Step 2 — Diff the ledger against `src/content.js`

Go through the file section by section and decide, for each value, whether it is still correct:

`HERO_STATS` · `PROGRESS_TABLE` · `BENCHMARK_BARS` · `DEPTH_TABLE` · `CORRECTNESS_STATS` ·
`SIMULATION_RUNS` · `HIGHLIGHT_CARDS` · `COMPUTE_PERFORMANCE` · `PACKAGED_APP_STATS` ·
`RECENTLY_COMPLETED` · `NEXT_TASKS` · `PIPELINE_STEPS` · `RUN_OPTIONS` · `ARCHITECTURE_LAYERS` ·
`TECH_STACK` · `LAST_UPDATED_DATE`

Three things to check that are easy to miss:

1. A figure in `HERO_STATS` usually appears again in a results table or a caption. Change it
   everywhere it occurs.
2. `RECENTLY_COMPLETED` and `NEXT_TASKS` are a pair — an item that got done moves out of
   `NEXT_TASKS` and into `RECENTLY_COMPLETED` with its date, newest first.
3. `LAST_UPDATED_DATE` must equal the date of the newest timeline entry.

## Step 3 — Apply

- **Edit `src/content.js` only.** Do not change the layout, palette, typography, components or
  section order. If a genuinely new fact needs a new section or a component change, stop and
  describe what you would add rather than building it.
- The done / in-progress counts and the donut chart in the Progress section are **computed from
  each row's `status`**. Edit the rows; never hand-write a count. `status` must be exactly
  `"Done"` or `"In progress"`.
- Keep the wording style already in the file: plain, precise, no hype words, no marketing
  adjectives, no added statistics, testimonials, awards or logos.
- **`PROJECT_NAME` stays as it is.** Every other parenthesised ALL-CAPS placeholder stays exactly
  as written unless Step 4 says otherwise.

## Step 4 — Placeholders and screenshots: fill what you can derive, report the rest

Fill only from evidence in the repos. Never guess a person, a team name or a URL.

- `GITHUB_REPO_URL` and `REPO_FOLDER_NAME` — take from the **engine repo's** git remote (not the
  site repo's). If the remote is missing, private, or has never been pushed, leave the placeholder
  and say so — a judge-facing link that 404s is worse than a visible placeholder.
- `GITHUB_RELEASE_DOWNLOAD_URL` and `WINDOWS_INSTALLER_LINK` — fill only if a real published
  GitHub Release with attached installers exists. CI build artifacts do not count: they expire
  after 30 days. If there is no release, leave both and add "cut a tagged release and attach both
  installers" to your report.
- `DOCUMENT_LINK`, `PPT_LINK`, `DEMO_VIDEO_LINK`, `TEAM_NAME`, `COLLEGE_NAME`, `TEAM_MEMBERS`,
  `MENTOR` — not derivable. Leave them and list them.
- **Screenshots.** `public/images/` currently holds no images, so all four `DASHBOARD_IMAGES`
  slots render as light-blue placeholder boxes. Look in the engine repo's `docs/images/`, `media/`
  and `archi res/` for real dashboard captures. Copy one in **only if it actually shows what the
  caption claims** — a 2D/3D map view, an ensemble panel, an impact panel, a validation panel —
  saving it under the exact filename `content.js` expects. A wrong screenshot under a right
  caption is a false claim. Leave the rest as placeholders.

## Non-negotiable phrasing rules

A claim audit on 6 September 2026 found the following fabricated in an earlier deck. None of them
may appear on the site, in any wording:

- "56 minutes end-to-end", "16 hours current practice", "17× faster" — no such benchmark exists.
- "100-member ensemble" — every real run is 2–6 members; 30 in the GPU benchmark.
- "Validated against real observed satellite flood extents" — not run. Still blocked by
  VERIFICATION_LOG #14.
- "A single Delft3D run takes 2–6 hours" — our own 300 m run takes 5 h; it boomerangs. Lead with
  *setup weeks → minutes* instead.
- "Four published breach regressions" — it is three embankment formulas plus Wahl (2004) bands,
  plus Costa (1985) for natural dams.
- "60 km downstream" — a design target. Demonstrated domains run 28 × 26 km to 240 × 188 km.

These phrasings must stay exact:

- The SPH handoff is **one-way (SWE → SPH)**. Never "coupled", never "two-way".
- We are **validated against the Delft3D FM kernel**. The project is not Delft3D, and the Delft3D
  kernel is never bundled. Delft3D naming stays conditional on the `delft3d_binary_used` flag.
- The Sentinel-1 work is **GRD change detection, not InSAR**. The DEM work is
  **observation-conditioned burn-in, not photogrammetry**.
- Damage and fatality coefficients are **unvetted placeholders** and must be labelled as such
  wherever they appear.
- Never call the system GPU-accelerated without saying it also runs on an ordinary processor.

If anything you find in the repo would require a claim the audit forbids, **stop and flag it**
rather than writing a softer version of it.

## Step 5 — Verify before you report

- Run `npm run build` in the site repo and confirm it completes. If you have no shell, say so and
  state that the build is unverified.
- Re-read your edited `content.js` end to end and confirm **every number on the page traces to a
  line in your ledger**.
- Confirm the Progress section's computed counts match the rows you left behind.
- Confirm timeline dates run newest first and the newest matches `LAST_UPDATED_DATE`.
- Confirm no file outside `src/content.js` changed, apart from any screenshot you copied into
  `public/images/`.
- Never commit the Cesium Ion token, and never bake it into a public build.

## Report

Finish with, in this order:

1. **Changes applied** — one line each, as `section — old → new`, with the source file and line
   that justifies the new value.
2. **Nothing-to-change** — sections you checked and left alone.
3. **Placeholders still open** — each one, and what is needed to fill it.
4. **Flags** — contradictions between repo files, claims you refused to write, and the two
   engine-`README.md` bugs (100-member, "coupled") if they are still there.
5. **Build status** — verified, or unverified and why.

Then stop. Do not commit or push; I will review the diff first.
