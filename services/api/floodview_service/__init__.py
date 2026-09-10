"""
FastAPI service layer for FloodView (integration brief §5.1).

This package replaces the lightweight stdlib floodview/api.py with a production
oriented service: FastAPI for the REST surface, Celery + Redis for async job
execution, and a thin Postgres store for run/job metadata and gauge time series.

Hard rule (brief §2.2): nothing in this service reimplements simulation logic.
Every job is a thin wrapper around the existing pipeline
(`run_dam_break_ensemble`) and the existing rapid estimate (`api.rapid_estimate`).

Layout:
  floodview_service/main.py     — FastAPI app + REST endpoints
  floodview_service/worker.py    — Celery app (broker + result backend = Redis)
  floodview_service/tasks.py     — job definitions (call into floodview.*)
  floodview_service/schemas.py   — Pydantic request/response models
  floodview_service/db.py        — thin Postgres (sqlite fallback) metadata store
  floodview_service/config.py    — settings (env-driven)
"""

from floodview_service.config import settings

__all__ = ["settings"]
