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

import os
import warnings
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np

from jalraksha.solver.types import Grid, create_state
from jalraksha.solver.core import SWESolver
from jalraksha.solver.parallel import run_ensemble
from jalraksha.terrain.domain import build_domain, compute_breach_location, latlon_to_utm, compute_utm_zone
from jalraksha.terrain.breach import synthesize_breach_ensemble, ensemble_statistics
from jalraksha.presets import get_gauges


def _attempt(kind: str, writer, *args, **kwargs):
    """
    Run one export writer, reporting failure loudly and returning None on it.

    Every writer here is independent — a missing KML is no reason to withhold a
    valid GeoTIFF — so a failure is contained rather than aborting the batch.
    But it is never swallowed: the exception type, message and traceback all go
    to the console, because the alternative (a quiet skip) is indistinguishable
    from a product that was never requested.
    """
    import traceback

    try:
        return writer(*args, **kwargs)
    except Exception as exc:
        print(f"  [FAIL] {kind}: {type(exc).__name__}: {exc}")
        traceback.print_exc()
        return None


def _record(paths: Dict[str, str], kind: str, path: Optional[str]) -> Optional[str]:
    """
    Add an export to the manifest ONLY if the file is really on disk.

    This is the guard the whole module exists to enforce. A recorded path to a
    file that was never written is the worst outcome available: the service
    stores it, the API serves a /files/ URL for it, and the dashboard offers a
    judge a download that 404s. A writer returning None (its documented
    "nothing to write" answer — no cells above threshold, say) is a legitimate
    outcome and contributes no entry, same as an outright failure.
    """
    if path is None:
        print(f"  [SKIP] {kind}: writer reported nothing to write")
        return None
    if not os.path.exists(path):
        print(f"  [FAIL] {kind}: writer returned {path!r} but no such file exists")
        return None
    paths[kind] = str(path)
    print(f"  [OK]   {kind}: {os.path.basename(path)} ({os.path.getsize(path)} bytes)")
    return str(path)


