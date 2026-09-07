"""
JalRaksha vs Delft3D FM vs analytical theory (Phase 19).

Runs the SAME dam-break through JalRaksha's own 2D SWE solver and through the
real Deltares D-Flow FM kernel, and — for the Ritter case — against the exact
solution both should reproduce.

WHY THREE CURVES AND NOT TWO. Two codes agreeing tells you they agree. It does
not tell you either is right, and when they disagree it does not tell you which
to believe. The Ritter dry-bed dam-break has a closed-form solution
(Ritter 1892), so plotting it alongside makes the comparison diagnostic rather
than merely reassuring. The Tehri case has no ground truth and is reported
honestly as engine-vs-engine agreement only.

MEASURED, on this machine, with dimrset 2026.01 (dflowfm-cli 1.2.184), on a
10 m dam-break at t = 40 s, dx = 10 m, scored over the interior:

    JalRaksha   vs exact   RMSE 0.0317 m   h@dam 4.532 m
    Delft3D FM  vs exact   RMSE 0.0349 m   h@dam 4.515 m
    engine vs engine       RMSE 0.0294 m
    exact                                  h@dam 4.444 m  (= 4*h0/9)

Both engines land within ~0.3% of theory and within 0.03 m of each other.

References:
  - Ritter, A. (1892) "Die Fortpflanzung der Wasserwellen", VDI Zeitschrift
    36(33):947-954.
  - Deltares (2024) "D-Flow Flexible Mesh User Manual".
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np

GRAVITY = 9.81


class BenchmarkUnavailableError(RuntimeError):
    """The benchmark could not be run — most often, no Delft3D kernel."""


def ritter_exact(x, t: float, h_left: float = 1.0):
    """
    Ritter (1892) exact solution: dry-bed dam-break, frictionless, flat bed.

    Initial condition: h = h_left for x < 0, h = 0 for x > 0, u = 0.

    Three regions, with c0 = sqrt(g*h_left) and xi = x/t:
      1. xi < -c0            undisturbed reservoir, h = h_left, u = 0
      2. -c0 <= xi <= 2*c0   rarefaction fan, u = (2/3)(xi + c0),
                             c = (2*c0 - xi)/3, h = c^2/g
      3. xi > 2*c0           dry bed

    The front advances at 2*c0 and the depth at the dam site is 4*h_left/9.

    Args:
        x: Coordinates (m) with the dam at x = 0.
        t: Time (s), strictly positive.
        h_left: Initial reservoir depth (m).

    Returns:
        (h_exact, u_exact) arrays shaped like x.
    """
    if t <= 0.0:
        raise ValueError("Ritter solution is only defined for t > 0")

    c0 = np.sqrt(GRAVITY * h_left)
    xi = np.asarray(x, dtype=float) / t

    h_exact = np.zeros_like(xi)
    u_exact = np.zeros_like(xi)

    reservoir = xi < -c0
    h_exact[reservoir] = h_left

    fan = (xi >= -c0) & (xi <= 2.0 * c0)
    celerity = (2.0 * c0 - xi[fan]) / 3.0
    h_exact[fan] = celerity * celerity / GRAVITY
    u_exact[fan] = 2.0 * (xi[fan] + c0) / 3.0

    return h_exact, u_exact


def run_ritter_jalraksha(x_centres: np.ndarray, t_end: float,
                         h_left: float, dx: float) -> np.ndarray:
    """JalRaksha's own SWE solver on the Ritter case, sampled at x_centres."""
    from jalraksha.solver.core import SWESolver
    from jalraksha.solver.types import Grid, create_state

    nx = x_centres.size
    grid = Grid(nx=nx, ny=1, dx=dx, dy=dx, x0=float(x_centres[0] - dx / 2.0))
    h_init = np.where(x_centres < 0.0, h_left, 0.0).reshape(1, nx)
    state = create_state(grid, h_init)

    # Frictionless, matching the analytical assumption and the Delft3D setup.
    solver = SWESolver(grid, manning_n=0.0, cfl=0.9)
    return np.asarray(solver.run(state, t_end).state.h).squeeze()


