# Dashboard integration — what was connected, and what it shows

Written for the SIH 2026 demo. This records what now reaches the browser, what
does not, and why — so nobody has to rediscover it under demo pressure.

## The headline

The problem was almost never missing science. Six modules already ran; their
output was discarded before it reached the API, or replaced by placeholders on
the way. Most of this work was plumbing, plus three genuine bugs.

## Bugs fixed

### 1. Fabricated gauge names on the Delft3D path

Selecting **Khadakwasla + Delft3D** produced a gauge table reading
`Gauge_10km`, `Gauge_25km`, `Gauge_50km`, `Gauge_100km`. Those are
`jalraksha/api.py`'s generic placeholders.

`tasks.py` built a stripped five-key config (`name`, `lat`, `lon`, `height_m`,
`storage_mm3`) which dropped `dam_id`. `get_downstream_gauges(lat, lon, None)`
then could not identify the dam, and Pune is outside the Tehri bounding box it
falls back to, so it emitted invented names. A judge would have seen four
fictional towns.

Fixed by passing the config through intact.

### 2. `solver="delft3d"` never ran Delft3D

It called `rapid_estimate` — an analytic celerity formula — and produced zero
exports, no map and no keyframes. It now runs the real kernel.

### 3. Delft3D could never succeed even when the kernel was present

Two independent causes, both silent:

- `jalraksha/delft3d/setup.py` writes a `[Grid] GridType=rectangular` INI as the
  `NetFile`. D-Flow FM cannot read that — it wants a UGRID netCDF mesh — so the
  kernel failed at mesh load **every time** and the run quietly became the
  built-in solver wearing a Delft3D label. Now uses
  `jalraksha/delft3d/dfm_model.py::build_dfm_model`, the UGRID writer already
  covered by `tests/test_delft3d_model.py`.
- `_parse_delft3d_output` read only `*_map.nc`, so `gauge_arrivals` was `{}` on
  success. A *successful* Delft3D run reported no arrivals while the fallback
  reported a full table — the better engine looked like the emptier one. Now
  reads `*_his.nc`, reusing the approach from
  `validation/delft3d_benchmark.py::_read_his_gauges`.

The comparison domain was also `40x40` cells at 30 m for **10 seconds** — a
1.2 km box against gauges 10–60 km away. Nothing in it could reach a gauge. Now
20 km at 100 m for 1 hour, over real DEM terrain.

A fourth, found while testing: `load_dem_as_grid` returns a `Grid` dataclass,
not a dict. Subscripting it raised `TypeError`, which a bare `except Exception`
caught and turned into a silent flat-bed fallback — the comparison ran on
invented terrain while reporting success. The except is now narrowed to
`FileNotFoundError`.

## Data that existed and was thrown away

`run_dam_break_ensemble` computed all of this; `tasks.py` dropped it when the
task returned. It is now written to `run_summary.json` and served on
`RunResult`:

| Field | Why it matters |
| :--- | :--- |
| `q_peak` median / p05 / p95 | Peak breach outflow **and its band**. The four regressions disagree by 3–4x; quoting one number misrepresents the method. |
| `t_fail` median / p05 / p95 | Breach formation time. |
| `regressions_used` | Which published equations ran — Froehlich, MacDonald, Costa, Von Thun. |
| `num_completed` / `num_ensemble` | A run where 3 of 100 members converged was indistinguishable from one where all 100 did. |
| `h_max_stats` | Peak depth across the domain. |
| `grid` + WGS84 bounds | Georeferencing; previously only inside the XDMF. |

Per gauge, `arrival_p05_s` / `arrival_p95_s` / `max_depth_m` / `note` are now
persisted. `max_depth_m` and `par_estimate` were DB columns written `None` on
every path since they were created. The `note` distinguishes *"the flood did
not reach here"* from *"this gauge is outside the solver domain"* — completely
different statements that both rendered as an em dash.

Failure reasons are persisted too. A failed run used to show `status: "failed"`
with the cause unrecoverable from any endpoint.

## New endpoints

| Endpoint | Purpose |
| :--- | :--- |
| `GET /runs` | All runs, newest first, with export counts. Backs the run picker — loading a previous run previously meant typing a 32-character hex id. |
| `GET /validation` | The correctness gates as pass/fail plus curves. Cached; `?refresh=true` re-runs. |
| `GET /gee/status` | Earth Engine availability without needing a reach. |

