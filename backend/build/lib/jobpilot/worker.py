"""Celery worker. Start with: celery -A jobpilot.worker worker -l info

Without JOBPILOT_REDIS_URL the API runs search runs in-process instead (dev/tests).
Scheduled searches: also run `celery -A jobpilot.worker beat -l info`, which sends the
orchestrator's scheduler tick once a minute. The independent monitor is a separate
process (`python -m jobpilot.monitor`) and does not use Celery.
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
    beat_schedule={
        "scheduler-tick": {
            "task": "jobpilot.scheduler_tick",
            "schedule": float(get_settings().scheduler_interval_s),
            "options": {"expires": max(30, get_settings().scheduler_interval_s - 5)},  # never run stale ticks
        },
    },
)


@celery_app.task(name="jobpilot.run_search", bind=True, max_retries=0)
def run_search(self, run_id: str) -> dict:
    from jobpilot.orchestrator.runs import execute_run

    return execute_run(uuid.UUID(run_id))


@celery_app.task(name="jobpilot.scheduler_tick", max_retries=0, time_limit=5 * 60, soft_time_limit=4 * 60)
def scheduler_tick() -> dict:
    from jobpilot.orchestrator.scheduler import tick

    def enqueue(run_id: uuid.UUID) -> None:
        run_search.delay(str(run_id))

    summary = tick(enqueue=enqueue)
    return {k: v for k, v in summary.items() if k != "at"}
