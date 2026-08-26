"""
End-to-end dam-break simulation pipeline (Phase 4).

Orchestrates:
1. Terrain setup (Phase 2)
2. Breach hydrograph ensemble (Phase 3)
3. 2D SWE solver loop (Phase 1) for each ensemble member
4. Arrival-time computation at downstream gauges
5. Raster export (COG, arrival times, max depths)

Entry point: run_dam_break_ensemble(config, ensemble_size=100)

Output: Results dict with ensemble statistics and raster paths

This is the MANDATORY core deliverable (Spec §4).
"""

import numpy as np
from typing import Dict, List, Optional, Tuple
import warnings

from jalraksha.solver.types import Grid, create_state
from jalraksha.solver.core import SWESolver
from jalraksha.solver.parallel import run_ensemble
from jalraksha.terrain.domain import build_domain, compute_breach_location, latlon_to_utm, compute_utm_zone
from jalraksha.terrain.breach import synthesize_breach_ensemble, ensemble_statistics


def define_downstream_gauges(dam_lat: float, dam_lon: float) -> List[Dict]:
    """
    Define 4 downstream gauge locations for Tehri dam.

    Spec §4.2: Koteshwar (13 km), Devprayag (28 km), Rishikesh (34.8 km), Haridwar (58.4 km).

    Args:
        dam_lat, dam_lon: Dam location (degrees)

    Returns:
        List of gauge dicts with name, distance_km, lat, lon
    """
    utm_zone = compute_utm_zone(dam_lat, dam_lon)

    # Real gauge sites along the Bhagirathi/Ganga corridor. These coordinates
    # were previously approximate to the point of being wrong: Koteshwar sat
    # ~4 km east of the gorge (so the flood never reached it), and Rishikesh and
    # Haridwar carried 77.x longitudes placing them ~112 km and ~29 km west of
    # the real towns. A gauge off the river reports no arrival no matter how
    # well the solver runs.
    gauges = [
        {
            "name": "Koteshwar",
            "distance_km": 13.0,
            "lat": 30.3167,
            "lon": 78.4833,
        },
        {
            "name": "Devprayag",
            "distance_km": 28.0,
            "lat": 30.15,
            "lon": 78.60,
        },
        {
            "name": "Rishikesh",
            "distance_km": 34.8,
            "lat": 30.0869,
            "lon": 78.2676,
        },
        {
            "name": "Haridwar",
            "distance_km": 58.4,
            "lat": 29.9457,
            "lon": 78.1642,
        },
    ]

    return gauges


