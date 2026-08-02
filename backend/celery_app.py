"""Celery application configuration. Implements TRD H5 (async task queue).

Workers (celery_app worker) and the scheduler (celery_app beat) both import
this module. Tasks are registered in subsequent phases.
"""

import os

from celery import Celery

broker_url = os.environ.get("CELERY_BROKER_URL", "redis://redis:6379/0")
result_backend = os.environ.get("CELERY_RESULT_BACKEND", "redis://redis:6379/1")

app = Celery("finance", broker=broker_url, backend=result_backend)

app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
)
