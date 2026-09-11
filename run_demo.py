"""
Headless end-to-end demo (no web stack required):

  build domain (Tehri) -> step SWE solver -> snapshot depth at 30 simulation
  times -> export_keyframes() -> real manifest.json + FD2320 PNGs on disk.

This proves the M2/M5 data path actually works on a running simulation.
"""

import numpy as np
from jalraksha.terrain.domain import (
    build_domain, compute_breach_location, compute_utm_zone, latlon_to_utm,
)
from jalraksha.solver.core import SWESolver
from jalraksha.impact.hazard import HazardClassifier
from jalraksha.export.keyframes import export_keyframes

cfg = {
    "name": "Tehri", "lat": 30.3789, "lon": 78.4789, "height_m": 260.0,
    "storage_mm3": 3540.0, "dam_type": "embankment", "failure_mode": "overtopping",
    "breach_bottom_elev_m": 30.0, "initial_surface_elev_m": 260.0,
}

grid, state, manning = build_domain(
    cfg, "data/dem/mosaic_30.38_78.48.tif", target_resolution=200.0
)

# Anchor the (synthetic) grid's metric origin at the real Tehri UTM coordinate
# so the keyframe bounds reproject to the correct WGS84 location. Use pyproj for
# a correct UTM easting/northing (latlon_to_utm is only a crude approximation).
from pyproj import Transformer
utm = compute_utm_zone(cfg["lat"], cfg["lon"])
east, north = Transformer.from_crs("EPSG:4326", f"EPSG:326{utm}", always_xy=True).transform(
    cfg["lon"], cfg["lat"]
)
grid.x0 = east - grid.nx * grid.dx / 2.0
grid.y0 = north + grid.ny * grid.dy / 2.0
grid.crs = f"EPSG:326{utm}"

solver = SWESolver(grid, manning_n=float(np.mean(manning)), cfl=0.9)
state = state.copy()
dt = solver.compute_cfl_timestep(state)

N_KEY = 30
T_END = 600.0  # seconds of simulation to capture
target_times = np.linspace(0.0, T_END, N_KEY)
snaps, next_idx = [], 0
t = 0.0
max_steps = 4000
for step in range(max_steps):
    state = solver.step(state)
    t += dt
    dt = solver.compute_cfl_timestep(state)
    while next_idx < len(target_times) and t >= target_times[next_idx]:
        snaps.append({"time_s": float(t), "depth": state.h.copy()})
        next_idx += 1
    if next_idx >= len(target_times):
        break

print(f"captured {len(snaps)} depth snapshots up to t={t:.1f}s; finite={bool(np.all(np.isfinite(state.h)))}")

result = {
    "dam_name": cfg["name"],
    "grid": {
        "nx": grid.nx, "ny": grid.ny, "dx": grid.dx, "dy": grid.dy,
        "x0": grid.x0, "y0": grid.y0, "crs": int(str(grid.crs).split(":")[1]),
    },
    "depth_series": snaps,
}

manifest = export_keyframes(result, HazardClassifier(), n_keyframes=30, out_dir="./data/keyframes/demo")
print(f"manifest written: {len(manifest.keyframes)} keyframes")
print("first keyframe bounds (WGS84):", [round(b, 4) for b in manifest.keyframes[0].bounds])
print("last  keyframe bounds (WGS84):", [round(b, 4) for b in manifest.keyframes[-1].bounds])
print("manifest json:", ("./data/keyframes/demo/manifest.json"))
