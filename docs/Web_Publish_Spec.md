# Web publish: desktop run → GitHub → phone

**Status:** design spec, not yet implemented.
**Written:** 2026-09-13.
**Audience:** the coding agent that will implement this in this checkout.

> Naming: **(PROJECT NAME)** is the product name in prose. Code identifiers,
> module paths and executable names below (`jalraksha_service`, `jalraksha-backend.exe`,
> `%LOCALAPPDATA%\JalRaksha`) are literal and must be typed exactly as written.

---

## 1. What this adds

Today a finished run is visible only on the machine that computed it, or on
another install after a `.jrpack` import. The demo therefore needs the laptop.

This spec adds a third path:

> The desktop app publishes a completed run to a **public GitHub repo**. A
> **static mobile page on GitHub Pages** takes a short code and renders that
> run — every panel the desktop dashboard shows, at phone size.

Judges do not install anything, do not join a LAN, and do not touch the laptop.
They scan a QR code or type an 8-character code.

**User story.** The operator runs Khadakwasla on the laptop, waits ~25 s, picks
**File → Publish run to web…**, and gets back a code (`K7M2-9QDX`) and a QR
code on screen. Four judges scan it. Each sees the run's numbers, the flood
animation, the map, the gauge arrival bands, the provenance banners and the
download links.

### Why GitHub and not a server

| | cost | expiry | needs an account/deploy | serves big files |
| :--- | :--- | :--- | :--- | :--- |
| **GitHub repo + Pages + Releases** | free | none | repo already exists | yes, via Releases |
| Cloudflare R2 + Worker | free tier | none | account + deployed Worker | yes |
| Supabase free tier | free tier | **project pauses when idle** | account | yes |
| Anonymous file hosts | free | days–weeks | no | unreliable |

GitHub wins on the one axis that matters two days before judging: nothing can
pause, expire or require a deploy that the operator forgot to renew. The repo,
the Pages site and the release assets are all already part of the submission
(see `submission_plan`: judges get a downloadable repo anyway).

### The three constraints this design is built around

1. **Everything published is public, permanently, and indexed.** A public repo
   is not "unguessable". Section 9 states what must never be in a bundle.
2. **The renderer process must gain no new powers.** The current security model
   (`desktop/electron/preload.js`) exposes a frozen object of plain values and
   **zero functions**; actions that touch the shell live in the application
   menu. Publishing touches the network and a credential, so it goes in the
   menu too. Do not add an IPC function for it.
3. **The phone must not claim more than the laptop does.** Every honesty label
   the dashboard renders — synthetic run, `dam_class_outside_fitted_population`,
   `delft3d_fallback_reason`, `sph_error`, Tier-1 screening caveat — is part of
   the bundle and must be rendered on the phone. See §11.4; this is a
   correctness requirement, not polish.

---

## 2. Architecture

```
LAPTOP (offline-capable)                      GITHUB (free)                 PHONE
──────────────────────────                    ─────────────                 ─────
JalRaksha.exe
 └ File → Publish run to web…
     └ spawns  jalraksha-backend.exe publish --run-id <id>
         ├ web_publish.build_bundle()
         │    reads DB rows + DATA_DIR artifacts
         │    → bundle.json (~80 KB)
         │    → frames/*.webp (30 × ~60 KB)
         │    → map/extent.webp, map/hydrograph.webp
         │    → downloads.json (names + sha256 + size)
         │
         ├ web_publish.push_bundle()  ── Git Data API, ONE commit ──▶  repo: docs/runs/<CODE>/…
         │                                                            repo: docs/runs/index.json
         └ web_publish.push_assets()  ── Releases API ─────────────▶  release run-<CODE>
                                                                       geotiff / xdmf+h5 / shp

                                                 GitHub Pages
                                                 https://<owner>.github.io/<repo>/m/
                                                       │
                                                       ▼
                                                 enter CODE  ──fetch──▶ ../runs/<CODE>/bundle.json
                                                                        lazy: frames, map
```

Three pieces to build:

| # | piece | where | language |
| :-- | :--- | :--- | :--- |
| **A** | bundle builder + GitHub transport | `services/api/jalraksha_service/web_publish.py` | Python |
| **B** | menu item, dialogs, QR, result window | `desktop/electron/main.js` (+ a small `publish.js`) | Node |
| **C** | mobile viewer | `mobile/` → published to `docs/m/` | vanilla HTML/JS |

Nothing in `frontend/` changes. Nothing in `main.py` changes. `tasks.py` does
not change. The publisher is a **reader** of what a finished run already wrote.

---

## 3. The share code

Run ids are 32-character hex. Nobody types that on a phone.

- **Alphabet:** Crockford base32 minus ambiguity → `0123456789ABCDEFGHJKMNPQRSTVWXYZ`
  (no I, L, O, U). 32 symbols.
