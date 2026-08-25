"""Settings for the JalRaksha service (env-driven, with sane demo defaults)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional


def _env(key: str, default: str) -> str:
    return os.environ.get(key, default)


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

    # Public demo dams (mirrors the Streamlit sidebar presets; Tehri is canonical).
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
    ]

    # Real downstream gauges for the Tehri corridor (brief §2.1, do not invent).
    TEHRI_GAUGES: List[dict] = [
        {"name": "Koteshwar", "distance_km": 13.0, "lat": 30.34, "lon": 78.53, "river": "Bhagirathi"},
        {"name": "Devprayag", "distance_km": 28.0, "lat": 30.15, "lon": 78.60, "river": "Ganga"},
        {"name": "Rishikesh", "distance_km": 34.8, "lat": 30.10, "lon": 77.10, "river": "Ganga"},
        {"name": "Haridwar", "distance_km": 58.4, "lat": 29.95, "lon": 77.86, "river": "Ganga"},
    ]

    # Solver backends selectable from the control panel.
    SOLVERS: List[str] = ["swe", "delft3d", "both"]

    def ensure_dirs(self) -> None:
        self.DATA_DIR.mkdir(parents=True, exist_ok=True)
        (self.DATA_DIR / "exports").mkdir(parents=True, exist_ok=True)
        (self.DATA_DIR / "keyframes").mkdir(parents=True, exist_ok=True)
        (self.DATA_DIR / "tiles").mkdir(parents=True, exist_ok=True)


settings = Settings()
