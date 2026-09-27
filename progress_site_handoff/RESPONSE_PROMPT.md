# Values to fill into the JalRaksha progress site — collected 27 September 2026

You are working in the progress-site repo (`D:\pd\chosen one\sih prototype progress`). Every
value below was collected from the engine repo (`D:\pd\chosen one\SIH prototype`, public
mirror `github.com/SatyajeetChavan30/SIH-prototype`, `main` = commit `1cd138d`) on 27 September
2026. Edit `src/content.js` (and copy images into `public/images/`) only as described here.

**Rules for applying this:**
- Change only what a row below gives a new value for. Anything marked `STILL MISSING` stays
  exactly as it is on the site now, placeholder included. Do not invent a replacement.
- Do not round, rephrase more favourably, or add a figure that is not in this file.
- Where this file says "unchanged", leave the site text alone.

---

## Blockers (read first)

1. **Honesty labels are switched off in the engine code on public `main`.** Commit `1cd138d`
   (25 Sep) put `return null;` at the top of the dashboard's `Caveat` component
   (`frontend/src/ui/index.jsx:132–133`, comment: "TEMP: all caveats/warnings hidden for demo
   recording — revert after demo"). While that is in place, the dashboard hides the synthetic
   strip, the unvetted-threshold notices and the boundary warnings. Because of this:
   - **No dashboard screenshots have been captured** (§3). Four of the six image slots stay
     empty until the switch is reverted and the capture is run.
   - The only unexpired CI installers (built 24 Sep from `1cd138d`) carry the same switch and
     must not be what `WINDOWS_INSTALLER_LINK` points to.
2. **No GitHub Release or tag exists.** `github.com/SatyajeetChavan30/SIH-prototype/releases`
   reads "There aren't any releases here" (fetched 27 Sep). `WINDOWS_INSTALLER_LINK` and
   `GITHUB_RELEASE_DOWNLOAD_URL` stay as placeholders.
3. **The document, deck and demo video have no public URL yet** (§1). Those three
   placeholders stay.
4. **The installers are still not code-signed.** The site already says so. Keep that text.
5. The repo itself is public and reachable. That link is fine.

---

## 1. Links

| Export | New value | Verified (HTTP status, login needed?) | Source / note |
| :--- | :--- | :--- | :--- |
| `GITHUB_REPO_URL` | **unchanged**: `https://github.com/SatyajeetChavan30/SIH-prototype` | 200, no login. The page was fetched logged-out on 27 Sep; the repo is public (default branch `main`), and an anonymous `git clone` also succeeded. | Keep. |
| `REPO_FOLDER_NAME` | **unchanged**: `SIH-prototype` | A fresh `git clone https://github.com/SatyajeetChavan30/SIH-prototype` on 27 Sep created the folder `SIH-prototype`. | Keep. |
| `GITHUB_RELEASE_DOWNLOAD_URL` | `STILL MISSING — no tagged Release exists` | The Releases page shows none (27 Sep). | Once a Release exists, the intended value is its tag page, e.g. `https://github.com/SatyajeetChavan30/SIH-prototype/releases/tag/v1.0.0`. **Do not fill this until the owner confirms the Release is live.** |
| `WINDOWS_INSTALLER_LINK` | `STILL MISSING — no Release; current CI installers carry Blocker 1` | — | The plan is one link to the same Release page (see below). |
| `DOCUMENT_LINK` | `STILL MISSING — owner has not yet identified the portal document or its public URL` | — | Nothing in the engine repo records it. |
| `DEMO_VIDEO_LINK` | `STILL MISSING — video.mp4 is not hosted anywhere public` | — | `video.mp4` (76 MB) is git-ignored and is not on Drive or YouTube. |
| `PPT_LINK` | `STILL MISSING — no public URL for the portal deck` | — | Decks exist locally in `media/`, but none is hosted, and the owner has not said which one was uploaded. |

**Installer link: ONE link.** Both builds (CPU and GPU) will be assets on the same GitHub
Release, so `WINDOWS_INSTALLER_LINK` should point to the Release page, and the page lets the
visitor pick CPU or GPU. No structural change to the site is needed. Only if the owner later
asks for separate direct CPU and GPU download buttons would the site need a second export and
a second button. That is not requested now.

**Run-it-yourself commands: one line to add, one line to adjust.** All of these were tested on
a fresh clone on 27 Sep (Linux, Python 3.11):

```
git clone https://github.com/SatyajeetChavan30/SIH-prototype
cd SIH-prototype
pip install -e ".[dev,viz]"
pip install -r services/api/requirements.txt
python scripts/run_api.py
npm install --prefix frontend
npm run dev --prefix frontend
```

- **Added line:** `pip install -r services/api/requirements.txt`. Without it,
  `python scripts/run_api.py` fails on a fresh clone with `ModuleNotFoundError: No module named
  'uvicorn'`, because FastAPI, uvicorn and Celery are not in the package's dependencies. With
  it, the API starts and `GET /health` returns `{"status":"ok","service":"JalRaksha API v1"}`.
- **Quoted extras:** `".[dev,viz]"` instead of `.[dev,viz]`. The quoted form means the same thing
  in bash and is safe in PowerShell and zsh. The unquoted form worked in bash in the test.
- `npm install --prefix frontend` and `npm run dev --prefix frontend` work unchanged. The
  dashboard served HTTP 200 on port 3000.
- "Needs Python 3.11+ and GDAL": **keep "Python 3.11+"** (`pyproject.toml`
  `requires-python = ">=3.11"`). On Linux, a separate GDAL install was **not** needed: the
  rasterio wheel bundles GDAL 3.10.3. Windows was not re-tested. The engine README still
  recommends a conda environment with GDAL on Windows. Suggested wording, if the site wants to
  be exact: "Needs Python 3.11+. On Windows, the README recommends a conda environment for
  GDAL." Otherwise leave the line as it is.

---

## 2. Team

| Export | New value | Source |
| :--- | :--- | :--- |
| `TEAM_NAME` | `STILL MISSING — not recorded in any repo file; waiting on the owner` | Every deck in the engine repo's `media/` still reads `<TEAM NAME>` |
| `COLLEGE_NAME` | `STILL MISSING — waiting on the owner` | — |
| `TEAM_MEMBERS` (6) | `STILL MISSING — waiting on the owner` | Git author history is not proof of membership, so it was not used |
| `MENTOR` | `STILL MISSING — waiting on the owner` | — |

No paste-ready JS for this section yet. Leave all nine team placeholders exactly as they are.

---

## 3. Screenshots

Folder: `D:\pd\chosen one\SIH prototype\progress_site_handoff\screenshots\`

| Filename | Absolute path | Pixel size | File size | Run ID + tab | What is visible | Honesty labels in frame |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `ritter-validation.png` | `D:\pd\chosen one\SIH prototype\progress_site_handoff\screenshots\ritter-validation.png` | 1540 × 980 | 112,246 bytes | Not a dashboard run. It is the figure the validation suite writes (`scripts/validate_against_delft3d.py --case ritter` → `data/validation/ritter_validation.png`, generated 11 Sep 2026) | Ritter (1892) exact, Delft3D FM (dflowfm-cli) and JalRaksha 2D SWE depth profiles on one axis; h₀ = 10 m, t = 40 s, Δx = 10 m; error panel below; footer "RMSE vs exact — JalRaksha 0.0317 m \| Delft3D FM 0.0349 m \| engines agree to 0.0294 m RMSE"; the 4h₀/9 = 4.44 m line | The figure itself shades the "boundary cells excluded from scoring (3 each end)" |
| `dashboard-2d3d.png` | — | — | — | — | `STILL MISSING — Blocker 1` | — |
| `dash-2d3d.png` | — | — | — | — | `STILL MISSING — Blocker 1` | — |
| `dash-ensemble.png` | — | — | — | — | `STILL MISSING — Blocker 1` | — |
| `dash-impact.png` | — | — | — | — | `STILL MISSING — Blocker 1` | — |
| `dash-validation.png` | — | — | — | — | `STILL MISSING — Blocker 1` | — |

The numbers in `ritter-validation.png` were checked against the suite's own
`data/validation/validation_metrics.json`: JalRaksha RMSE 0.031732 m, Delft3D FM 0.034942 m,
engine agreement 0.029435 m, depth at dam 4.5317 / 4.5152 m against 4.4444 m exact. These
match the site's 0.0317 / 0.0349 / 0.0294 m and 4.532 / 4.515 / 4.444 m.

**Copy instruction:** copy `ritter-validation.png` into the site's `public/images/`
unchanged. The other five slots stay empty for now. A separate handoff will deliver them
after the engine's `Caveat` switch is reverted.

**Captions:** no caption changes are needed for `ritter-validation.png`.

---

## 4. Updated figures

| content.js export / location | Old value | New value | Source (file:line or command) |
| :--- | :--- | :--- | :--- |
| `LAST_UPDATED_DATE` | `"20 September 2026"` | `"27 September 2026"` | Collection date |
| `HERO_STATS[0]` (test count) | 960 passing, 7 skipped (20 Sep) | **Unchanged — keep.** Not re-measured on the development machine. See the note below. | `docs/progress.md:10` still records `960 passed, 7 skipped` measured 2026-09-20 |
| `PROGRESS_TABLE` D4 | In progress; Ritter only | **Unchanged** | No new comparison figures in `docs/validation_findings.md` or `docs/progress.md` since 20 Sep |
| `PROGRESS_TABLE` D6 | In progress; unvetted placeholders | **Unchanged**: no primary citations found | `docs/VERIFICATION_LOG.md` rows 32, 35, 36, 39 all still `❌ TODO` |
| `PROGRESS_TABLE` D1–D3, D5, D7, D8, D10–D12 | Done | **Unchanged, no regression found.** The blocking solver gates (`tests/test_solver.py`) pass on a fresh clone. | Fresh-clone test run, 27 Sep |
| `PROGRESS_TABLE` D9 detail | "Nine tabs: 2D + 3D · Gauges · Ensemble · Impact · SPH · Comparison · Validation · Provenance · Downloads …" | **Changed.** A Registry tab was added on 20 Sep, and the SPH tab appears only for runs that have near-field SPH output. See the JS below. | `frontend/src/App.jsx:86–98` (tab list; SPH conditional at line 93); commit `8ea8073` |
| `PROGRESS_TABLE` D10 detail | 18 products (40-member run), 25 (river blockage) | **Unchanged** | `RUN_5_PROGRESS.md` "Completed runs" (bf0839d4: 23 export rows, 18 export products); `docs/progress.md:143` (Rishi Ganga: 25 exports) |
| `RECENTLY_COMPLETED` | latest 19 Sep | **5 new entries** (JS below) | Commits `f222c54`, `986d405`, `8ea8073`, `bc92ecd`, `923778d` (20 Sep); `088402c`, `753bbf4`, `2418658`, `3459742` (21 Sep); `1cd138d` (25 Sep, README text only) |
| `NEXT_TASKS` | 7 items | 6 still open; the workstreams item changed (JS below) | See the per-item notes below |
| `HERO_INSTALL_NOTE`, `RESOURCES_NOTES[0]` (unsigned) | not code-signed | **Unchanged, still true** | `.github/workflows/windows-installer.yml:87–89` (`CSC_IDENTITY_AUTO_DISCOVERY: "false"`, "the installer is unsigned"); `desktop/README.md:355` |
| `PACKAGED_APP_STATS[3]` (sizes) | 320 MB / 429 MB | **Unchanged for now.** These match the 13 Sep builds (335,656,689 B = 320.1 MiB CPU; 450,087,129 B = 429.2 MiB GPU, commit `824059c`). No Release exists yet. Re-measure when one is cut. | `dist/windows/*.exe` in the engine repo |
| `PACKAGED_APP_STATS` timings (13 Sep) | 2.4 s / ~25 s / 2 s | **Unchanged**: not re-measured | — |
| `COMPUTE_PERFORMANCE`, hero 11.5× | 12.6× / 20.3× / 11.5× | **Unchanged**: not re-measured | — |
| Drainage (`HIGHLIGHT_CARDS[0]`) | 96.4 % of 85.314 MCM on 28 × 26 km | **Unchanged.** No newer drainage result is in the allowed sources. The 240 × 188 km runs (`48f7ac59`, `1d3d3c45`) exited 0.000 MCM and did not test drainage. | `docs/validation_findings.md` §8, lines 428–438 |
| `RESOURCES_NOTES[2]` (DualSPHysics not bundled) | not in installers | **Unchanged, still true** | Engine `README.md:13` ("not carried in the installers") |

**Test-count note.** A full `pytest` run on a fresh Linux clone of `1cd138d` (27 Sep, Python
3.11, no GPU, no Delft3D kernel, no Earth Engine) gave **908 passed, 79 skipped, 5 failed**
(992 tests collected). All five failures come from that environment: `hydrolib-core` and
`earthengine-api` are not installed; two `compyle` compatibility tests assume the Python
3.12+ `ast` module; and one worker-termination timeout. This is **not** comparable with the
development-machine figure, so do not put it on the site. Keep `HERO_STATS[0]` as it is until
the owner re-measures on the development machine.

### Paste-ready JS

Replace the D9 row's `detail` only:

```js
    detail:
      "Ten tabs: 2D + 3D · Gauges · Ensemble · Impact · SPH (shown for runs with near-field SPH output) · Comparison · Validation · Registry · Provenance · Downloads — plus a Compute selector for choosing the processor or the GPU, 1/2/5/10× playback, and the same dashboard inside a Windows app",
```

Add these entries at the **top** of `RECENTLY_COMPLETED`, above the existing 19 Sep entry:

```js
  {
    date: "25 Sep 2026",
    text: "The engine README was corrected to match what was measured: the largest ensembles run are 40 members (most runs use 2–6), the SPH near field is fed by a one-way handoff and is not coupled back, the loss-of-life figure is not a published model, and the damage coefficients are unvetted placeholders.",
  },
  {
    date: "21 Sep 2026",
    text: "Corridor conditioning can now be switched on from the dashboard, so the conditioning behind the drainage run no longer needs a script. It is off by default, and a run that uses it is labelled as modified terrain. Two fixes: runs that use both solvers now show their SPH tab, and a run opened from a shared link now shows its own site and map.",
  },
  {
    date: "20 Sep 2026",
    text: "A Registry tab lists the four sites this install can model and works out whether each one is ready, instead of asserting it. That check found that Tehri's stored elevation data does not cover its own 60 km study area, and the tab says so. Bhakra, Idukki and Hirakud are listed as not runnable, with the reason.",
  },
  {
    date: "20 Sep 2026",
    text: "A \"Datasets on this machine\" section on the Provenance tab lists only files that are actually on disk (136 files, 2.6 GB when first measured), with their licences and checksums. The Provenance tab also now names the Delft3D FM kernel whenever a run used it.",
  },
  {
    date: "20 Sep 2026",
    text: "A Word report for any finished run, generated from the Downloads tab. It prints only what the run recorded: a missing figure reads \"not recorded for this run\", and the honesty page comes second, not in an appendix. Each new run also now saves its volume balance, the number that shows whether drainage was tested at all.",
  },
```

Replace `NEXT_TASKS` with:

```js
export const NEXT_TASKS = [
  "Compare the scenarios quantitatively on the real Indian sites, not only on the Ritter benchmark (requirement D4).",
  "Find primary citations for the damage, fatality and evacuation-directive coefficients, or keep them labelled as placeholders (requirement D6).",
  "Score the flood extents against observed satellite flood extents with published CSI / F1 metrics. Until that is done, we do not claim validation against real floods.",
  "Build the five remaining planned feature workstreams — weather and inflow, breach risk, named scenarios, survey cards and a reservoir state strip — designed, not started.",
  "Publish a finished run from the app to a phone-viewable page, so judges can see results without touching the laptop (designed, not yet built).",
  "Sign the Windows installers, so first-run warnings go away.",
  "Work through the highest-severity items in our own defect register.",
];
```

Per-item status of the old list:
1. D4 on real sites: **still open**.
2. D6 citations: **still open** (verification rows 32, 35, 36, 39 are TODO).
3. CSI/F1 against observed floods: **still open** (`docs/VERIFICATION_LOG.md`, Phase 9: "DEFERRED … blocking any claim of validation against real observed flood extents").
4. Remaining workstreams: **changed.** Slice 2 (20 Sep) built three more (report, registry, dataset catalogue); five are designed and not started (engine `CLAUDE.md:346–350`).
5. Publish-to-phone: **still open**. The spec exists (`docs/Web_Publish_Spec.md`); no code for it exists.
6. Code-sign installers: **still open**.
7. Defect register: **still open**. The register (`docs/JalRaksha_Technical_Reference_Manual.md`) is unchanged since 12 Sep.

---

## 5. Still missing

| Value | What is needed | Who acts |
| :--- | :--- | :--- |
| Five dashboard screenshots | Revert the two `Caveat` lines in the engine's `frontend/src/ui/index.jsx`, start the API and Vite, then run `python progress_site_handoff/capture_site_screenshots.py` from the engine repo root. The script refuses to run while the switch is present. | Owner (revert), then the engine session (capture and review) |
| `GITHUB_RELEASE_DOWNLOAD_URL`, `WINDOWS_INSTALLER_LINK` | Revert the switch, push, build fresh installers, and create tag `v1.0.0` plus a Release with both installers. Then re-measure the installer sizes. | Owner approves; the engine session prepares the commands |
| `DOCUMENT_LINK` | Public, no-login URL of the detailed document submitted on the portal | Owner |
| `PPT_LINK` | Public URL of the deck exactly as uploaded to the portal | Owner (upload plus share link) |
| `DEMO_VIDEO_LINK` | Unlisted YouTube upload or a Drive link set to "anyone with the link". Also confirm the video was not recorded with the labels switched off. | Owner |
| `TEAM_NAME`, `COLLEGE_NAME`, `TEAM_MEMBERS` ×6, `MENTOR` | Exactly as registered on the SIH portal | Owner |
| `HERO_STATS[0]` re-measure | `python -m pytest -q` on the development machine | Owner or engine session |
| Browser-tab title (`index.html`) | Still reads `(PROJECT NAME) — SIH 2026 · PS 26161`. `content.js` already uses `PROJECT_NAME = "JalRaksha"`, which matches the decks and repo. Whether that is the name **as registered on the portal** has not been confirmed. **Do not change `index.html`** until the owner confirms. | Owner |
