"""Celery application (broker + result backend = Redis, per brief §5.1)."""

from __future__ import annotations

import os

from celery import Celery
from jalraksha_service.config import settings

celery_app = Celery(
    "jalraksha",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_track_started=True,
    worker_prefetch_multiplier=1,
)

# Local/dev convenience: with CELERY_EAGER=1, tasks run synchronously in-process
# so `POST /runs` works without a real Redis broker/worker (this environment has
# neither). Docker Compose does not set this, so the real broker path is untouched.
if os.environ.get("CELERY_EAGER") == "1":
    celery_app.conf.update(task_always_eager=True, task_eager_propagates=True)

# Import task definitions so they register with the app.
from jalraksha_service import tasks  # noqa: E402,F401
