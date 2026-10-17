"""Celery worker. Start with: celery -A jobpilot.worker worker -l info

Without JOBPILOT_REDIS_URL the API runs search runs in-process instead (dev/tests).
Scheduled searches (Celery beat) arrive in Phase 5.
"""

import uuid

from celery import Celery

from jobpilot.config import get_settings

_redis = get_settings().redis_url or "redis://localhost:6379/0"
celery_app = Celery("jobpilot", broker=_redis, backend=_redis)
celery_app.conf.update(
    task_acks_late=True,  # a crashed worker leaves the task for redelivery
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_time_limit=15 * 60,
    task_soft_time_limit=14 * 60,
)


@celery_app.task(name="jobpilot.run_search", bind=True, max_retries=0)
def run_search(self, run_id: str) -> dict:
    from jobpilot.orchestrator.runs import execute_run

    return execute_run(uuid.UUID(run_id))
