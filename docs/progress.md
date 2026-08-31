# Progress checkpoint — 2026-08-29

Snapshot of what is done, what is running, and what is left, written for
picking the work back up without re-deriving context.

## Servers, verified running

```bash
python scripts/run_api.py          # :8000 — up, /health returns {"status":"ok"}
npm run dev --prefix frontend      # :3000 — dashboard loads
```

Dashboard at http://localhost:3000, checked by reading the live page: dam
picker, breach-mode selector, ensemble/solver controls, the gauge panel, a
`2D + 3D | Downloads | Comparison` tab bar, and a live SAR banner reading
*"No observed SAR extent... precision 0.010 against JRC Global Surface Water
... below the required 0.5. No mask is produced for this reach"* — the Tehri
gorge refusal from finding #2 below, rendering correctly end-to-end.

## What's new since the four-part wire-up (Parts 1–4, complete)

A Delft3D FM validation harness was added on top of the finished Parts 1–4
system (exports, honest engine labelling, real PySPH, live GEE):

- **`jalraksha/delft3d/ugrid.py`** — real UGRID-1.0 mesh writer. The previous
  `NetFile` was an INI stub the FM kernel could not read; this was the
  blocking defect.
- **`jalraksha/delft3d/dfm_model.py`** — full D-Flow FM input set (`_net.nc`,
  `.mdu`, initial-field samples, observation points, `dimr_config.xml`).
- **`jalraksha/delft3d/runner.py`** — finds `dflowfm-cli.exe` (previously only
  looked for `dflowfm`), auto-discovers Deltares installs, sets the kernel's
  own `PATH` (`share`, `lib`) before invoking it.
- **`jalraksha/validation/delft3d_benchmark.py`** + **`scripts/validate_against_delft3d.py`**
  — runs the Ritter dam-break through both JalRaksha and a real Delft3D FM
  kernel, scores both against the exact analytical solution, plots a
  three-curve comparison figure.
- **CLAUDE.md** — the "never claim Delft3D" rule is now conditional on
  `delft3d_binary_used`: real kernel run → named as Delft3D FM with its build;
  fallback → unchanged "Delft3D-class, NOT Delft3D FM" language.
- **`ControlPanel.jsx`** — gauge list now reads `result.gauges[].arrival_time_s`
  from a loaded run, falling back to the static reference list only when no
  run is loaded.
- **`docs/validation_findings.md`** — the measured numbers below, plus an
  explicit "Not verified" section.

### Measured result — the SIH slide

Ritter (1892) dry-bed dam-break, h₀ = 10 m, t = 40 s, Δx = 10 m, scored
against theory, 3 boundary cells trimmed each end (see finding below):

| | RMSE vs exact | depth at dam |
|---|---:|---:|
| JalRaksha 2D SWE | 0.0317 m | 4.532 m |
| Delft3D FM | 0.0349 m | 4.515 m |
| exact (4h₀/9) | — | 4.444 m |

Engine-vs-engine: 0.0294 m RMSE. Figure: `data/validation/ritter_validation.png`.

Reproduce: `python scripts/validate_against_delft3d.py --case ritter`

### Two findings worth remembering

1. **The first Ritter numbers were wrong** (JalRaksha 0.0445 vs Delft3D 0.0897,
   Delft3D looking twice as bad) — an outermost-cell accumulation artifact in
   the closed D-Flow FM domain, not a real solver difference. Now trimmed and
   shaded on the figure.
2. **Tehri refuses to run**, on purpose. An axis-aligned dam row is a poor
   stand-in for a barrier across a winding Himalayan valley — it put a
   downstream gauge inside the "reservoir." The connected-fill fix then found
   no connected volume at all. `compare_tehri` raises
   `BenchmarkUnavailableError` with that reason rather than comparing two
   models of still water. Not fixed; the fix is locating the barrier along the
   real impoundment.

Test suite: **435 passed, 4 skipped** (Delft3D + GEE-dependent tests skip
cleanly without those installs).

## Dashboard integration — DONE (2026-08-29)

Everything listed here as outstanding on 2026-08-28 has since been built. Full
record in `docs/dashboard_integration.md`; the short version:

- **Eight tabs**, all showing real data: 2D+3D · Gauges · Ensemble · Impact ·
  SPH · Comparison · Validation · Downloads. Panels stay MOUNTED and hide with
  CSS, so switching tabs no longer tears down the Cesium viewer and Leaflet map.
- **`hazard_summary` and `breach_stats` are rendered.** They are persisted as a
  `run_summary.json` export and served on `RunResult`, with a hazard legend on
  the map and an Ensemble tab showing the q_peak band, breach formation time,
  regressions used and members converged.
- **Validation tab** runs the blocking gates against the live build: lake at
  rest 5.98e-14 m/s, mass conservation 0.000000%, Ritter RMSE 0.0317 m
  (JalRaksha) vs 0.0349 m (Delft3D FM), with all three curves on one axis.
- **Impact tab** — live GHSL population at risk, Graham loss-of-life ranges,
  FD2320 hazard classes, and explicit "no data source integrated" cards where
  there genuinely is none (buildings).
- **Run picker** (`GET /runs`) replaces typing a 32-character hex id.
- **Earth Engine is live** — `JALRAKSHA_GEE_PROJECT=sih-prototype-506812`, set
  in `scripts/run_api.py`.
- **Delft3D FM genuinely runs** and returns real gauge arrivals from `_his.nc`.

## Defects found by driving the dashboard — FIXED (2026-08-29)

Four problems surfaced only by using the thing end to end. All four are fixed;
`docs/dashboard_integration.md` carries the full diagnosis of each.

| Symptom | Cause | Now |
| :--- | :--- | :--- |
| Every run stuck at "running 5%" | Status written 3 times total, none in between | Phase + percentage, e.g. "Solving member 12/30" |
| API stalled during any run | Task ran on a thread inside uvicorn, holding the GIL | Subprocess; endpoints answer in 0.21 s while solving |
| Delft3D runs took ~20 min | `_run_comparison` always ran a 14,149-particle PySPH sim | SPH gated to `solver="both"`; a Delft3D run is **47 s** |
| Validation never returned | Gates ran inside the request, launching a Delft3D kernel | Background thread + disk cache; 0.22 s cached |

Plus: ParaView now uses each dam's own `vertical_exaggeration` /
`nominal_depth_m` (both dams were hardcoded to 1.5 / 25.0); the Cesium Ion
token now actually takes effect (`vite.config.js` read `process.env` inside
`define`, which overwrote what Vite loaded from `.env.local` with empty
strings); and the SAR refusal is a collapsible badge rather than a large orange
block.

## Still open

- **Cesium Ion token lives in `frontend/.env.local`**, which is git-ignored.
  A fresh clone needs it re-created or the globe falls back to Cesium's default
  token with no terrain.
- **Delft3D reaches only the nearest gauges** in a 3 h run (Deccan Gymkhana
  17.8 min through Baramati 155.1 min at 30 min simulated); longer corridors
  need longer runs, same as the SWE side.
- **Breach width uses Von Thun & Gillette**, an EMBANKMENT fit, applied to a
  masonry gravity dam. Flagged wherever the ensemble is reported
  (`dam_class_outside_fitted_population`), not silently absorbed.
- **Khadakwasla's structural figures are UNVETTED** — 39.6 m / 85.31 MCM /
  14.72 km2 from a secondary review, not a primary CWC/NRLD register entry.
  Tagged in `jalraksha/presets.py` and pinned by a test so the tag cannot be
  dropped silently.
- **`prototype specs.md` §17** still has not been appended with the newer
  unvetted coefficients (`ALPHA_VISCOSITY`, `MIN_TILE_SEPARABILITY`,
  `MIN_JRC_PRECISION`, `WARNING_LEAD_TIME_S`, Ritter celerity factor).
- **`.coverage` is tracked** and is a test artifact; `node_modules/` is tracked
  deliberately (offline-first vendoring), which is why dependency changes show
  as thousands of modified files.

## Next step, if resuming

Rehearse the full demo script end to end and screenshot each tab — the one
thing not yet done is running the twelve-step judge walkthrough start to
finish on a quiet machine. After that, pre-bake a clean set of demo runs (one
good SWE run per dam) and prune the 29 accumulated test runs from the picker.
