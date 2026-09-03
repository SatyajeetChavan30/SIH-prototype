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
    scenario_type: str = Field(
        "dam_break",
        description="dam_break | river_blockage | river_overflow",
    )
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
    domain_margins_km: Optional[Dict[str, float]] = Field(
        None,
        description="Optional asymmetric domain extent "
                    "{'west':.., 'east':.., 'south':.., 'north':..} (km from the "
                    "dam), for a domain deliberately biased downstream instead of "
                    "centred on the dam. Overrides the preset's domain_radius_km "
                    "entirely when given; the domain stays dam-centred otherwise.",
    )
    fill_max_depth_m: float = Field(
        3.0, ge=0,
        description="Threshold-limited depression fill applied to the DEM before "
                    "the solver runs (metres). Fills only pits shallower than this "
                    "-- resampling noise from bilinear downsampling of narrow "
                    "channels -- leaving genuine basins (reservoirs, lakes) "
                    "untouched. 0 disables it.",
    )
    notch_breach: bool = Field(
        True,
        description="Lower the bed at the breach cell to the dam-height invert "
                    "before the run, so a failed dam has an actual gap instead of "
                    "only a source term. Without this, water spreading upstream "
                    "from the isotropic point injection is walled into the "
                    "reservoir bowl by the intact DEM crest and never drains.",
    )
    breach_formation_time_s: Optional[float] = Field(
        None, gt=0,
        description="Breach formation time (s). Controls how ABRUPT the release "
                    "is — a short value is the flash-flood / rapid-failure "
                    "scenario. None uses the module default (~27 min). This is "
                    "an assumption, not a derived value, and travels into every "
                    "member's metadata as failure_time_assumed.",
    )

    # ── River blockage (landslide dam) ───────────────────────────────────────
    #
    # Meaningful ONLY when scenario_type == "river_blockage". Supplying them on
    # any other scenario is rejected rather than ignored: a request whose
    # parameters silently do nothing is the failure the breach module's own
    # comment about `failure_mode` complains about.
    #
    # Note what is NOT here: storage. A landslide dam has no published gross
    # storage, so the impounded volume is measured from a hypsometric fill of
    # the updated DEM. jalraksha.terrain.breach refuses a blockage run whose
    # storage came from anywhere else.
    blockage_source: str = Field(
        "manual",
        description="manual | detect. 'manual' is the offline-first default: "
                    "the operator supplies the barrier. 'detect' asks Sentinel-1 "
                    "for a new water body first and may legitimately refuse over "
                    "steep terrain.",
    )
    blockage_lat: Optional[float] = Field(
        None, description="Barrier axis latitude (deg). NOT the dam."
    )
    blockage_lon: Optional[float] = Field(
        None, description="Barrier axis longitude (deg). NOT the dam."
    )
    blockage_crest_height_m: Optional[float] = Field(
        None, gt=0,
        description="Deposit crest height ABOVE THE VALLEY FLOOR (m), not an "
                    "absolute elevation. The two differ by a kilometre or more "
                    "in the Himalaya and both look plausible.",
    )
    blockage_width_m: Optional[float] = Field(
        None, gt=0, description="Deposit crest length ACROSS the valley (m)."
    )
    blockage_thickness_m: Optional[float] = Field(
        None, gt=0, description="Deposit extent ALONG the valley (m). Defaults to two cells."
    )
    blockage_breach_mode: str = Field(
        "overtop",
        description="overtop | full_notch. Changes the local cross-section, not "
                    "the released volume — that comes from the routing.",
    )
    blockage_date_pre: Optional[str] = Field(
        None, description="Pre-event window start for detection (YYYY-MM-DD)."
    )
    blockage_date_post: Optional[str] = Field(
        None, description="Post-event date for detection (YYYY-MM-DD)."
    )

    def to_dam_config(self) -> Dict[str, Any]:
        valid_scenarios = {"dam_break", "river_blockage", "river_overflow"}
        if self.scenario_type not in valid_scenarios:
            raise ValueError(
                f"Unsupported scenario_type {self.scenario_type!r}. "
                f"Choose from {sorted(valid_scenarios)}"
            )
        self._validate_blockage_fields()
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
            # A blockage site is exempt. It publishes no height, no gross storage
            # and no dam type BECAUSE a landslide deposit has none: the crest
            # height comes from the barrier spec and the storage from a
            # hypsometric fill of the updated DEM. Applying the dam refusal here
            # would 422 every blockage preset for correctly declining to invent
            # figures. The blockage fields are required instead, in
            # _validate_blockage_fields.
            if cfg.get("record_type") == "blockage":
                unvetted = []
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
            if self.scenario_type == "river_blockage":
                if None in (self.lat, self.lon):
                    raise ValueError(
                        "A custom river_blockage run needs lat/lon for the "
                        "domain centre. It does NOT need height_m or "
                        "storage_mm3: the barrier crest comes from "
                        "blockage_crest_height_m and the impounded volume is "
                        "measured from the updated DEM."
                    )
                cfg = {"name": "Landslide blockage", "lat": self.lat, "lon": self.lon}
            else:
                if None in (self.lat, self.lon, self.height_m, self.storage_mm3):
                    raise ValueError(
                        "Provide dam_id or all of lat/lon/height_m/storage_mm3"
                    )
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
        cfg["scenario_type"] = self.scenario_type
        if self.breach_formation_time_s is not None:
            cfg["breach_formation_time_s"] = float(self.breach_formation_time_s)

        if self.scenario_type == "river_blockage":
            # Deliberately NOT setting breach_bottom_elev_m /
            # initial_surface_elev_m from height_m here. Those two lines are
            # dam-break assumptions — a breach invert a tenth of the way up the
            # wall, a reservoir surface at the crest — and for a blockage the
            # true values are the barrier crest and the valley floor, absolute
            # elevations that are not known until the DEM has been read. Setting
            # them from a dam preset's height would route a landslide lake
            # against the wrong structure's geometry and still look reasonable.
            # tasks.py fills them from the burned geometry's provenance.
            cfg.update(
                {
                    "blockage_source": self.blockage_source,
                    "blockage_lat": self.blockage_lat,
                    "blockage_lon": self.blockage_lon,
                    "blockage_crest_height_m": self.blockage_crest_height_m,
                    "blockage_width_m": self.blockage_width_m,
                    "blockage_thickness_m": self.blockage_thickness_m,
                    "blockage_breach_mode": self.blockage_breach_mode,
                    "blockage_date_pre": self.blockage_date_pre,
                    "blockage_date_post": self.blockage_date_post,
                    # Refused by breach._synthesize_blockage_ensemble until
                    # tasks.py replaces it with a measured volume. The marker is
                    # the point: an absent storage_source is also refused, so a
                    # future refactor that drops this line fails loudly instead
                    # of quietly letting a slider set the outburst volume.
                    "storage_source": "hypsometric_fill_pending",
                }
            )
            # Storage from the request is meaningless for a landslide dam and
            # must not survive into the ensemble.
            cfg.pop("storage_mm3", None)
            cfg.pop("surface_area_km2", None)
            return cfg

        cfg["breach_bottom_elev_m"] = max(0.0, float(cfg.get("height_m", 100)) * 0.1)
        cfg["initial_surface_elev_m"] = float(cfg.get("height_m", 100))
        return cfg

    def _validate_blockage_fields(self) -> None:
        """
        Blockage parameters are required for a blockage and rejected elsewhere.

        Rejecting rather than ignoring: a request carrying a barrier position
        that changes nothing is worse than one that fails, because the operator
        has no way to tell which happened.
        """
        blockage_fields = {
            "blockage_lat": self.blockage_lat,
            "blockage_lon": self.blockage_lon,
            "blockage_crest_height_m": self.blockage_crest_height_m,
            "blockage_width_m": self.blockage_width_m,
            "blockage_thickness_m": self.blockage_thickness_m,
            "blockage_date_pre": self.blockage_date_pre,
            "blockage_date_post": self.blockage_date_post,
        }

        if self.scenario_type != "river_blockage":
            supplied = sorted(k for k, v in blockage_fields.items() if v is not None)
            if supplied or self.blockage_source != "manual":
                raise ValueError(
                    f"Blockage parameters were supplied on a "
                    f"{self.scenario_type!r} run, where they do nothing: "
                    f"{supplied or ['blockage_source']}. Set "
                    f"scenario_type='river_blockage' to use them."
                )
            return

        if self.blockage_source not in ("manual", "detect"):
            raise ValueError(
                f"blockage_source must be 'manual' or 'detect', got "
                f"{self.blockage_source!r}."
            )

        if self.blockage_breach_mode not in ("overtop", "full_notch"):
            raise ValueError(
                f"blockage_breach_mode must be 'overtop' or 'full_notch', got "
                f"{self.blockage_breach_mode!r}."
            )

        if self.blockage_source == "manual":
            missing = [
                name
                for name in (
                    "blockage_lat", "blockage_lon",
                    "blockage_crest_height_m", "blockage_width_m",
                )
                if blockage_fields[name] is None
            ]
            if missing:
                raise ValueError(
                    f"A manual river_blockage run needs the barrier geometry. "
                    f"Missing: {', '.join(missing)}. The barrier is not the dam, "
                    f"so none of it can be taken from the preset."
                )

        # A barrier narrower than a couple of grid cells is a mesh artefact: its
        # outflow would be set by the grid spacing rather than by the deposit.
        # Caught here, at submission, rather than twenty minutes into a run.
        if self.blockage_width_m is not None:
            min_width_m = 2.0 * float(self.target_resolution)
            if float(self.blockage_width_m) < min_width_m:
                cells = float(self.blockage_width_m) / float(self.target_resolution)
                raise ValueError(
                    f"blockage_width_m={self.blockage_width_m:g} m spans only "
                    f"{cells:.1f} cells at {self.target_resolution:g} m "
                    f"resolution. A barrier narrower than {min_width_m:g} m "
                    f"cannot be resolved on this grid — widen the deposit or "
                    f"refine target_resolution."
                )


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
    scenario_type: Optional[str] = None


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
    # Present only when the terrain was modified for this run. Folded into the
    # result rather than served from its own endpoint so a panel cannot forget
    # to fetch it: the dashboard MUST label a run whose DEM was rebuilt, and the
    # 3D view shows the modified terrain whether or not anything says so.
    dem_update: Optional[Dict[str, Any]] = None
    dem_used: Optional[str] = None


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