def compute_arrival_times_at_gauges(
    results_ensemble: List[Dict],
    grid: Grid,
    gauges: List[Dict],
    threshold_h: float = 0.1,
    bed_elevation: np.ndarray = None,
    channel_search_m: float = 1200.0,
) -> Dict:
    """
    Compute arrival times at downstream gauges across ensemble.

    For each gauge, finds the first time h(gauge) exceeds threshold.

    Args:
        results_ensemble: List of result dicts from solver, each containing:
            {
                "t_arrival": np.ndarray [ny, nx],  time of first wetting (s)
                "h_max": np.ndarray [ny, nx],      max depth
                "sample_id": int,                  ensemble member index
            }
        grid: Grid definition
        gauges: List of gauge dicts from define_downstream_gauges()
        threshold_h: Depth threshold for arrival (m)

    Returns:
        {
            "Koteshwar": {"median": 1800, "p05": 1600, "p95": 2000, "unit": "s"},
            ...
        }
    """
    arrival_times_dict = {}

    # Get grid cell centres
    x_centres, y_centres = grid.cell_centres_2d()

    # Every gauge must be projected into the DOMAIN's UTM zone, not its own.
    # Letting latlon_to_utm pick per gauge silently mixed CRSs: Rishikesh sits in
    # zone 43 while the Tehri domain is zone 44, so its easting was measured from
    # a different central meridian and the "nearest cell" lookup below landed
    # hundreds of km away.
    domain_zone = int(str(grid.crs).split(":")[-1]) % 100

    # A gauge outside the domain has no meaningful nearest cell; argmin would
    # silently snap it to a boundary cell and report that cell's arrival time.
    x_min, x_max, y_min, y_max = grid.extent()

    for gauge in gauges:
        gauge_lat = gauge["lat"]
        gauge_lon = gauge["lon"]

        _zone, x_utm, y_utm = latlon_to_utm(gauge_lat, gauge_lon, utm_zone=domain_zone)

        if not (x_min <= x_utm <= x_max and y_min <= y_utm <= y_max):  # noqa: E501
            arrival_times_dict[gauge["name"]] = {
                "median": None, "p05": None, "p95": None, "num_samples": 0,
                "distance_km": gauge["distance_km"],
                "note": "Gauge lies outside the solver domain; increase domain_radius_km",
            }
            warnings.warn(
                f"Gauge {gauge['name']} ({gauge_lat}, {gauge_lon}) is outside the "
                f"{grid.nx * grid.dx / 1000:.0f} km domain — no arrival can be computed."
            )
            continue

        # Find nearest grid cell to gauge
        dist_to_gauge = np.sqrt((x_centres - x_utm) ** 2 + (y_centres - y_utm) ** 2)
        j_gauge, i_gauge = np.unravel_index(np.argmin(dist_to_gauge), dist_to_gauge.shape)

        # Snap onto the river channel: within channel_search_m, take the LOWEST
        # bed cell rather than the geometrically nearest one.
        #
        # A gauge measures river stage, so it belongs on the river. At 200-400 m
        # cells the Bhagirathi gorge is sub-grid, and the nearest cell to a
        # gauge's coordinate is often part way up the canyon wall. Koteshwar
        # snapped to a cell at 853 m with the valley floor at 752 m only three
        # cells away, and so reported "no arrival" while the flood ran 70 m deep
        # past it — while Devprayag, 15 km further downstream, happened to land
        # on the channel and did report an arrival. Reporting the far gauge wet
        # and the near one dry is the giveaway that this is a sampling artifact,
        # not physics.
        if bed_elevation is not None and channel_search_m > 0:
            radius = max(1, int(round(channel_search_m / min(grid.dx, grid.dy))))
            j0, j1 = max(0, j_gauge - radius), min(grid.ny, j_gauge + radius + 1)
            i0, i1 = max(0, i_gauge - radius), min(grid.nx, i_gauge + radius + 1)
            window = bed_elevation[j0:j1, i0:i1]
            dj, di = np.unravel_index(np.argmin(window), window.shape)
            j_gauge, i_gauge = j0 + dj, i0 + di

        # Extract arrival times from all ensemble members
        arrival_times_ensemble = []
        for result in results_ensemble:
            t_arrival_grid = result.get("t_arrival")
            if t_arrival_grid is None:
                continue

            # Arrival time at this gauge cell
            t_arr = t_arrival_grid[j_gauge, i_gauge]

            if np.isfinite(t_arr) and t_arr > 0:
                arrival_times_ensemble.append(float(t_arr))

        if len(arrival_times_ensemble) > 0:
            arrival_times_dict[gauge["name"]] = {
                "median": float(np.median(arrival_times_ensemble)),
                "p05": float(np.percentile(arrival_times_ensemble, 5)),
                "p95": float(np.percentile(arrival_times_ensemble, 95)),
                "mean": float(np.mean(arrival_times_ensemble)),
                "std": float(np.std(arrival_times_ensemble)),
                "num_samples": len(arrival_times_ensemble),
                "unit": "s",
                "distance_km": gauge["distance_km"],
            }
        else:
            # No arrival detected at this gauge
            arrival_times_dict[gauge["name"]] = {
                "median": None,
                "p05": None,
                "p95": None,
                "num_samples": 0,
                # Callers format this alongside the arrival time; omitting it
                # here made every no-arrival gauge a TypeError downstream.
                "distance_km": gauge["distance_km"],
                "note": "No arrival detected in ensemble",
            }

    return arrival_times_dict