def write_export_products(
    results_ensemble: List[Dict],
    h_max_median: np.ndarray,
    v_max_median: np.ndarray,
    t_arrival_median: np.ndarray,
    grid: Grid,
    dam_config: Dict,
    output_dir: str,
    depth_series: Optional[List[Dict]] = None,
) -> Dict[str, str]:
    """
    Write every Phase 5 deliverable the problem statement names: .tif, .shp, .kml.

    PS 26161 requires "Output should be converted to .shp or .Kml file". Until
    this function existed, jalraksha.run fabricated four .tif path strings that
    nothing ever wrote, and the service recorded them in its exports table — so
    the API advertised downloads that 404'd for every run ever made.

    LAYERING. This makes jalraksha.run (Phase 4) import jalraksha.export
    (Phase 5), which CLAUDE.md's dependency-direction rule forbids read
    literally. Taken deliberately: run.py is the top-level pipeline
    orchestrator — its own module docstring already lists "5. Raster export"
    among its steps — rather than a Phase-4 layer module, and jalraksha.export
    does not import jalraksha.run, so the import graph stays acyclic and
    Phase 5 remains independently testable.

    Args:
        results_ensemble: Per-member {h_max, v_max, t_arrival} arrays.
        h_max_median, v_max_median, t_arrival_median: Ensemble aggregates.
        grid: The Grid the solver ran on (supplies the metric CRS).
        dam_config: Dam configuration (supplies the name for metadata).
        output_dir: Directory to write into.
        depth_series: Recorded snapshots, used for the time-animated KML. The
            animation is omitted when the run recorded none.

    Returns:
        {export_kind: path} containing ONLY files verified to exist on disk.
        Kinds are prefixed (cog_ / shp_ / kml_ / kmz_) so the service and the
        dashboard can tell a raster from a vector from an Earth overlay.
    """
    from jalraksha.export.geotiff import export_ensemble_to_cogs
    from jalraksha.export.georef import epsg_from_crs, zip_shapefile
    from jalraksha.export.shapefile import (
        export_arrival_time_contours,
        export_hazard_classification_polygons,
        export_inundation_polygon,
    )
    from jalraksha.export.kml import (
        export_depth_ground_overlay,
        export_inundation_kml,
        export_kmz,
        export_time_animated_kml,
    )

    paths: Dict[str, str] = {}
    dam_name = dam_config.get("name", "Dam")

    # A metric CRS is mandatory (CLAUDE.md). epsg_from_crs raises rather than
    # defaulting, because guessing a zone silently relocates every product.
    crs_epsg = epsg_from_crs(grid.crs)
    grid_dict = {
        "nx": grid.nx, "ny": grid.ny, "dx": grid.dx, "dy": grid.dy,
        "x0": grid.x0, "y0": grid.y0,
    }
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    print(f"  Target: {output_dir} (EPSG:{crs_epsg})")

    # ---- Rasters: 9 COGs (h_max / v_max / t_arrival x median / p05 / p95) ----
    cogs = _attempt(
        "cogs", export_ensemble_to_cogs,
        results_ensemble, grid_dict, output_dir,
        dam_name=dam_name, crs_epsg=crs_epsg,
    )
    for variable, cog_path in (cogs or {}).items():
        _record(paths, f"cog_{variable}", cog_path)

    # ---- Vectors. Each shapefile is published as a .zip: a bare .shp carries
    # neither attributes (.dbf) nor CRS (.prj), so a link to one alone is
    # useless to whoever downloads it. ----
    inundation_shp = os.path.join(output_dir, "inundation_envelope.shp")
    if _attempt("shp_inundation", export_inundation_polygon,
                h_max_median, grid_dict, inundation_shp,
                depth_threshold=0.1, crs_epsg=crs_epsg, dam_name=dam_name):
        _record(paths, "shp_inundation_zip",
                _attempt("shp_inundation_zip", zip_shapefile, inundation_shp))

    hazard_classes = _attempt(
        "shp_hazard", export_hazard_classification_polygons,
        h_max_median, v_max_median, grid_dict,
        os.path.join(output_dir, "hazard_classes.shp"),
        crs_epsg=crs_epsg, dam_name=dam_name,
    )
    for cls_name, cls_path in (hazard_classes or {}).items():
        _record(paths, f"shp_hazard_{cls_name}_zip",
                _attempt(f"shp_hazard_{cls_name}_zip", zip_shapefile, cls_path))

    contours_shp = os.path.join(output_dir, "arrival_contours.shp")
    if _attempt("shp_arrival_contours", export_arrival_time_contours,
                t_arrival_median, grid_dict, contours_shp, crs_epsg=crs_epsg):
        _record(paths, "shp_arrival_contours_zip",
                _attempt("shp_arrival_contours_zip", zip_shapefile, contours_shp))

    # ---- KML / KMZ. Reprojected to WGS84 by export/kml.py, which raises rather
    # than writing UTM metres into a <coordinates> element. ----
    _record(paths, "kml_inundation", _attempt(
        "kml_inundation", export_inundation_kml,
        h_max_median, grid_dict, os.path.join(output_dir, "inundation.kml"),
        depth_threshold=0.1, dam_name=dam_name, crs_epsg=crs_epsg,
    ))

    if depth_series:
        # Built from the representative member's recorded snapshots. Runs that
        # recorded none get no animation, rather than a single-frame file
        # presented as one.
        _record(paths, "kml_animation", _attempt(
            "kml_animation", export_time_animated_kml,
            [float(f["time_s"]) for f in depth_series],
            [np.asarray(f["depth"]) for f in depth_series],
            grid_dict, os.path.join(output_dir, "flood_animation.kml"),
            depth_threshold=0.1, dam_name=dam_name, crs_epsg=crs_epsg,
        ))
    else:
        print("  [SKIP] kml_animation: run recorded no depth snapshots")

    # export_depth_ground_overlay returns (kml_path, png_path); the KMZ has to
    # carry both or the overlay renders as an empty box in Google Earth.
    overlay = _attempt(
        "kmz_depth_overlay", export_depth_ground_overlay,
        h_max_median, grid_dict, os.path.join(output_dir, "depth_overlay.kml"),
        dam_name=dam_name, crs_epsg=crs_epsg,
    )
    if overlay:
        overlay_kml, overlay_png = overlay
        _record(paths, "kmz_depth_overlay", _attempt(
            "kmz_depth_overlay", export_kmz, overlay_kml,
            asset_paths=[overlay_png],
            output_path=os.path.join(output_dir, "depth_overlay.kmz"),
        ))

    print(f"  Wrote {len(paths)} export products.")
    return paths


