"""
FastAPI service layer for JalRaksha (integration brief §5.1).

This package replaces the lightweight stdlib jalraksha/api.py with a production
oriented service: FastAPI for the REST surface, Celery + Redis for async job
execution, and a thin Postgres store for run/job metadata and gauge time series.

Hard rule (brief §2.2): nothing in this service reimplements simulation logic.
Every job is a thin wrapper around the existing pipeline
(`run_dam_break_ensemble`) and the existing rapid estimate (`api.rapid_estimate`).

Layout:
  jalraksha_service/main.py     — FastAPI app + REST endpoints
  jalraksha_service/worker.py    — Celery app (broker + result backend = Redis)
  jalraksha_service/tasks.py     — job definitions (call into jalraksha.*)
  jalraksha_service/schemas.py   — Pydantic request/response models
  jalraksha_service/db.py        — thin Postgres (sqlite fallback) metadata store
  jalraksha_service/config.py    — settings (env-driven)
"""

from jalraksha_service.config import settings

__all__ = ["settings"]
