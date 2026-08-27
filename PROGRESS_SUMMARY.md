# JalRaksha Integration — Status

> **Read this first.** Until this pass, the solver had never run on real terrain,
> and its terrain was wired in backwards: `terrain/domain.py` assigned the
> elevation field to `State.h` (water DEPTH) while the bed `b` stayed flat at
> zero. Every run therefore began with the whole domain under ~1500 m of standing
> water, and every gauge "arrived" within a fraction of a second. **All arrival
> times, depths, and inundation areas produced before this pass are void.** The
> chain is now fixed end to end and verified against real Copernicus GLO-30.


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
`frontend/src/panels/ComparisonPanel.jsx` provides the "SPH vs
Delft3D-Class" comparison tab (originally ported from the since-removed
Streamlit dashboard). Verified with a real `solver="both"` run: RMSE/bias/CSI/
overlap metric cards, both matplotlib figures, and the gauge arrival table all
render. Handles the no-comparison-data case (`solver="swe"` runs) gracefully.

Note: the SPH side of this comparison is synthesized (particle positions from
`np.random`, arrivals from a wave-celerity approximation). This is a
pre-existing limitation of `jalraksha/delft3d/comparison.py`, reached via
`services/api/jalraksha_service/tasks.py::_run_comparison` — not introduced by
the frontend, and not a real PySPH run.

### Real terrain end to end ✅ (this pass)

**Phase 0 — DEM fetch.** `dem.py::fetch_dem()` was dead code: `clipped_path` and
`product_key` were used but never assigned, so every call raised
`NameError`. Nothing in the repo could produce a DEM, and the eight files in
`data/dem/` had been hand-staged from outside it — all 200×200 at 0.005° with
*identical* bounds despite filenames implying six different tiles. Now fixed and
re-fetched for real: 6 distinct tiles at 0.000277° (30 m), clipped to
3891 × 4510, elevations 246–6902 m.

`/vsicurl` also needed `GDAL_DISABLE_READDIR_ON_OPEN=EMPTY_DIR` — without it GDAL
lists the whole bucket prefix before opening and hangs long enough to look like a
network failure, silently tripping the synthetic-terrain fallback. Those settings
are now baked into `_fetch_tile_window`.

**Phase 2 — reprojection.** `conditioning.py::load_dem_as_grid()` is the single
honest DEM→Grid path (4326 → correct UTM zone via `rasterio.warp`, nodata fill,
smoothing). It replaces `preprocess_dem`'s old arithmetic, which divided a span
in *degrees* by a resolution in *metres* (nx = 1.0/200 → 0, clamped to a 10×10
floor) and hardcoded EPSG:32643 everywhere.

**Phase 4 — breach injection.** `inject_breach_hydrograph` set a *velocity* and
never added mass. Against a dry bed that is a no-op, so no water entered the
domain at all; it only ever appeared to work because the domain was pre-flooded.
It is now a volume source (`Q·dt/cell_area`), which also makes no assumption
about which way downstream points — the real bed routes the water.

**Gauge coordinates.** Rishikesh and Haridwar carried longitudes of 77.10 and
77.86, placing them ~112 km and ~29 km west of the actual towns, off the Ganga
corridor entirely. Koteshwar sat ~4 km east of the gorge. Corrected across all
six files that defined them.

**Gauge sampling.** Gauges now snap to the lowest bed cell within 1.2 km rather
than the geometrically nearest one. At 200–400 m the Bhagirathi gorge is
sub-grid, so the nearest cell to a gauge is often part way up the canyon wall:
Koteshwar snapped to 853 m with the valley floor at 752 m three cells away and
reported "no arrival" while the flood ran 70 m deep past it — while Devprayag,
15 km *further* downstream, happened to land on the channel and did report one.
A far gauge wet and a near one dry is the signature of a sampling artifact.

Also fixed: every gauge was projected into *its own* UTM zone rather than the
domain's (Rishikesh is zone 43, the domain is 44), and the per-member step cap
was sized from the dry-bed timestep, truncating runs after a handful of real steps.

**Environment.** `jalraksha/__init__.py` now repairs a broken inherited
`PROJ_LIB`. This machine has PostgreSQL/PostGIS exporting one whose database
layout predates what rasterio's PROJ expects, which made every CRS lookup fail.

### M4 — Self-hosted Cesium terrain ✅ (this pass)

`tools/cesium/build_terrain_tiles.py` tiles the **same DEM the solver
conditions**, so 2D and 3D match by construction. 1089 tiles, 9.2 MB, levels
0–12, built in seconds.

Format is `heightmap-1.0`, not quantized-mesh: `cesium-terrain-builder` is a C++
build we do not have, and `pydelatin`/`pymartini` have no Python 3.14 wheels.
Cesium 1.144 still supports heightmap natively
(`@cesium/engine/.../CesiumTerrainProvider.js:148`), and it is pure numpy.

Verified by decoding tiles the way CesiumJS does and comparing to the DEM: max
deviation 8.6 m over 30 sample points; Tehri reads 814 m (reservoir surface),
Devprayag 449 m (real ≈470 m).

