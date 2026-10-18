"""Scheduler without Celery: `python -m jobpilot.scheduler` ticks every JOBPILOT_SCHEDULER_INTERVAL_S.

With Redis configured, prefer Celery beat (`celery -A jobpilot.worker beat`), which sends the same
tick to the worker. Both are safe to run at once: ticks take an advisory lock and each due time
is dispatched exactly once.
"""

import logging
import time

from jobpilot.config import get_settings
from jobpilot.orchestrator.scheduler import tick

log = logging.getLogger("jobpilot.scheduler")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    interval = get_settings().scheduler_interval_s
    log.info("scheduler started, ticking every %ss", interval)
    while True:
        started = time.monotonic()
        try:
            summary = tick()
            if summary.get("dispatched"):
                log.info("dispatched %s", summary["dispatched"])
        except Exception:
            log.exception("scheduler tick failed")  # the monitor sees the stale heartbeat if this persists
        time.sleep(max(1.0, interval - (time.monotonic() - started)))


if __name__ == "__main__":
    main()