def inject_breach_hydrograph(
    state: "State",
    grid: Grid,
    i_breach: int,
    j_breach: int,
    t_s: float,
    dt_s: float,
    q_t_array: np.ndarray,
    t_array: np.ndarray,
) -> None:
    """
    Inject breach outflow as boundary condition.

    Args:
        state: State object (modified in-place)
        grid: Grid definition
        i_breach, j_breach: Breach cell indices
        t_s: Current simulation time (s)
        dt_s: Time step (s)
        q_t_array: Breach hydrograph discharge [m³/s]
        t_array: Time array for hydrograph

    Modifies state.u, state.v, state.h at breach cell to enforce discharge.
    """
    # Find current discharge from hydrograph
    # Interpolate linearly if t_s falls between two time steps
    idx = np.searchsorted(t_array, t_s)
    if idx >= len(q_t_array) or idx == 0:
        q_current = 0
    else:
        # Linear interpolation
        t_prev = t_array[idx - 1]
        t_next = t_array[idx] if idx < len(t_array) else t_prev + dt_s
        q_prev = q_t_array[idx - 1]
        q_next = q_t_array[idx] if idx < len(q_t_array) else q_prev

        if t_next > t_prev:
            alpha = (t_s - t_prev) / (t_next - t_prev)
            q_current = (1 - alpha) * q_prev + alpha * q_next
        else:
            q_current = q_prev

    if q_current <= 0:
        return  # No injection

    # Add the discharged VOLUME as depth: Q [m3/s] * dt [s] / cell area [m2].
    #
    # This previously imposed a velocity instead (u = Q / (h * width)) and never
    # added mass. Against a dry bed that is a no-op — there is no water for the
    # velocity to act on, and the solver zeroes velocities in dry cells anyway —
    # so no water ever entered the domain. It only appeared to work because the
    # old build_domain filled h with terrain elevation, leaving the whole domain
    # pre-flooded to ~1500 m.
    #
    # A mass source is also the right primitive now that the bed is real
    # topography: it makes no assumption about which way "downstream" points,
    # and the well-balanced solver routes the water downhill on its own. The old
    # version pushed flow in +x regardless of the actual valley orientation.
    cell_area = grid.dx * grid.dy
    delta_h = q_current * dt_s / cell_area

    state.h[j_breach, i_breach] += delta_h