## Dashboard tabs

**2D + 3D** · **Gauges** · **Ensemble** · **Impact** · **SPH** · **Comparison**
· **Validation** · **Downloads**

Panels now stay **mounted** and are hidden with CSS. The previous ternary
unmounted the inactive branch, so every tab click tore down and rebuilt the
Cesium viewer and Leaflet map. That also fixed a pre-existing layout bug: the
Cesium viewer grew without bound (52,748 px against a 557 px viewport) because
flex/grid children default to `min-height: auto`. Now bounded.

### Validation tab

Three gates, run against the live build, mirroring the blocking CI tests
exactly (same seeds, same grids, same thresholds) so the badge and the merge
gate can never disagree:

| Gate | Result |
| :--- | :--- |
| Lake at rest | PASS — 5.98e-14 m/s spurious velocity over random bathymetry, 1000 steps |
| Mass conservation | PASS — 0.000000% volume drift, 1000 steps |
| Ritter dam-break | PASS — JalRaksha RMSE **0.0317 m**, Delft3D FM **0.0349 m** vs the exact solution |

The Ritter chart overlays three curves on a shared axis: exact, JalRaksha, and
the real Deltares kernel. They lie on top of each other — that is the result.

### Impact tab

Every tile carries a real number or states why it does not:

- **Population at risk** — live GHSL census counts. Verified on Tehri: **322 at
  risk of 295,025 in the domain**, split across the three warning-urgency bands.
- **Loss of life** — Graham (USBR DSO-99-06) joined to those bands. Shown as a
  range across all three severity assumptions, never a single number.
- **Hazard classes** — FD2320, coloured from the classifier's own palette so
  the legend cannot drift from the pixels.
- **Buildings** — *"No data source integrated."* There is no building-footprint
  dataset in this build. Google Open Buildings is licence-compatible and is the
  intended source. A count derived from population density would be a number
  invented from another number.
- **Damage** — shown only if computed, and labelled UNVETTED: the asset values
  are fixed constants, not derived from the catchment.

## Earth Engine

Now live. `earthengine authenticate` had already been run; the only thing
missing was the project id.

```
JALRAKSHA_GEE_PROJECT=sih-prototype-506812
```

Set in `scripts/run_api.py` (via `setdefault`, so a real environment variable
still wins) because `.claude/launch.json` has no env field.

**Demo note — this is a feature, not a fault.** For Khadakwasla the SAR fetch
retrieves a real Sentinel-1 scene and then *refuses it*:

> precision 0.486 against JRC Global Surface Water … below the required 0.5.
> 51% of the detected water is not water — over steep terrain, radar shadow in
> VV is indistinguishable from a flat surface by backscatter alone.

That is the quality gate working. Tehri returns a usable mask. **No synthetic
overlay is ever produced** — the earlier spec asked for one; it was not built,
because a labelled synthetic flood layer survives a screenshot badly and the
codebase refuses it by design.

## SPH

`solver="sph"` runs the **full SWE pipeline and then** the near-field handoff —
it is not an alternative solver. The window is ~600 m over 15 s and can never
reach a downstream gauge (`reaches_downstream_gauges` is hardcoded false).

The panel shows the surge-front advance (genuinely time-resolved, recorded every
solver step) and the final particle cloud, decimated to ~2000 points with the
full count stated. PySPH runs with intermediate dumps disabled, so there is one
snapshot and **not** an animation — the panel says so rather than implying
otherwise.

## Offline

Leaflet's stylesheet was a `<link>` to `unpkg.com`. It is now bundled — the map
rendered as unstyled tiles with no zoom control the moment the machine was
offline, in a project whose premise is offline-first.

## Delft3D: working, and what it took

`solver="both"` and `solver="delft3d"` now run the real Deltares kernel and
return genuine gauge arrivals. Measured on Khadakwasla:

| Gauge | Delft3D FM | JalRaksha SWE |
| :--- | ---: | ---: |
| Deccan Gymkhana (10.5 km) | 66.0 min, 8.32 m | 109 min |
| Shivajinagar (12.1 km) | 78.0 min, 5.44 m | — |

Two engines, same dam, same corridor, arrival times of the same order and
visibly different. That is the comparison the tab exists to show.

**Six bugs stood between the kernel and a usable result**, each of which
produced a confidently wrong answer rather than an obvious failure:

1. **`setup.py`'s NetFile was unreadable by D-Flow FM.** It writes a
   `GridType=rectangular` INI where the kernel wants a UGRID mesh, so the run
   failed at mesh load *every time* and silently became the built-in solver
   wearing a Delft3D label. Now uses `dfm_model.py::build_dfm_model`.
2. **The parser looked in the wrong directory.** D-Flow FM writes into
   `DFM_OUTPUT_<name>/`, not beside the `.mdu`. A run that had genuinely
   succeeded was reported as "output could not be parsed" and downgraded.
3. **`gauge_arrivals` was hardcoded `{}`.** The parser read only `*_map.nc`, so
   a SUCCESSFUL kernel run reported no arrivals while the fallback reported a
   full table — the better engine looked like the emptier one. Now reads
   `*_his.nc`.
4. **The pool-finder's direction vector was negated.** `estimate_pool_surface_m`
   names its parameter `upstream_dir` but its body reads `# points downstream`
   and selects the disc opposite to it. Negating sampled the discharge channel
   and the Pune plain instead of the reservoir. Corrected, the pool resolves to
   580.0 m (Khadakwasla) and 814.0 m (Tehri) — exactly what `presets.py` and
   `reservoir.py` record.
5. **`to_dam_config()` never emitted `domain_radius_km`.** Only the HTTP layer
   bolted it on, so every library-side caller ran with no domain cap: a 70 km
   grid against a 27 km DEM, **83.7% NoData**, and a zeroed mesh. Now emitted at
   the source; NoData back to 1.98%.
6. **Dry cells were initialised at bed level.** The kernel derives its bed from
   mesh NODES (`BedlevType=3`) while the array is cell-centred; over rough
   terrain the two disagree by tens of metres, and every cell where the node
   mean fell lower started WET. The kernel reported an initial volume of
   **2.833e10 m³ — 28,330 MCM against an intended 85.3**, conserved, with
   closed boundaries. Dry cells are now set 200 m below bed; initial volume
   comes back as 8.473e7 against 8.53e7 intended.

**Two modelling pieces were missing entirely**, not just wrong:

- **No breach.** The model was a full reservoir behind intact ground. It
  conserved volume perfectly, seeped from 398 to 960 wet cells in an hour, and
  reached nothing. `_cut_breach` now removes the barrier from the pool through
  the dam down to the reservoir floor, at the Von Thun & Gillette (1990) width.
- **Too short a run.** An hour of simulated time cannot reach a gauge the SWE
  side takes 109 minutes to hit, so "no arrival" was the honest answer to the
  wrong question. Matched to the SWE run's 3 h.

**The reservoir initial condition** is built from published figures rather than
read off the DEM, because GLO-30 is a surface model: it samples the water
surface, so `water_level - bed` over a reservoir is zero and filling to the
DEM's own surface impounds nothing. The pool is located as the flat spike it is
(largest connected patch within ±0.5 m of the pool surface — connectivity alone
gives 276 km² across the Pune plain), and the bed beneath it is carved so the
impounded volume equals the published gross storage exactly. Volume governs a
dam-break, so preserving it matters more than matching the FRL surface area —
and those legitimately differ, the DEM having captured the pool below full.

A plausibility guard remains: a reservoir whose mean depth would exceed the dam
height refuses, falls back to the built-in solver, and writes the reason into
`comparison_metrics.json` so the Comparison tab states it rather than showing
an empty panel.

## A flaky test that was a real server defect

`tests/test_api.py::TestSimulateEndpoint` failed in full-suite runs and passed
in isolation — the classic signature of a server that cannot overlap requests,
though it took two attempts to read it that way.

The first fix treated a symptom: `/api/v1/simulate` runs the breach ensemble,
whose Numba kernels take ~22 s to compile on first use and ~0.5 s after, against
a 5 s client timeout. Warming the kernels in the fixture removed the compile
from the timed request and fixed three of the four failures.

The remaining one was the actual defect. `jalraksha/api.py::start_api_server`
used `HTTPServer`, which handles requests **strictly one at a time** on a single
`serve_forever` thread, so any slow handler blocks everything queued behind it.
Under machine load that queueing intermittently exceeded the timeout. Switched
to `ThreadingHTTPServer` with `daemon_threads`:

```
before:  21 passed in 19.87s
after:   21 passed in  2.05s
```

