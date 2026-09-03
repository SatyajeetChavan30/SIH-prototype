"""
Observation-conditioned DEM update for a landslide-dammed river — Phase 2.

WHAT THIS IS, IN ONE SENTENCE

Copernicus GLO-30 with a landslide barrier burned into it, written as a new
GeoTIFF that says so in its own metadata.

WHAT THIS IS NOT

It is not photogrammetry, not InSAR, and not an elevation surface derived from
imagery. Those are the obvious readings of "rebuild the DEM from live satellite
images", and none of them is achievable on this project's data policy:

  * Stereo optical pairs (Cartosat, Pleiades, WorldView) are the only practical
    route to a post-event DSM at this scale, and they are geo-fenced or
    commercial. CLAUDE.md forbids CartoDEM and Bhuvan outright.
  * Sentinel-1 INTERFEROMETRY would work in principle, but Earth Engine carries
    only GRD, not SLC. Producing an SLC interferogram means SNAP or ISCE,
    offline, at hours per pair — against a demo-day assumption of no network.
  * Optical stereo from Sentinel-2 does not exist: it is a single-look sensor.

So the DEM is UPDATED rather than regenerated. The satellite supplies WHERE the
new water is; the stale DEM supplies HOW HIGH the ground is; the barrier
geometry — operator-supplied or derived from the detected lake's outlet —
supplies what changed. Every product written here carries
``JALRAKSHA_NOT_A_SURVEY`` stating exactly that, because the file outlives this
docstring and may reach someone who never read it.

Do not "improve" this into a photogrammetry path. The constraint is a data
licence, not a missing algorithm.

TWO IMPLEMENTATION DECISIONS WORTH KNOWING

1. DELTA-ADD, NOT ROUND-TRIP. The geometry is computed in the solver's metric
   UTM grid, but only the CHANGE is reprojected back and added to the untouched
   source raster. Reprojecting the whole DEM to UTM and back would resample
   every pixel through two bilinear passes and smooth the channel — the same
   effect ``load_dem_as_grid``'s smoothing table measures at tens of metres of
   valley-floor error. With delta-add, every pixel outside the barrier footprint
   stays BIT-IDENTICAL to the Copernicus source, which is both more honest and
   trivially testable.

2. CONTENT-ADDRESSED FILENAMES, NO TTL. The cache has no date-based staleness
   concept anywhere in this repo and should not grow one: a TTL invents a policy
   nobody can cite, and it would cold-start warm caches on demo day against the
   offline-first rule. Instead the filename carries a hash of every input,
   including the source DEM's MD5, so a changed input produces a different file
   and an unchanged one is reused.

   Updated products are written to a SUBDIRECTORY of the DEM cache, never
   alongside the clipped originals. ``jalraksha.cache.get_cached_dem`` ends in a
   sorted glob over ``dem_{lat:.2f}_{lon:.2f}*.tif`` and returns the first
   match, so a file named ``dem_30.38_79.73_blockage.tif`` would sort ahead of
   ``..._clipped.tif`` and silently become the DEM for every run at that
   location — including ordinary dam-break runs.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import warnings
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import numpy as np
import rasterio
from affine import Affine
from rasterio.warp import Resampling, reproject

from jalraksha.terrain.blockage import (
    VOLUME_DATUM,
    BlockageError,
    build_blockage_geometry,
)
from jalraksha.terrain.conditioning import load_dem_as_grid

#: Subdirectory of the DEM cache that updated products are written to. Never
#: the cache root — see this module's docstring, decision 2.
UPDATED_SUBDIR = "updated"

#: The sentence that travels with every file this module writes.
NOT_A_SURVEY_NOTICE = (
    "NOT photogrammetry, NOT InSAR, NOT an elevation surface derived from "
    "imagery. This is Copernicus GLO-30 with a landslide barrier and, where an "
    "observation was available, an observed lake extent burned into it. Point "
    "elevations outside the modified footprint are unchanged Copernicus values; "
    "inside it they are a constructed geometry, not a measurement."
)

#: Observation provenance values. There is no fourth: a barrier is either
#: derived from a satellite scene, from a cached one, or supplied by an operator.
#: Nothing here ever synthesizes one.
OBSERVATION_SOURCES = ("sentinel1_grd", "cached", "manual_operator_input")


class DemUpdateError(Exception):
    """Raised when an observation-conditioned DEM cannot be written honestly."""


@dataclass(frozen=True)
class BlockageSpec:
    """
    The barrier an update is built from.

    ``crest_height_m`` is ABOVE THE VALLEY FLOOR, never an absolute elevation.
    The two differ by a kilometre or more in the Himalaya and both look like
    plausible numbers, so the distinction is carried in the field name and
    converted exactly once, inside ``blockage.burn_barrier``.
    """

    barrier_lat: float
    barrier_lon: float
    crest_height_m: float
    width_m: float
    thickness_m: Optional[float] = None
    breach_mode: str = "overtop"
    catchment_area_km2: Optional[float] = None
    direction_search_radius_cells: Tuple[int, int] = (5, 12)

    def __post_init__(self) -> None:
        if self.crest_height_m is None or float(self.crest_height_m) <= 0.0:
            raise DemUpdateError(
                f"crest_height_m must be a positive height above the valley "
                f"floor (got {self.crest_height_m!r})."
            )
        if self.width_m is None or float(self.width_m) <= 0.0:
            raise DemUpdateError(
                f"width_m must be a positive crest length across the valley "
                f"(got {self.width_m!r})."
            )
        if self.breach_mode not in ("overtop", "full_notch"):
            raise DemUpdateError(
                f"breach_mode must be 'overtop' or 'full_notch', got "
                f"{self.breach_mode!r}."
            )

    def fingerprint(self) -> str:
        """Stable string form, for the content hash."""
        return json.dumps(asdict(self), sort_keys=True, default=str)


@dataclass
class DemUpdateProvenance:
    """
    Everything a reader needs to judge an updated DEM, in one record.

    Written three ways on purpose: as GeoTIFF tags on the raster itself (so the
    file is self-describing wherever it ends up), as a JSON sidecar (so the
    stage-storage curve, which does not fit in a flat tag, survives), and into
    the run summary (so the dashboard can label what it is drawing).
    """

    product: str
    not_a_survey: str
    source_dem: str
    source_dem_md5: str
    source_dem_crs: str
    observation_source: str
    spec_hash: str
    created_at: str
    updated_dem: str = ""
    provenance_json: str = ""
    lake_mask: str = ""
    observation_scene_id: Optional[str] = None
    observation_acquired_at: Optional[str] = None
    observation_threshold_db: Optional[float] = None
    observation_collection: Optional[str] = None
    observation_bbox: Optional[list] = None
    detection_status: Optional[str] = None
    barrier: Dict[str, Any] = field(default_factory=dict)
    lake: Dict[str, Any] = field(default_factory=dict)
    stage_storage: Dict[str, Any] = field(default_factory=dict)
    indices: Dict[str, Any] = field(default_factory=dict)
    raster: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_geotiff_tags(self) -> Dict[str, str]:
        """
        Flatten to string tags. Nested structures are summarised, not dropped —
        the full record lives in the sidecar, but a raster that travels alone
        must still say what it is and what changed.
        """
        tags: Dict[str, str] = {
            "JALRAKSHA_PRODUCT": self.product,
            "JALRAKSHA_NOT_A_SURVEY": self.not_a_survey,
            "SOURCE_DEM": self.source_dem,
            "SOURCE_DEM_MD5": self.source_dem_md5,
            "SOURCE_DEM_CRS": self.source_dem_crs,
            "OBSERVATION_SOURCE": self.observation_source,
            "SPEC_HASH": self.spec_hash,
            "CREATED_AT": self.created_at,
            "VOLUME_DATUM": VOLUME_DATUM,
        }
        for key, value in (
            ("OBSERVATION_SCENE_ID", self.observation_scene_id),
            ("OBSERVATION_ACQUIRED_AT", self.observation_acquired_at),
            ("OBSERVATION_THRESHOLD_DB", self.observation_threshold_db),
            ("OBSERVATION_COLLECTION", self.observation_collection),
            ("OBSERVATION_BBOX", self.observation_bbox),
            ("DETECTION_STATUS", self.detection_status),
        ):
            if value is not None:
                tags[key] = str(value)

        for prefix, payload in (
            ("BARRIER", self.barrier),
            ("LAKE", self.lake),
            ("RASTER", self.raster),
        ):
            for key, value in payload.items():
                if value is None or isinstance(value, (dict, list)):
                    continue
                tags[f"{prefix}_{key}".upper()] = str(value)

        return tags


def _file_md5(path: Path) -> str:
    digest = hashlib.md5()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _spec_hash(
    spec: BlockageSpec, source_md5: str, observation: Optional[Dict[str, Any]]
) -> str:
    """
    Content address for one update.

    Covers the barrier geometry, the source DEM's own contents, and the identity
    of the observing scene. Change any of them and the filename changes; change
    none and the cached product is reused byte for byte.
    """
    payload = {
        "spec": spec.fingerprint(),
        "source_dem_md5": source_md5,
        "observation_source": (observation or {}).get("source", "manual_operator_input"),
        "observation_scene_id": (observation or {}).get("scene_id"),
        "observation_acquired_at": (observation or {}).get("acquired_at"),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True).encode("utf-8")
    ).hexdigest()


def _utm_north_up_affine(grid) -> Affine:
    """
    World transform for the solver grid, north-up.

    Duplicates ``jalraksha.export.georef.grid_affine`` deliberately: that module
    is Phase 5, and Phase 2 importing it would be a backwards dependency. The
    two conventions it encodes are load-bearing — x0/y0 are the domain's
    LOWER-LEFT CORNER, not a cell centre, and the solver is south-up while every
    raster format is north-up.
    """
    return Affine.translation(
        float(grid.x0), float(grid.y0) + int(grid.ny) * float(grid.dy)
    ) * Affine.scale(float(grid.dx), -float(grid.dy))


def updated_dem_path(
    out_dir: Path,
    barrier_lat: float,
    barrier_lon: float,
    domain_radius_km: float,
    observation_label: str,
    spec_hash: str,
) -> Path:
    """Content-addressed filename. See this module's docstring, decision 2."""
    stamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%d")
    return Path(out_dir) / (
        f"dem_{barrier_lat:.4f}_{barrier_lon:.4f}_r{domain_radius_km:g}km"
        f"_obscond_{observation_label}_{stamp}_{spec_hash[:8]}.tif"
    )