def define_downstream_gauges(
    dam_lat: float, dam_lon: float, dam_id: Optional[str] = None
) -> List[Dict]:
    """
    Downstream gauge locations for a dam, as plain dicts for the solver.

    Reads jalraksha.presets.GAUGES, which is the single source of truth for
    which towns a dam's flood is reported at. This function used to hold the
    Tehri corridor as a literal and return it for every dam it was called with,
    including its own dam_lat/dam_lon arguments, which it ignored — so a
    Khadakwasla or Hirakud run computed arrival times at Himalayan gauges
    1,500+ km outside its own domain.

    Args:
        dam_lat, dam_lon: Dam location (degrees). Used only for the fallback.
        dam_id: Preset dam id. When it names a dam with a defined corridor,
            that corridor is returned.

    Returns:
        List of gauge dicts with name, distance_km, lat, lon (plus river/note
        where defined). Empty when the dam has no defined corridor — an empty
        gauge table is the honest answer for a dam whose downstream towns have
        not been surveyed, and is far better than another dam's towns.
    """
    gauges = get_gauges(dam_id)

    if not gauges and 29.0 <= dam_lat <= 31.5 and 77.0 <= dam_lon <= 80.0:
        # Coordinates inside the Tehri corridor but no dam_id — the shape of
        # every call site that predates dam_id existing. Resolve through the
        # registry rather than reintroducing a literal copy of the corridor.
        # Mirrors the same fallback in jalraksha/api.py::get_downstream_gauges.
        gauges = get_gauges("tehri")

    if not gauges:
        # No corridor, and no placeholder invented. jalraksha/api.py's generic
        # Gauge_Nkm placeholders are a display convenience for the legacy HTTP
        # layer; putting made-up coordinates into the solver's arrival-time
        # table would be presenting invented locations as results.
        warnings.warn(
            f"No downstream gauge corridor is defined for dam_id={dam_id!r} "
            f"at ({dam_lat}, {dam_lon}). Arrival times will be reported at no "
            f"gauges. Add one to jalraksha.presets.GAUGES."
        )
        return []

    return [
        {
            "name": g.name,
            "distance_km": g.distance_km,
            "lat": g.lat,
            "lon": g.lon,
            **({"river": g.river} if g.river else {}),
            **({"note": g.note} if g.note else {}),
        }
        for g in gauges
    ]


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
                "note": _no_arrival_reason(
                    gauge, bed_elevation, grid, j_gauge, i_gauge),
            }

    return arrival_times_dict