def run_ritter_delft3d(work_dir, x_centres: np.ndarray, t_end: float,
                       h_left: float, dx: float, n_cross: int = 3,
                       dflowfm_path: Optional[str] = None) -> Dict:
    """
    The same Ritter case through the real D-Flow FM kernel.

    The 1D problem is run as a narrow 2D channel, which is how FM represents it;
    the centreline is extracted afterwards.

    Raises:
        BenchmarkUnavailableError: when no kernel is installed, or the run
            fails. Never returns a substitute.
    """
    from jalraksha.delft3d.dfm_model import build_dfm_model
    from jalraksha.delft3d.runner import (
        _run_dflowfm_binary, kernel_environment, resolve_dflowfm,
    )

    executable = resolve_dflowfm(dflowfm_path)
    if executable is None:
        raise BenchmarkUnavailableError(
            "No Delft3D FM kernel found. Set JALRAKSHA_DFLOWFM_EXE to the full "
            "path of dflowfm-cli.exe, or install a Delft3D FM Suite edition "
            "that ships plugins/DeltaShell.Dimr/kernels."
        )

    nx = x_centres.size
    # The model grid starts at x=0 internally; the dam sits mid-domain and the
    # analytical comparison shifts back to dam-at-zero afterwards.
    x_offset = float(x_centres[0] - dx / 2.0)
    grid = {"nx": nx, "ny": n_cross, "dx": dx, "dy": dx, "x0": 0.0, "y0": 0.0}

    bed = np.zeros((n_cross, nx))
    dam_col = int(np.searchsorted(x_centres, 0.0))
    water = bed.copy()
    water[:, :dam_col] = h_left

    model = build_dfm_model(
        output_dir=work_dir, grid_dict=grid, bed_elevation=bed,
        initial_water_level=water, duration_s=t_end, name="ritter",
        manning_n=0.0, crs_epsg=None,
        map_interval_s=max(t_end / 8.0, 1.0),
    )

    started = time.perf_counter()
    run = _run_dflowfm_binary(model["mdu_path"], executable=executable, timeout_s=1800)
    wall_clock = time.perf_counter() - started

    if not run["success"]:
        raise BenchmarkUnavailableError(
            f"Delft3D FM failed on the Ritter case: "
            f"{run.get('error') or run.get('stderr', '')[-400:]}"
        )

    depth, times, face_x = _read_map_centreline(
        Path(model["output_dir"]) / f"DFM_OUTPUT_ritter" / "ritter_map.nc")

    return {
        "depth": depth,                       # [n_time, nx]
        "times": times,
        "x": face_x + x_offset,               # back into dam-at-zero coordinates
        "executable": executable,
        "wall_clock_s": wall_clock,
        "model_dir": str(model["output_dir"]),
    }


def _read_map_centreline(map_path: Path):
    """Depth along the channel centreline from a D-Flow FM `_map.nc`."""
    import netCDF4 as nc

    if not Path(map_path).exists():
        raise BenchmarkUnavailableError(
            f"Delft3D produced no map output at {map_path}."
        )

    ds = nc.Dataset(map_path)
    try:
        times = np.asarray(ds.variables["time"][:], dtype=float)
        depth = np.asarray(ds.variables["mesh2d_waterdepth"][:], dtype=float)
        face_x = np.asarray(ds.variables["mesh2d_face_x"][:], dtype=float)
        face_y = np.asarray(ds.variables["mesh2d_face_y"][:], dtype=float)
    finally:
        ds.close()

    centre = np.isclose(face_y, np.median(face_y))
    order = np.argsort(face_x[centre])
    return depth[:, centre][:, order], times, face_x[centre][order]