def cache_key(
    barrier_lat: float, barrier_lon: float, domain_radius_km: float, spec_hash: str
) -> str:
    """Cache registry key, mirroring ``jalraksha.dem.fetch_dem``'s product key."""
    return (
        f"jalraksha://dem/observation-conditioned/"
        f"{barrier_lat:.4f}_{barrier_lon:.4f}/r{domain_radius_km:g}km/{spec_hash}"
    )


def write_observation_conditioned_dem(
    stale_dem_path: str | Path,
    spec: BlockageSpec,
    out_dir: str | Path,
    observation: Optional[Dict[str, Any]] = None,
    observed_water_mask: Optional[np.ndarray] = None,
    target_resolution: float = 100.0,
    domain_radius_km: float = 30.0,
    register_cache: bool = True,
) -> Tuple[Path, DemUpdateProvenance]:
    """
    Burn a landslide barrier into a DEM and write the result with provenance.

    Args:
        stale_dem_path: The pre-event Copernicus clip. Never modified.
        spec: Barrier geometry. ``crest_height_m`` is above the valley floor.
        out_dir: Directory for updated products — must NOT be the DEM cache
            root; see this module's docstring.
        observation: The satellite observation this update is conditioned on, as
            returned by the Sentinel-1 layer: ``source``, ``scene_id``,
            ``acquired_at``, ``threshold_db``, ``bbox``. ``None`` means the
            barrier was supplied by an operator, and the product is labelled
            ``manual_operator_input`` with no scene id anywhere in it.
        observed_water_mask: The detected lake, on the solver grid, when one
            exists. Used to CALIBRATE the crest and to score the modelled lake
            against what was seen — never to overwrite the bed.
        target_resolution: Grid resolution the geometry is computed at, metres.
        domain_radius_km: Half-width of the working domain, km.
        register_cache: Register the product so a repeat spec is served offline.

    Returns:
        (path_to_updated_geotiff, provenance).
    """
    stale_dem_path = Path(stale_dem_path)
    out_dir = Path(out_dir)
    if not stale_dem_path.exists():
        raise DemUpdateError(f"Source DEM not found: {stale_dem_path}")

    observation = dict(observation or {})
    observation_source = observation.get("source", "manual_operator_input")
    if observation_source not in OBSERVATION_SOURCES:
        raise DemUpdateError(
            f"Unknown observation source {observation_source!r}. Valid sources: "
            f"{list(OBSERVATION_SOURCES)}. There is no fourth state: a barrier "
            f"is derived from a live scene, from a cached one, or supplied by an "
            f"operator, and nothing here fabricates one."
        )
    if observation_source == "manual_operator_input" and observation.get("scene_id"):
        raise DemUpdateError(
            "An operator-supplied barrier carries a scene id. A manually placed "
            "barrier must never be labelled with a satellite scene: the label is "
            "what tells a reader whether anything was observed at all."
        )

    source_md5 = _file_md5(stale_dem_path)
    spec_hash = _spec_hash(spec, source_md5, observation)
    observation_label = (
        str(observation.get("scene_id") or observation_source)
        .replace("/", "_")
        .replace(" ", "_")[:40]
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    output_path = updated_dem_path(
        out_dir,
        spec.barrier_lat,
        spec.barrier_lon,
        domain_radius_km,
        observation_label,
        spec_hash,
    )
    sidecar_path = output_path.with_suffix(".provenance.json")

    if output_path.exists() and sidecar_path.exists():
        # Content-addressed, so an existing file with this name was built from
        # exactly these inputs. Offline-first: reuse rather than rebuild.
        provenance = DemUpdateProvenance(**json.loads(sidecar_path.read_text("utf-8")))
        print(f"[dem-update] Cache hit: {output_path.name}")
        return output_path, provenance

    # ── Geometry, in the solver's metric grid ────────────────────────────────
    grid, bed_elevation = load_dem_as_grid(
        str(stale_dem_path),
        spec.barrier_lat,
        spec.barrier_lon,
        target_resolution=target_resolution,
        domain_radius_km=domain_radius_km,
    )

    try:
        geometry = build_blockage_geometry(
            bed_elevation,
            grid,
            spec.barrier_lat,
            spec.barrier_lon,
            spec.crest_height_m,
            spec.width_m,
            thickness_m=spec.thickness_m,
            observed_water_mask=observed_water_mask,
            catchment_area_km2=spec.catchment_area_km2,
            direction_search_radius_cells=spec.direction_search_radius_cells,
        )
    except BlockageError as exc:
        raise DemUpdateError(
            f"The barrier geometry could not be constructed, so no updated DEM "
            f"was written: {exc}"
        ) from exc

    barrier = geometry.barrier
    updated_bed = barrier.bed_with_barrier

    if spec.breach_mode == "full_notch":
        updated_bed = _cut_notch(updated_bed, barrier, grid)

    delta_utm = updated_bed - bed_elevation

    # ── Delta-add back onto the untouched source ─────────────────────────────
    with rasterio.open(stale_dem_path) as src:
        profile = src.profile.copy()
        source_band = src.read(1)
        source_crs = src.crs
        source_transform = src.transform
        source_nodata = src.nodata

    delta_source_grid = np.zeros(source_band.shape, dtype=np.float64)
    reproject(
        # to_north_up: the solver is south-up, every raster format is not.
        source=np.ascontiguousarray(np.flipud(delta_utm)),
        destination=delta_source_grid,
        src_transform=_utm_north_up_affine(grid),
        src_crs=grid.crs,
        src_nodata=0.0,
        dst_transform=source_transform,
        dst_crs=source_crs,
        dst_nodata=0.0,
        # NEAREST, not bilinear. A bilinear pass would smear the barrier's edge
        # across neighbouring cells AND perturb pixels the barrier never touched,
        # which is exactly the bit-identical guarantee this design exists for.
        resampling=Resampling.nearest,
    )

    updated_band = source_band.astype(np.float64) + delta_source_grid
    if source_nodata is not None:
        # Never raise a nodata cell into a real-looking elevation.
        nodata_mask = source_band == source_nodata
        updated_band[nodata_mask] = source_nodata
        if np.any(nodata_mask & (delta_source_grid > 0)):
            warnings.warn(
                "Part of the barrier footprint falls on nodata in the source "
                "DEM and was not written. The domain may not cover the barrier."
            )

    changed = delta_source_grid > 0.0
    if not changed.any():
        raise DemUpdateError(
            "The barrier reprojected onto the source DEM without changing a "
            "single cell. Either the barrier lies outside the source raster or "
            "the two grids do not overlap; writing an 'updated' DEM identical to "
            "its source would be a product that claims a change it does not "
            "contain."
        )

    profile.update(
        {
            "driver": "GTiff",
            "count": 1,
            "dtype": profile.get("dtype", "float32"),
            "compress": "deflate",
        }
    )
    # A striped source carries block sizes GDAL rejects unless TILED=YES. Copying
    # the profile wholesale is right for everything else in it, so drop just the
    # two keys rather than rebuilding the profile and losing the source's CRS,
    # transform and nodata along with them.
    if not profile.get("tiled"):
        profile.pop("blockxsize", None)
        profile.pop("blockysize", None)

    provenance = _build_provenance(
        spec=spec,
        geometry=geometry,
        observation=observation,
        observation_source=observation_source,
        source_dem=stale_dem_path,
        source_md5=source_md5,
        source_crs=str(source_crs),
        spec_hash=spec_hash,
        changed_cells=int(changed.sum()),
        max_change_m=float(delta_source_grid.max()),
        grid=grid,
        target_resolution=target_resolution,
        domain_radius_km=domain_radius_km,
    )
    provenance.updated_dem = str(output_path)
    provenance.provenance_json = str(sidecar_path)

    with rasterio.open(str(output_path), "w", **profile) as dst:
        dst.write(updated_band.astype(profile["dtype"]), 1)
        dst.update_tags(**provenance.to_geotiff_tags())

    # The impounded lake as its own raster, on the source DEM's grid.
    #
    # A genuine product, not a debugging aid: it is the extent a satellite would
    # see once the barrier fills, it is the thing an operator compares a later
    # scene against, and it is what "how big is the lake" means on a map. Written
    # here rather than derived downstream because this is the only place the mask
    # exists — the provenance carries its area and volume, not its geometry.
    #
    # Nearest-neighbour, like the delta: a mask must stay a mask. Bilinear would
    # produce fractional membership at the shoreline and a polygon traced from it
    # would wander.
    lake_path = output_path.with_name(output_path.stem + "_lake.tif")
    lake_source_grid = np.zeros(source_band.shape, dtype=np.uint8)
    reproject(
        source=np.ascontiguousarray(
            np.flipud(geometry.lake.mask.astype(np.uint8))
        ),
        destination=lake_source_grid,
        src_transform=_utm_north_up_affine(grid),
        src_crs=grid.crs,
        src_nodata=0,
        dst_transform=source_transform,
        dst_crs=source_crs,
        dst_nodata=0,
        resampling=Resampling.nearest,
    )
    lake_profile = dict(profile)
    lake_profile.update({"dtype": "uint8", "nodata": 0})
    with rasterio.open(str(lake_path), "w", **lake_profile) as dst:
        dst.write(lake_source_grid, 1)
        dst.update_tags(
            **{
                **provenance.to_geotiff_tags(),
                "JALRAKSHA_PRODUCT": "impounded_lake_extent",
                "JALRAKSHA_LAYER_MEANING": (
                    "1 = impounded behind the landslide barrier at the usable "
                    "crest. This is an INITIAL CONDITION constructed from terrain, "
                    "not a solver output and not an observed water extent."
                ),
            }
        )
    provenance.lake_mask = str(lake_path)

    sidecar_path.write_text(
        json.dumps(provenance.to_dict(), indent=2, default=str), encoding="utf-8"
    )

    if register_cache:
        _register(output_path, spec, domain_radius_km, spec_hash, out_dir, provenance)

    print(
        f"[dem-update] Wrote {output_path.name}: barrier "
        f"{barrier.crest_height_m:.1f} m x {barrier.width_m_final:.0f} m, "
        f"{provenance.raster['cells_modified']} cells modified, lake "
        f"{geometry.lake_volume_mm3:.2f} MCM over {geometry.lake_area_km2:.2f} km2 "
        f"({observation_source})"
    )
    return output_path, provenance


def _cut_notch(bed: np.ndarray, barrier, grid) -> np.ndarray:
    """
    Cut the barrier down to the valley floor along the flow line.

    The full-breach idealisation: the deposit is removed rather than eroded
    progressively. Changes the local cross-section, NOT the released volume —
    that comes from the routing against the stage-storage curve, which is
    computed before this is applied.
    """
    bed = bed.copy()
    ny, nx = bed.shape
    di, dj = barrier.flow_direction
    perp_i, perp_j = -dj, di

    # Narrower than the deposit: a notch is the opening water cuts through it,
    # not the removal of the whole landform.
    notch_halfwidth = max(1, barrier.halfwidth_cells // 4)
    for step in range(-barrier.thickness_cells - 1, barrier.thickness_cells + 2):
        for offset in range(-notch_halfwidth, notch_halfwidth + 1):
            i = int(round(barrier.i_barrier + step * di + offset * perp_i))
            j = int(round(barrier.j_barrier + step * dj + offset * perp_j))
            if 0 <= i < nx and 0 <= j < ny:
                bed[j, i] = min(bed[j, i], barrier.floor_elevation_m)
    return bed


def _build_provenance(
    *,
    spec: BlockageSpec,
    geometry,
    observation: Dict[str, Any],
    observation_source: str,
    source_dem: Path,
    source_md5: str,
    source_crs: str,
    spec_hash: str,
    changed_cells: int,
    max_change_m: float,
    grid,
    target_resolution: float,
    domain_radius_km: float,
) -> DemUpdateProvenance:
    barrier = geometry.barrier
    table = geometry.stage_storage

    return DemUpdateProvenance(
        product="observation_conditioned_dem_update",
        not_a_survey=NOT_A_SURVEY_NOTICE,
        source_dem=str(source_dem),
        source_dem_md5=source_md5,
        source_dem_crs=source_crs,
        observation_source=observation_source,
        spec_hash=spec_hash,
        created_at=_dt.datetime.now(_dt.timezone.utc).isoformat(),
        observation_scene_id=observation.get("scene_id"),
        observation_acquired_at=observation.get("acquired_at"),
        observation_threshold_db=observation.get("threshold_db"),
        observation_collection=observation.get("collection"),
        observation_bbox=observation.get("bbox"),
        detection_status=observation.get("detection_status"),
        barrier={
            "lat": spec.barrier_lat,
            "lon": spec.barrier_lon,
            "crest_height_m": barrier.crest_height_m,
            "crest_elevation_m": barrier.crest_elevation_m,
            "floor_elevation_m": barrier.floor_elevation_m,
            "width_m_requested": barrier.width_m_requested,
            "width_m_final": barrier.width_m_final,
            "halfwidth_growth_iterations": barrier.growth_iterations,
            "downstream_leak_cells": barrier.downstream_leak_cells,
            "volume_m3": barrier.barrier_volume_m3,
            "volume_plausible_for_a_natural_dam": (
                barrier.volume_is_plausible_for_a_natural_dam
            ),
            "breach_mode": spec.breach_mode,
        },
        lake={
            "volume_m3": table.volume_at_usable_crest_m3,
            "volume_mm3": geometry.lake_volume_mm3,
            "area_km2": geometry.lake_area_km2,
            "surface_elevation_m": table.usable_crest_m,
            "spill_detected_at_m": table.spill_detected_at_m,
            "volume_datum": VOLUME_DATUM,
            "storage_exponent_fit": table.fit_b,
            "storage_fit_residual_log10": table.fit_residual,
            **{
                key: value
                for key, value in geometry.observation.items()
                if not isinstance(value, (dict, list))
            },
        },
        stage_storage=table.to_dict(),
        indices=geometry.indices,
        raster={
            "cells_modified": changed_cells,
            "max_elevation_change_m": max_change_m,
            "working_crs": str(grid.crs),
            "working_resolution_m": float(target_resolution),
            "domain_radius_km": float(domain_radius_km),
        },
    )


def _register(
    output_path: Path,
    spec: BlockageSpec,
    domain_radius_km: float,
    spec_hash: str,
    out_dir: Path,
    provenance: DemUpdateProvenance,
) -> None:
    """Register the product so a repeat spec is served offline."""
    try:
        from jalraksha.cache import store_cache

        store_cache(
            cache_key(spec.barrier_lat, spec.barrier_lon, domain_radius_km, spec_hash),
            output_path,
            out_dir,
            metadata={
                "format": "GeoTIFF",
                "product": "observation-conditioned DEM update",
                "not_a_survey": True,
                "observation_source": provenance.observation_source,
                "spec_hash": spec_hash,
            },
        )
    except Exception as exc:  # pragma: no cover - registration is not the product
        warnings.warn(f"Could not register the updated DEM in the cache: {exc}")


def dam_config_updates_from_provenance(
    provenance: DemUpdateProvenance,
) -> Dict[str, Any]:
    """
    The fields a blockage run's dam_config must take from the burned geometry.

    Storage, surface area, crest and valley floor all come from the terrain
    here. Passing any of them from a preset or a dashboard slider is what
    ``breach._synthesize_blockage_ensemble`` refuses, and this function is how a
    caller supplies them correctly.
    """
    return {
        "storage_mm3": float(provenance.lake["volume_mm3"]),
        "surface_area_km2": float(provenance.lake["area_km2"]),
        "storage_source": "hypsometric_fill",
        "lake_volume_datum": provenance.lake["volume_datum"],
        "initial_surface_elev_m": float(provenance.lake["surface_elevation_m"]),
        "breach_bottom_elev_m": float(provenance.barrier["floor_elevation_m"]),
        "height_m": float(provenance.barrier["crest_height_m"]),
        "dam_type": "landslide",
        "lat": float(provenance.barrier["lat"]),
        "lon": float(provenance.barrier["lon"]),
    }
