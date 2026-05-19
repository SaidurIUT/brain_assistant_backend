from celery import Celery
from celery.schedules import crontab

from app.core.config import settings

celery_app = Celery(
    "brain_assistant_jobs",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.jobs.tasks"],
)

celery_app.conf.update(
    task_default_queue="brain-jobs",
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_always_eager=settings.celery_task_always_eager,
    task_eager_propagates=settings.celery_task_eager_propagates,
    beat_schedule={
        "enqueue-due-external-source-syncs": {
            "task": "jobs.enqueue_due_external_source_syncs",
            "schedule": crontab(minute="*/15"),
        },
        "enqueue-stale-queued-jobs": {
            "task": "jobs.enqueue_stale_queued_jobs",
            "schedule": crontab(minute="*/2"),
        },
    },
)
