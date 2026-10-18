"""Profile versioning. Every save creates a new immutable version; verification
carries over only for facts whose content did not change."""

import hashlib
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from jobpilot.db import models as m
from jobpilot.domain.errors import DomainError, NotFound
from jobpilot.domain.scoring import ProfileView

CATEGORIES = {"education", "employment", "skill", "project", "language", "eligibility", "location", "gap",
              "contact", "certification"}
# Contact details are rendered on documents but never sent to an AI provider.
PRIVATE_CATEGORIES = {"contact"}
SKILL_CONTEXTS = {"professional", "project", "coursework", "learning", "unspecified"}

# Seed data from the brief. Everything starts UNVERIFIED; blanks are for you to fill.
# `entry` groups facts: one job, one degree, one project. Personal contact details are
# deliberately blank here — enter them in the app (they stay in your database only).
SEED_FACTS: list[dict] = [
    {"category": "contact", "key": "full_name", "value": ""},
    {"category": "contact", "key": "email", "value": ""},
    {"category": "contact", "key": "phone", "value": ""},
    {"category": "contact", "key": "linkedin", "value": ""},
    {"category": "contact", "key": "github", "value": ""},
    {"category": "education", "entry": "bachelor", "key": "degree", "value": "Bachelor of Engineering in Information Technology"},
    {"category": "education", "entry": "bachelor", "key": "university", "value": "Savitribai Phule Pune University, India"},
    {"category": "education", "entry": "bachelor", "key": "start", "value": ""},
    {"category": "education", "entry": "bachelor", "key": "graduation", "value": "2024-06"},
    {"category": "education", "entry": "bachelor", "key": "cgpa", "value": "8.79/10"},
    {"category": "education", "entry": "master", "key": "degree", "value": ""},
    {"category": "education", "entry": "master", "key": "university", "value": ""},
    {"category": "education", "entry": "master", "key": "start", "value": ""},
    {"category": "employment", "entry": "sasken", "key": "employer", "value": "Sasken Technologies"},
    {"category": "employment", "entry": "sasken", "key": "location", "value": ""},
    {"category": "employment", "entry": "sasken", "key": "start", "value": "2024-10"},
    {"category": "employment", "entry": "sasken", "key": "first_title", "value": "Associate Software Engineer"},
    {"category": "employment", "entry": "sasken", "key": "promoted_to", "value": "Software Engineer"},
    {"category": "employment", "entry": "sasken", "key": "promotion_date", "value": ""},
    {"category": "employment", "entry": "sasken", "key": "end", "value": "2025-08"},
    {"category": "employment", "entry": "sasken", "key": "focus",
     "value": "Android development and Android framework-related work"},
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
    {"category": "eligibility", "key": "availability", "value": ""},
]


def _content(f: dict) -> tuple:
    return (f["category"], (f.get("entry") or "").strip().lower(), f["key"].strip().lower(),
            (f.get("value") or "").strip(), f.get("context"))


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
                entry=(f.get("entry") or "").strip().lower() or None,
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
    return {"category": f.category, "entry": f.entry, "key": f.key, "value": f.value, "context": f.context}


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


def set_verified_many(db: Session, fact_ids: list, verified: bool) -> int:
    """Verify (or unverify) several facts of the current version at once. Empty facts are skipped."""
    version = current_version(db)
    facts = db.scalars(select(m.ProfileFact).where(m.ProfileFact.id.in_(fact_ids),
                                                   m.ProfileFact.version_id == version.id)).all()
    if len(facts) != len(set(fact_ids)):
        raise DomainError("not_current_version", "Some facts are not in the current profile version; reload the page")
    changed = 0
    for f in facts:
        if verified and not f.value:
            continue
        if f.verified != verified:
            f.verified = verified
            changed += 1
    db.flush()
    return changed


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
        if f.category in PRIVATE_CATEGORIES:
            continue
        for_ai.append({"id": str(f.id), "category": f.category, "entry": f.entry, "key": f.key, "value": f.value,
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


def export_facts(version: m.ProfileVersion) -> list[dict]:
    return [{**_as_dict(f), "source_note": f.source_note, "verified": f.verified} for f in version.facts]


def import_facts(db: Session, facts: list[dict], note: str) -> m.ProfileVersion:
    """Save imported facts as a new version. Imports never mark anything verified:
    you confirm each fact in the app."""
    clean = [{k: f.get(k) for k in ("category", "entry", "key", "value", "context", "source_note")} for f in facts]
    return save_version(db, clean, note=note)
