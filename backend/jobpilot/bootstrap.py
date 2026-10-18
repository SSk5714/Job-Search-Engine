"""Idempotent first-run setup: sources, seed profile, default search, admin user.

Run with `python -m jobpilot.bootstrap` (the API also calls it at startup).
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from jobpilot.api.deps import hash_password
from jobpilot.config import get_settings
from jobpilot.db import models as m
from jobpilot.db.session import SessionLocal
from jobpilot.domain.profile import SEED_FACTS, save_version
from jobpilot.orchestrator.runs import sync_sources


def ensure_user(db: Session, username: str, password: str) -> m.User:
    user = db.scalar(select(m.User).where(m.User.username == username))
    if user is None:
        user = m.User(username=username, password_hash=hash_password(password))
        db.add(user)
        db.flush()
    return user


def bootstrap(db: Session) -> None:
    sync_sources(db)
    settings = get_settings()
    if settings.admin_username and settings.admin_password and db.scalar(select(m.User).limit(1)) is None:
        ensure_user(db, settings.admin_username, settings.admin_password)
    if db.scalar(select(m.CandidateProfile).limit(1)) is None:
        save_version(db, SEED_FACTS, note="Seed from brief — all facts unverified", seed=True)
    if not settings.test_jobs_enabled:
        from jobpilot.ops.purge import purge_test_jobs

        purge_test_jobs(db)  # real jobs only: remove anything the Mock job board ever added
    if db.scalar(select(m.SearchConfig).limit(1)) is None:
        db.add(m.SearchConfig(
            name="Germany — all tracks",
            filters={"countries": ["DE"], "cities": [], "keywords": [], "tracks": ["A", "B", "C", "D"],
                     "work_modes": [], "employment_types": [], "seniority": [], "max_age_days": 30},
            source_codes=["mock"] if settings.test_jobs_enabled else ["ba_jobsuche", "arbeitnow"],
        ))
    db.commit()


def main() -> None:
    db = SessionLocal()
    try:
        bootstrap(db)
        print("Bootstrap complete")
    finally:
        db.close()


if __name__ == "__main__":
    main()