- **Length:** 8 symbols = 40 bits. Displayed grouped: `K7M2-9QDX`.
- **Generation:** `secrets.token_bytes(5)` → base32 → uppercase. Re-roll on
  collision with an existing entry in `docs/runs/index.json` (retry 5×, then
  fail loudly).
- **Input normalisation on the phone:** uppercase, strip everything not in the
  alphabet, map the confusables the user will type anyway — `I`/`L`→`1`,
  `O`→`0`, `U`→`V`. A code typed as `k7m2 9qdx` must resolve.
- **Mapping storage:** the code *is* the path — `docs/runs/<CODE>/bundle.json`.
  No database, no lookup service.
- **Reverse mapping:** store `share_code` on the run row so republishing the
  same run reuses its code instead of creating an orphan. Add a nullable
  `share_code TEXT` column in `db.py` with the existing migration pattern; if
  the column is absent (old DB), fall back to a lookup in `index.json`.

**40 bits is not a secret.** It stops a stranger guessing a code; it does not
make the run private. The repo is public.

---

## 4. Bundle format v1

One directory per published run, under `docs/runs/<CODE>/`:

```
docs/runs/<CODE>/
  bundle.json          the whole run, minus heavy rasters       ~40–120 KB
  frames/
    manifest.json      frame index: t_s, url, hazard_summary
    f000.webp … f029.webp                                       ~60 KB each
  map/
    extent.webp        final flood-extent overlay (transparent) ~150 KB
    hydrograph.webp    comparison hydrograph, when present      ~60 KB
    depth.webp         comparison depth map, when present       ~150 KB
  downloads.json       the heavy exports, with release-asset URLs
```

Target: **under 5 MB per run** in the repo. Everything above that goes to a
release (§7).

### 4.1 `bundle.json`

The shape mirrors `GET /runs/{id}/result` (`main.py:448`) so the phone and the
dashboard read the same field names. Additions are `bundle_format`,
`share_code`, `published_at`, `source`, `map`, `frames`, `validation` and
`caveats`. **No field is invented.** A value the run did not produce is `null`
and the phone renders "not recorded", never a placeholder number.

```jsonc
{
  "bundle_format": 1,
  "share_code": "K7M29QDX",
  "run_id": "e2e09ea3…",
  "published_at": "2026-09-13T14:22:07Z",

  "source": {
    "app_version": "1.0.0",          // jalraksha.__version__
    "git_sha": "824059c",            // from build-info.json, or "unknown"
    "variant": "GPU",                // CPU | GPU | checkout
    "machine_os": "Windows 11"       // platform.platform(), coarse
  },

  // ── identity ────────────────────────────────────────────────────────────
  "dam_name": "Khadakwasla",
  "dam_id": "khadakwasla",
  "scenario_type": "dam_break",
  "solver": "swe",
  "solver_backend": "GPU (CUDA, NVIDIA GeForce RTX 4050 Laptop GPU, float64)",
  "status": "done",
  "error": null,
  "created_at": "2026-09-13T13:58:11Z",

  // ── copied verbatim from the run's own artifacts ────────────────────────
  "params":             { /* run row params, MINUS the redaction list in §9.3 */ },
  "engine":             { /* run_summary.json → engine */ },
  "grid":               { /* run_summary.json → grid: nx, ny, dx, dy, crs, center */ },
  "ensemble":           { /* run_summary.json → ensemble: p5/p50/p95 */ },
  "rapid_estimate":     { /* run_summary.json → rapid_estimate, or null */ },
  "hazard_summary":     { /* last keyframe's hazard_summary, incl. dam_class flags */ },
  "population_at_risk": { /* population_at_risk.json, or null */ },
  "impact":             { /* impact.json, or null */ },
  "sph":                { /* sph_near_field.json, incl. sph_error, or null */ },
  "comparison":         { /* comparison_metrics.json body as GET /runs/{id}/comparison
                             returns it: metrics, gauge_comparison, sph_engine,
                             sph_error, delft3d_engine_label, delft3d_binary_used,
                             delft3d_fallback_reason, gauge_arrival_method — or null */ },
  "dem": {
    "dem_used": "dem_18.44_73.77_clipped.tif",   // BASENAME only, not a path
    "source": "Copernicus GLO-30",
    "dem_update": { /* run_summary.json → dem.dem_update, with file fields
                       rewritten to downloads.json keys, or null */ }
  },

  "gauges": [
    {
      "gauge_name": "Sinhagad Road",
      "distance_km": 8.2,
      "arrival_time_s": 1380.0,
      "arrival_p05_s": 1020.0,
      "arrival_p95_s": 2040.0,
      "max_depth_m": 3.4,
      "note": null,
      "par_estimate": null
    }
  ],

  // ── media, all paths relative to this bundle.json ───────────────────────
  "frames": {
    "count": 30,
    "manifest": "frames/manifest.json",
    "width": 720, "height": 540,
    "bounds": [[18.38, 73.70], [18.52, 73.84]],   // [[S,W],[N,E]] WGS84
    "duration_s": 10800,
    "note": null            // e.g. "downsampled from 90 frames"
  },
  "map": {
    "extent": "map/extent.webp",
    "bounds": [[18.38, 73.70], [18.52, 73.84]],
    "hydrograph": "map/hydrograph.webp",   // or null
    "depth": "map/depth.webp",             // or null
    "legend": [                             // hazard classes, from HazardClassifier
      { "label": "Low",      "color": "#9ecae1", "min_m": 0.1 },
      { "label": "Moderate", "color": "#4292c6", "min_m": 0.5 },
      { "label": "High",     "color": "#08519c", "min_m": 1.5 },
      { "label": "Extreme",  "color": "#08306b", "min_m": 3.0 }
    ]
  },

  "downloads": "downloads.json",

  // ── the honesty block: §11.4 renders every one of these ─────────────────
  "caveats": [
    { "level": "info",
      "text": "Tier-1 screening. Point depths are indicative only." },
    { "level": "warn",
      "text": "Masonry gravity dam: outside the fitted population of every
               breach regression in the ensemble.",
      "key": "dam_class_outside_fitted_population" }
  ],
  "is_synthetic": false          // from params; true ⇒ the phone shows a red banner
}
```

