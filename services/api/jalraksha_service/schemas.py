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
    kind: str  # geotiff | shapefile | kml | keyframe_manifest | terrain_tileset
    path_or_url: str


class RunResult(BaseModel):
    run_id: str
    dam_name: str
    exports: List[ExportRef]
    keyframe_manifest_url: Optional[str] = None
    gauges: List[GaugeResult]
    hazard_summary: Optional[Dict[str, Any]] = None
    comparison_url: Optional[str] = None


class ComparisonResult(BaseModel):
    run_id: str
    metrics: Dict[str, Any] = Field(default_factory=dict)
    maps: List[ExportRef] = Field(default_factory=list)


class DamPreset(BaseModel):
    id: str
    name: str
    lat: float
    lon: float
    height_m: float
    storage_mm3: float
    dam_type: str
    river: str
    state: str


class GeoSarResponse(BaseModel):
    reach: str
    observed_extent_url: Optional[str] = None
    threshold_db: float = -17.0
    acquired_at: Optional[str] = None
    note: str = "Stub — promote gee/sar.py to live Sentinel-1 GRD (brief §5.6)."
