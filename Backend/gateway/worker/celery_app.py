from __future__ import annotations

import os

from celery import Celery

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")

celery_app = Celery("extraction_worker", broker=REDIS_URL, backend=None)

celery_app.conf.update(
    task_default_queue="extraction",
    # At-least-once delivery: the broker only drops a message once the task
    # function returns/raises. If the worker process is killed mid-task, Redis
    # redelivers the message to another worker instead of losing the job.
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
    task_time_limit=int(os.getenv("CELERY_TASK_TIME_LIMIT_SECONDS", "300")),
    task_soft_time_limit=int(os.getenv("CELERY_TASK_SOFT_TIME_LIMIT_SECONDS", "270")),
    worker_concurrency=int(os.getenv("CELERY_WORKER_CONCURRENCY", "2")),
    timezone="UTC",
    beat_schedule={
        "recover-stale-extraction-jobs": {
            "task": "worker.tasks.recover_stale_jobs",
            "schedule": float(os.getenv("JOB_RECOVERY_SWEEP_SECONDS", "60")),
        },
    },
    # PDF/URL ingestion (text extraction, OCR, scraping) runs on its own
    # queue/worker so a slow OCR job never delays queued extraction jobs.
    task_routes={
        "worker.ingestion_tasks.*": {"queue": "ingestion"},
    },
)

# Imported for their side effects: registers tasks on this app. Deferred to
# the bottom of the module because they import celery_app back from here.
from . import tasks  # noqa: E402, F401
from . import ingestion_tasks  # noqa: E402, F401