**Builder rule:** the `caveats` array is **derived, not authored**. Build it
from exactly these conditions, in this order, and add nothing else:

| condition | level | text |
| :--- | :--- | :--- |
| always | info | Tier-1 screening; point depths indicative only. |
| `params.is_synthetic` | **error** | Synthetic demonstration run. These numbers are not a simulation of a real event. |
| `hazard_summary.dam_class_outside_fitted_population` | warn | `hazard_summary.dam_class_note` verbatim |
| `comparison.delft3d_binary_used == false` and comparison present | warn | `"Delft3D FM binary did not run: " + delft3d_fallback_reason` |
| `sph.sph_error` or `comparison.sph_error` truthy | warn | `"Near-field SPH did not run: " + <the error>` |
| any gauge with a `note` | info | that note, prefixed with the gauge name |
| `dem.dem_update` present | info | Terrain was modified for this run; see provenance in downloads. |
| `engine` missing or `grid` missing | warn | Run predates the run-summary artifact; engine and grid are not recorded. |

### 4.2 `frames/manifest.json`

```jsonc
{
  "source_count": 30,          // keyframes the run actually produced
  "count": 30,                 // frames in this bundle
  "frames": [
    { "i": 0, "t_s": 0.0,    "url": "f000.webp",
      "hazard_summary": { /* per-frame, as the run wrote it */ } }
  ]
}
```

Keep the run's own `t_s`. Do not re-time. If the run produced more than 40
frames, take an evenly-spaced subset **that always includes the first and the
last**, and set `frames.note` in `bundle.json` to
`"downsampled from N frames"`. The last frame carries the hazard summary the
dashboard headlines, so losing it changes what the phone reports.

### 4.3 `downloads.json`

```jsonc
{
  "release_tag": "run-K7M29QDX",
  "release_url": "https://github.com/<owner>/<repo>/releases/tag/run-K7M29QDX",
  "files": [
    { "kind": "geotiff", "name": "max_depth.tif", "bytes": 41288192,
      "sha256": "…", "url": "https://github.com/…/releases/download/run-K7M29QDX/max_depth.tif",
      "licence": "JalRaksha model output … Terrain: Copernicus DEM GLO-30 …" }
  ],
  "omitted": [
    { "kind": "hdf5", "name": "run.h5", "bytes": 2483027968,
      "reason": "larger than the 2 GB release-asset limit" }
  ]
}
```

`licence` reuses `RUN_OUTPUT_LICENCE` from `data_packs.py:60`. Do not write a
new licence string.

---

## 5. What is published, and what is not

| artifact | kind | where | why |
| :--- | :--- | :--- | :--- |
| run row, gauge rows | DB | `bundle.json` | small |
| `run_summary.json` | run_summary | inlined | small |
| `impact.json`, `population_at_risk.json`, `sph_near_field.json` | json | inlined | small |
| `comparison_metrics.json` | comparison_metrics | inlined | small |
| keyframe PNGs | keyframe_manifest siblings | `frames/*.webp`, re-encoded | 30 × ~60 KB |
| comparison depth map / hydrograph PNGs | images | `map/*.webp` | small |
| GeoTIFF rasters | geotiff etc. | **release asset** | tens–hundreds of MB |
| `.xdmf` + its `.h5` | xdmf | **release asset**, both files | can be GB |
| shapefile set | shapefile | **release asset**, zipped | multi-file |
| updated DEM + provenance | dem_update* | **release asset** | large raster |
| the DEM the run read | — | **never** | large, and it is an input, not a product |
| `desktop.json`, tokens, logs | — | **never** | §9 |

`_run_files()` in `data_packs.py:161` already computes "every file a run needs".
**Reuse it.** Then partition by size: `≤ 8 MB and web-renderable` → repo,
everything else → release. Do not re-implement the file discovery; the keyframe
siblings and the `.xdmf`/`.h5` pairing are exactly the cases a re-implementation
gets wrong.