def run_dam_break_ensemble(
    dam_config: Dict,
    dem_path: str,
    ensemble_size: int = 100,
    output_dir: str = "./results",
    solver_duration_s: float = 10800,
    target_resolution: float = 200.0,
    record_depth_snapshots: bool = False,
    n_snapshots: int = 30,
    n_workers: Optional[int] = None,
    domain_radius_km: float = 60.0,
    use_synthetic_terrain: bool = False,
) -> Dict:
    """
    Run full end-to-end dam-break simulation for ensemble of breach hydrographs.

    This is the MANDATORY core deliverable (Spec §4, Phase 4).

    Args:
        dam_config: Dict with keys:
            - "name": Dam name (str)
            - "lat": Latitude (degrees)
            - "lon": Longitude (degrees)
            - "height_m": Height above lowest foundation (m)
            - "storage_mm3": Gross storage (MCM)
            - "dam_type": "embankment", "concrete", etc.
            - "failure_mode": "overtopping", "piping", etc.
        dem_path: Path to DEM GeoTIFF (from Phase 0 cache)
        ensemble_size: Number of breach ensemble members (default 100)
        output_dir: Output directory for rasters
        solver_duration_s: Simulation time (default 3 hours)
        target_resolution: Grid resolution (m)
        record_depth_snapshots: If True, snapshot the depth grid of the
            ensemble member closest to the median peak outflow at
            `n_snapshots` evenly-spaced simulation times, returned as
            `depth_series` for `jalraksha.export.keyframes.export_keyframes`.
            Off by default: recording every member's full time series is
            memory-prohibitive for large ensembles, so only one representative
            member is snapshotted.
        n_snapshots: Number of snapshot times when `record_depth_snapshots=True`.
        n_workers: Ensemble members to run concurrently. None uses every CPU
            core; 1 forces in-process execution (needed when the caller is
            itself inside a worker process, and useful for debugging).
        domain_radius_km: Half-width of the square solver domain (km).
        use_synthetic_terrain: Emergency fallback to an analytic valley instead
            of the real DEM. Results are not real terrain — see build_domain.

    Returns:
        {
            "breach_stats": {...},              ensemble statistics from Phase 3
            "arrival_times": {...},             arrival times at gauges
            "h_max_ensemble": [...],            max depths per member
            "raster_paths": {...},              exported COG paths
            "num_completed": int,               successful ensemble members
            "gauges": [...],                    gauge definitions
        }

    References:
        Spec §4: End-to-end dam-break pipeline
        Spec §4.1: Breach injection, solver runtime
        Spec §4.2: Downstream gauges
        Spec §4.3: Arrival-time threshold (h ≥ 0.1 m)
    """
    print(f"\n[Phase 4] Starting end-to-end dam-break for {dam_config['name']}")
    print(f"  Ensemble size: {ensemble_size} members")
    print(f"  Solver duration: {solver_duration_s/3600:.1f} hours")

    # =========================================================================
    # Step 1: Build terrain (Phase 2)
    # =========================================================================
    print("\n[Step 1] Building terrain domain...")
    try:
        grid, state_init, manning_field = build_domain(
            dam_config,
            dem_path,
            target_resolution=target_resolution,
            domain_radius_km=domain_radius_km,
            use_synthetic_terrain=use_synthetic_terrain,
        )
        print(f"  Grid: {grid.nx} x {grid.ny} cells @ {grid.dx:.0f} m")
        print(f"  Domain: {grid.nx * grid.dx / 1000:.1f} x {grid.ny * grid.dy / 1000:.1f} km")
    except Exception as e:
        print(f"  ERROR building domain: {e}")
        return {"error": str(e)}

    # Compute breach location
    dam_lat = dam_config["lat"]
    dam_lon = dam_config["lon"]
    utm_zone = compute_utm_zone(dam_lat, dam_lon)
    i_breach, j_breach, b_breach = compute_breach_location(
        state_init, grid, dam_lat, dam_lon, utm_zone
    )

    # Define downstream gauges
    gauges = define_downstream_gauges(dam_lat, dam_lon)
    print(f"  Downstream gauges: {[g['name'] for g in gauges]}")

    # =========================================================================
    # Step 2: Generate breach ensemble (Phase 3)
    # =========================================================================
    print("\n[Step 2] Generating breach hydrograph ensemble...")
    try:
        hydrographs = synthesize_breach_ensemble(dam_config, num_samples=ensemble_size)
        breach_stats = ensemble_statistics(hydrographs)
        print(f"  Q_peak median: {breach_stats['q_peak_median']:.0f} m3/s")
        print(f"  Q_peak range: {breach_stats['q_peak_p05']:.0f}-{breach_stats['q_peak_p95']:.0f} m3/s (5th-95th)")
        print(f"  Regressions used: {breach_stats['regressions_used']}")
    except Exception as e:
        print(f"  ERROR generating ensemble: {e}")
        return {"error": str(e)}

    # =========================================================================
    # Step 3: Run solver for each ensemble member (Phase 1)
    # =========================================================================
    print(f"\n[Step 3] Running solver for {ensemble_size} ensemble members...")
    results_ensemble = []
    h_max_ensemble = []
    depth_series: List[Dict] = []

    # Pick the member whose peak outflow is closest to the ensemble median as
    # the "representative" member to snapshot for keyframe export (§5.3 of the
    # integration brief) — recording every member's depth history is
    # memory-prohibitive for ensembles of 100-10,000.
    snapshot_sample_id = None
    snapshot_times = None
    if record_depth_snapshots and hydrographs:
        q_peaks = [h["metadata"]["q_peak_m3_s"] for h in hydrographs]
        q_target = breach_stats.get("q_peak_median", np.median(q_peaks))
        snapshot_sample_id = int(np.argmin(np.abs(np.array(q_peaks) - q_target)))
        snapshot_times = np.linspace(0, solver_duration_s, n_snapshots)

    member_results = run_ensemble(
        hydrographs=hydrographs,
        grid=grid,
        state_init=state_init,
        manning_field=manning_field,
        i_breach=i_breach,
        j_breach=j_breach,
        solver_duration_s=solver_duration_s,
        snapshot_sample_id=snapshot_sample_id,
        snapshot_times=snapshot_times,
        n_workers=n_workers,
    )

    for member in member_results:
        sample_id = member["sample_id"]
        if not member.get("success"):
            print(f"  Member {sample_id + 1}/{ensemble_size}: [FAIL] {member.get('error', '')[:60]}")
            warnings.warn(f"Sample {sample_id} failed: {member.get('error')}")
            continue

        metadata = member["metadata"]
        print(
            f"  Member {sample_id + 1}/{ensemble_size}: [OK] "
            f"(Q_peak={metadata['q_peak_m3_s']:.0f}, "
            f"t_fail={metadata['failure_time_s'] / 60:.1f} min)"
        )
        results_ensemble.append({
            "t_arrival": member["t_arrival"],
            "h_max": member["h_max"],
            "sample_id": sample_id,
            "metadata": metadata,
        })
        h_max_ensemble.append(member["h_max"])
        if member.get("depth_series"):
            depth_series = member["depth_series"]

    print(f"\n  Completed: {len(results_ensemble)}/{ensemble_size} members")

    if len(results_ensemble) == 0:
        return {"error": "No ensemble members completed successfully"}

    # =========================================================================
    # Step 4: Compute arrival times at gauges
    # =========================================================================
    print("\n[Step 4] Computing arrival times at downstream gauges...")
    arrival_times_gauges = compute_arrival_times_at_gauges(
        results_ensemble, grid, gauges, threshold_h=0.1,
        bed_elevation=state_init.b,
    )

    for gauge_name, times in arrival_times_gauges.items():
        if times.get("median") is not None:
            t_med_min = times["median"] / 60
            t_p05_min = times["p05"] / 60
            t_p95_min = times["p95"] / 60
            print(f"  {gauge_name:12s}: {t_med_min:6.1f} min (5th-95th: {t_p05_min:6.1f}-{t_p95_min:6.1f} min)")
        else:
            print(f"  {gauge_name:12s}: No arrival detected")

    # =========================================================================
    # Step 5: Aggregate ensemble statistics
    # =========================================================================
    print("\n[Step 5] Aggregating ensemble statistics...")
    h_max_ensemble_array = np.array(h_max_ensemble)

    h_max_median = np.median(h_max_ensemble_array, axis=0)
    h_max_p05 = np.percentile(h_max_ensemble_array, 5, axis=0)
    h_max_p95 = np.percentile(h_max_ensemble_array, 95, axis=0)

    print(f"  Max depth (median): {np.nanmax(h_max_median):.2f} m")
    print(f"  Max depth (p95):    {np.nanmax(h_max_p95):.2f} m")

    # =========================================================================
    # Step 6: Export rasters (COG format — Phase 5 scope, pulled forward)
    # =========================================================================
    print("\n[Step 6] Exporting rasters to COG format...")
    # TODO: Implement COG export (Phase 5)
    # For now, just note the output structure
    raster_paths = {
        "h_max_median": f"{output_dir}/h_max_median_cog.tif",
        "h_max_p05": f"{output_dir}/h_max_p05_cog.tif",
        "h_max_p95": f"{output_dir}/h_max_p95_cog.tif",
        "t_arrival_median": f"{output_dir}/t_arrival_median_cog.tif",
    }
    print("  (COG export marked for Phase 5)")

    # =========================================================================
    # Final report
    # =========================================================================
    print("\n" + "=" * 70)
    print("PHASE 4 COMPLETE: End-to-End Dam-Break Pipeline")
    print("=" * 70)

    result = {
        "dam_name": dam_config["name"],
        "breach_stats": breach_stats,
        "arrival_times": arrival_times_gauges,
        "h_max_stats": {
            "median": float(np.nanmax(h_max_median)),
            "p05": float(np.nanmax(h_max_p05)),
            "p95": float(np.nanmax(h_max_p95)),
        },
        "raster_paths": raster_paths,
        "num_completed": len(results_ensemble),
        "num_ensemble": ensemble_size,
        "gauges": gauges,
        "grid": {
            "nx": grid.nx, "ny": grid.ny, "dx": grid.dx, "dy": grid.dy,
            "x0": grid.x0, "y0": grid.y0, "crs": grid.crs,
        },
        # The bed the solver actually ran on. Downstream 3D visualization needs
        # the terrain to place the water surface (water_z = terrain_z + depth),
        # and re-deriving it by re-running build_domain risks silently rendering
        # a different surface from the one the flood was computed over.
        # Row 0 is the SOUTHERNMOST row (Grid.cell_centres_y increases north).
        "terrain_elevation": state_init.b,
    }
    if record_depth_snapshots:
        result["depth_series"] = depth_series
    return result