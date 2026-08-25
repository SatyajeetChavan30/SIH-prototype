# JalRaksha Integration — Status

Status of the integration brief's M1–M8 milestones (wrapping the existing
`jalraksha/` simulation engine in a browser-based 2D/3D dashboard).

**Read this before trusting any milestone as "done".** Each claim below says how
it was verified. Anything not verified in a running system is marked as such.

## Verified working (exercised end-to-end)

### M1 — Service layer (FastAPI + Celery/Redis)
`services/api/jalraksha_service/` wraps the existing pipeline. `POST /runs` →
`GET /runs/{id}` → `GET /runs/{id}/result` was driven end-to-end against a real
Tehri run; exports, gauge results, and a real keyframe manifest come back.

- Files written to disk under `DATA_DIR` are served at `/files/...` (static
  mount in `main.py`); endpoints return `/files/...` paths, and the frontend
  resolves them via `resolveApiUrl()` in `frontend/src/api.js`.
- CORS is enabled — the Vite dev server (`:3000`) and API (`:8000`) are
  different origins.
- **Local dev without Redis**: set `CELERY_EAGER=1`. Tasks then run in a
  background thread in-process, so `POST /runs` still returns immediately and
  the frontend's poll-until-done flow behaves exactly as with a real worker.
  Docker Compose does not set this, so the real broker path is untouched.

```bash
CELERY_EAGER=1 JALRAKSHA_DATA_DIR=./data python -m uvicorn jalraksha_service.main:app --app-dir services/api --port 8000
```

### M2 — Keyframe export (§5.3)
`jalraksha/export/keyframes.py` produces the manifest + PNG stack that drives
both the 2D slider and the 3D overlay. **This was previously dead code**: the
pipeline never recorded a depth time series, so export silently never fired.
Now fixed:

- `run_dam_break_ensemble()` takes `record_depth_snapshots=True, n_snapshots=N`
  and snapshots the depth grid of the ensemble member closest to the median peak
  outflow (recording every member is memory-prohibitive at ensemble sizes of
  100–10,000).
- Its returned `grid` dict now carries `x0, y0, crs`, so keyframes geo-register
  correctly. Verified: a Tehri run's keyframe bounds centre on 78.481 E, 30.378 N.
- 30 keyframes generated and served over HTTP in a real run.

### M3 — React shell + Leaflet 2D panel
Builds and runs. `npm install && npm run build` succeeds with Cesium bundled.
Verified in a browser: control panel, Leaflet map with the flood overlay,
gauge/dam markers, playback controls, and tab switching all render and work.

- `vite-plugin-cesium` added — without it Cesium's Workers/Assets/Widgets never
  get copied and `resium` fails at runtime.
- Scrubbing the playback slider moves **both** panels in lock-step (verified:
  slider → keyframe 18/30 → Leaflet overlay swapped to the matching PNG and the
  3D layer visibility followed).
- "Load run id…" loads a previously-completed run without re-simulating —
  survives a page refresh and lets a demo start from a pre-baked run.

### M5 — Tier-1 3D flood overlay (§5.5.3)
Cesium viewer renders with dam/gauge entities, camera fly-to presets, and the
flood keyframes as geo-registered imagery layers driven by the shared
`SimulationClock`. Two real bugs fixed here:

- `new Cesium.SingleTileImageryProvider({...})` throws on Cesium ≥ 1.104
  (requires explicit `tileWidth`/`tileHeight`); switched to the async
  `SingleTileImageryProvider.fromUrl()` factory.
- The previous code added all 30 keyframes as simultaneous layers and set
  `layer.interval`, which is not a Cesium API — they stacked and never swapped.
  Layers are now pre-built hidden, and only the active keyframe's layer is shown.
- `<Viewer full />` made the Cesium canvas cover the whole window, swallowing
  every click on the control panel. The viewer is now contained in its pane.

### M7 (partial) — Comparison tab (§5.7)
`frontend/src/panels/ComparisonPanel.jsx` ports the Streamlit "SPH vs
Delft3D-Class" tab. Verified with a real `solver="both"` run: RMSE/bias/CSI/
overlap metric cards, both matplotlib figures, and the gauge arrival table all
render. Handles the no-comparison-data case (`solver="swe"` runs) gracefully.

Note: the SPH side of this comparison is synthesized (particle positions from
`np.random`, arrivals from a wave-celerity approximation) — that is inherited
from the existing Streamlit implementation this ports, not introduced here.

## Not done — needs tools unavailable in the build environment

### M4 — Self-hosted Cesium terrain ⚠️ THE KEY REMAINING GAP
The brief is right that terrain must match the solver's DEM exactly, or the
flood overlay visibly floats through hills / clips underground. Neither terrain
source is configured yet, and the 3D panel **shows a red warning banner** saying
so rather than silently rendering misaligned terrain.

Two paths:
1. **Cesium ion** (lower setup risk): run `tools/cesium/upload_terrain_to_ion.py`
   with a `CESIUM_ION_TOKEN`, then set `VITE_CESIUM_ION_TOKEN` and
   `VITE_CESIUM_ION_ASSET_ID`. **That script is unverified** — written without an
   ion account or network access to test against; check its request shapes
   against Cesium's current REST API docs before relying on it.
2. **Self-hosted `cesium-terrain-builder`**: no `ctb` binary available here.
   Scene3D already falls back to `${VITE_TILES_URL}/terrain` if ion is unset.

### M6 — Live GEE SAR
`jalraksha/gee/{auth,population,sar}.py` still return mock data. No Earth Engine
credentials available. `GET /gee/latest` returns the stub gracefully.

### M7 — Docker/Compose
`docker-compose.yml` and `services/api/Dockerfile` exist and read correctly, but
**Docker is not installed here, so `docker compose up` was never run.** Known
open question: the `frontend` service maps `3000:3000` but nothing confirms the
container actually serves on 3000 in production mode (a built Vite app needs a
static server or `vite preview` as its CMD).

### M8 — Blender cinematic render
Not attempted; no Blender binary available.

## Test status

`python -m pytest tests/` → **334 passed, 4 failed, 2 skipped**.

The 4 failures are pre-existing and unrelated to this integration (2 in
`test_dem.py` about tile naming/URL format, 2 in `test_terrain.py`). This is down
from 6 failures: fixing `latlon_to_utm` to use pyproj (it previously returned a
crude flat-earth approximation that put Tehri at 137°E) also fixed two of them.

Real bugs found and fixed in the existing code along the way:
- `run.py` called `latlon_to_utm(lat, lon, utm_zone)` — the function takes 2 args.
  Every gauge arrival-time computation crashed.
- `latlon_to_utm` used a flat-earth approximation instead of a real projection.
- `cache.get_cached_dem()` was called by the worker but did not exist anywhere.
- Keyframe PNGs were rendered upside-down relative to map/Cesium bounds
  conventions (image row 0 is north; grid row 0 is south).

## Running the demo locally

```bash
CELERY_EAGER=1 JALRAKSHA_DATA_DIR=./data python -m uvicorn jalraksha_service.main:app --app-dir services/api --port 8000
```

```bash
npm install --prefix frontend && npm run dev --prefix frontend
```

Then open http://localhost:3000. Note that simulated time drives compute cost:
the control panel's "Simulated time" slider defaults to 30 min, and a 5-minute
simulated run at 200 m resolution takes a few minutes of wall clock. Pre-bake a
run before a demo and reload it by ID rather than simulating live.
