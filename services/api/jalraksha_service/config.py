"""Settings for the JalRaksha service (env-driven, with sane demo defaults)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

# The only module-level import from the `jalraksha` package anywhere under
# services/api — every other cross-package import is deferred into a function
# body, because modules like jalraksha.run and jalraksha.delft3d pull in heavy
# geospatial dependencies (rasterio, geopandas) that would slow API startup.
# jalraksha.presets is exempt: it imports only dataclasses and typing, and
# nothing from the rest of its own package, so importing it eagerly is free.
#
# Direction matters — service depends on library, never the reverse. That is
# jalraksha/presets.py's own stated rule for this exact situation.
from jalraksha.presets import KHADAKWASLA, RISHI_GANGA, get_gauges


def _env(key: str, default: str) -> str:
    return os.environ.get(key, default)


def _demo_dam_from_preset(preset: Any) -> Dict[str, Any]:
    """
    Adapt a jalraksha.presets.DamPreset into this API's /dams wire shape.

    Deliberately a function here rather than a method on DamPreset: the wire
    shape belongs to the service, and pushing it into the library would invert
    the dependency direction the preset module explicitly forbids.

    Field names differ (`dam_id` -> `id`), and the preset carries a dozen fields
    the API does not publish (epsg, frl_m, barrier geometry, exaggeration...).
    Copying values instead of retyping them is the point: the two registries
    cannot drift out of sync on lat/lon/height/storage.
    """
    return {
        "id": preset.dam_id,
        "name": preset.name,
        "lat": preset.lat,
        "lon": preset.lon,
        "height_m": preset.height_m,
        "storage_mm3": preset.storage_mm3,
        "dam_type": preset.dam_type,
        "river": preset.river,
        "state": preset.state,
        "domain_radius_km": preset.domain_radius_km,
        # Carried because the solver genuinely uses it: reservoir_storage_curve
        # derives the storage exponent b from it, and without it falls back to
        # assuming a cone. Omitting it here would have left the API path on the
        # cone default while the CLI path used the real curve — the same dam
        # routing two different reservoirs depending on how it was launched.
        "surface_area_km2": preset.surface_area_km2,
        # Visualization settings, published because POST /runs/{id}/open-paraview
        # needs them. The note above about the API not publishing exaggeration
        # predates ParaView being wired to the service: without these, every dam
        # rendered at render_static.py's generic defaults instead of its own.
        "vertical_exaggeration": preset.vertical_exaggeration,
        "nominal_depth_m": preset.nominal_depth_m,
        # The dam's own downstream corridor, published so the dashboard can
        # draw the right towns on selection instead of falling back to a
        # hardcoded Tehri list. Same reasoning as the rest of this adapter:
        # copied from the library, never retyped here.
        "gauges": [
            {
                "name": g.name, "distance_km": g.distance_km,
                "lat": g.lat, "lon": g.lon, "river": g.river, "note": g.note,
            }
            for g in get_gauges(preset.dam_id)
        ],
        # Which incident types this record can model. Published so the dashboard
        # can gate its scenario selector per site instead of hard-pinning every
        # non-dam-break scenario to one dam, which is what it used to do.
        "record_type": "dam",
        "scenario_types": ["dam_break", "river_blockage", "river_overflow"],
    }


def _demo_blockage_from_preset(preset: Any) -> Dict[str, Any]:
    """
    Adapt a jalraksha.presets.BlockagePreset into the /dams wire shape.

    Publishes height_m, storage_mm3 and dam_type as None ON PURPOSE. A landslide
    deposit has no engineered height and no published gross storage; the crest
    comes from the barrier spec and the volume from a hypsometric fill of the
    updated DEM at run time. ``record_type: "blockage"`` is what tells
    RunRequest.to_dam_config to skip the vetted-figures refusal that would
    otherwise 422 this record for correctly declining to invent them.
    """
    return {
        "id": preset.site_id,
        "name": preset.name,
        "lat": preset.lat,
        "lon": preset.lon,
        "height_m": None,
        "storage_mm3": None,
        "dam_type": None,
        "river": preset.river,
        "state": preset.state,
        "domain_radius_km": preset.domain_radius_km,
        "surface_area_km2": None,
        "vertical_exaggeration": preset.vertical_exaggeration,
        "nominal_depth_m": preset.nominal_depth_m,
        "gauges": [
            {
                "name": g.name, "distance_km": g.distance_km,
                "lat": g.lat, "lon": g.lon, "river": g.river, "note": g.note,
            }
            for g in get_gauges(preset.site_id)
        ],
        "record_type": "blockage",
        # A blockage site models one thing. Offering "dam break" here would ask
        # the breach regressions for the failure of a structure that does not
        # exist.
        "scenario_types": ["river_blockage"],
        "blockage_crest_height_m": preset.barrier_crest_height_m,
        "blockage_width_m": preset.barrier_width_m,
        # Where to START placing the barrier. Terrain-derived, not surveyed,
        # and separate from lat/lon so the map marker stays on the reach.
        "suggested_barrier_lat": preset.suggested_barrier_lat,
        "suggested_barrier_lon": preset.suggested_barrier_lon,
        "blockage_date_pre": preset.detect_date_pre,
        "blockage_date_post": preset.detect_date_post,
        "note": preset.note,
    }


class Settings:
    # Where results / exports / keyframe manifests / terrain tiles live on disk.
    # In Docker this is the mounted ./data volume (see docker-compose §5.8).
    DATA_DIR: Path = Path(_env("JALRAKSHA_DATA_DIR", "./data"))

    # Redis broker + result backend for Celery.
    REDIS_URL: str = _env("REDIS_URL", "redis://localhost:6379/0")

    # Postgres connection. Falls back to sqlite if not provided (local dev).
    DATABASE_URL: str = _env(
        "DATABASE_URL", "sqlite:///./data/jalraksha.db"
    )

    # Public demo dams for GET /dams; Tehri is canonical.
    DEMO_DAMS: List[dict] = [
        {
            "id": "tehri",
            "name": "Tehri Dam",
            "lat": 30.3789,
            "lon": 78.4789,
            "height_m": 260.0,
            "storage_mm3": 3540.0,
            "dam_type": "embankment",
            "river": "Bhagirathi",
            "state": "Uttarakhand",
            "domain_radius_km": 60.0,
            # Tehri's entry is hand-written rather than built from its preset,
            # so these have to be repeated here. Kept in sync with
            # jalraksha/presets.py::TEHRI, which test_presets.py pins.
            "vertical_exaggeration": 1.2,
            "nominal_depth_m": 120.0,
            "gauges": [
                {
                    "name": g.name, "distance_km": g.distance_km,
                    "lat": g.lat, "lon": g.lon, "river": g.river, "note": g.note,
                }
                for g in get_gauges("tehri")
            ],
        },
        {
            "id": "bhakra",
            "name": "Bhakra Dam",
            "lat": 31.4167,
            "lon": 76.4333,
            "height_m": 226.0,
            "storage_mm3": 9340.0,
            "dam_type": "gravity",
            "river": "Sutlej",
            "state": "Himachal Pradesh",
            "domain_radius_km": 60.0,
            # No preset, no surveyed corridor, and no staged DEM (see
            # tasks.py::_resolve_dem). Publishing an empty list is the honest
            # answer; publishing Tehri's towns here is what the old duplicated
            # gauge lists effectively did.
            "gauges": [],
        },
        {
            "id": "idukki",
            "name": "Idukki Dam",
            "lat": 9.8400,
            "lon": 76.9800,
            "height_m": 168.0,
            "storage_mm3": 1994.0,
            "dam_type": "arch",
            "river": "Periyar",
            "state": "Kerala",
            "domain_radius_km": 60.0,
            # No preset, no surveyed corridor, and no staged DEM (see
            # tasks.py::_resolve_dem). Publishing an empty list is the honest
            # answer; publishing Tehri's towns here is what the old duplicated
            # gauge lists effectively did.
            "gauges": [],
        },
        {
            "id": "hirakud",
            "name": "Hirakud Dam",
            "lat": 21.5400,
            "lon": 83.8700,
            "height_m": 60.0,
            "storage_mm3": 5810.0,
            "dam_type": "gravity",
            "river": "Mahanadi",
            "state": "Odisha",
            "domain_radius_km": 60.0,
            # No preset, no surveyed corridor, and no staged DEM (see
            # tasks.py::_resolve_dem). Publishing an empty list is the honest
            # answer; publishing Tehri's towns here is what the old duplicated
            # gauge lists effectively did.
            "gauges": [],
        },
        # Sourced from jalraksha/presets.py rather than retyped, so the preset
        # and the API cannot disagree about where this dam is.
        #
        # UPDATED 2026-08-28: height_m / storage_mm3 / dam_type are no longer
        # None. They are user-supplied figures (51.3 m, 33.5 MCM, masonry
        # gravity) and the preset still carries a TODO: UNVETTED tag on each,
        # because no primary CWC / NRLD / Maharashtra WRD citation was
        # obtained. Consequences of that change:
        #   * GET /dams now publishes real numbers, and Run no longer 422s.
        #   * The dam is a MASONRY GRAVITY structure while every breach
        #     regression in the ensemble is an embankment fit. That is flagged
        #     separately, per run, as dam_class_outside_fitted_population in
        #     hazard_summary — not silently absorbed into the peak.
        #   * Its DEM (dem_18.44_73.77_clipped.tif) IS staged, so _resolve_dem
        #     succeeds. bhakra/idukki/hirakud still have none.
        _demo_dam_from_preset(KHADAKWASLA),
        # The Rishi Ganga / Dhauliganga confluence at Raini — a river-BLOCKAGE
        # site, not a dam. The problem statement names it first among the
        # natural lake formations, and its 20 km domain sits entirely inside the
        # already staged N30_00_E079 Copernicus window, so it runs offline.
        #
        # It publishes no height, storage or dam type, and record_type
        # "blockage" is what stops RunRequest.to_dam_config refusing it for that.
        _demo_blockage_from_preset(RISHI_GANGA),
    ]

    # ParaView desktop integration (POST /runs/{id}/open-paraview).
    #
    # This launches a GUI application on the machine running the API. That is
    # the demo laptop, where browser and API share a host — it is NOT something
    # that can work for a remote user of a deployed API, and under
    # docker-compose the api container is headless Linux with no ParaView at
    # all. The endpoint reports that condition explicitly rather than hanging.
    # Forward slashes on purpose: Windows accepts them everywhere, and they
    # survive being written, copied into an env var, or pasted into a shell
    # without the backslash-escaping accidents that a literal "in" invites.
    PARAVIEW_EXE: str = _env(
        "JALRAKSHA_PARAVIEW_EXE", "C:/Program Files/ParaView 6.2.0/bin/paraview.exe")
    PVPYTHON_EXE: str = _env(
        "JALRAKSHA_PVPYTHON_EXE", "C:/Program Files/ParaView 6.2.0/bin/pvpython.exe")

    # Delft3D FM. Empty means "look on PATH"; set this to the full path of the
    # dflowfm executable to use an install that is not on PATH.
    #
    # When neither finds a binary, solver="both" runs JalRaksha's own 2D SWE
    # solver instead and SAYS SO — jalraksha/delft3d/runner.py labels the result
    # "JalRaksha built-in 2D SWE - Delft3D-class, NOT Delft3D FM" and the
    # Comparison tab shows it as a banner. Per CLAUDE.md the built-in solver may
    # be described as Delft3D-CLASS (it solves the same depth-averaged 2D
    # Saint-Venant equations); it must never be presented as Delft3D itself.
    #
    # Forward slashes, as with PARAVIEW_EXE above: Windows accepts them and they
    # survive being pasted into an env var without backslash-escaping accidents.
    DFLOWFM_EXE: str = _env("JALRAKSHA_DFLOWFM_EXE", "")

    # Google Earth Engine. Empty means Earth Engine is simply unavailable, and
    # every consumer says so rather than substituting anything: GET /gee/latest
    # answers source="unavailable" with a reason, and the population-at-risk
    # figure is omitted rather than estimated from an assumed density.
    #
    # Needs all three of: `pip install earthengine-api`, `earthengine
    # authenticate`, and a Cloud project with the Earth Engine API enabled
    # (free for non-commercial use via https://code.earthengine.google.com/register).
    # jalraksha.gee.auth reads this same variable directly — the library cannot
    # import this module, since service depends on library and never the reverse.
    GEE_PROJECT: str = _env("JALRAKSHA_GEE_PROJECT", "")

    # (TEHRI_GAUGES was removed here: it was a fifth copy of the Tehri corridor
    # with zero consumers. The corridors now live in jalraksha.presets.GAUGES,
    # keyed by dam, and reach this module through _demo_dam_from_preset.)

    # Solver backends selectable from the control panel.
    # "sph" runs the near-field PySPH handoff in addition to the SWE pipeline.
    # It is deliberately last: the near-field window is 600 m over 15 s and can
    # never reach a downstream gauge, so it answers a different question from
    # the other three and must not read as a drop-in alternative to them.
    SOLVERS: List[str] = ["swe", "delft3d", "both", "sph"]

    def ensure_dirs(self) -> None:
        self.DATA_DIR.mkdir(parents=True, exist_ok=True)
        (self.DATA_DIR / "exports").mkdir(parents=True, exist_ok=True)
        (self.DATA_DIR / "keyframes").mkdir(parents=True, exist_ok=True)
        (self.DATA_DIR / "tiles").mkdir(parents=True, exist_ok=True)


settings = Settings()