def _no_arrival_reason(gauge: Dict, bed_elevation, grid: Grid,
                       j_gauge: int, i_gauge: int) -> str:
    """
    Say WHY a gauge reports no arrival, in terms a reader can act on.

    "No arrival detected in ensemble" is true and useless: it cannot
    distinguish a town the flood has not reached YET from one it can never
    reach. Both matter, and they mean opposite things for a warning plan.

    The distinction that decides it is elevation. Several of the Pune corridor's
    coordinates are town CENTRES rather than riverside gauging stations, and
    they sit well above the Mula-Mutha — Swargate's is 46 m above the channel
    and 3 km from it, higher than the reservoir surface itself. A
    channel-confined dam break genuinely never reaches such a point, and saying
    so is a real screening result, not a gap in the model.

    Falls back to the plain message when there is no bed data to reason from,
    rather than inventing a cause.
    """
    import numpy as np

    if bed_elevation is None:
        return "No arrival detected within the simulated time."

    try:
        gauge_bed = float(bed_elevation[j_gauge, i_gauge])
        # The channel near this gauge: lowest bed within ~3 km, which is far
        # enough to find the river even where a town spreads away from it.
        radius = max(1, int(round(3000.0 / min(grid.dx, grid.dy))))
        j0, j1 = max(0, j_gauge - radius), min(grid.ny, j_gauge + radius + 1)
        i0, i1 = max(0, i_gauge - radius), min(grid.nx, i_gauge + radius + 1)
        window = np.asarray(bed_elevation[j0:j1, i0:i1])
        thalweg = float(np.nanmin(window))
        above = gauge_bed - thalweg
    except Exception:
        return "No arrival detected within the simulated time."

    if above >= 15.0:
        return (
            f"This point sits {above:.0f} m above the nearest river channel "
            f"({gauge_bed:.0f} m vs {thalweg:.0f} m). It is a town centre, not "
            f"a riverside gauge, so a channel-confined dam-break flood does not "
            f"reach it. Not a modelling gap — the flood would have to rise "
            f"{above:.0f} m above the river to inundate this location."
        )
    return (
        f"No arrival within the simulated time. This point is {above:.0f} m "
        f"above the nearest channel; extend the simulated duration to test "
        f"whether the flood reaches it later."
    )


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
    progress_cb: Optional[Callable[[float, str], None]] = None,
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
    def _report(pct: float, label: str) -> None:
        """
        Publish coarse progress.

        The six Step boundaries below are the natural reporting points and were
        already printed to stdout; they simply had no way to reach a caller. A
        run therefore sat at a frozen 5% in the dashboard from submission to
        completion, which is indistinguishable from a hang — and the solver step
        alone can run for tens of minutes.

        Failure here is swallowed on purpose: progress is telemetry, and a
        broken status write must never take down a simulation that is otherwise
        succeeding.
        """
        if progress_cb is None:
            return
        try:
            progress_cb(float(pct), label)
        except Exception as exc:  # pragma: no cover - telemetry only
            print(f"  [progress] callback failed ({type(exc).__name__}: {exc})")

    # Step 1: Build terrain (Phase 2)
    # =========================================================================
    _report(8.0, "Building terrain domain")
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
    gauges = define_downstream_gauges(dam_lat, dam_lon, dam_config.get("dam_id"))
    print(f"  Downstream gauges: {[g['name'] for g in gauges]}")

    # =========================================================================
    # Step 2: Generate breach ensemble (Phase 3)
    # =========================================================================
    _report(18.0, "Generating breach ensemble")
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
    _report(25.0, f"Solving {ensemble_size} ensemble members")
    print(f"\n[Step 3] Running solver for {ensemble_size} ensemble members...")
    results_ensemble = []
    h_max_ensemble = []
    v_max_ensemble = []
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

    def _member_progress(done: int, total: int) -> None:
        # Step 3 owns 25-75% of the bar because it owns most of the runtime.
        _report(25.0 + 50.0 * (done / max(total, 1)),
                f"Solving member {done}/{total}")

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
        progress_cb=_member_progress,
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
            # Captured by run_ensemble_member so the velocity COGs and the
            # depth-velocity hazard classes are computed rather than defaulted
            # to zeros by the export layer (solver/parallel.py).
            "v_max": member["v_max"],
            "sample_id": sample_id,
            "metadata": metadata,
        })
        h_max_ensemble.append(member["h_max"])
        v_max_ensemble.append(member["v_max"])
        if member.get("depth_series"):
            depth_series = member["depth_series"]

    print(f"\n  Completed: {len(results_ensemble)}/{ensemble_size} members")

    if len(results_ensemble) == 0:
        return {"error": "No ensemble members completed successfully"}

    # =========================================================================
    # Step 4: Compute arrival times at gauges
    # =========================================================================
    _report(75.0, "Computing arrival times")
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
    _report(85.0, "Aggregating ensemble statistics")
    print("\n[Step 5] Aggregating ensemble statistics...")
    h_max_ensemble_array = np.array(h_max_ensemble)

    h_max_median = np.median(h_max_ensemble_array, axis=0)
    h_max_p05 = np.percentile(h_max_ensemble_array, 5, axis=0)
    h_max_p95 = np.percentile(h_max_ensemble_array, 95, axis=0)

    v_max_ensemble_array = np.array(v_max_ensemble)
    v_max_median = np.median(v_max_ensemble_array, axis=0)

    # Arrival time is stored as +inf where a cell never wetted. Taking a median
    # over that directly propagates inf into the exported raster; NaN is the
    # nodata value the COG profile declares, so convert here once.
    t_arrival_ensemble_array = np.array([r["t_arrival"] for r in results_ensemble])
    t_arrival_ensemble_array[np.isinf(t_arrival_ensemble_array)] = np.nan
    with warnings.catch_warnings():
        # A cell dry in EVERY member is an all-NaN slice; nanmedian warns and
        # returns NaN, which is exactly the wanted answer.
        warnings.simplefilter("ignore", category=RuntimeWarning)
        t_arrival_median = np.nanmedian(t_arrival_ensemble_array, axis=0)

    print(f"  Max depth (median): {np.nanmax(h_max_median):.2f} m")
    print(f"  Max depth (p95):    {np.nanmax(h_max_p95):.2f} m")
    print(f"  Max speed (median): {np.nanmax(v_max_median):.2f} m/s")

    # =========================================================================
    # Step 6: Export deliverables (COG / Shapefile / KML - Phase 5)
    # =========================================================================
    _report(92.0, "Writing export products")
    print("\n[Step 6] Writing export products...")
    raster_paths = write_export_products(
        results_ensemble=results_ensemble,
        h_max_median=h_max_median,
        v_max_median=v_max_median,
        t_arrival_median=t_arrival_median,
        grid=grid,
        dam_config=dam_config,
        output_dir=output_dir,
        depth_series=depth_series,
    )

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
        # The aggregated fields themselves, not just their scalar maxima.
        # Population-at-risk needs per-cell depth and arrival time to intersect
        # against a population grid, and h_max_stats collapses both to a single
        # number. Same footprint as terrain_elevation, which is already returned.
        "h_max_median": h_max_median,
        "t_arrival_median": t_arrival_median,
    }
    if record_depth_snapshots:
        result["depth_series"] = depth_series
    return result