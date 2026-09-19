# Run #5: 40-Member Khadakwasla GPU Ensemble (500×400 km, 500 m, 96 h)

## Execution Details

**Launch:** 2026-09-15, ~13:19 UTC  
**Run ID:** 324083cc8860488a8ada543dd27aae59  
**Log:** `data/runs/khadakwasla_gpu_500x400_500m_96h_40m.log`  
**PID:** 25068  

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

## Progress (Real-time)

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

## Expected Outputs (on completion)

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

## Verification Checklist (post-completion)

- [ ] Log contains "status: done" and "40 of 40 members converged"
- [ ] Volume balance shows >80 MCM exited, <5 MCM retained
- [ ] Keyframe manifest has `overlay_warped: true`
- [ ] Both `*_4326.png` and `*_3857.png` keyframes exist
- [ ] Dashboard loads run and Map2D renders flood on Bhima/Mutha channels
- [ ] Arrival times at gauges show 40-member bands (p05, p50, p95)
- [ ] Final hazard counts follow FD2320 classification
- [ ] Screenshot confirms flood band alignment with terrain

## Comparison to 044fa3e3 (10 members, same domain, 500 m)

| Metric | 044fa3e3 (10m) | Run #5 (40m) |
|--------|---|---|
| Grid | 1000×800 @ 500m | 1000×800 @ 500m |
| Released | 85.31 MCM | ~85 MCM (expected) |
| Exited | 82.22 MCM (96.4%) | >80 MCM (expected) |
| Retained | 3.09 MCM (3.6%) | <5 MCM (expected) |
| Safe at | 9.44 h | TBD |
| Arrival spread | 10 members | 40 members |
| Hazard spread | 10 members | 40 members (tighter consensus) |

## Notes

- Flood confined by released volume (85 MCM), not by boundary—exits at ~26 km on east side of narrow exit domain
- SPH runs only on breach-adjacent 1.5 km window, not whole domain
- Keyframes automatically warped on export (no backfill step needed)
- GPU chunking transparent to user; progress reported per member
- Expected wall time: ~8 h total (4–5 h on ensemble solve, 2–3 h on SPH + export)