Worth recording because it was never only a test problem: a single-threaded demo
server stalls the same way in front of an audience the moment two requests
overlap.

## Four defects found by driving the dashboard

### Every run showed "running 5%" forever

Two independent causes. `db.update_run_status` was called exactly three times —
5% at the start, 100% at the end, 0% on error — with nothing in between, so
even a perfectly responsive API had nothing to display. `run_dam_break_ensemble`
and `run_ensemble` now take a `progress_cb`; all four of `run_ensemble`'s
completion paths report through one counter, and a `phase` string travels with
the percentage. "running 5%" became "Solving member 12/30".

### The API stalled while any run was in flight

Runs executed on a `threading.Thread` inside uvicorn. A dam-break run is
CPU-bound throughout and holds the GIL — the flux kernels are `@njit` *without*
`nogil=True`, and the delft3d path is pure Python plus PySPH plus matplotlib.
`GET /validation` returned nothing after 120 s.

Runs now execute in a subprocess (`jalraksha_service/run_worker.py`), which has
its own interpreter and its own GIL. Measured while a run was actively solving:

```
/health      HTTP 200 in 0.211s
/dams        HTTP 200 in 0.212s
/runs        HTTP 200 in 0.222s
/validation  HTTP 200 in 0.222s
```

A real Celery broker remains available via `scripts/run_api.py --broker`; it is
not the default because Redis as a demo-day dependency is what `CELERY_EAGER`
exists to avoid.

### Delft3D runs took ~20 minutes

They were not hung. The kernel finished quickly and then the run entered a
14,149-particle PySPH simulation, because `_run_comparison` called
`_run_near_field_sph` unconditionally. SPH is now gated to `solver="both"`.

**A Delft3D run went from ~20 minutes to 47 seconds**, still reporting
`delft3d_binary_used: True` and all seven Pune gauges (Deccan Gymkhana 17.8 min
through Baramati 155.1 min). The Comparison tab states that SPH was *not
requested* rather than implying it failed.

### Validation never completed

The gates ran inside the request handler — two 1000-step solves plus
`compare_ritter`, which launches its own Delft3D kernel. They now run on a
background thread with a disk-persisted cache; the endpoint answers immediately
with `status: running` and the panel polls. Cached responses return in 0.22 s,
and the result survives a restart because the gates are deterministic.

### Also fixed while in there

- **ParaView used the wrong scale for every dam.** `open-paraview` built a fixed
  literal argument list, so both dams rendered at `--exaggeration 1.5` and
  `--depth-max 25.0`. Khadakwasla's preset asks for 2.0 and 18.5 — and with
  1,170 m of relief across 54 km (Tehri: 6,495 m across 120 km) it rendered as a
  near-flat plate, with its 13.4 m flood at 53% of a ramp scaled for 25 m. The
  arguments now come from the run's own preset, plus `--focus-water` so a 6 km²
  inundation in a 54 km box is actually framed. `main.py` was added to the
  `.pvsm` staleness check, without which every cached state would have kept its
  old 1.5x warp and the fix would have looked like it did nothing.
- **The Cesium token could never take effect.** `vite.config.js` read
  `process.env.VITE_*` inside `define`, which sees only the shell environment —
  and because `define` is a literal text substitution, it *overwrote* whatever
  Vite had loaded from `.env.local` with empty strings. Now uses `loadEnv`, with
  `process.env` still winning where set. The Ion nag banner is gone and terrain
  renders. The token lives in `frontend/.env.local`, which is git-ignored (the
  rule was added first, and verified with `git check-ignore`, before the file
  was written).
- **The SAR refusal read as an error.** It is correct behaviour — a real
  Sentinel-1 scene scored 0.486 precision against JRC permanent water and was
  declined — but it rendered as a large orange block over the map. Now a
  one-line badge that expands on click. The wording is unchanged; only the
  prominence.

## Known gaps

- **Cesium 3D terrain needs an Ion access token** (`VITE_CESIUM_ION_TOKEN`).
  Without it the globe renders but shows an Ion warning. Pre-existing.
- **Runs created before this work have no ensemble statistics, no p05/p95 band
  and no peak depth** — those fields did not exist when they were written. They
  render as blanks, correctly. New runs are complete.
- Runs orphaned by an API restart are marked failed at startup; eight were
  stuck at `running` in the demo database.
