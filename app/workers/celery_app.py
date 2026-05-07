from celery import Celery

from app.config import get_settings

settings = get_settings()

celery_app = Celery(
    "email_context",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=[
        "app.modules.summarization.tasks",
        "app.workers.beat_schedule",
    ],
)
celery_app.conf.update(
    task_track_started=True,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_always_eager=settings.celery_task_always_eager,
)

