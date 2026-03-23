"""
Celery app configuration and task definitions.
"""
from celery import Celery
from app.config import get_settings

settings = get_settings()

celery_app = Celery(
    "salesintel",
    broker=settings.redis_url,
    backend=settings.redis_url,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=300,  # 5 minutes max per task
    task_soft_time_limit=240,
    worker_prefetch_multiplier=1,
    worker_max_tasks_per_child=100,
)

# Auto-discover tasks from workers module
celery_app.autodiscover_tasks(["app.workers"])