### Image re-encoding

PNG keyframes are 200–600 KB each; 30 of them would be 15 MB in a repo that
must stay small. Re-encode with Pillow (already a dependency):

```python
im = Image.open(png).convert("RGBA")
im.thumbnail((720, 720), Image.LANCZOS)     # keep aspect; never upscale
im.save(out, "WEBP", quality=80, method=4)  # RGBA WebP keeps transparency
```

Expected: 40–80 KB per frame. If Pillow lacks WebP on the build machine, fall
back to PNG with `optimize=True` and set `frames.note`; do not fail the publish.

---

## 6. Backend: `services/api/jalraksha_service/web_publish.py`

New module. Same shape as `data_packs.py`: a library plus a `main(argv)` CLI, no
HTTP endpoint. **An HTTP endpoint would let any page in any browser on the
machine push to the repo with the operator's token** — the same reasoning that
kept pack import off the API (`data_packs.py:41`).

### 6.1 Public functions

```python
BUNDLE_FORMAT = 1

class PublishError(RuntimeError): ...

def new_share_code(index: dict) -> str: ...

def build_bundle(run_id: str, out_dir: Path, *,
                 share_code: str | None = None,
                 max_frames: int = 40) -> dict:
    """Write the §4 tree into out_dir. Pure local; no network. Returns the
    manifest dict it wrote. Raises PublishError if the run is not 'done',
    is unknown, or has zero exports."""

def push_bundle(bundle_dir: Path, cfg: "PublishConfig", *,
                progress=None) -> dict:
    """One commit containing every file in bundle_dir plus the updated
    index.json. Returns {commit_sha, page_url}."""

def push_assets(files: list[Path], cfg, tag: str, *, progress=None) -> list[dict]:
    """Create-or-reuse release `tag`, upload each file, return asset records."""

def publish_run(run_id: str, cfg, *, progress=None) -> dict:
    """build → push_assets → rewrite downloads.json → push_bundle.
    Order matters: asset URLs must exist before the bundle that links them."""

def unpublish(share_code: str, cfg) -> None:
    """Delete docs/runs/<CODE>/, drop the index entry, delete the release."""
```

### 6.2 CLI

```
jalraksha-backend.exe publish --run-id <id> [--dry-run] [--out <dir>]
                              [--config <path>] [--json]
jalraksha-backend.exe publish --list
jalraksha-backend.exe publish --unpublish <CODE>
```

- `--dry-run --out <dir>` builds the bundle locally and **makes no network
  call**. This is the offline path (§13) and the thing to test first.
- `--json` prints one JSON object on stdout and nothing else, so `main.js` can
  parse it. Progress goes to **stderr** as `PROGRESS <pct> <message>` lines.
  Follow whatever `pack` already does here and stay consistent with it.
- Exit codes: `0` ok, `2` bad usage, `3` run not publishable, `4` auth/network,
  `5` remote rejected (limits, conflict).

### 6.3 `PublishConfig`

Read from `%LOCALAPPDATA%\JalRaksha\config\desktop.json`, new `publish` block
(the file's existing keys are untouched; unknown keys are already ignored and
logged):

```jsonc
{
  "publish": {
    "repo": "owner/repo",
    "branch": "main",
    "path_prefix": "docs/runs",
    "pages_base": "https://owner.github.io/repo/",
    "tokenFile": "C:/Users/me/.jalraksha/publish-token.txt"
  }
}
```

Token resolution order — **argv is never one of them** (§9.1):

1. `JALRAKSHA_PUBLISH_TOKEN` environment variable
2. the file at `publish.tokenFile` (first line, stripped)
3. `%LOCALAPPDATA%\JalRaksha\config\publish-token.txt`

If none resolves: exit 4 with
`"No GitHub token. Put a fine-grained token in <path> — see docs/Web_Publish_Spec.md §9."`

---

## 7. GitHub transport

### 7.1 The bundle: one commit via the Git Data API

Do **not** use `PUT /repos/{o}/{r}/contents/{path}` in a loop. 33 files would be
33 commits and 33 round-trips, and the second one races the first's `sha`.

```
GET  /repos/{o}/{r}/git/ref/heads/{branch}          → base_sha
GET  /repos/{o}/{r}/git/commits/{base_sha}          → base_tree
POST /repos/{o}/{r}/git/blobs   × N                 {content: b64, encoding:"base64"}
POST /repos/{o}/{r}/git/trees   {base_tree, tree:[{path,mode:"100644",type:"blob",sha}]}
POST /repos/{o}/{r}/git/commits {message, tree, parents:[base_sha]}
PATCH /repos/{o}/{r}/git/refs/heads/{branch} {sha}   (fast-forward only, force:false)
```

- Commit message: `publish: run <CODE> (<dam_name>)`.
- `index.json` is read from the **base tree**, not from a cached copy, and
  rewritten in the same commit. Two publishes minutes apart must not lose an
  entry.
