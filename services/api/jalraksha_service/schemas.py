"""Pydantic request/response schemas for the JalRaksha REST API (brief §5.1)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class RunRequest(BaseModel):
    """POST /runs payload. Either a dam_id preset or explicit lat/lon geometry."""
    dam_id: Optional[str] = Field(None, description="Preset dam id (tehri, bhakra, ...)")
    lat: Optional[float] = Field(None, description="Dam latitude (deg)")
    lon: Optional[float] = Field(None, description="Dam longitude (deg)")
    height_m: Optional[float] = Field(None, description="Dam height (m)")
    storage_mm3: Optional[float] = Field(None, description="Gross storage (MCM)")
    dam_type: str = "embankment"
    failure_mode: str = "overtopping"
    breach_mode: str = "central"
    ensemble_size: int = Field(100, ge=1, le=10000)
    solver: str = Field("swe", description="swe | delft3d | both")
    solver_duration_s: float = Field(
        1800.0, gt=0,
        description="Simulated time (s). Compute cost scales with this — 1800 s "
                    "(30 min) keeps a demo run responsive; the pipeline's own "
                    "default of 10800 s is a ~35 min compute per member at 200 m.",
    )
    target_resolution: float = Field(200.0, gt=0, description="Grid resolution (m)")
    breach_formation_time_s: Optional[float] = Field(
        None, gt=0,
        description="Breach formation time (s). Controls how ABRUPT the release "
                    "is — a short value is the flash-flood / rapid-failure "
                    "scenario. None uses the module default (~27 min). This is "
                    "an assumption, not a derived value, and travels into every "
                    "member's metadata as failure_time_assumed.",
    )

    def to_dam_config(self) -> Dict[str, Any]:
        if self.dam_id:
            from jalraksha_service.config import settings
            preset = next((d for d in settings.DEMO_DAMS if d["id"] == self.dam_id), None)
            if preset is None:
                raise ValueError(f"Unknown dam_id: {self.dam_id}")
            cfg = dict(preset)
            # The registry key is `id` on the wire but `dam_id` in a dam_config
            # — define_downstream_gauges and rapid_estimate both look for the
            # latter to find this dam's own corridor.
            cfg["dam_id"] = cfg.pop("id", self.dam_id)
            # Not solver inputs; they would ride along into breach.py otherwise.
            domain_radius_km = cfg.pop("domain_radius_km", None)
            cfg.pop("gauges", None)
            if domain_radius_km is not None:
                cfg["domain_radius_km"] = domain_radius_km
            # surface_area_km2 is left IN cfg deliberately — unlike gauges and
            # the domain radius it is a real solver input, read by
            # reservoir_storage_curve. Drop it when unknown so breach.py's own
            # `surface_area_km2=None` fallback path is unchanged for dams
            # that do not have one.
            if cfg.get("surface_area_km2") is None:
                cfg.pop("surface_area_km2", None)
            # A preset can be published without vetted structural figures (see
            # DamPreset's docstring). The solver's breach regressions cannot run
            # on None, so refuse here with a message naming exactly what is
            # missing, mirroring jalraksha.presets.PresetError. submit_run turns
            # ValueError into a 422.
            #
            # This also replaces a real crash: the two lines below do
            # float(cfg.get("height_m", 100)), and .get's default only fires on a
            # MISSING key — a present-but-None value raised TypeError and
            # surfaced as an opaque HTTP 500.
            unvetted = [
                field for field in ("height_m", "storage_mm3", "dam_type")
                if cfg.get(field) is None
            ]
            if unvetted:
                raise ValueError(
                    f"{cfg.get('name', self.dam_id)} has no vetted value for "
                    f"{', '.join(unvetted)}. These are required by the breach "
                    f"regressions. Per CLAUDE.md, unvetted coefficients must not "
                    f"be guessed — supply a primary CWC / dam-authority source "
                    f"before running the solver for this dam. Terrain and "
                    f"reservoir visualization do not need them."
                )
        else:
            if None in (self.lat, self.lon, self.height_m, self.storage_mm3):
                raise ValueError("Provide dam_id or all of lat/lon/height_m/storage_mm3")
            cfg = {
                "name": "Custom", "lat": self.lat, "lon": self.lon,
                "height_m": self.height_m, "storage_mm3": self.storage_mm3,
            }
        cfg["dam_type"] = self.dam_type
        # NOTE ON failure_mode: it reaches ONE function,
        # xu_zhang_2009_peak_outflow, and xu_zhang is not in
        # DEFAULT_REGRESSION_FAMILIES while its coefficients are unverified. So
        # this field currently changes nothing in a default ensemble. The
        # parameter that does change the character of the release is
        # breach_formation_time_s below.
        cfg["failure_mode"] = self.failure_mode
        if self.breach_formation_time_s is not None:
            cfg["breach_formation_time_s"] = float(self.breach_formation_time_s)
        cfg["breach_bottom_elev_m"] = max(0.0, float(cfg.get("height_m", 100)) * 0.1)
        cfg["initial_surface_elev_m"] = float(cfg.get("height_m", 100))
        return cfg


class RunStatus(BaseModel):
    run_id: str
    status: str  # queued | running | done | failed
    progress_pct: float = 0.0
    # What the run is doing right now, e.g. "Solving member 12/30". Until this
    # existed the only status writes were 5% at submission and 100% at the end,
    # so every run displayed a frozen "running 5%" for its whole duration -
    # indistinguishable from a hang, and reported as one.
    phase: Optional[str] = None
    solver: str
    created_at: Optional[str] = None
    error: Optional[str] = None


class GaugeResult(BaseModel):
    """
    One downstream gauge's outcome for a run.

    arrival_p05_s / arrival_p95_s are the ensemble's 5th-95th band. They were
    computed by compute_arrival_times_at_gauges from the first day and dropped
    before persistence, so the dashboard could only show a bare median - an
    ensemble result presented as if it were a single deterministic number.

    `note` carries the reason a gauge has no arrival ("Gauge lies outside the
    solver domain..."), which is the difference between "the flood did not get
    there" and "we did not simulate that far".
    """

    gauge_name: str
    distance_km: float
    arrival_time_s: Optional[float] = None
    arrival_p05_s: Optional[float] = None
    arrival_p95_s: Optional[float] = None
    max_depth_m: Optional[float] = None
    par_estimate: Optional[float] = None
    note: Optional[str] = None


class ExportRef(BaseModel):
    """
    One downloadable product of a run.

    `kind` is prefixed by product family so a client can group without parsing
    filenames (jalraksha.run.write_export_products is the producer):

      cog_<var>_<pct>       Cloud-Optimized GeoTIFF, e.g. cog_h_max_median,
                            cog_v_max_p95, cog_t_arrival_median
      shp_*_zip             zipped ESRI Shapefile bundle (.shp/.shx/.dbf/.prj),
                            e.g. shp_inundation_zip, shp_hazard_extreme_zip,
                            shp_arrival_contours_zip
      kml_*                 KML in WGS84, e.g. kml_inundation, kml_animation
      kmz_*                 KMZ bundle, e.g. kmz_depth_overlay
      keyframe_manifest     2D/3D playback manifest
      xdmf                  ParaView 3D dataset
      comparison_metrics    SPH vs Delft3D-class comparison JSON

    Shapefiles are published zipped on purpose: a bare .shp carries neither
    attributes (.dbf) nor a CRS (.prj), so serving one alone is not a usable
    download.
    """

    kind: str
    path_or_url: str


class EnsembleSummary(BaseModel):
    """
    The breach ensemble's own statistics.

    Every field here was computed by run_dam_break_ensemble and then discarded
    when the task returned. Peak outflow and its 5th-95th band, the breach
    formation time, which published regressions were used and how many members
    converged are the numbers that make an ensemble run defensible - and none
    of them could be seen from the browser.

    num_completed vs num_ensemble matters more than it looks: a run where 3 of
    100 members converged was indistinguishable from one where all 100 did.
    """

    q_peak_median_m3s: Optional[float] = None
    q_peak_p05_m3s: Optional[float] = None
    q_peak_p95_m3s: Optional[float] = None
    q_peak_mean_m3s: Optional[float] = None
    q_peak_std_m3s: Optional[float] = None
    t_fail_median_s: Optional[float] = None
    t_fail_p05_s: Optional[float] = None
    t_fail_p95_s: Optional[float] = None
    regressions_used: List[str] = Field(default_factory=list)
    num_samples: Optional[int] = None
    num_completed: Optional[int] = None
    num_ensemble: Optional[int] = None
    h_max_stats: Optional[Dict[str, Any]] = None
    dam_class_outside_fitted_population: Optional[bool] = None
    dam_class_note: Optional[str] = None
    dam_type: Optional[str] = None


class GridSummary(BaseModel):
    """
    Solver grid geometry, so a client can georeference what it downloads.

    Previously this existed only inside the XDMF/HDF5 written for ParaView,
    which meant the browser had no way to place a raster it fetched.
    """

    nx: Optional[int] = None
    ny: Optional[int] = None
    dx: Optional[float] = None
    dy: Optional[float] = None
    x0: Optional[float] = None
    y0: Optional[float] = None
    crs: Optional[str] = None
    bounds_wgs84: Optional[List[float]] = None


class EngineInfo(BaseModel):
    """
    Which engine actually produced these numbers.

    delft3d_binary_used is the field the naming rule in CLAUDE.md turns on: True
    means it IS Delft3D FM and may be named as such; False means the built-in
    solver ran and `fallback_reason` says why. The dashboard must never present
    the second case as the first, so this travels with every result rather than
    being inferred from the requested solver.
    """

    name: Optional[str] = None
    label: Optional[str] = None
    delft3d_binary_used: Optional[bool] = None
    fallback_reason: Optional[str] = None


class RunResult(BaseModel):
    run_id: str
    dam_name: str
    exports: List[ExportRef]
    keyframe_manifest_url: Optional[str] = None
    gauges: List[GaugeResult]
    hazard_summary: Optional[Dict[str, Any]] = None
    ensemble: Optional[EnsembleSummary] = None
    grid: Optional[GridSummary] = None
    engine: Optional[EngineInfo] = None
    impact: Optional[Dict[str, Any]] = None
    sph: Optional[Dict[str, Any]] = None
    rapid_estimate: Optional[Dict[str, Any]] = None
    solver: Optional[str] = None
    status: Optional[str] = None
    # Why a run failed. Previously the reason existed only in the Celery task's
    # return value, which nothing reads, so a failed run was a dead end in the UI.
    error: Optional[str] = None
    # Domain-wide population at risk, from GHSL census counts over this run's
    # own grid. `available: false` with a `reason` when no population grid could
    # be obtained — no headcount is ever invented to fill the gap.
    population_at_risk: Optional[Dict[str, Any]] = None
    comparison_url: Optional[str] = None


class RunListEntry(BaseModel):
    """One row of GET /runs - the dashboard's run picker."""

    run_id: str
    dam_id: Optional[str] = None
    dam_name: Optional[str] = None
    status: str
    solver: Optional[str] = None
    created_at: Optional[str] = None
    export_count: int = 0
    gauge_count: int = 0
    error: Optional[str] = None


class GeeStatus(BaseModel):
    """
    GET /gee/status - whether Earth Engine is usable, and if not, why.

    `reason` is Earth Engine's own message passed through verbatim (or this
    project's own "JALRAKSHA_GEE_PROJECT is not set..." text, which names the
    exact variable and the free registration URL). It is written to be shown to
    a person, so render it rather than mapping it to a generic string.
    """

    available: bool
    reason: Optional[str] = None
    project: Optional[str] = None


class ValidationCheck(BaseModel):
    """
    One validation gate.

    `passed` is the headline; `detail` carries the measured value against the
    threshold so a viewer can see HOW well it passed, not merely that a badge
    is green. `series` is populated only for checks that have a curve to draw
    (Ritter), and holds x plus one array per engine.
    """

    name: str
    passed: Optional[bool] = None
    detail: Optional[str] = None
    metrics: Optional[Dict[str, Any]] = None
    series: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class ValidationResult(BaseModel):
    """
    GET /validation.

    `status` is "running" while the gates execute on a background thread and
    "done" once a result exists. They are never run inside the request: they
    perform real solver work, including a Delft3D kernel launch, and holding
    the connection open for that returned nothing after 120 seconds when a
    simulation was competing for the machine.
    """

    checks: List[ValidationCheck] = Field(default_factory=list)
    generated_at: Optional[str] = None
    cached: bool = False
    status: str = "done"


class ComparisonResult(BaseModel):
    run_id: str
    metrics: Dict[str, Any] = Field(default_factory=dict)
    maps: List[ExportRef] = Field(default_factory=list)


class GaugePoint(BaseModel):
    """
    One downstream location in a dam's corridor, as published by GET /dams.

    Distinct from GaugeResult above: this is the STATIC geometry of a gauge
    (where it is), so the dashboard can draw markers and camera presets for the
    selected dam before any run exists. GaugeResult is the per-run OUTCOME
    (when the water arrived) and deliberately carries no coordinates.

    `note` exists because at least one real gauge needs a caveat attached to it
    — Baramati is inside Khadakwasla's domain but off its river — and a caveat
    that only lives in a Python comment never reaches the person reading the
    map.
    """

    name: str
    distance_km: float
    lat: float
    lon: float
    river: Optional[str] = None
    note: Optional[str] = None


class DamPreset(BaseModel):
    """
    One entry of GET /dams.

    height_m / storage_mm3 / dam_type are Optional because a dam can legitimately
    be *locatable* without having vetted structural figures: Khadakwasla is in the
    list so it can be found and its terrain visualized, but CLAUDE.md forbids
    guessing unvetted coefficients, and no primary CWC / Maharashtra WRD source
    exists for its height or storage. Publishing null is the honest answer.

    Optionality here affects DISPLAY only. RunRequest.to_dam_config refuses to
    build a solver config when any of the three is missing, so a null can never
    reach the breach regressions.
    """

    id: str
    name: str
    lat: float
    lon: float
    height_m: Optional[float] = None
    storage_mm3: Optional[float] = None
    dam_type: Optional[str] = None
    river: str
    state: str
    domain_radius_km: Optional[float] = None
    surface_area_km2: Optional[float] = None
    # Visualization settings, consumed server-side by open-paraview. Published
    # so the values actually in use are inspectable from the wire rather than
    # only visible by reading config.py — they were silently stripped before,
    # which made "is ParaView getting this dam's exaggeration?" unanswerable
    # without adding a print statement.
    vertical_exaggeration: Optional[float] = None
    nominal_depth_m: Optional[float] = None
    # Empty for a dam with no surveyed corridor (bhakra/idukki/hirakud). An
    # empty list is meaningful here and must not be filled with another dam's
    # towns — which is exactly what the dashboard did before this field existed.
    gauges: List[GaugePoint] = Field(default_factory=list)


class GeoSarResponse(BaseModel):
    """
    GET /gee/latest — the most recent OBSERVED water extent for a reach.

    `source` is the field that matters and is never guessed:
      sentinel1_grd  a live Earth Engine query returned this scene
      cached         a previously fetched real scene, served because the live
                     query could not run; `acquired_at` is still ITS date
      unavailable    nothing could be produced; `reason` says why

    There is no fourth state. Synthetic data is never returned here.

    `threshold_db` is Optional with NO default on purpose. It used to default to
    -17.0, which meant a request that fetched nothing still answered with a
    plausible-looking threshold. It is now populated only when a scene was
    actually thresholded, and the value is derived per scene by Otsu's method
    rather than assumed.

    NOTE ON NAMING: this is observed WATER, not observed FLOOD. Over Tehri on an
    ordinary day it is the reservoir and the river.
    """

    reach: str
    source: str = "unavailable"
    reason: Optional[str] = None
    scene_id: Optional[str] = None
    acquired_at: Optional[str] = None
    threshold_db: Optional[float] = None
    threshold_method: Optional[str] = None
    water_fraction: Optional[float] = None
    bbox: Optional[List[float]] = None
    observed_extent_url: Optional[str] = None
    geotiff_url: Optional[str] = None
    note: Optional[str] = None
