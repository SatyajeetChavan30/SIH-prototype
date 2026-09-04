# Progress checkpoint — 2026-09-04

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

Test suite at the time of this section: **435 passed, 4 skipped** (Delft3D + GEE-dependent tests skip
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

## River blockage + observation-conditioned DEM update — DONE (2026-09-03)

The second half of PS-26161: natural dam / lake formations, not just dam
failures. Full record in CLAUDE.md; measurements in `validation_findings.md`
§5–7; dashboard changes in `dashboard_integration.md`.

**Four new library modules**, all respecting the phase-dependency rule:

| Module | Phase | Does |
| :--- | :--- | :--- |
| `terrain/blockage.py` | 2 | Burns the barrier, PROVES it spans the valley, hypsometric fill, stage-storage curve, stability indices. Pure numpy — no I/O, no network |
| `terrain/natural_dam.py` | 3 | Natural-dam regressions and their own wider bands. Sibling of `breach.py`, not part of it: Wahl's bands are embankment fits |
| `terrain/dem_update.py` | 2 | Writes the updated GeoTIFF by delta-add, with provenance. Never imports `gee`, so the offline path has no optional dependency |
| `gee/blockage_detect.py` | 9 | Sentinel-1 new-water detection. Refusal-first, three states, no synthetic path |

**Verified end to end** through the API on the Rishi Ganga: 25 exports,
provenance banner, DEM-update panel with stage-storage chart, downloadable
GeoTIFF + sidecar + lake mask. All blocking gates pass. Suite now at **600 passed, 4 skipped**.

**Five defects found along the way, none introduced by this work:**

1. A tile cache *hit* that did not cover the request — tiles are cached under
   the full tile's URL but hold only some earlier domain's window. Tehri's tile
   answered for a domain 60 km east, then died inside `rasterio.mask`. Now
   re-fetches the **union**, so a tile only ever grows.
2. A square UTM domain needs a clip **√2** wider than its radius. An 18 km
   domain on an 18 km clip ran 11.3% on nearest-neighbour fill and reported a
   lake **2.5× too large**.
3. Any *named* Himalayan site without a corridor silently borrowed **Tehri's
   gauges** — `bhakra`, `idukki` and `hirakud` were equally exposed.
4. A minority arrival reported as consensus, with a contradictory 0.0 m depth
   beside it (the ensemble median of `h_max` over members that never arrived).
5. A steep river mistaken for a hillside town: a 3 km window measures the
   river's own fall, so a point *on* the channel read as 64 m above it.

## Khadakwasla drainage plateau — FIXED (2026-09-03)

A 24 h Khadakwasla run on the old 27 km dam-centred domain (54 x 54 km) did not
recede. The hazard classification peaked at t ~ 17,876 s and then **plateaued**:
46 cells stayed SEVERE for the last 7.5 simulated hours, and roughly **42% of the
released volume was permanently trapped**. The same peak time appeared in both a
10-member and a 100-member baseline, so it was structural, not an ensemble
artefact.

Three separate causes, each producing water that had nowhere to go:

| Cause | Fix | Default |
| :--- | :--- | :--- |
| The dam ridge is still intact in the DEM. `inject_breach_hydrograph` only ADDS depth at one cell — a source term with no momentum direction — so the fraction spreading back upstream landed in the real closed reservoir bowl and sat there | `run.py::_notch_breach_into_bed` carves a gap through the crest down to the dam-height invert, clamped never to dig below the local terrain floor just outside the notch | `notch_breach=True` |
| Bilinear downsampling of a narrow channel manufactures spurious local minima along the flow corridor, and the solver's own water pools in them permanently | `terrain/conditioning.py::fill_depressions` — priority-flood seeded from the domain boundary (the only place the transmissive boundary lets water exit), with the raise per cell capped so genuine basins survive | `fill_max_depth_m=3.0` |
| A dam-centred square spends half its cells on the Western Ghats and the Arabian Sea, and the flood has no downstream to drain into | `load_dem_as_grid(margins_km=...)`, exposed as `RunRequest.domain_margins_km`, gives an asymmetric rectangle biased downstream | none — per-request override only |

**The notch is not a hole in an intact wall.** The invert is the crest elevation
at the breach cell minus `dam_config["height_m"]` — the one breach-geometry
number every hydrograph member carries, and the value Froehlich / Von Thun-style
regressions assume for a full-depth breach. Dam height is a fixed ensemble input,
not sampled per member, so there is one notch geometry shared by the whole
ensemble, exactly like the terrain.

**The depression fill is deliberately not "fill everything to guarantee
drainage."** It computes the full hydrological fill, then caps the raise actually
applied at the threshold. A one- or two-metre pit (resampling noise) fills
completely; a real reservoir bowl keeps standing at very nearly its original
depth, because only its top 3 m is touched. Erasing genuine terrain to make the
water leave would have hidden the same defect behind a nicer graph.

**Preset defaults are unchanged.** `domain_margins_km` was used as a per-request
override for this investigation, not written into
`jalraksha/presets.py::khadakwasla`. Every default Khadakwasla run, the dashboard
demo included, still gets the same 27 km dam-centred square. The cached DEM at
`data/dem/dem_18.44_73.77_clipped.tif` was widened to 240 x 188 km (40 km west /
200 km east / 94 km north and south) to support the wider domain; it is a
superset of the old 57 x 56 km clip, so nothing that worked before stopped
working, and `test_domain_radius_does_not_exceed_the_cached_dem` still passes
with much more headroom.

Covered by `tests/test_terrain.py`:
`test_fill_depressions_shallow_filled_deep_preserved`,
`test_fill_depressions_unrestricted_removes_all_local_minima`,
`test_notch_breach_lowers_bed_and_respects_local_floor`.

**The confirmation run has not completed.** `scripts/run_khadakwasla_drainage_check.py`
exercises all three fixes together — 240 x 188 km at 300 m, 24 h, 4 members — and
writes a compact hazard time-series to
`data/keyframes/khadakwasla_drainage_check/hazard_series.json`. That file does
not exist yet, so the plateau is **fixed in mechanism but not yet re-measured**.
The script exists rather than a `POST /runs` because an API-submitted run
executes in a subprocess spawned by the server and dies with it — that happened
three times in one session, each time silently discarding hours of compute,
because `run_ensemble` returns every member at once and writes nothing
per-member. The script is nobody's child and survives the server coming and
going.

## Untracked working files

Two files are present but not committed:

- **`scripts/run_khadakwasla_drainage_check.py`** — the standalone verification
  run described above.
- **`JalRaksha_MultiHazard_Workflow.drawio`** — an editable draw.io flowchart of
  the full multi-hazard pipeline: satellite monitoring feedback loop, hazard-type
  branch (dam breach / river blockage), breach-mode and near-field/far-field
  splits, validation gate, export engine, storage. Legend marks the satellite and
  river-blockage lanes as new. Not referenced by any code or doc yet.

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
- **Rishi Ganga has no quantitative benchmark yet.** The published HEC-RAS
  figures need **channel** coordinates for Rishiganga and Tapovan; the gazetteer
  town centres sit 1,319 m and 79 m above the nearest channel and were removed.
  Source those and the blockage path gains a real validation case
  (literature.md §11.2, verification queue row 26).
- **Walder & O'Connor (1997) and Peng & Zhang (2012) are untranscribed** and
  quarantined. Costa (1985) is the only active natural-dam regression, so a
  blockage ensemble has no inter-method spread and takes its range from a
  prediction band whose width is itself a placeholder (queue rows 19–22).
- **Blockage runs are expensive on steep terrain.** The CFL limit cuts the
  timestep as a deep release accelerates down a gorge: 55 m / 0.6 MCM solved
  4 members in ~15 min at 100 m, the 120 m / 26 MCM case took ~40. Pre-compute
  anything large before a live demo.
- **The Khadakwasla drainage fix is unmeasured.** All three mechanisms are
  implemented, defaulted on and unit-tested, but the 24 h confirmation run has
  not finished, so there is no post-fix hazard curve to put beside the plateaued
  one. Run `python scripts/run_khadakwasla_drainage_check.py` and compare
  `hazard_series.json` against the ~46 stuck SEVERE cells.
- **A wide downstream domain is expensive.** The verification run is 240 x 188 km
  at 300 m — 800 x 627 cells — for 24 simulated hours across 4 members. Budget
  hours, not minutes, and do not start it during a demo.
- **Verification-only launch entries** (`api-verify` on :8010,
  `frontend-verify` on :3010) and the git-ignored `frontend/.env.verify.local`
  exist so the dashboard can be driven without colliding with a dev API on
  :8000. Harmless; delete if unwanted.

## Next step, if resuming

Finish the Khadakwasla drainage measurement — `python
scripts/run_khadakwasla_drainage_check.py`, then read
`data/keyframes/khadakwasla_drainage_check/hazard_series.json` and confirm the
severe-cell count actually falls after the t ~ 17,876 s peak instead of holding
at 46. That is the one open loop with a number attached to it.

Then rehearse the full demo script end to end and screenshot each tab — the
twelve-step judge walkthrough has still never been run start to finish on a
quiet machine. After that, pre-bake a clean set of demo runs (one good SWE run
per dam) and prune the 29 accumulated test runs from the picker.
