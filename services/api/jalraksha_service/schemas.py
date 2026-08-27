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

    def to_dam_config(self) -> Dict[str, Any]:
        if self.dam_id:
            from jalraksha_service.config import settings
            preset = next((d for d in settings.DEMO_DAMS if d["id"] == self.dam_id), None)
            if preset is None:
                raise ValueError(f"Unknown dam_id: {self.dam_id}")
            cfg = dict(preset)
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
        cfg["failure_mode"] = self.failure_mode
        cfg["breach_bottom_elev_m"] = max(0.0, float(cfg.get("height_m", 100)) * 0.1)
        cfg["initial_surface_elev_m"] = float(cfg.get("height_m", 100))
        return cfg


class RunStatus(BaseModel):
    run_id: str
    status: str  # queued | running | done | failed
    progress_pct: float = 0.0
    solver: str
    created_at: Optional[str] = None


class GaugeResult(BaseModel):
    gauge_name: str
    distance_km: float
    arrival_time_s: Optional[float] = None
    max_depth_m: Optional[float] = None
    par_estimate: Optional[float] = None


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


class RunResult(BaseModel):
    run_id: str
    dam_name: str
    exports: List[ExportRef]
    keyframe_manifest_url: Optional[str] = None
    gauges: List[GaugeResult]
    hazard_summary: Optional[Dict[str, Any]] = None
    # Domain-wide population at risk, from GHSL census counts over this run's
    # own grid. `available: false` with a `reason` when no population grid could
    # be obtained — no headcount is ever invented to fill the gap.
    population_at_risk: Optional[Dict[str, Any]] = None
    comparison_url: Optional[str] = None


class ComparisonResult(BaseModel):
    run_id: str
    metrics: Dict[str, Any] = Field(default_factory=dict)
    maps: List[ExportRef] = Field(default_factory=list)


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
