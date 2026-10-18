import uuid
from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from jobpilot.api import serializers as s
from jobpilot.api.deps import (
    COOKIE,
    current_user,
    hash_password,
    make_session_token,
    run_idempotent,
    verify_or_dummy,
    verify_password,
)
from jobpilot.config import get_settings
from jobpilot.db import models as m
from jobpilot.db.session import get_db
from jobpilot.domain import profile as profile_svc
from jobpilot.domain.errors import DomainError
from jobpilot.security import MIN_PASSWORD

auth = APIRouter(prefix="/auth", tags=["auth"])
router = APIRouter(prefix="/profile", tags=["profile"], dependencies=[Depends(current_user)])


class LoginIn(BaseModel):
    username: str
    password: str


def _set_cookie(response: Response, user: m.User) -> None:
    settings = get_settings()
    response.set_cookie(COOKIE, make_session_token(user), httponly=True, samesite="strict",
                        secure=settings.cookie_secure, max_age=settings.session_max_age_s, path="/")


def _throttle(db: Session, username: str) -> None:
    """Per-username and global limits on failed sign-ins inside a sliding window."""
    s = get_settings()
    since = datetime.now(UTC) - timedelta(minutes=s.login_window_minutes)
    failed = select(func.count()).select_from(m.LoginAttempt).where(
        m.LoginAttempt.success.is_(False), m.LoginAttempt.at >= since)
    per_user = db.scalar(failed.where(m.LoginAttempt.username == username)) or 0
    overall = db.scalar(failed) or 0
    if per_user >= s.login_max_failures or overall >= s.login_global_max_failures:
        raise DomainError("too_many_attempts", f"Too many failed sign-ins. Wait {s.login_window_minutes} minutes "
                          "and try again.", {"retry_after_s": s.login_window_minutes * 60}, status_code=429)


def _client_ip(request: Request) -> str | None:
    """For the attempt log only (it can be spoofed, so limits never depend on it)."""
    fwd = request.headers.get("x-forwarded-for")
    ip = fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else None)
    return ip[:64] if ip else None


@auth.post("/login")
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    name = body.username.strip()[:80]
    _throttle(db, name)
    user = db.scalar(select(m.User).where(m.User.username == name))
    ok = verify_or_dummy(user.password_hash if user else None, body.password)
    db.add(m.LoginAttempt(username=name, ip=_client_ip(request), success=ok))
    db.commit()
    if not ok:
        raise DomainError("invalid_credentials", "Wrong username or password", status_code=401)
    _set_cookie(response, user)
    return {"username": user.username}


@auth.post("/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    """Signs out everywhere: every existing session cookie stops working."""
    try:
        user = current_user(request, db)
    except DomainError:
        user = None
    if user is not None:
        user.session_version += 1
        db.commit()
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


class PasswordIn(BaseModel):
    current_password: str = Field(max_length=200)
    new_password: str = Field(max_length=200)


@auth.post("/password")
def change_password(body: PasswordIn, response: Response, user: m.User = Depends(current_user),
                    db: Session = Depends(get_db)):
    """Changes your password and ends every other session; this browser stays signed in."""
    if not verify_password(user.password_hash, body.current_password):
        db.add(m.LoginAttempt(username=user.username, success=False))
        db.commit()
        raise DomainError("invalid_credentials", "Your current password is wrong", status_code=401)
    if len(body.new_password) < MIN_PASSWORD:
        raise DomainError("validation_error", f"Use at least {MIN_PASSWORD} characters", status_code=422)
    if body.new_password == body.current_password or body.new_password.lower() == user.username.lower():
        raise DomainError("validation_error", "Choose a new password that differs from the old one and your "
                          "username", status_code=422)
    user.password_hash = hash_password(body.new_password)
    user.password_changed_at = datetime.now(UTC)
    user.session_version += 1
    db.commit()
    _set_cookie(response, user)
    return {"ok": True, "changed_at": user.password_changed_at}


@auth.get("/me")
def me(user: m.User = Depends(current_user)):
    return {"username": user.username}


def _profile_out(version: m.ProfileVersion) -> dict:
    facts = [s.fact(f) for f in version.facts]
    filled = [f for f in facts if f["value"]]
    return {"version_id": version.id, "version_no": version.version_no, "note": version.note,
            "created_at": version.created_at, "facts": facts,
            "verified_count": sum(1 for f in facts if f["verified"]), "filled_count": len(filled),
            "total_count": len(facts)}


@router.get("")
def get_profile(db: Session = Depends(get_db)):
    return _profile_out(profile_svc.current_version(db))


class FactIn(BaseModel):
    category: str
    entry: str | None = Field(default=None, max_length=64)
    key: str = Field(min_length=1, max_length=80)
    value: str = Field(default="", max_length=4000)
    context: str | None = None
    source_note: str | None = Field(default=None, max_length=255)


class ProfileIn(BaseModel):
    facts: list[FactIn]
    note: str | None = Field(default=None, max_length=255)


@router.put("")
def save_profile(body: ProfileIn, request: Request, db: Session = Depends(get_db)):
    def handler():
        version = profile_svc.save_version(db, [f.model_dump() for f in body.facts], body.note)
        return 200, _profile_out(version)

    return run_idempotent(db, request, "PUT /profile", body.model_dump(), handler)


class VerifyIn(BaseModel):
    verified: bool


@router.post("/facts/{fact_id}/verify")
def verify_fact(fact_id: uuid.UUID, body: VerifyIn, db: Session = Depends(get_db)):
    fact = profile_svc.set_verified(db, fact_id, body.verified)
    db.commit()
    return s.fact(fact)


@router.get("/versions")
def versions(db: Session = Depends(get_db)):
    profile = profile_svc.get_profile(db)
    rows = db.scalars(select(m.ProfileVersion).where(m.ProfileVersion.profile_id == profile.id)
                      .order_by(m.ProfileVersion.version_no.desc())).all()
    return [{"id": v.id, "version_no": v.version_no, "note": v.note, "created_at": v.created_at,
             "current": v.id == profile.current_version_id} for v in rows]


@router.get("/export")
def export_profile(db: Session = Depends(get_db)):
    """Your current profile as JSON (includes contact details; keep the file private)."""
    v = profile_svc.current_version(db)
    return {"format": "jobpilot-profile-v1", "version_no": v.version_no, "facts": profile_svc.export_facts(v)}


class ImportIn(BaseModel):
    format: str = Field(pattern="^jobpilot-profile-v1$")
    facts: list[FactIn] = Field(min_length=1, max_length=500)


@router.post("/import")
def import_profile(body: ImportIn, request: Request, db: Session = Depends(get_db)):
    """Replace the profile with imported facts as a NEW version. Nothing is marked verified."""
    def handler():
        version = profile_svc.import_facts(db, [f.model_dump() for f in body.facts], "Imported from file")
        return 200, _profile_out(version)

    return run_idempotent(db, request, "POST /profile/import", body.model_dump(), handler)


@router.get("/master-cv")
def master_cv(format: Literal["pdf", "docx"] = "pdf", db: Session = Depends(get_db)):
    """Your untailored CV from every verified fact. Generated on demand, never overwritten."""
    from jobpilot.documents.service import master_cv as build

    data = build(db, format)
    media = "application/pdf" if format == "pdf" else \
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    return Response(data, media_type=media, headers={"Content-Disposition": f'attachment; filename="master-cv.{format}"'})
