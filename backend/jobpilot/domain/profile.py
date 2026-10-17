"""Profile versioning. Every save creates a new immutable version; verification
carries over only for facts whose content did not change."""

import hashlib
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from jobpilot.db import models as m
from jobpilot.domain.errors import DomainError, NotFound
from jobpilot.domain.scoring import ProfileView

CATEGORIES = {"education", "employment", "skill", "project", "language", "eligibility", "location", "gap"}
SKILL_CONTEXTS = {"professional", "project", "coursework", "learning", "unspecified"}

# Seed data from the brief. Everything starts UNVERIFIED; blanks are for you to fill.
SEED_FACTS: list[dict] = [
    {"category": "education", "key": "degree", "value": "Bachelor of Engineering in Information Technology"},
    {"category": "education", "key": "university", "value": "Savitribai Phule Pune University, India"},
    {"category": "education", "key": "graduation", "value": "2024-06"},
    {"category": "education", "key": "cgpa", "value": "8.79/10"},
    {"category": "employment", "key": "employer", "value": "Sasken Technologies"},
    {"category": "employment", "key": "start", "value": "2024-10"},
    {"category": "employment", "key": "first_title", "value": "Associate Software Engineer"},
    {"category": "employment", "key": "promoted_to", "value": "Software Engineer"},
    {"category": "employment", "key": "end", "value": "2025-08"},
    {"category": "employment", "key": "focus", "value": "Android development and Android framework-related work"},
    *[
        {"category": "skill", "key": s.lower(), "value": s, "context": "unspecified"}
        for s in ["Java", "Kotlin", "C++", "Python", "Android", "AOSP", "JNI", "AIDL", "Camera2", "CameraX",
                  "Spring Boot", "Spring MVC", "REST", "JPA", "Hibernate", "MySQL", "Maven", "Gradle"]
    ],
    {"category": "gap", "key": "since_2025_08", "value": ""},
    {"category": "location", "key": "current", "value": "Chemnitz, Germany"},
    {"category": "location", "key": "relocation", "value": ""},
    {"category": "language", "key": "german", "value": ""},
    {"category": "language", "key": "english", "value": ""},
    {"category": "eligibility", "key": "enrolment_status", "value": ""},
    {"category": "eligibility", "key": "work_authorization", "value": ""},
    {"category": "eligibility", "key": "sponsorship_required", "value": ""},
]


def _content(f: dict) -> tuple:
    return (f["category"], f["key"].strip().lower(), (f.get("value") or "").strip(), f.get("context"))


def _hash(facts: list[dict]) -> str:
    return hashlib.sha256(json.dumps(sorted(map(_content, facts)), default=str).encode()).hexdigest()


def get_profile(db: Session) -> m.CandidateProfile:
    profile = db.scalar(select(m.CandidateProfile).limit(1))
    if profile is None:
        raise NotFound("Profile")
    return profile


def current_version(db: Session) -> m.ProfileVersion:
    profile = get_profile(db)
    version = db.get(m.ProfileVersion, profile.current_version_id)
    if version is None:
        raise NotFound("Profile version")
    return version


def save_version(db: Session, facts: list[dict], note: str | None = None, seed: bool = False) -> m.ProfileVersion:
    for f in facts:
        if f["category"] not in CATEGORIES:
            raise DomainError("validation_error", f"Unknown category {f['category']}", status_code=422)
        if f["category"] == "skill" and f.get("context") not in SKILL_CONTEXTS:
            raise DomainError("validation_error", "Skills need a context: " + ", ".join(sorted(SKILL_CONTEXTS)),
                              status_code=422)
    profile = db.scalar(select(m.CandidateProfile).limit(1))
    prev_verified: set[tuple] = set()
    next_no = 1
    if profile is None:
        profile = m.CandidateProfile()
        db.add(profile)
        db.flush()
    else:
        prev = db.get(m.ProfileVersion, profile.current_version_id)
        if prev is not None:
            next_no = prev.version_no + 1
            prev_verified = {_content(_as_dict(f)) for f in prev.facts if f.verified}
            if prev.content_hash == _hash(facts) and not seed:
                return prev  # nothing changed

    version = m.ProfileVersion(profile_id=profile.id, version_no=next_no, content_hash=_hash(facts), note=note)
    db.add(version)
    db.flush()
    for i, f in enumerate(facts):
        db.add(
            m.ProfileFact(
                version_id=version.id,
                category=f["category"],
                key=f["key"].strip(),
                value=(f.get("value") or "").strip(),
                context=f.get("context"),
                verified=_content(f) in prev_verified,
                source_note=f.get("source_note"),
                sort_order=i,
            )
        )
    profile.current_version_id = version.id
    db.flush()
    db.refresh(version)
    return version


def _as_dict(f: m.ProfileFact) -> dict:
    return {"category": f.category, "key": f.key, "value": f.value, "context": f.context}


def set_verified(db: Session, fact_id, verified: bool) -> m.ProfileFact:
    version = current_version(db)
    fact = db.get(m.ProfileFact, fact_id)
    if fact is None or fact.version_id != version.id:
        raise DomainError("not_current_version", "Only facts in the current profile version can be verified")
    if verified and not fact.value:
        raise DomainError("empty_fact", "Fill in a value before verifying this fact", status_code=422)
    fact.verified = verified
    db.flush()
    return fact


def profile_view(version: m.ProfileVersion) -> ProfileView:
    """Verified facts only. This snapshot is all that matchers (rules or Claude) ever see."""
    skills, elig, langs = {}, {}, {}
    other: list[str] = []
    for_ai: list[dict] = []
    unverified = 0
    for f in version.facts:
        if not f.verified:
            if f.value:
                unverified += 1
            continue
        for_ai.append({"id": str(f.id), "category": f.category, "key": f.key, "value": f.value,
                       "context": f.context})
        if f.category not in ("skill", "eligibility", "language"):
            other.append(str(f.id))
        if f.category == "skill":
            skills[f.value.lower()] = str(f.id)
        elif f.category == "eligibility":
            elig[f.key] = (f.value, str(f.id))
        elif f.category == "language":
            langs[f.key.lower()] = (f.value, str(f.id))
    return ProfileView(version_id=str(version.id), skills=skills, eligibility=elig, languages=langs,
                       unverified_count=unverified, other_fact_ids=other, facts_for_ai=for_ai)
