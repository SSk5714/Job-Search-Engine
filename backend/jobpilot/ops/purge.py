"""Remove every job that came from the Mock job board (invented test data), with everything
attached to it: applications, scores, documents and their files, history, notifications.
Real jobs are never touched. Runs automatically at start-up when test jobs are switched off."""

from __future__ import annotations

import logging
import shutil

from sqlalchemy import delete, or_, select, update
from sqlalchemy.orm import Session

from jobpilot.db import models as m

log = logging.getLogger("jobpilot.purge")
TEST_SOURCES = ("mock", "mock_broken")


def purge_test_jobs(db: Session) -> dict:
    src_ids = list(db.scalars(select(m.JobSource.id).where(m.JobSource.code.in_(TEST_SOURCES))))
    job_ids = list(db.scalars(select(m.Job.id).where(m.Job.source_id.in_(src_ids)))) if src_ids else []
    app_ids = list(db.scalars(select(m.Application.id).where(m.Application.job_id.in_(job_ids)))) if job_ids else []
    out = {"jobs": len(job_ids), "applications": len(app_ids)}

    if app_ids:
        for a in app_ids:  # notifications pointing at these applications
            db.execute(delete(m.Notification).where(or_(m.Notification.link == f"/review?id={a}",
                                                        m.Notification.dedup_key.like(f"%{a}%"),
                                                        m.Notification.alert_key.like(f"%{a}%"))))
        for model in (m.SubmissionAttempt, m.Approval, m.FormField, m.Document, m.FollowUp, m.RecruiterInteraction,
                      m.ApplicationStateHistory):
            db.execute(delete(model).where(model.application_id.in_(app_ids)))
        db.execute(delete(m.Application).where(m.Application.id.in_(app_ids)))
    if job_ids:
        db.execute(update(m.Job).where(m.Job.duplicate_of_id.in_(job_ids)).values(duplicate_of_id=None))
        db.execute(delete(m.JobMatchEvaluation).where(m.JobMatchEvaluation.job_id.in_(job_ids)))
        db.execute(delete(m.Job).where(m.Job.id.in_(job_ids)))

    # runs that only searched test sources, and their worker records
    runs = [r for r in db.scalars(select(m.SearchRun)).all()
            if (r.summary or {}).get("sources") and set(r.summary["sources"]) <= set(TEST_SOURCES)]
    run_ids = [r.id for r in runs]
    if run_ids:
        for rid in run_ids:
            db.execute(delete(m.Notification).where(m.Notification.dedup_key == f"high_fit:{rid}"))
        db.execute(update(m.Job).where(m.Job.first_seen_run_id.in_(run_ids)).values(first_seen_run_id=None))
        db.execute(update(m.ScheduleDispatch).where(m.ScheduleDispatch.run_id.in_(run_ids)).values(run_id=None))
        ar_ids = list(db.scalars(select(m.AgentRun.id).where(m.AgentRun.run_id.in_(run_ids))))
        if ar_ids:
            db.execute(delete(m.TaskAttempt).where(m.TaskAttempt.agent_run_id.in_(ar_ids)))
            db.execute(delete(m.AgentRun).where(m.AgentRun.id.in_(ar_ids)))
        db.execute(delete(m.SearchRun).where(m.SearchRun.id.in_(run_ids)))
    out["runs"] = len(run_ids)

    # saved searches must not use the test board any more
    for c in db.scalars(select(m.SearchConfig)).all():
        codes = [x for x in (c.source_codes or []) if x not in TEST_SOURCES]
        if codes != list(c.source_codes or []):
            c.source_codes = codes or ["ba_jobsuche"]
            c.source_options = {k: v for k, v in (c.source_options or {}).items() if k not in TEST_SOURCES}
    db.execute(update(m.JobSource).where(m.JobSource.code.in_(TEST_SOURCES)).values(enabled=False))
    # browser errors from test-job addresses
    db.execute(delete(m.ErrorEvent).where(m.ErrorEvent.component == "browser",
                                          m.ErrorEvent.message.like("%.example%")))
    db.flush()

    # files of the removed applications (CVs, letters, screenshots)
    if app_ids:
        from jobpilot.documents.service import storage_root

        root = storage_root()
        for a in app_ids:
            for p in (root / str(a), root / "evidence" / str(a)):
                if p.exists():
                    shutil.rmtree(p, ignore_errors=True)
    if any(out.values()):
        log.warning("removed test data: %s", out)
    return out