- If `PATCH` returns 422 (non-fast-forward, someone pushed meanwhile): re-read
  the ref, rebuild the tree on the new base, retry. Cap at 3 attempts.
- Blob payloads are base64; keep each request under ~25 MB. With the §5 split
  no repo file exceeds 8 MB, so one blob per file is fine.
- Rate limit: 5,000 requests/hour authenticated. A publish is ~40 requests.
  Surface `X-RateLimit-Remaining` in the log line, not in the UI.

### 7.2 Heavy exports: release assets

```
POST /repos/{o}/{r}/releases              {tag_name:"run-<CODE>", name, body, draft:false}
  409/422 already exists → GET /repos/{o}/{r}/releases/tags/run-<CODE>
POST <upload_url>?name=<file>             Content-Type: application/octet-stream
  409 asset exists → DELETE /repos/{o}/{r}/releases/assets/{id}, then re-upload
```

- Release body: dam, date, app version, git sha, and `RUN_OUTPUT_LICENCE`.
- Per-asset limit 2 GB. A file over it goes into `downloads.omitted` with the
  reason; it does **not** fail the publish.
- Shapefiles ship as one `<name>.shp.zip` — a `.shp` without its `.dbf`/`.shx`
  is useless and four separate assets invite exactly that mistake.
- Upload with streaming (`requests` with a file object, or `urllib` with a
  chunked reader). Do not read a 2 GB file into memory.

### 7.3 Repo layout and Pages

```
docs/                     ← GitHub Pages source: "main / docs"
  m/index.html            the mobile viewer (built from mobile/)
  m/app.js  m/app.css  m/sw.js  m/manifest.webmanifest
  runs/index.json
  runs/<CODE>/…
  .nojekyll               REQUIRED — without it Pages ignores nothing, but Jekyll
                          will choke on some filenames and slow every build
```

Settings → Pages → Deploy from a branch → `main` / `/docs`. No Action, no build
step, no secret.

`docs/runs/index.json`:

```jsonc
{ "updated_at": "2026-09-13T14:22:07Z",
  "runs": [ { "code": "K7M29QDX", "run_id": "e2e09ea3…", "dam_name": "Khadakwasla",
              "created_at": "…", "published_at": "…", "solver": "swe",
              "is_synthetic": false, "bytes": 2317421 } ] }
```

**Repo size discipline.** Pages sites are capped at 1 GB and the repo should
stay well under it. At ~3 MB per run that is hundreds of runs — but every
publish is a permanent commit, so `git` history grows even after `unpublish`.
Publish deliberately, not on every test run. `--dry-run` exists for testing.

---

## 8. Desktop wiring

### 8.1 Menu

In `buildMenu()` (`main.js:212`), File menu, directly after
`"Import data pack…"`:

```js
{ label: "Publish run to web…", click: () => publishRun() },
{ label: "Manage published runs…", click: () => managePublished() },
```

Both are disabled (`enabled: false`) when `publish.repo` is absent from
`desktop.json`, with a tooltip pointing at this document. An operator who never
configures publishing sees a greyed item, not an error.

### 8.2 `publishRun()` flow

1. `GET <apiUrl>/runs?limit=50`, keep `status === "done" && export_count > 0`.
2. Show a picker (a `BrowserWindow` with a small local HTML list, or
   `dialog.showMessageBox` with up to 8 buttons for the MVP — the list window is
   better and is ~60 lines).
3. Spawn `jalraksha-backend.exe publish --run-id <id> --json`, reusing the
   existing spawn/log helper that `importDataPack()` uses.
4. Parse `PROGRESS` lines from stderr into a progress window.
5. On success show a **result window**: the code in large monospace with a copy
   button, the full URL, and a **QR code**.
6. On failure show `dialog.showMessageBox({type:"error"})` with the process's
   stderr tail — the same treatment pack import failures already get.

### 8.3 QR code

`https://<pages_base>m/?r=K7M29QDX` is ~45 characters → QR version 3, error
correction M. Render it **offline**; never call an online QR service (that would
leak the code to a third party and fail at a venue with no wifi).

Add `qrcode-generator` (MIT, ~12 KB, zero deps) to `desktop/package.json`
`dependencies` — note `dependencies`, not `devDependencies`, so electron-builder
bundles it. Draw to a canvas in the result window at ≥ 256 px with a 4-module
quiet zone, dark modules on white regardless of OS theme.

### 8.4 What does **not** change

- `preload.js` gains **no** new key and **no** function. The dashboard page
  never learns the token, the repo name or the publish state.
- `navigation.js` still blocks navigation; the result window's "open in browser"
  uses `shell.openExternal` on an `https:` URL, which is already allowed.
- No auto-publish. A run is published only by an explicit menu action.

---

## 9. Credentials and what must never leave the laptop

This is the section to get right. Everything else is recoverable.

### 9.1 The token