#: Cells trimmed from each end before scoring.
#:
#: The outermost cell of a closed D-Flow FM domain accumulates water: measured
#: at 1.06 m on a 2000 m domain and still 0.41 m on 4000 m, while its immediate
#: neighbours sit at 0.001-0.03 m. A broad reflection would grow with a shorter
#: domain and spread over many cells; this does neither, so it is an edge-cell
#: artifact rather than physics. Left in, it alone tripled Delft3D's RMSE
#: against the exact solution and would have made the comparison read as
#: "Delft3D is worse" when the real cause was the boundary.
#:
#: Boundary cells are not part of the interior solution in any finite-volume
#: scheme, so excluding them is standard — but it is done explicitly, reported
#: in the output, and drawn on the figure rather than quietly dropped.
BOUNDARY_MARGIN_CELLS = 3


def compare_ritter(work_dir, h_left: float = 10.0, t_end: float = 40.0,
                   domain_m: float = 4000.0, dx: float = 10.0,
                   dflowfm_path: Optional[str] = None,
                   boundary_margin_cells: int = BOUNDARY_MARGIN_CELLS) -> Dict:
    """
    Run the Ritter dam-break through both engines and score both against theory.

    Args:
        work_dir: Where the Delft3D model is built and run.
        h_left: Reservoir depth (m).
        t_end: Simulated duration (s). The domain must be long enough that the
            front (at 2*t*sqrt(g*h0)) stays well inside it.
        domain_m: Total channel length, centred on the dam.
        dx: Cell size (m), the same for both engines.
        dflowfm_path: Explicit kernel path; auto-discovered when omitted.
        boundary_margin_cells: Cells excluded from scoring at each end — see
            BOUNDARY_MARGIN_CELLS.

    Returns:
        Dict with `x`, `analytical`, `jalraksha`, `delft3d` depth profiles at
        t_end, plus RMSE and max-error for each engine and the provenance of the
        Delft3D run. Scores are computed over the interior only; `scored_mask`
        records which cells counted.
    """
    nx = int(domain_m / dx)
    # Dam at x = 0, domain centred on it.
    x_centres = (np.arange(nx) + 0.5) * dx - domain_m / 2.0

    analytical, _ = ritter_exact(x_centres, t_end, h_left=h_left)
    jalraksha = run_ritter_jalraksha(x_centres, t_end, h_left, dx)

    d3d = run_ritter_delft3d(work_dir, x_centres, t_end, h_left, dx,
                             dflowfm_path=dflowfm_path)
    # Sample the Delft3D profile at the same x as everything else.
    delft3d = np.interp(x_centres, d3d["x"], d3d["depth"][-1])

    # Interior only — see BOUNDARY_MARGIN_CELLS.
    interior = np.zeros(nx, dtype=bool)
    margin = max(int(boundary_margin_cells), 0)
    interior[margin:nx - margin if margin else nx] = True

    def score(predicted):
        error = (predicted - analytical)[interior]
        return {
            "rmse_m": float(np.sqrt(np.mean(error ** 2))),
            "max_abs_error_m": float(np.max(np.abs(error))),
            "depth_at_dam_m": float(predicted[np.argmin(np.abs(x_centres))]),
        }

    return {
        "case": "ritter",
        "h_left_m": h_left,
        "t_end_s": t_end,
        "dx_m": dx,
        "x": x_centres,
        "analytical": analytical,
        "jalraksha": jalraksha,
        "delft3d": delft3d,
        "exact_depth_at_dam_m": 4.0 * h_left / 9.0,
        "front_position_analytical_m": 2.0 * t_end * np.sqrt(GRAVITY * h_left),
        "jalraksha_vs_analytical": score(jalraksha),
        "delft3d_vs_analytical": score(delft3d),
        "engine_agreement": {
            "rmse_m": float(np.sqrt(np.mean(((jalraksha - delft3d)[interior]) ** 2))),
            "max_abs_error_m": float(np.max(np.abs((jalraksha - delft3d)[interior]))),
        },
        "scored_mask": interior,
        "boundary_margin_cells": margin,
        "delft3d_executable": d3d["executable"],
        "delft3d_wall_clock_s": d3d["wall_clock_s"],
    }