Served from the API at `/tiles` (CORS-enabled) so local dev needs no second
process; Docker Compose still uses the nginx `tiles` service.
`tools/cesium/upload_terrain_to_ion.py` remains as an **unverified** alternative
for anyone who prefers Cesium ion.

## Not done — needs tools unavailable in the build environment

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

## Performance — parallel ensemble, not GPU

Ensemble members are independent and previously ran strictly one at a time.
`solver/parallel.py` now defines `run_ensemble_member()` as the **single**
definition of member physics, called by both the sequential and process-pool
paths — the old module reimplemented the time-stepping loop with its own
simplified breach injection, so parallel runs would have silently computed
different physics from sequential ones. Verified bit-identical.

**The cores were never idle.** The premise that sequential members waste a
multi-core machine was wrong: the flux kernels are `@njit(parallel=True)` and
already fan out over `prange`. Measured on this codebase (400 m, 600×600,
16 logical cores): **12.8 s per member on 16 threads vs 30.3 s on 1 — only
2.37× for 16× the threads**, which is normal for a memory-bound stencil that
synchronises every timestep.

That poor scaling is precisely what makes ensemble parallelism worthwhile.
Per unit wall time, 16 single-threaded members deliver 16/30.3 = 0.53 members/s
against 1/12.8 = 0.078 for one all-threads member — nearly **7× the throughput**.
The two axes compete for the same cores, so workers are pinned to one thread
(`_init_worker`) and parallelism is spent across members instead.

Three traps found and fixed while measuring this, each of which silently ate the
benefit:
- **Nested parallelism** — 8 workers × 16 numba threads on 16 cores thrashed.
- **Native thread pools** — each worker also starts its own OpenBLAS/OMP pool;
  16 of them exhausted RAM outright (`OpenBLAS error: Memory allocation still
  failed`). Fixed by exporting single-thread env vars in the parent *before* the
  pool spawns, since children inherit `os.environ` and an initializer runs too
  late (after the child has already imported numpy).
- **A per-member threshold was the wrong test.** Whether the pool wins depends on
  ensemble size, not member duration; the code now estimates both totals from a
  timed probe and picks the cheaper. A 16-member run was being sent down the
  sequential path by the old rule.

Windows callers must guard their entry point with `if __name__ == "__main__":`
— spawned children re-import `__main__`. Without it the pool raises, and
`run_ensemble` degrades to sequential rather than failing the run.

**Measured result:** a 16-member ensemble (400 m, 30 min simulated) runs in
**93.8 s across 6 workers vs 187.4 s sequential — 2.00×**, with results verified
bit-identical. The cost model predicted 81 s vs 138 s, so it is calibrated.

2× rather than the 6× a naive "16 cores, 16 members" estimate suggests, because
the sequential baseline was *already* using all cores (2.37× intra-member) and
because worker count is capped by RAM, not cores — each worker is a full
interpreter at ~400 MB. On a box with more memory the same code should reach
~5–6× (the model gives 225 s vs 1280 s for 100 members at 16 workers). Raising
the worker cap is the highest-value next step, not more parallelism elsewhere.

**GPU was evaluated and declined.** The hot loop is `@njit(parallel=True)` scalar
kernels on `float64`, which `solver/types.py` documents as "not negotiable"
because the lake-at-rest gate needs it. Consumer Ada (RTX 4050) runs float64 at
1/64 of float32 (~0.2 vs ~13 TFLOPS), so a float64 CUDA port would likely be
*slower* than the current CPU kernels, and `flux.py:48` deliberately forbids
`fastmath` because the well-balanced C-property depends on strict IEEE ordering.
Making a GPU worthwhile would mean relaxing float64 to float32 and re-validating
the blocking gates. (`numba.cuda` is also non-functional here: the driver is
present but `nvvm.dll` is not, so no CUDA toolkit.)

## Test status

`python -m pytest tests/` → **344 passed, 0 failed** (was 6 failed at the start
of this work).

Two tests were not merely failing but *vacuous*, and are now real:
- `test_arrival_times_monotonic` placed its gauges outside the domain, so all
  three snapped to the same corner cell and `t[1] >= t[0]*0.9` held trivially. It
  now positions them inside the domain and asserts strict ordering.
- `test_arrival_times_mock_results` only checked that dict keys existed; it now
  asserts real arrival values and downstream ordering.

Two more encoded a dead endpoint (`cloud.sdsc.edu`, now 401) and were asserting
against the *old* tile-naming convention — the code was right, the tests were
stale. Updated to the AWS convention.

Real bugs found and fixed in existing code along the way:
- **`terrain/domain.py` put elevation in `h` instead of `b`** — the headline bug.
- `inject_breach_hydrograph` set velocity but never added mass (no-op on a dry bed).
- `run.py` called `latlon_to_utm(lat, lon, utm_zone)` — the function takes 2 args.
- `latlon_to_utm` used a flat-earth approximation that put Tehri at 137°E.
- `compute_breach_location` returned a hardcoded 1300 m unrelated to the terrain.
- `cache.get_cached_dem()` was called by the worker but did not exist.
- Keyframe PNGs rendered upside-down (image row 0 is north; grid row 0 is south).
- `solver/parallel.py` failed to import at all (`Tuple` never imported).

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