- **Type:** GitHub **fine-grained** personal access token.
- **Resource owner:** the account that owns the repo. **Only the one repo.**
- **Repository permissions:** `Contents: Read and write`. Nothing else — no
  Actions, no workflows, no metadata beyond the mandatory read.
  `Contents: write` covers both the Git Data API and Releases.
- **Expiry:** set it to ~2 weeks past the judging date. Not "no expiration".
- **Storage:** a plain file outside the repo, e.g.
  `%LOCALAPPDATA%\JalRaksha\config\publish-token.txt`. Add
  `publish-token*.txt` and `*.jrtoken` to `.gitignore` now, before writing any
  code.
- **Never in argv.** On Windows any process can read another's command line.
  Pass by env var or file only. The CLI must have no `--token` flag at all —
  not even an undocumented one, because it will end up in a shell history.
- **Never in a log.** Add a redactor to the desktop log writer: replace
  `/gh[pous]_[A-Za-z0-9]{20,}/g` and `/github_pat_[A-Za-z0-9_]{20,}/g` with
  `***`. Apply it to both `desktop-*.log` and `backend-*.log`.
- **Never in the installer.** Add a build check mirroring the existing one that
  verifies the Cesium token is absent from the frontend build: grep the packaged
  `resources/` tree for the two token regexes and fail the build on a hit.
- **Revocation:** if a token is ever pasted anywhere public, revoke it in GitHub
  settings first and rotate the file second. Nothing in the app caches it.

### 9.2 The Cesium Ion token stays out

The mobile page is public and static. A Cesium Ion token in it is a token
anyone can lift. **The mobile viewer is 2D only** (Leaflet + OpenStreetMap
tiles, no key needed). 3D stays on the desktop, where the token comes from
`desktop.json` at runtime. Do not "just add a 3D tab".

### 9.3 Bundle redaction

Before writing `params` into `bundle.json`, drop these keys and any key matching
`/token|secret|key|credential|password/i`:

- `gee_project`, any Earth Engine identifier
- `cesium_ion_token`, `cesium_ion_asset_id`
- absolute filesystem paths — everywhere in the bundle, emit **basenames only**
  (`dem_18.44_73.77_clipped.tif`, not `C:/Users/satyajeet/…`). A username in a
  path is personal data on a public site.
- `paraviewExe`, `pvpythonExe`, `dflowfmExe`
- the machine hostname

Implement this as one `redact(obj)` walker applied to the **whole bundle** just
before serialisation, plus an assertion in the test suite (§14) that no
published fixture contains a drive letter, a `/Users/` or a `\Users\` segment.

### 9.4 Publishing is irreversible in practice

`unpublish` removes the files from `main` and deletes the release, so the Pages
site stops serving them — but the commit stays in git history and GitHub may
have cached or a crawler may have copied it. Say this in the confirm dialog:
*"Anything published to a public repository should be treated as permanent."*

---

## 10. Mobile viewer: build and shape

Source in `mobile/`, output copied to `docs/m/`. **No framework, no bundler.**
The desktop dashboard is React + Vite + Cesium and takes seconds to boot; a
judge on venue 4G needs first paint in under two seconds. Three hand-written
files plus Leaflet from a CDN is the right size for this job.

```
mobile/
  index.html        ~200 lines: shell, code entry, section skeletons
  app.js            ~700 lines: fetch, render, player, map, cache
  app.css           ~400 lines: mobile-first, the white + light-blue theme
                                already chosen for the progress site
  sw.js             ~80 lines: cache-first for bundles, network-first for index
  manifest.webmanifest