# ─── Tehri: real terrain, no ground truth ────────────────────────────────────

#: Depth at which a gauge counts as reached, matching the solver's own arrival
#: threshold (CLAUDE.md / Spec 4.3).
ARRIVAL_THRESHOLD_M = 0.1


def _arrival_from_series(times: np.ndarray, depth: np.ndarray) -> Optional[float]:
    """First time a depth series crosses the arrival threshold, or None."""
    reached = np.nonzero(np.asarray(depth) >= ARRIVAL_THRESHOLD_M)[0]
    return float(times[reached[0]]) if reached.size else None


def _read_his_gauges(his_path: Path) -> Dict[str, Dict]:
    """
    Per-observation-point water depth series from a D-Flow FM `_his.nc`.

    This is why the model writes an observation-point file at all: the history
    output gives depth AT each gauge directly, rather than requiring the map
    file to be searched for a nearest cell. It also replaces the standing
    "TODO: read *_his.nc observation stations for true gauge arrivals" that
    runner._parse_delft3d_output carried while it returned no arrivals at all.
    """
    import netCDF4 as nc

    if not Path(his_path).exists():
        raise BenchmarkUnavailableError(
            f"Delft3D produced no history output at {his_path}; without it "
            f"there are no gauge time series to compare."
        )

    ds = nc.Dataset(his_path)
    try:
        times = np.asarray(ds.variables["time"][:], dtype=float)
        names_var = next((v for v in ("station_name", "station_id")
                          if v in ds.variables), None)
        # The history file records water LEVEL and bed level, not depth — there
        # is no `waterdepth` variable in it, unlike the map file. Depth is the
        # difference, which also keeps dry stations at exactly zero rather than
        # at a negative level-minus-bed.
        if names_var is None or "waterlevel" not in ds.variables:
            raise BenchmarkUnavailableError(
                f"{his_path} has no station names or waterlevel "
                f"(variables present: {sorted(ds.variables)})."
            )

        raw_names = np.asarray(ds.variables[names_var][:])
        names = []
        for row in raw_names:
            text = "".join(c.decode() if isinstance(c, bytes) else str(c)
                           for c in np.atleast_1d(row))
            names.append(text.strip().strip(chr(39)).strip())
        level = np.asarray(ds.variables["waterlevel"][:], dtype=float)
        if "bedlevel" in ds.variables:
            bed = np.asarray(ds.variables["bedlevel"][:], dtype=float)
            # bedlevel is per-station and constant in time; level is [time, station].
            depth = np.maximum(0.0, level - np.atleast_2d(bed))
        else:
            depth = np.maximum(0.0, level)
    finally:
        ds.close()

    return {name: {"times": times, "depth": depth[:, i]}
            for i, name in enumerate(names)}