class BlockageDetectionResponse(BaseModel):
    """
    GET /gee/blockage — has a new water body appeared on this reach.

    Mirrors GeoSarResponse's contract, including its rule: THERE IS NO FOURTH
    STATE. Either a live scene pair was differenced, or a previously fetched
    detection is served from cache, or the request is refused with a reason.
    Nothing here fabricates a lake, and no field is filled with a plausible
    default when the underlying measurement was not made.

    A refusal over steep terrain is an ordinary outcome, not an error: the
    manual barrier path runs fully offline and is the demo's guaranteed floor.
    """

    reach: str
    source: str = "unavailable"  # sentinel1_change_detection | cached | unavailable
    reason: Optional[str] = None
    # The POST scene's own identity. A single scene, not a composite — that is
    # what lets the DEM provenance name the acquisition it was built from.
    scene_id_post: Optional[str] = None
    acquired_at_post: Optional[str] = None
    date_pre_start: Optional[str] = None
    date_pre_end: Optional[str] = None
    # Derived per scene, not once for the pair: orbit, incidence angle and soil
    # moisture differ between acquisitions.
    threshold_db_pre: Optional[float] = None
    threshold_db_post: Optional[float] = None
    threshold_method: Optional[str] = None
    # The transplanted gate. Measured on the PRE scene's total water, never on
    # the difference — a new lake is definitionally absent from JRC permanent
    # water, so that gate on the difference would reject every true positive.
    precision_of_pre_mask_vs_jrc: Optional[float] = None
    recall_of_pre_mask_vs_jrc: Optional[float] = None
    new_water_fraction: Optional[float] = None
    fraction_near_drainage: Optional[float] = None
    # An independent construction of the same quantity, reported for comparison
    # rather than enforced.
    amplitude_form_fraction: Optional[float] = None
    amplitude_threshold_db: Optional[float] = None
    bbox: Optional[List[float]] = None
    mask_geotiff_url: Optional[str] = None
    mask_png_url: Optional[str] = None
    # NOTE: no per-candidate list. The detector produces a MASK; scoring each
    # patch individually would need the DEM inside the Earth Engine call, which
    # crosses this package's layering boundary. Fields that are always empty
    # look like a feature that is broken rather than one that was not built, so
    # they are absent rather than present-and-empty.
    note: Optional[str] = None


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

    # ── Scenario capability and blockage-site fields ─────────────────────────
    #
    # Declared here BECAUSE FastAPI's response_model silently strips anything a
    # model does not name. config.py published these and the dashboard never saw
    # them: every site fell back to "models all scenarios", which is the same
    # behaviour the hard-pin bug produced and just as invisible.
    #
    # "dam" | "blockage". A blockage site publishes no height, storage or dam
    # type by nature, and this is what tells to_dam_config to skip the
    # vetted-figures refusal rather than 422 the record for being correct.
    record_type: Optional[str] = None
    # Which incidents this site can model, so the scenario selector can be gated
    # per site instead of pinning every river scenario to one dam.
    scenario_types: Optional[List[str]] = None
    # Published barrier dimensions, when any exist. Both are None for Rishi
    # Ganga: no crest height or width is published for the 2021 blockage, and
    # the record declines to invent them.
    blockage_crest_height_m: Optional[float] = None
    blockage_width_m: Optional[float] = None
    # Sentinel-1 change-detection window for this site's event.
    blockage_date_pre: Optional[str] = None
    blockage_date_post: Optional[str] = None
    # A TERRAIN-DERIVED starting position for the operator, not a surveyed
    # deposit location. Separate from lat/lon, which is the reach centre and can
    # legitimately sit on high ground.
    suggested_barrier_lat: Optional[float] = None
    suggested_barrier_lon: Optional[float] = None
    note: Optional[str] = None


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
