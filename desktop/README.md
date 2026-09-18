# JalRaksha for Windows (desktop app)

The desktop app puts the existing JalRaksha dashboard, the FastAPI service and
the simulation worker into one Windows installer. It does not replace any of
them. The browser dashboard (`python scripts/run_api.py` +
`npm run dev --prefix frontend`) and the Docker Compose deployment still work
as before.

## Architecture

```
JalRaksha.exe (Electron main process, desktop/electron/main.js)
 ├─ picks a free 127.0.0.1 port
 ├─ starts resources\backend\jalraksha-backend.exe serve --port N      (PyInstaller, onedir)
 │     └─ runs:  jalraksha-backend.exe run-worker <payload>             (detached, as before)
 │           └─ solver pool processes                                   (multiprocessing, frozen)
 ├─ waits for GET /health (at most 120 s; stops early if the process dies)
 ├─ serves resources\frontend (the Vite build) from a loopback static server
 └─ BrowserWindow → http://127.0.0.1:<ui-port>
       sandbox, contextIsolation, no nodeIntegration
       preload exposes a frozen, read-only window.jalrakshaDesktop {apiUrl, …}
```

- **The page talks to the API only over localhost.** Its API URL comes from
  the preload bridge at runtime, so no port is compiled in.
  `frontend/src/runtimeConfig.js` falls back to the build-time `VITE_*`
  values, which means web builds behave exactly as before.
- **Navigation is locked down.**
  - The window can only go to the dashboard's own origin.
  - Links to API `/files/...` open a save dialog.
  - https links open in the system browser.
  - Everything else is blocked.
  - Pop-ups are denied, and so are permission prompts (camera, geolocation, …).
- **ParaView** is offered only when `GET /capabilities` says it can work:
  `paraview.exe`, `pvpython.exe` and the render script all exist, and the
  caller is on the same machine. A remote or cloud deployment never offers it.

## Where data goes

