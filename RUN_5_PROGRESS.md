# Run #5: 40-Member Khadakwasla GPU Ensemble (500×400 km, 500 m, 96 h)

## Execution Details

**Launch:** 2026-09-15, ~13:19 UTC
**Run ID at launch:** `324083cc8860488a8ada543dd27aae59` — **this launch did not complete.**
The run database records it `failed`, with the reason *"Orphaned: no live worker process
for this run when the API started, and it was still marked running."*
**The run that actually completed from this launch is
`81e0578bf94b47e98e74cc2c8da84f1b`, started 2026-09-15 16:45 UTC.** A second run on the
same domain, `bf0839d4af234b56b20612b43d3db413`, completed on 2026-09-18 with `solver="swe"`.
Both are recorded under *Completed runs* below.
**Log:** `data/runs/khadakwasla_gpu_500x400_500m_96h_40m.log`
**PID (of the orphaned launch):** 25068

## Configuration

| Parameter | Value |
|-----------|-------|
| Domain | 500 × 400 km |
| Resolution | 500 m cells |
| Grid | 1000 × 800 = 800,000 cells |
| Members | 40 (CUDA GPU, chunked at ~10/batch) |
| Solver | SWE + near-field SPH |
| Backend | CUDA (RTX 4050) |
| Duration | 96 hours (345,600 s) |
| SPH window | 1.5 km, 150,000 particles |
| Snapshots | 60 keyframes |

## Progress snapshot taken while the run was live

> Kept as the launch record. All six steps have since completed — see *Completed runs*.

### ✓ Completed

1. **Terrain domain** (Step 1)
   - DEM loaded: `dem_18.44_73.77_clipped.tif`
   - Cells filled: 3,731 (0.47% nodata)
   - Depression fill: 50,405 cells raised (max 3.0 m)
   - Bed elevation: 0.0–1504.4 m (mean 512.5 m)
   - Injection at Khadakwasla: 566.5 m crest → 562.0 m invert (39.6 m breach)

2. **Breach ensemble** (Step 2, Phase 3)
   - All 40 members generated ✓
   - Q_peak median: 12,080 m³/s
   - Range: 8,234–37,764 m³/s (5th–95th)
   - Regressions: Costa 1985, Froehlich 1995, Macdonald–Langridge 1984, Von Thun–Gillette 1990

### ⏳ In Progress

3. **Ensemble solve** (Step 3)
   - 40 members solving on GPU CUDA backend
   - Expected chunking: ~10 members per VRAM batch
   - Estimated for this step: 2–4 h (depends on GPU utilization)

### ⏱️ Pending

4. **Near-field SPH** (Step 4, Phase 7)
   - Near-dam violent dynamics over 1.5 km window
   - 150,000 particles

5. **Keyframe export** (Step 5)
   - 60 time-tagged keyframes (auto-warped to EPSG:4326 + EPSG:3857)
   - Hazard classification (FD2320)
   - Manifest with `overlay_warped: true`

6. **Impact analysis** (Step 6, Phase 9)
   - Population at risk (GHSL)
   - Damage (built-up exposure)
   - Arrival times at 6 downstream gauges

## Expected outputs at launch — predictions, not results

> **Everything in this block was written before the run finished and is kept only as the
> launch record. The volume-balance prediction below did not hold.** See *Completed runs*
> for what was measured.

### Volume Balance (critical validation)
- **Released:** ~85 MCM (Khadakwasla storage)
- **Exited:** >80 MCM (96.4% like `e2e09ea3`)
- **Retained:** <5 MCM (3.6% like `e2e09ea3`)
- **Closure:** <0.01% (mass conservation)

### Hazard Summary (FD2320, 40-member consensus)
- LOW / MODERATE / SIGNIFICANT / EXTREME cells
- Counts aggregated across all 40 members
- Per-member variability measured (p05, p50, p95)

### Gauge Arrivals (6 locations, 40-member bands)
1. **Deccan Gymkhana** (close)
2. **Swargate** (Pune urban)
3. **Shivajinagar** (Pune urban)
4. **Hadapsar** (eastern fringe)
5. **Magarpatta City** (eastern fringe)
6. **Loni Kalbhor** (far downstream)

Per gauge: arrival time distribution (p05, p50, p95), peak depth (median + band)

### Keyframe Manifest
- 60 PNG pairs (4326 + 3857 warped)
- `simulation_info.overlay_warped: true`
- Both `png_url` and `png_url_mercator` present
- Both `bounds` (WGS84) and `bounds_mercator` (WGS84 in Mercator) present

### Run Summary
- `status: "done"` (all members converged, no failures)
- `solver_backend: "cuda"`
- Grid: 1000 × 800 @ 500 m
- Volume balance: released, exited, retained, closure
- 40-member arrival table + hazard counts

## Verification checklist written at launch (predictions)

> The second item — ">80 MCM exited, <5 MCM retained" — was not met, and was never going
> to be on a domain this size. See *Completed runs*.