def compare_tehri(work_dir, dem_path: Optional[str] = None,
                  resolution_m: float = 200.0, domain_radius_km: float = 25.0,
                  duration_s: float = 5400.0,
                  dflowfm_path: Optional[str] = None) -> Dict:
    """
    The Tehri dam-break through both engines, compared at the downstream gauges.

    NO GROUND TRUTH EXISTS for this case, so unlike Ritter it is reported as
    engine-vs-engine agreement only. Disagreement here does not say which
    engine is wrong — that is exactly why the Ritter case is run alongside.

    Gauges outside the modelled domain, or that the flood does not reach within
    the simulated duration, are reported as None rather than extrapolated.

    Raises:
        BenchmarkUnavailableError: if the DEM or the kernel is missing.
    """
    from jalraksha.delft3d.dfm_model import build_dfm_model
    from jalraksha.delft3d.runner import _run_dflowfm_binary, resolve_dflowfm
    from jalraksha.run import define_downstream_gauges
    from jalraksha.solver.core import SWESolver
    from jalraksha.solver.types import create_state
    from jalraksha.terrain.conditioning import load_dem_as_grid
    from jalraksha.terrain.domain import latlon_to_utm

    executable = resolve_dflowfm(dflowfm_path)
    if executable is None:
        raise BenchmarkUnavailableError(
            "No Delft3D FM kernel found; cannot run the Tehri comparison."
        )

    dam_lat, dam_lon, dam_height = 30.3789, 78.4789, 260.0
    if dem_path is None:
        dem_path = str(Path("data") / "dem" / "dem_30.38_78.48_clipped.tif")
    if not Path(dem_path).exists():
        raise BenchmarkUnavailableError(
            f"No Tehri DEM at {dem_path}. Fetch it with jalraksha.dem.fetch_dem first."
        )

    grid_obj, bed = load_dem_as_grid(
        dem_path, dam_lat, dam_lon, target_resolution=resolution_m,
        domain_radius_km=domain_radius_km)
    grid = {"nx": grid_obj.nx, "ny": grid_obj.ny, "dx": grid_obj.dx,
            "dy": grid_obj.dy, "x0": grid_obj.x0, "y0": grid_obj.y0}
    crs_epsg = int(str(grid_obj.crs).rsplit(":", 1)[-1])

    # WHICH SIDE IS THE RESERVOIR? Not simply "rows below ny//2" — that is a
    # compass direction, and the Bhagirathi does not run north. Splitting the
    # domain by array index put Koteshwar (13 km downstream, but SOUTH of the
    # dam) inside the reservoir, so it started wet and both engines reported an
    # arrival time of 0.0 min.
    #
    # The reservoir is the impounded water behind the dam: cells on the UPHILL
    # side whose bed lies below the crest. Uphill is decided from the terrain
    # itself, the same way the near-field SPH domain decides it.
    from jalraksha.sph.pysph_runner import orient_downhill

    _oriented, rotations = orient_downhill(bed)
    dam_row = grid_obj.ny // 2

    # Reservoir surface = VALLEY FLOOR at the dam site + dam height. Taking the
    # median of the dam row instead averages the thalweg together with the
    # ridges either side of it: on a 25 km Himalayan window that put the surface
    # near 1760 m rather than Tehri's ~830 m, impounding several hundred metres
    # of water over half the domain. Delft3D duly reported water levels rising
    # to 1533 m at Koteshwar — the model was not wrong, the initial condition
    # was.
    centre = slice(max(dam_row - 2, 0), dam_row + 3)
    thalweg = float(np.min(bed[centre, :]))
    reservoir_level = thalweg + dam_height

    # rot90 count tells us which edge is upstream; recover an upstream mask in
    # the ORIGINAL orientation rather than rotating the whole model.
    jj, ii = np.mgrid[0:grid_obj.ny, 0:grid_obj.nx]
    upstream = {
        0: jj < dam_row,
        1: ii >= grid_obj.nx // 2,
        2: jj >= dam_row,
        3: ii < grid_obj.nx // 2,
    }[rotations % 4]

    # A HYDRAULICALLY CONNECTED impoundment, not "every upstream cell below the
    # crest". The axis-aligned split is a straight line across a winding
    # Himalayan valley, so it put Koteshwar — 13 km DOWNSTREAM, but on the
    # upstream side of the line and 300 m below the crest — inside the
    # reservoir. It started wet, and both engines dutifully reported an arrival
    # time of zero.
    #
    # The reservoir is instead the set of cells below the crest that are
    # connected to the dam WITHOUT crossing it: the dam row is punched out as a
    # barrier first, so the fill cannot leak into the downstream valley.
    from scipy import ndimage

    below_crest = bed < reservoir_level
    barrier = np.zeros_like(below_crest)
    barrier[max(dam_row - 1, 0):dam_row + 2, :] = True
    fillable = below_crest & ~barrier & upstream

    labels, _count = ndimage.label(fillable)
    # Seed at the deepest fillable cell adjacent to the barrier — the thalweg
    # immediately behind the dam.
    seed_rows = np.where(upstream.any(axis=1))[0]
    seed_row = seed_rows[np.argmin(np.abs(seed_rows - dam_row))] if seed_rows.size else dam_row
    candidates = np.where(fillable[seed_row])[0]
    if candidates.size:
        seed_col = candidates[np.argmin(bed[seed_row, candidates])]
        reservoir_label = labels[seed_row, seed_col]
        impounded = (labels == reservoir_label) if reservoir_label else np.zeros_like(fillable)
    else:
        impounded = np.zeros_like(fillable)

    water = bed.copy()
    water[impounded] = reservoir_level
    impounded_km2 = float(impounded.sum() * grid["dx"] * grid["dy"] / 1e6)

    # An empty impoundment is not a dam break. Refuse rather than run both
    # engines on still water and publish the resulting "arrival times", which
    # would be a comparison of two models of nothing.
    #
    # KNOWN LIMITATION, not a transient bug: the reservoir is seeded from an
    # axis-aligned dam row, and a straight line across a winding Himalayan
    # valley is a poor stand-in for a dam wall. Locating the barrier along the
    # real impoundment (from the DEM, or from the reservoir polygon) is the
    # correct fix and is not implemented. Until it is, this case is expected to
    # refuse on steep sinuous terrain such as Tehri.
    if impounded_km2 <= 0.0:
        raise BenchmarkUnavailableError(
            f"No reservoir could be impounded behind the dam row for this "
            f"domain (crest {reservoir_level:.0f} m, thalweg {thalweg:.0f} m, "
            f"{domain_radius_km:.0f} km radius at {resolution_m:.0f} m). The "
            f"axis-aligned dam row does not follow the real valley, so there is "
            f"no connected volume behind it. No comparison is produced — see "
            f"compare_tehri's KNOWN LIMITATION note."
        )

    # Gauges, projected into the DOMAIN's UTM zone rather than each gauge's own
    # — mixing zones is what once put Rishikesh hundreds of km from the river.
    zone = crs_epsg % 100
    gauges = []
    for gauge in define_downstream_gauges(dam_lat, dam_lon):
        _, easting, northing = latlon_to_utm(gauge["lat"], gauge["lon"], utm_zone=zone)
        inside = (grid["x0"] <= easting <= grid["x0"] + grid["nx"] * grid["dx"]
                  and grid["y0"] <= northing <= grid["y0"] + grid["ny"] * grid["dy"])
        gauges.append({**gauge, "x": easting, "y": northing, "inside_domain": inside})

    # --- JalRaksha -----------------------------------------------------------
    depth_init = np.maximum(0.0, water - bed)
    state = create_state(grid_obj, depth_init.astype(np.float64), b_init=bed)
    solver = SWESolver(grid_obj, manning_n=0.03, cfl=0.3)

    t_arrival = np.full((grid_obj.ny, grid_obj.nx), np.inf)
    t_sim, steps = 0.0, 0
    dt = solver.compute_cfl_timestep(state)
    while t_sim < duration_s and steps < 2_000_000:
        state = solver.step(state)
        t_sim += dt
        dt = solver.compute_cfl_timestep(state)
        newly_wet = (state.h >= ARRIVAL_THRESHOLD_M) & np.isinf(t_arrival)
        t_arrival[newly_wet] = t_sim
        steps += 1

    # --- Delft3D FM ----------------------------------------------------------
    observation = [{"name": g["name"], "x": g["x"], "y": g["y"]}
                   for g in gauges if g["inside_domain"]]
    model = build_dfm_model(
        output_dir=work_dir, grid_dict=grid, bed_elevation=bed,
        initial_water_level=water, duration_s=duration_s, name="tehri",
        manning_n=0.03, crs_epsg=crs_epsg, observation_points=observation,
        map_interval_s=max(duration_s / 60.0, 30.0))

    started = time.perf_counter()
    run = _run_dflowfm_binary(model["mdu_path"], executable=executable, timeout_s=7200)
    wall_clock = time.perf_counter() - started
    if not run["success"]:
        raise BenchmarkUnavailableError(
            "Delft3D FM failed on the Tehri case: "
            + str(run.get("error") or (run.get("stdout") or "")[-500:]))

    series = _read_his_gauges(
        Path(model["output_dir"]) / "DFM_OUTPUT_tehri" / "tehri_his.nc")

    rows = []
    for gauge in gauges:
        jr = None
        if gauge["inside_domain"]:
            i = min(max(int(round((gauge["x"] - grid["x0"]) / grid["dx"])), 0),
                    grid["nx"] - 1)
            j = min(max(int(round((gauge["y"] - grid["y0"]) / grid["dy"])), 0),
                    grid["ny"] - 1)
            value = t_arrival[j, i]
            jr = None if np.isinf(value) else float(value)

        match = series.get(gauge["name"])
        d3 = _arrival_from_series(match["times"], match["depth"]) if match else None

        rows.append({
            "name": gauge["name"],
            "distance_km": gauge["distance_km"],
            "inside_domain": gauge["inside_domain"],
            "jalraksha_arrival_s": jr,
            "delft3d_arrival_s": d3,
            "delta_s": (jr - d3) if (jr is not None and d3 is not None) else None,
        })

    return {
        "case": "tehri",
        "note": ("No ground truth exists for this case. Figures show "
                 "engine-vs-engine agreement, not accuracy."),
        "resolution_m": resolution_m,
        "domain_radius_km": domain_radius_km,
        "duration_s": duration_s,
        "reservoir_level_m": reservoir_level,
        "thalweg_elevation_m": thalweg,
        "impounded_area_km2": impounded_km2,
        "gauges": rows,
        "delft3d_executable": executable,
        "delft3d_wall_clock_s": wall_clock,
    }


