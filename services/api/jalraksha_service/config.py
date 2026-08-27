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
from jalraksha.presets import KHADAKWASLA


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
        },
        # Sourced from jalraksha/presets.py rather than retyped, so the preset
        # and the API cannot disagree about where this dam is.
        #
        # EXPECTED, NOT A BUG: height_m, storage_mm3 and dam_type come back None.
        # The preset marks them UNVETTED — there is no primary CWC / Maharashtra
        # WRD source — and CLAUDE.md forbids guessing them. Consequences:
        #   * GET /dams publishes nulls for those three (DamPreset allows it).
        #   * Selecting this dam and pressing Run returns a 422 naming them,
        #     raised by RunRequest.to_dam_config. That is the correct stopping
        #     point: the breach regressions cannot run without them.
        #   * If they are ever filled in, the next failure is _resolve_dem's
        #     "no DEM staged" — no Khadakwasla DEM is cached. Also correct.
        # Terrain and reservoir visualization need none of the three, which is
        # why the dam is worth listing at all.
        _demo_dam_from_preset(KHADAKWASLA),
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

    # Real downstream gauges for the Tehri corridor (brief §2.1, do not invent).
    TEHRI_GAUGES: List[dict] = [
        {"name": "Koteshwar", "distance_km": 13.0, "lat": 30.3167, "lon": 78.4833, "river": "Bhagirathi"},
        {"name": "Devprayag", "distance_km": 28.0, "lat": 30.15, "lon": 78.60, "river": "Ganga"},
        {"name": "Rishikesh", "distance_km": 34.8, "lat": 30.0869, "lon": 78.2676, "river": "Ganga"},
        {"name": "Haridwar", "distance_km": 58.4, "lat": 29.9457, "lon": 78.1642, "river": "Ganga"},
    ]

    # Solver backends selectable from the control panel.
    SOLVERS: List[str] = ["swe", "delft3d", "both"]

    def ensure_dirs(self) -> None:
        self.DATA_DIR.mkdir(parents=True, exist_ok=True)
        (self.DATA_DIR / "exports").mkdir(parents=True, exist_ok=True)
        (self.DATA_DIR / "keyframes").mkdir(parents=True, exist_ok=True)
        (self.DATA_DIR / "tiles").mkdir(parents=True, exist_ok=True)


settings = Settings()