- [ ] Log contains "status: done" and "40 of 40 members converged"
- [ ] Volume balance shows >80 MCM exited, <5 MCM retained
- [ ] Keyframe manifest has `overlay_warped: true`
- [ ] Both `*_4326.png` and `*_3857.png` keyframes exist
- [ ] Dashboard loads run and Map2D renders flood on Bhima/Mutha channels
- [ ] Arrival times at gauges show 40-member bands (p05, p50, p95)
- [ ] Final hazard counts follow FD2320 classification
- [ ] Screenshot confirms flood band alignment with terrain

## Completed runs — measured

Two runs completed on this domain configuration: Khadakwasla, **1,000 x 800 cells at
500 m = 500 x 400 km**, **96 h of simulated flood time**, **40 members**, GPU CUDA float64
on an RTX 4050 laptop GPU.

| Run | Solver | Wall-clock compute time | Exports |
| :--- | :--- | ---: | ---: |
| `81e0578bf94b47e98e74cc2c8da84f1b` (15 Sep) | `both` (SWE + near-field SPH) | **28,007 s = 7 h 47 min** | 24 export rows |
| `bf0839d4af234b56b20612b43d3db413` (18 Sep) | SWE only | **28,950 s = 8 h 2 min** (solve 28,873 s) | 23 export rows, 18 export products |

Identical volume balance on both, median of 40 members:

> released **85.259 MCM** - exited **0.000 MCM (0.0 %)** - retained **85.259 MCM (100 %)** -
> closure **0.000 %**

**These runs do not test drainage.** No water left the domain, because the flood front did
not reach a boundary. On a 500 x 400 km box the flood is contained by its own released
volume, so `safe_at` and `fully_green_at` are both null and 100 % retained is the expected,
correct result. It is **not** the drainage defect that was fixed on 6 September, and it is
**not** a demonstration that drainage works. The launch prediction of ">80 MCM exited" did
not happen and could not have.

Final hazard cell counts at 96 h of simulated time, both runs: **210 low - 119 moderate -
59 significant - 13 extreme**, 401 wet cells out of 800,000, wet severity 0.247.

From the SWE-only run (`bf0839d4`):

- Gauge arrivals in simulated time (median, p05-p95): **Deccan Gymkhana 119.3 min
  (64.0-139.3)**, **Shivajinagar 151.9 min (85.1-176.2)**, **Loni Kalbhor 430.1 min
  (344.3-474.5)**. Swargate, Hadapsar and Magarpatta City record **no arrival** within the
  96 h simulated.
- Max depth median **9.75 m**, p95 **14.57 m**; max speed median **5.55 m/s**.
- **Roughness was uniform, n = 0.03 — not land-cover derived** (`roughness.is_uniform` in
  the run summary). Every impact figure from this run inherits that.
- The live ESA WorldCover cropland fetch failed (HTTP 400) and **no land cover was
  synthesised** — the refusal behaviour working as designed.

## The drainage run is a different run, on a different domain

The figures 85.31 MCM released / 82.22 MCM exited (96.4 %) / 3.09 MCM retained (3.6 %) /
safe at 9.44 h belong to **`e2e09ea3201d4d42b7a7dbcd5fac4b81`**, measured on the
**28 x 26 km exit domain at 200 m, 6 members, 30 h of simulated time, 2,739.7 s wall-clock
compute**. An earlier version of this file credited them to `044fa3e3` on the
500 x 400 km domain. That was wrong and is corrected here.

| | `e2e09ea3` (drainage run) | `81e0578b` / `bf0839d4` (this domain) |
| :--- | :--- | :--- |
| Domain | 28 x 26 km exit domain | 500 x 400 km |
| Resolution | 200 m | 500 m |
| Members | 6 | 40 |
| Simulated time | 30 h | 96 h |
| Wall-clock compute | 2,739.7 s | 28,007 s / 28,950 s |
| Released | 85.314 MCM | 85.259 MCM |
| Exited | 82.219 MCM (96.4 %) | 0.000 MCM (0.0 %) |
| Retained | 3.090 MCM (3.6 %) | 85.259 MCM (100 %) |
| Closure | 0.007 % | 0.000 % |
| `safe_at_s` | 33,977.7 s (9.44 h simulated) | null |
| `fully_green_at_s` | null (201 cells wet at 30 h) | null |

Three qualifications travel with the `e2e09ea3` figures and are not optional:

1. It deliberately clips the study area — 82 MCM crossed the eastern edge and is
   downstream and unmodelled. That is the "exits at ~26 km on the east side of a narrow
   exit domain" note; it describes this run, not the 500 x 400 km runs.
2. Four variables changed at once against the plateaued runs, so only the volume balance
   is cleanly attributable.
3. Hadapsar and Magarpatta City are boundary-contaminated at 3.0 km from the outflow edge.

`044fa3e3` is a real run — 500 x 400 km, 500 m, completed 2026-09-14 — but no figures are
quoted for it here, because none have been verified against `docs/validation_findings.md`.

## Notes

- SPH runs only on the breach-adjacent window, not the whole domain
- Keyframes are automatically warped on export (no backfill step needed)
- GPU chunking is transparent to the user; progress is reported per member
- The launch estimate of ~8 h total wall-clock compute was close: 7 h 47 min for the
  `both` run and 8 h 2 min for the SWE-only run