```

Copy step: `npm run mobile:build` = `node mobile/build.mjs`, which copies the
files, inlines a `?v=<git sha>` cache-buster into the script/style tags, and
writes `docs/m/`. Keep it a copy, not a bundle — someone must be able to read
the published source and see the same file.

### 10.1 Routes

- `/m/` — code entry: one large input, a **Recent** list from `localStorage`,
  and a **Browse published runs** link reading `../runs/index.json`.
- `/m/?r=CODE` — loads that run directly. This is the QR target.
- Bad code → "No run published with code CODE." plus the entry form back.
  Distinguish 404 (no such run) from a network failure; a judge on bad wifi must
  not be told the code is wrong.

---

## 11. Mobile viewer: what it shows

Everything the desktop dashboard shows, minus 3D and minus anything that needs
the API. Map each desktop panel to a phone section:

| desktop panel | phone section | source in bundle |
| :--- | :--- | :--- |
| header / run picker | **Run header** | `dam_name`, `scenario_type`, `solver`, `solver_backend`, `created_at`, `source` |
| ControlPanel (params) | **Scenario** (collapsed) | `params` |
| Map2D | **Map** | `map.extent` + `map.bounds` on Leaflet/OSM, hazard legend |
| keyframe player | **Animation** | `frames/*` |
| GaugesPanel | **Gauges** | `gauges[]` |
| EnsemblePanel | **Ensemble** | `ensemble` |
| ImpactPanel | **Impact** | `impact`, `population_at_risk` |
| SphPanel | **Near-field (SPH)** | `sph` |
| ComparisonPanel | **Comparison** | `comparison` |
| ValidationPanel | **Validation** | `validation` (see §11.5) |
| DownloadsPanel | **Downloads** | `downloads.json` |
| DemUpdateBanner | banner in **Scenario** | `dem.dem_update` |
| Scene3D | **omitted** | — |

Order on the phone: header → caveats → headline numbers → map → animation →
gauges → ensemble → impact → SPH → comparison → validation → scenario →
downloads → provenance footer. A judge scrolls top-down; put the answer first.

### 11.1 Headline numbers

Four tiles, in this order: **peak discharge (p50, with p5–p95)**, **peak breach
width**, **inundated area**, **population at risk**. Each tile shows the
uncertainty band underneath in smaller type when the bundle has one, and the
word "not recorded" when it does not. Never show a bare median where a band
exists — that is the failure the p05/p95 plumbing was added to prevent
(`tasks.py:1674`).

### 11.2 Animation player

- Preload frames 0 and `count-1`; lazy-load the rest as the scrubber moves.
- Controls: play/pause, a range scrubber, the frame's `t_s` shown as `h:mm:ss`,
  and a 0.5×/1×/2× speed toggle. Default 4 fps.
- Frames sit on the Leaflet map as an image overlay at `frames.bounds` so
  panning and zooming work, with a "full screen" toggle.
- On a slow connection show the first frame immediately and a "loading 30
  frames" line; never block the page on the animation.

### 11.3 Gauges

A table, not a chart: name, distance, arrival p50 with the p5–p95 band, max
depth. Any gauge with a `note` renders the note in full beneath the row. A
gauge with a null arrival shows "did not arrive within the simulated window" and
its note — not a dash.

### 11.4 Caveats — mandatory

Render `caveats[]` as a stack of coloured bars **immediately under the run
header, above every number**, using `level` for colour (error = red, warn =
amber, info = grey). They are not collapsible and not dismissible.

If `is_synthetic` is true the whole page gets a red top border and the string
**"SYNTHETIC — NOT A REAL SIMULATION"** in the header. The desktop has three
layers of labelling for synthetic runs; the phone must not be the weak link.

A bundle whose `bundle_format` is newer than the viewer knows renders a warning
bar and then renders what it can — never a blank page.

### 11.5 Validation

`GET /validation` is machine-level, not run-level, and is slow on a cold call.
Do not call it during publish. Instead: if a cached validation result exists on
the publishing machine, embed a **summary** (gate name, pass/fail, the measured
value) as `bundle.validation`; otherwise set it to `null` and have the phone
show "Validation gates: see the repository." Do not trigger a validation run
from the publisher.

### 11.6 Offline behaviour

- Service worker: cache-first for `runs/<CODE>/*` (immutable once published),
  network-first with a 3 s timeout for `runs/index.json`.
- A viewed run stays readable offline. Show a "cached copy, published <date>"
  line when served from cache.
- `manifest.webmanifest` with the (PROJECT NAME) icon (`JalRaksha_Icon.svg` →
  192/512 px PNG) so a judge can add it to the home screen.
- The OSM basemap needs the network. Offline, the map shows the extent overlay
  on a plain graticule with a "basemap unavailable offline" note — the same
  honest degradation the desktop README documents for its own offline case.

### 11.7 Accessibility and phone reality

- Minimum tap target 44 px; the code input is `inputmode="text"`
  `autocapitalize="characters"` `autocomplete="off"`.
- Works at 360 px wide. Tables scroll horizontally inside their own container;
  the page body never scrolls sideways.
- Hazard colours must not be the only signal — label every class in text too.
- Respects `prefers-color-scheme`, with the white + light-blue palette as the
  light theme.

---

## 12. Failure modes

| situation | behaviour |
| :--- | :--- |
| no token | exit 4, message names the file path and this doc |
| token expired / revoked | exit 4, "GitHub rejected the token (401). Create a new fine-grained token with Contents: write." |
| token lacks Contents: write | exit 4, "(403) The token does not have Contents: write on `<repo>`." |
| repo not found / renamed | exit 4, names the configured repo |
| no network | exit 4, "Could not reach api.github.com. Publish needs internet; use --dry-run to build the bundle offline." |
| run not done | exit 3, states the status |
| run has zero exports | exit 3, "This run produced no artifacts; there is nothing to publish." |
| ref moved mid-publish | retry 3×, then exit 5 |
| asset > 2 GB | not fatal; listed in `downloads.omitted` |
| republish of an existing code | replaces the bundle in one commit, reuses the release, bumps `published_at` |
| Pages not yet built | the code works within ~1 min; the result window says "the page may take up to a minute to appear" |
| partial failure (assets up, bundle push fails) | leave the release; the next attempt reuses the tag. Never leave a `bundle.json` pointing at assets that are not there — that is why `push_assets` runs first. |

---

## 13. Offline / LAN fallback

`--dry-run --out <dir>` produces the identical tree with `downloads.json`
listing local filenames instead of URLs. Two uses:

1. **Venue with no internet.** The desktop's existing loopback static server
   (`desktop/electron/static-server.js`) serves `docs/m/` plus the bundle dir on
   `0.0.0.0:<port>`, and the result window shows a QR to
   `http://<lan-ip>:<port>/m/?r=CODE`. The viewer is the same file, fetching the
   same paths. **This requires binding off 127.0.0.1** — gate it behind an
   explicit "Share on this network" action and a confirm dialog, and bind back
   to loopback when it is turned off.
2. **Review before publishing.** Build the bundle, read `bundle.json`, confirm
   the redaction did its job, then publish.

Build the dry-run path first. It is most of the work and it is testable without
a token.

---

## 14. Tests and acceptance

### Python (`tests/test_web_publish.py`)

- `build_bundle` on the flagship Khadakwasla run produces the §4 tree; every
  path in `bundle.json` resolves to a file that exists in it.
- **Redaction:** the serialised bundle contains no `C:\`, no `/Users/`, no
  `\Users\`, no `gh[pous]_`, no `github_pat_`, and none of the §9.3 keys.
  Parameterise over at least two runs.
- `caveats` is exactly the §4.1 table for a constructed run with every flag set,
  and contains only the Tier-1 line for a clean one.
- A synthetic run yields `is_synthetic: true` and the error-level caveat.
- Frame downsampling from 90 → 40 keeps the first and last frame and sets
  `frames.note`.
- Nulls: a run with no `impact.json` yields `"impact": null` and the builder
  does not raise.
- `new_share_code` produces only alphabet characters and avoids a code already
  in a given index.
- Transport is tested against a stub (`responses` or a local `http.server`), not
  against GitHub. Cover: 401, 403, 422 non-fast-forward retry, 409 asset exists.

### Node (`desktop/test/publish.test.mjs`)

- The menu item is present and disabled without `publish.repo` in config.
- `PROGRESS` stderr lines parse into percentages.
- The log redactor replaces both token shapes.
- No new key appears on the preload bridge (extend the existing bridge test that
  asserts 0 exposed functions).

### Build check

- Packaged `resources/` contains neither token regex. Fail the build on a hit,
  the same way the Cesium-token check already does.

### Manual acceptance — run this before judging

1. Publish the flagship run. Code returned in under 60 s on a normal connection.
2. On a phone **on mobile data, not the venue wifi**, scan the QR. First
   meaningful paint under 3 s.
3. Every section in the §11 table renders, with no "undefined" and no `[object Object]`.
4. The animation plays through all frames and the scrubber seeks.
5. Every download link downloads and its sha256 matches `downloads.json`.
6. Airplane mode, reload: the cached run still renders, labelled as cached.
7. Publish a synthetic run: the red banner and the error caveat appear.
8. A wrong code says "no run published with that code", not a blank page.
9. `git log -p` on the publish commit: no token, no absolute path, no username.

---

## 15. Limits, measured against the plan

| limit | value | this design |
| :--- | :--- | :--- |
| GitHub file size (hard) | 100 MB | repo files ≤ 8 MB |
| GitHub file size (warning) | 50 MB | never hit |
| recommended repo size | < 1 GB | ~3 MB per published run |
| Pages site size | 1 GB | same |
| Pages bandwidth | 100 GB/month (soft) | ~5 MB per judge per run |
| Pages builds | 10/hour (soft) | one per publish |
| release asset size | 2 GB | larger files are listed as omitted |
| release count | unlimited | one tag per published run |
| REST rate limit | 5,000/hour | ~40 requests per publish |

---

## 16. Out of scope

- Running a simulation from the phone. The solver, Delft3D, PySPH and GEE stay
  on the laptop — the assessment in `submission_plan` stands unchanged.
- Live progress of an in-flight run on the phone. Publishing is for finished
  runs only. (A later `status.json` polled every 5 s would work, but it costs a
  commit per poll — do not.)
- 3D on the phone (§9.2).
- Authentication or private runs. The repo is public by design; if a run must be
  private, do not publish it.
- Editing or deleting a run from the phone.

---

## 17. Suggested build order

1. `build_bundle` + redaction + `--dry-run`, with the Python tests. No network.
2. The mobile viewer against a dry-run bundle served by `python -m http.server`.
   This is where the real work is; do it while the transport does not exist yet.
3. `push_bundle` (Git Data API) against a scratch repo.
4. `push_assets` (Releases).
5. Electron menu, progress, result window, QR.
6. Pages setup, `index.json`, browse list, service worker.
7. The build check and the log redactor.
8. Manual acceptance (§14) on a real phone, on mobile data.

Steps 1–2 deliver a demonstrable thing (a bundle a judge can open from a USB
stick or the LAN) before any credential exists. If time runs short, that alone
is a working fallback.