Nothing is written inside the install directory. Everything is written under
`%LOCALAPPDATA%\JalRaksha\`:

| path | contents |
| :--- | :--- |
| `data\` | `JALRAKSHA_DATA_DIR`: DEMs, runs, exports, keyframes, `jalraksha.db`, per-run logs `data\runs\<id>.log` |
| `logs\` | `desktop-YYYYMMDD.log` (shell), `backend-YYYYMMDD.log` (API), `smoke.json` / `smoke.png` |
| `cache\numba\` | `NUMBA_CACHE_DIR`, compiled kernels (rebuilt when missing) |
| `cache\matplotlib\` | `MPLCONFIGDIR` |
| `config\desktop.json` | optional settings, see below |
| `electron\` | Electron/Chromium profile |

Uninstalling removes the program but keeps this folder, so runs and imported
packs survive. Delete the folder by hand to remove them.

### `desktop.json` (optional)

The file is only needed for the features that require it. Only the keys below
are read; anything else is ignored and noted in `logs\desktop-*.log`.

```json
{
  "cesiumIonToken": "…",          // 3D terrain; the installer carries NO token
  "cesiumIonAssetId": "…",
  "geeProject": "my-gcp-project", // Earth Engine; run `earthengine authenticate` yourself
  "paraviewExe": "C:/Program Files/ParaView 6.2.0/bin/paraview.exe",
  "pvpythonExe": "C:/Program Files/ParaView 6.2.0/bin/pvpython.exe",
  "dflowfmExe": "C:/Program Files/Deltares/…/dflowfm-cli.exe",
  "dataDir": "D:/some/checkout/data"   // absolute; use an existing data folder instead
}
```

(Real JSON has no comments. The comments above are for explanation only.)

Credentials are never bundled. The Cesium token reaches the page at runtime
from this file. Earth Engine uses the credentials that `earthengine authenticate`
stores in the user's profile. Without them, the dashboard reports Earth Engine
as unavailable with the reason, and it never substitutes synthetic data.

## Data packs

The installer contains **no data**. A fresh install lists no runs until you
import a pack with **File → Import data pack…** (`.jrpack`).

- **What a pack holds.** A pack is a zip containing:
  - `manifest.json`: every file with its sha256 and its licence
  - `db.json`: the run, gauge and export rows
  - the files themselves
- **Validation comes first.** Import checks the whole pack before writing
  anything:
  - It refuses paths outside the data folder.
  - It refuses checksum mismatches.
  - It refuses a file that already exists with *different* content. It never
    overwrites.
  - It refuses a synthetic run that the pack does not declare as synthetic.
- **Runs that already exist are skipped.**
- **Export and import from a checkout:**

  ```bash
  python -m jalraksha_service.data_packs export --run-id <id> --out x.jrpack --name "…" --include data/dem/…tif="licence text"
  ```

  ```bash
  python -m jalraksha_service.data_packs import x.jrpack
  ```

  Run both from the repo root with `PYTHONPATH=services/api;.`.

**The Khadakwasla pack** is built with `npm run desktop:pack:khadakwasla`, which
writes `dist/packs/JalRaksha-khadakwasla-<sha>.jrpack`. It contains:

- the flagship run `e2e09ea3…` (`khadakwasla_drain_to_green`), or else the
  newest completed Khadakwasla run that has imagery
- `dem_18.44_73.77_clipped.tif` (Copernicus GLO-30), so new Khadakwasla runs
  work offline
- the Pune-basin GHS-POP (area-corrected v2 only), GHS-BUILT-S and WorldCover
  caches (CC BY 4.0)

It is built from a checkout's `data/`, so CI cannot build it.

## Developer commands

Run all of these from the repo root.

```bash
npm run desktop:install
```
Runs `npm ci` for `frontend/` and `desktop/`. If `desktop/node_modules/electron/path.txt` is missing afterwards, run `node desktop/node_modules/electron/install.js`.

```bash
npm run desktop:dev
```
Starts Electron, `scripts/run_api.py` on a free port and the Vite dev server. It uses the checkout's `./data`.

```bash
npm run desktop:smoke
```
Same startup, then loads the UI, probes `/health`, `/capabilities`, `/backends` and `/runs`, writes `logs/smoke.json` and `smoke.png`, and quits.

```bash
npm run desktop:test
```
Runs the shell's unit tests (node:test).

```bash
npm run desktop:build
```
Builds the frontend and freezes the CPU backend into `desktop/build/`.

```bash
npm run desktop:package
```
Builds an unpacked app in `desktop/build/electron-cpu/win-unpacked/`.

```bash
npm run desktop:dist:cpu
```
Builds the CPU installer and writes it to `dist/windows/`.

```bash
npm run desktop:dist:gpu
```
Builds the GPU installer and writes it to `dist/windows/`.

```bash
npm run desktop:dist
```
Builds both installers.

```bash
npm run version:check
```
Checks that `jalraksha.__version__` matches both `package.json` files.

Smoke flags for the Electron binary: `--smoke`, `--smoke-run=<run_id>` (also
loads that run's result, manifest and first keyframe) and `--smoke-out=<file>`.

Environment contract for development and testing:

| variable | effect |
| :--- | :--- |
| `JALRAKSHA_DESKTOP_ROOT` | use this folder instead of `%LOCALAPPDATA%\JalRaksha` |
| `JALRAKSHA_DESKTOP_PYTHON` | interpreter that runs the checkout (default `python`) |
| `JALRAKSHA_DESKTOP_UI_URL` | development only: use an already-running Vite server |

The build script, `desktop/scripts/build.mjs`, takes these flags:

- `--stage build|package|dist`
- `--variant cpu|gpu`
- `--python <3.14 interpreter>`
- `--skip-frontend`, `--skip-backend`, `--skip-install`
- `--use-python-env`

It builds the backend in a pinned venv (`desktop/build/venv-<variant>`) from
`desktop/backend/requirements-<variant>.txt`. PySPH is installed afterwards
from `requirements-sph.txt` with `--no-build-isolation`. Its isolated build
fails on Python 3.14, and it needs **MSVC Build Tools** on the build machine.

## Installer

- **Name:** `dist/windows/JalRaksha-<version>+<git-sha>-win-x64-<CPU|GPU>-Setup.exe`
  - A build from uncommitted changes gets `-dirty` after the SHA.
- **Installer type:** NSIS (assisted), x64.
  - Per-user by default; the installer also offers "all users".
  - Creates a Start menu shortcut and an uninstall entry.
  - No auto-update.
- **Traceability:** `resources\build-info.json` records version, git SHA, UTC
  build time and variant. **Help → About** shows the same. Run provenance
  (`solver_backend`, Delft3D labels, etc.) is unchanged: it comes from the
  service as before.

### CPU vs GPU installers

- **CPU:** numba CPU kernels only. `/backends` reports CUDA unavailable, with
  numba's own import error as the reason.
- **GPU:** additionally bundles numba-cuda (with NVVM/NVRTC wheels) and
  pyopencl.
  - **It still needs an NVIDIA driver on the machine.** The installer cannot
    bundle one.
  - At startup the backend runs the same real probe as the browser dashboard.
    `auto` uses the GPU only if a float64 kernel compiles and runs; otherwise
    it uses the CPU and says why.
  - An explicit `cuda` request on a machine that cannot run it is refused at
    submission, as before.
- **Near-field SPH:**
  - On the CPU, PySPH compiles Cython at runtime, which needs MSVC Build Tools
    on the machine running the app.
  - Without MSVC, SPH reports why it did not run, and the SWE result is
    unaffected.
  - The GPU variant can run SPH through OpenCL when the driver provides a
    float64 OpenCL device.
- **Delft3D FM** is never bundled (Deltares licence). Without `dflowfmExe`,
  `solver="both"` falls back to the built-in solver, with its honest label.

### Size

Measured on commit `824059c` plus working-tree changes, built on 2026-09-13:

| variant | installer | installed size | frozen backend alone |
| :--- | ---: | ---: | ---: |
| CPU | 320.1 MB | 1,156 MB (8,268 files) | 819 MB |
| GPU | 429.2 MB | ~1.6 GB (11,300 files) | 1,232 MB |

The deepest bundled path is 129 characters below the install folder (a CUDA
CCCL header). Keep the install folder under about 120 characters, or the NSIS
uninstaller cannot delete that file: Windows' 260-character `MAX_PATH` applies.
The default `%LOCALAPPDATA%\Programs\JalRaksha` is well inside the limit. A
measured test install under a 130-character folder left exactly that one file.

### Diagnosing the GPU

Run this command against the installed app:

```bash
"<install dir>\resources\backend\jalraksha-backend.exe" diagnose
```

It prints JSON showing:

- which `numba.cuda` implementation loaded
- whether a device is available, and numba's own error if not
- the full capability probe

Freezing the CUDA stack failed four different ways before it worked, and this
output shows which case you are in (`desktop/backend/jalraksha-backend.spec`,
`GPU_RAW_TREES`):

1. numba's legacy `numba.cuda` loaded instead of numba-cuda
2. extensions were missing
3. a delvewheel DLL was missing
4. `cuda.core` compiled modules or metadata were missing

## Validation record (2026-09-13, this machine: Windows 11, RTX 4050 Laptop GPU)

Everything below was measured. Nothing is inferred.

**Python tests:**

- `python -m pytest tests/ -q`: 821 passed, 7 skipped, 0 failed. This includes
  the blocking lake-at-rest and mass-conservation gates and the new
  `test_desktop_runtime.py` / `test_data_packs.py`.

**Build checks:**

- `node --test "desktop/test/*.test.mjs"`: 15/15.
- Frontend web build (`npm run build --prefix frontend`): ok.
- Desktop frontend build: ok. The build verified the local Cesium token is absent
  from the output.

**Development mode (`--dev --smoke`):**

- The backend was healthy in about 3 s.
- The bridge is frozen, exposes 0 functions, and no Node globals are visible.
- The flagship run's result, 90-keyframe manifest and first PNG all loaded.
- No process was left after quit.

**Packaged CPU app:**

- The backend was healthy in 2.4 s. `/backends` offers `auto,cpu` and says
  numba-cuda is not bundled.
- The Khadakwasla pack (86.2 MB, 228 files) imported in 2 s. Re-import skipped
  the run and copied 0 files.
- A 2-member, 15-minute Khadakwasla run through the frozen backend finished in
  about 25 s, with 20 exports and `CPU (numba, float64)`.
  - The first attempt solved and exported, then failed on a missing `redis`
    module. That is now bundled.
- Exit paths:
  - Keep: the backend was killed without `/T`, and the worker was still alive.
  - Stop: `stop-active-runs` killed the worker, and the run shows
    failed / "Stopped by the user when quitting…".

**Installed CPU app** (silent `/S /D=` install):

- The smoke test passed with data under `%LOCALAPPDATA%\JalRaksha\data`.
- The install directory had 0 changed files after launch.
- Silent uninstall removed the files, the shortcut and the uninstall entry, and
  kept the user data.

**Packaged GPU app:**

- The frozen probe reports CUDA available on the RTX 4050, and SPH OpenCL
  available.
- A `backend=cuda` Khadakwasla run finished in about 14 s, labelled
  `GPU (CUDA, NVIDIA GeForce RTX 4050 Laptop GPU, float64)`.
- Loading the imported run through the run picker showed the corridor gauges
  with arrival times and 90 frames (`logs\smoke.png`).

**Installed GPU app:**

- The smoke test passed with CUDA available.
- The install directory had 0 changed files.
- Uninstall left one file, the `MAX_PATH` case above.

**Not measured:**

- A machine without an NVIDIA driver running the GPU installer (it should
  report the probe failure and use the CPU).
- A clean machine with no MSVC running near-field SPH on the CPU.
- Either installer built by the GitHub Actions workflow. It has not run yet.

### Offline caveats

- Everything the solver needs runs from the data folder after a pack import or
  the first DEM fetch.
- The **basemaps are online services**: OpenStreetMap tiles in 2D, and Cesium
  ion imagery/terrain in 3D. They need internet. Offline, the run overlays
  still load, but the background is blank.

## Code signing

The installers are **unsigned**, so Windows SmartScreen warns on first run.

To sign them:

1. Obtain an Authenticode certificate (EV removes the SmartScreen warm-up).
2. Provide it to electron-builder as `CSC_LINK` (a path or base64 `.pfx`) and
   `CSC_KEY_PASSWORD`. In CI, add both as repository secrets and pass them to
   the "Build installer" step.
3. Remove `CSC_IDENTITY_AUTO_DISCOVERY: "false"` from
   `.github/workflows/windows-installer.yml`.

No signing secret is used or needed anywhere today.

## CI and releasing

`.github/workflows/windows-installer.yml` triggers on pushes to `main`, `v*`
tags, and manual dispatch.

1. **Checks:**
   - version consistency
   - the blocking solver gates and the desktop-facing service tests
   - the desktop unit tests
   - the web frontend build
2. **Installer (cpu, gpu):** a clean Windows runner builds each installer and
   uploads it as an artifact named after its version and commit. Artifacts
   are kept for 30 days.

A change to the project therefore produces new installers on the next push to
`main`. Installed copies do not change; users install the new build.

**Releasing.** The repository has no release automation configured. To publish
a release:

1. Push a `vX.Y.Z` tag, after setting `__version__` in `jalraksha/__init__.py`
   and running `npm run version:sync`.
2. Wait for the workflow to finish.
3. Download both installer artifacts.
4. Attach them to a GitHub Release by hand.
