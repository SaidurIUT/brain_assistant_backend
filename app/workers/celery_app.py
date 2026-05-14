from celery import Celery

from app.core.config import settings

celery = Celery(
    "brain_assistant",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.workers.process_event"],
)

celery.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
)
