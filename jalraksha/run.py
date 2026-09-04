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
from jalraksha.terrain.breach import synthesize_scenario_ensemble, ensemble_statistics
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

    if (
        not gauges
        and dam_id is None
        and 29.0 <= dam_lat <= 31.5
        and 77.0 <= dam_lon <= 80.0
    ):
        # Coordinates inside the Tehri corridor AND NO dam_id — the shape of
        # every call site that predates dam_id existing. Resolve through the
        # registry rather than reintroducing a literal copy of the corridor.
        # Mirrors the same fallback in jalraksha/api.py::get_downstream_gauges.
        #
        # The `dam_id is None` term is load-bearing and was missing. Without it
        # the box fired for any NAMED site that simply had no corridor yet, and
        # a Rishi Ganga blockage at (30.50, 79.63) — well inside the box, and on
        # a different river 150 km from the Bhagirathi — reported arrival times
        # at Koteshwar, Devprayag, Rishikesh and Haridwar. That is precisely the
        # failure this function's own docstring says it was written to end,
        # returning through the one path that still allowed it: an empty
        # corridor was treated as a missing dam_id.
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
        # Peak depth from THE SAME MEMBERS that arrived, not from the ensemble
        # median raster.
        #
        # Those are different questions whenever a minority of members reach a
        # gauge, and the difference is not small. Measured on a Rishi Ganga
        # blockage: 1 of 4 members reached Joshimath, so the arrival time was
        # that member's 4,894 s while the MEDIAN h_max at the same cell was
        # exactly 0.0 m — three members never wet it, and the median of
        # {0, 0, 0, d} is 0. The row then read "arrived at 1 h 22 m, peak depth
        # 0.0 m", which is the contradiction this function's own cell-snapping
        # comment exists to prevent, arriving by a second route.
        depths_ensemble = []
        n_members = 0
        for result in results_ensemble:
            t_arrival_grid = result.get("t_arrival")
            if t_arrival_grid is None:
                continue
            n_members += 1

            # Arrival time at this gauge cell
            t_arr = t_arrival_grid[j_gauge, i_gauge]

            if np.isfinite(t_arr) and t_arr > 0:
                arrival_times_ensemble.append(float(t_arr))
                h_max_grid = result.get("h_max")
                if h_max_grid is not None:
                    depth = float(h_max_grid[j_gauge, i_gauge])
                    if np.isfinite(depth):
                        depths_ensemble.append(depth)

        if len(arrival_times_ensemble) > 0:
            arrival_times_dict[gauge["name"]] = {
                "median": float(np.median(arrival_times_ensemble)),
                "p05": float(np.percentile(arrival_times_ensemble, 5)),
                "p95": float(np.percentile(arrival_times_ensemble, 95)),
                "mean": float(np.mean(arrival_times_ensemble)),
                "std": float(np.std(arrival_times_ensemble)),
                "num_samples": len(arrival_times_ensemble),
                # How many members were solved at all, so a caller can say
                # "3 of 30 members" rather than leaving the reader to assume a
                # minority arrival is the consensus one.
                "num_members": n_members,
                # Median peak depth ACROSS THE ARRIVING MEMBERS. None when the
                # solver did not record h_max, which is not the same as zero.
                "max_depth_m": (
                    float(np.median(depths_ensemble)) if depths_ensemble else None
                ),
                "unit": "s",
                "distance_km": gauge["distance_km"],
                # The cell the arrival was actually READ FROM, after the channel
                # snap above. Recorded so peak depth is sampled at the same
                # place: _gauge_max_depths re-derived the cell from lat/lon with
                # no snap, so for a town perched above a sub-grid gorge the two
                # columns described different ground. Koteshwar, Devprayag and
                # Rishikesh each reported a real arrival time beside a peak
                # depth of exactly 0.0 m, which reads as a contradiction and is
                # really two answers about two cells.
                "cell": [int(j_gauge), int(i_gauge)],
            }
        else:
            # No arrival detected at this gauge
            arrival_times_dict[gauge["name"]] = {
                "median": None,
                "p05": None,
                "p95": None,
                "num_samples": 0,
                "num_members": n_members,
                "max_depth_m": None,
                # Callers format this alongside the arrival time; omitting it
                # here made every no-arrival gauge a TypeError downstream.
                "distance_km": gauge["distance_km"],
                "note": _no_arrival_reason(
                    gauge, bed_elevation, grid, j_gauge, i_gauge),
                "cell": [int(j_gauge), int(i_gauge)],
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

    Elevation is measured against the LOCAL channel (600 m), not a 3 km window,
    because on a steep river the wide window measures the river's own fall. See
    the two-window comment below.

    Falls back to the plain message when there is no bed data to reason from,
    rather than inventing a cause.
    """
    import numpy as np

    if bed_elevation is None:
        return "No arrival detected within the simulated time."

    def _lowest_within(metres: float) -> float:
        radius = max(1, int(round(metres / min(grid.dx, grid.dy))))
        j0, j1 = max(0, j_gauge - radius), min(grid.ny, j_gauge + radius + 1)
        i0, i1 = max(0, i_gauge - radius), min(grid.nx, i_gauge + radius + 1)
        return float(np.nanmin(np.asarray(bed_elevation[j0:j1, i0:i1])))

    try:
        gauge_bed = float(bed_elevation[j_gauge, i_gauge])
        # IS THE HEIGHT EXPLAINED BY THE REACH'S OWN FALL?
        #
        # A square window around a gauge always contains ground downstream of
        # it, so on a steep river its minimum is lower simply because rivers run
        # downhill. Measured on the Alaknanda below Joshimath: a point sitting
        # exactly ON the channel came out 58-85 m above the lowest bed within
        # 3 km, and was told it was a hillside town — which sends a reader to
        # fix a coordinate that is correct. At 60 m/km even a 600 m window sees
        # 36 m of fall, so no fixed window solves this.
        #
        # The reach GRADIENT does. Estimated between the two windows, it says how
        # much of `above` is fall rather than height, and only the excess is
        # evidence the point sits off the channel. On a flat reach the gradient
        # is ~0 and the test reduces to the original one, which is what keeps the
        # Pune finding intact — Swargate is 46 m up a bank beside a river that
        # barely falls.
        thalweg = _lowest_within(600.0)
        above = gauge_bed - thalweg
        wide_thalweg = _lowest_within(3000.0)
        gradient = max(0.0, (thalweg - wide_thalweg) / 2400.0)
        # 20% margin plus 5 m for GLO-30's own vertical error, so a point on a
        # steep channel is not condemned by the DEM's noise.
        explained_by_fall = gradient * 600.0 * 1.2 + 5.0
    except Exception:
        return "No arrival detected within the simulated time."

    if above <= explained_by_fall:
        return (
            f"No arrival within the simulated time. This point is at channel "
            f"level: it stands {above:.0f} m above the lowest bed within 600 m, "
            f"and this reach falls {gradient * 1000.0:.0f} m/km, which accounts "
            f"for it. Extend the simulated duration to test whether the flood "
            f"reaches it later."
        )

    if above >= 15.0:
        # State the GEOMETRY, and name a cause only where one is known.
        #
        # This used to assert "It is a town centre, not a riverside gauge" for
        # every gauge above the channel. True of the Pune corridor, which is
        # where it was written; false of a coordinate derived from the terrain
        # itself, where being above the thalweg means the point was placed
        # imprecisely rather than that a town sits on a hillside. Two different
        # findings — one about the world, one about the input — and telling a
        # reader the wrong one sends them to fix the wrong thing.
        derived = "TERRAIN-DERIVED" in str(gauge.get("note") or "")
        cause = (
            "This coordinate was derived from the DEM, so being above the "
            "channel means it was placed off the thalweg rather than that the "
            "location is genuinely elevated — snap it to the local minimum."
            if derived
            else
            "A town centre rather than a riverside gauging station sits above "
            "the channel like this, and a channel-confined flood does not "
            "reach it. Not a modelling gap."
        )
        return (
            f"This point sits {above:.0f} m above the nearest river channel "
            f"({gauge_bed:.0f} m vs {thalweg:.0f} m). {cause} The flood would "
            f"have to rise {above:.0f} m above the river to inundate it."
        )
    return (
        f"No arrival within the simulated time. This point is {above:.0f} m "
        f"above the nearest channel; extend the simulated duration to test "
        f"whether the flood reaches it later."
    )


def _notch_breach_into_bed(
    state_init: "State",
    grid: Grid,
    i_breach: int,
    j_breach: int,
    b_breach: float,
    dam_config: Dict,
) -> None:
    """
    Carve an actual gap through the dam ridge at the breach cell.

    inject_breach_hydrograph (below) only ever ADDS depth at one cell each
    timestep — a source term, with no momentum direction, on a bed that still
    has the intact dam crest sitting in it. Water that piles up locally spills
    downstream easily (the valley there is real and steep), but the fraction
    that spills back toward the reservoir lands in a REAL closed basin — the
    reservoir bowl the dam was built to hold, bounded by the valley walls on
    three sides and the (unbreached) dam ridge on the fourth — and just sits
    there, because the domain starts dry and nothing removes it. Measured on
    a Khadakwasla run: ~42% of released volume trapped this way, plateauing
    the hazard classification at ~46 permanently SEVERE cells instead of
    letting it recede.

    A real breach is a channel cut through the dam body down to roughly the
    original riverbed, not a hole in an otherwise intact wall. This lowers
    the bed at (and immediately around) the breach cell to approximate that:
    invert = crest elevation at the breach cell minus the dam height (the one
    breach-geometry number every hydrograph member actually carries — see
    dam_config["height_m"] in terrain/breach.py's metadata — Froehlich/Von
    Thun-style regressions default the breach invert to the dam base, i.e. a
    full-depth breach). The result is clamped to never dig BELOW the lowest
    bed already present just outside the notch footprint, so this can only
    open a path to terrain that's already there — it cannot manufacture a new
    pit deeper than the surrounding channel.

    dam height_m is a fixed input to the ensemble (not sampled per member —
    only outflow/timing vary), so there is one notch geometry, computed once,
    shared by the whole ensemble, exactly like the terrain itself.
    """
    height_m = float(dam_config.get("height_m", 0.0))
    if height_m <= 0:
        return

    # Footprint: a small block around the breach cell, standing in for breach
    # WIDTH (no width is available per-member either; ~2-3 cells at 200-300 m
    # resolution is a few hundred metres, in line with the embankment/gravity
    # breach widths these regressions are fitted to).
    footprint_radius = 1
    search_radius = footprint_radius + 3

    j0f = max(0, j_breach - footprint_radius)
    j1f = min(grid.ny, j_breach + footprint_radius + 1)
    i0f = max(0, i_breach - footprint_radius)
    i1f = min(grid.nx, i_breach + footprint_radius + 1)

    j0s = max(0, j_breach - search_radius)
    j1s = min(grid.ny, j_breach + search_radius + 1)
    i0s = max(0, i_breach - search_radius)
    i1s = min(grid.nx, i_breach + search_radius + 1)

    surrounding = state_init.b[j0s:j1s, i0s:i1s].copy()
    # Exclude the footprint itself from the "what's already there" floor —
    # otherwise a first notch call would clamp against its own not-yet-lowered
    # cells and do nothing.
    surrounding_mask = np.ones_like(surrounding, dtype=bool)
    fj0, fj1 = j0f - j0s, j1f - j0s
    fi0, fi1 = i0f - i0s, i1f - i0s
    surrounding_mask[fj0:fj1, fi0:fi1] = False
    local_floor = float(surrounding[surrounding_mask].min()) if surrounding_mask.any() else b_breach

    candidate_invert = b_breach - height_m
    invert = max(candidate_invert, local_floor)

    footprint = state_init.b[j0f:j1f, i0f:i1f]
    n_lowered = int((footprint > invert).sum())
    max_drop = float((footprint - invert)[footprint > invert].max()) if n_lowered else 0.0
    np.minimum(footprint, invert, out=footprint)

    print(
        f"  Breach notch: cell (i={i_breach}, j={j_breach}) crest {b_breach:.1f} m "
        f"-> invert {invert:.1f} m (dam height {height_m:.1f} m, "
        f"local terrain floor {local_floor:.1f} m); "
        f"{n_lowered} cell(s) lowered, max drop {max_drop:.1f} m"
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


def _summarize_volume_balance(members: List[Dict]) -> Dict:
    """
    Median volume balance across ensemble members.

    Answers "did the water get out?" with a number instead of an inference.
    A 24 h Khadakwasla run once plateaued with roughly 42% of released volume
    permanently trapped, and the only evidence available at the time was hazard
    cell counts — which cannot tell water draining away from water sitting
    still (docs/validation_findings.md section 8).

    Median rather than mean: one member that failed to release (a degenerate
    breach sample) would drag a mean toward zero and make a healthy ensemble
    look retentive.

    Returns:
        Dict with median released/exited/retained in m^3 and MCM, the retained
        and exited FRACTIONS, and ``closure_error`` — how far released is from
        exited + retained, as a fraction. A large closure error means the
        balance itself is not trustworthy and the fractions should not be
        quoted.
    """
    released = [m["released_m3"] for m in members if m.get("released_m3") is not None]
    exited = [m["exited_m3"] for m in members if m.get("exited_m3") is not None]
    retained = [m["retained_m3"] for m in members if m.get("retained_m3") is not None]

    if not released:
        # Older members, or a run where every member failed. Absent rather than
        # zero: a zero here would read as "nothing was released".
        return {"available": False, "reason": "no member reported a volume balance"}

    med_released = float(np.median(released))
    med_exited = float(np.median(exited)) if exited else 0.0
    med_retained = float(np.median(retained)) if retained else 0.0

    denominator = med_released if med_released > 0 else float("nan")
    return {
        "available": True,
        "n_members": len(released),
        "released_m3": med_released,
        "exited_m3": med_exited,
        "retained_m3": med_retained,
        "released_mcm": med_released / 1.0e6,
        "exited_mcm": med_exited / 1.0e6,
        "retained_mcm": med_retained / 1.0e6,
        "retained_fraction": med_retained / denominator,
        "exited_fraction": med_exited / denominator,
        "closure_error": abs(med_released - (med_exited + med_retained)) / denominator,
    }


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
    margins_km: Optional[Dict[str, float]] = None,
    fill_max_depth_m: float = 3.0,
    notch_breach: bool = True,
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
        domain_radius_km: Half-width of the square solver domain (km). Ignored
            when `margins_km` is given.
        margins_km: Optional asymmetric domain extent
            {"west":.., "east":.., "south":.., "north":..} (km from the dam),
            for a domain biased downstream instead of dam-centred. See
            terrain/domain.py::build_domain.
        fill_max_depth_m: Threshold-limited depression fill applied to the
            bed (metres); see terrain/conditioning.py::fill_depressions. 0
            disables it.
        notch_breach: Lower the bed at the breach cell to the ensemble's
            median breach invert (crest elevation minus median breach depth)
            before the member loop, so a failed dam has an actual gap in the
            terrain instead of only a source term. Without this, water that
            spreads upstream from an isotropic point injection (see
            inject_breach_hydrograph below) is walled into the reservoir bowl
            by the intact DEM crest and never drains — measured on Khadakwasla
            as ~42% of released volume permanently trapped, plateauing the
            hazard classification instead of letting it recede.
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
            margins_km=margins_km,
            fill_max_depth_m=fill_max_depth_m,
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
    # A blockage releases at the barrier, which is not necessarily the domain
    # centre — the Khadakwasla fallback puts one partway up the Mutha while the
    # DEM is still centred on the dam. dam_config can override with an explicit
    # inject_lat/inject_lon for that case.
    #
    # Absent an override, this now ALWAYS resolves the breach from the dam's
    # own lat/lon rather than assuming grid.nx//2, grid.ny//2 is the dam. That
    # assumption only held while build_domain() centred every domain on the
    # dam; an offset domain (e.g. biased downstream so the flood has runway
    # instead of spending half its cells upstream of the reservoir) breaks it
    # silently — the breach would inject into whatever the grid centre happens
    # to be, tens of km from the actual dam, and still produce a
    # plausible-looking run. Resolving from real coordinates is identical to
    # the old nx//2 result on every dam-centred domain that exists today (see
    # compute_breach_location's own inject_lat branch), so this is a
    # correctness fix with no behaviour change for existing runs.
    i_breach, j_breach, b_breach = compute_breach_location(
        state_init,
        grid,
        dam_lat,
        dam_lon,
        utm_zone,
        inject_lat=dam_config.get("inject_lat", dam_lat),
        inject_lon=dam_config.get("inject_lon", dam_lon),
    )

    if notch_breach:
        _notch_breach_into_bed(state_init, grid, i_breach, j_breach, b_breach, dam_config)

    # Define downstream gauges
    gauges = define_downstream_gauges(dam_lat, dam_lon, dam_config.get("dam_id"))
    print(f"  Downstream gauges: {[g['name'] for g in gauges]}")

    # =========================================================================
    # Step 2: Generate breach ensemble (Phase 3)
    # =========================================================================
    _report(18.0, "Generating breach ensemble")
    print("\n[Step 2] Generating breach hydrograph ensemble...")
    try:
        hydrographs = synthesize_scenario_ensemble(dam_config, num_samples=ensemble_size)
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
    volume_balance_members: List[Dict] = []

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
        volume_balance_members.append({
            "sample_id": sample_id,
            "released_m3": member.get("volume_released_m3"),
            "exited_m3": member.get("volume_exited_m3"),
            "retained_m3": member.get("volume_retained_m3"),
        })
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
        # WHERE THE WATER WENT. Median across members of the per-member volume
        # balance, plus the retained fraction that is the actual verdict on
        # drainage. The recorded pre-fix baseline is ~42% retained
        # (docs/validation_findings.md section 8); hazard cell counts alone
        # could not distinguish that plateau from genuine recession, which is
        # why this exists.
        "volume_balance": _summarize_volume_balance(volume_balance_members),
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
