import numpy as np
from jalraksha.terrain.domain import (
    build_domain, compute_breach_location, compute_utm_zone,
)
from jalraksha.solver.core import SWESolver

cfg = {
    "name": "Tehri", "lat": 30.3789, "lon": 78.4789, "height_m": 260.0,
    "storage_mm3": 3540.0, "dam_type": "embankment", "failure_mode": "overtopping",
    "breach_bottom_elev_m": 30.0, "initial_surface_elev_m": 260.0,
}

grid, state, manning = build_domain(
    cfg, "data/dem/mosaic_30.38_78.48.tif", target_resolution=200.0
)
print("DOMAIN OK:", grid.nx, "x", grid.ny, "dx=", grid.dx, "crs=", grid.crs)

utm = compute_utm_zone(cfg["lat"], cfg["lon"])
i, b, jb = compute_breach_location(state, grid, cfg["lat"], cfg["lon"], utm)
print("breach cell:", i, jb)

solver = SWESolver(grid, manning_n=float(np.mean(manning)), cfl=0.9)
print("CFL dt:", round(solver.compute_cfl_timestep(state), 3), "s")

state = state.copy()
t = 0.0
dt = solver.compute_cfl_timestep(state)
maxes = []
for step in range(40):
    state = solver.step(state)
    t += dt
    maxes.append(float(np.nanmax(state.h)))
print("max depth over 40 steps:", [round(m, 3) for m in maxes[:5]], "...", round(maxes[-1], 3))
print("finite?", bool(np.all(np.isfinite(state.h))), "wet cells:", int(np.sum(state.h > 0.1)))