def plot_tehri_gauges(result: Dict, out_path) -> Path:
    """Arrival time per gauge, both engines side by side."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    rows = result["gauges"]
    positions = np.arange(len(rows))

    def minutes(value):
        return (value / 60.0) if value is not None else np.nan

    fig, ax = plt.subplots(figsize=(10, 5.5))
    ax.bar(positions - 0.2, [minutes(r["jalraksha_arrival_s"]) for r in rows],
           width=0.4, color="#1565C0", label="JalRaksha 2D SWE")
    ax.bar(positions + 0.2, [minutes(r["delft3d_arrival_s"]) for r in rows],
           width=0.4, color="#E53935", label="Delft3D FM")

    for k, row in enumerate(rows):
        if row["jalraksha_arrival_s"] is None and row["delft3d_arrival_s"] is None:
            reason = ("outside modelled domain" if not row["inside_domain"]
                      else "flood did not reach it")
            ax.text(k, 0.4, "not reached\n(" + reason + ")", ha="center",
                    va="bottom", fontsize=8, color="#7a3e00")

    ax.set_xticks(positions)
    ax.set_xticklabels([r["name"] + "\n" + format(r["distance_km"], ".0f") + " km"
                        for r in rows])
    ax.set_ylabel("arrival time (min)")
    ax.set_title("Tehri dam-break - arrival at downstream gauges\n"
                 "engine-vs-engine agreement (no ground truth for this case)")
    ax.legend()
    ax.grid(axis="y", alpha=0.3)

    fig.tight_layout()
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=140)
    plt.close(fig)
    return out_path
