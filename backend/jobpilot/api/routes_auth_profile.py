import uuid

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from jobpilot.api import serializers as s
from jobpilot.api.deps import COOKIE, current_user, make_session_token, run_idempotent, verify_password
from jobpilot.config import get_settings
from jobpilot.db import models as m
from jobpilot.db.session import get_db
from jobpilot.domain import profile as profile_svc
from jobpilot.domain.errors import DomainError

auth = APIRouter(prefix="/auth", tags=["auth"])
router = APIRouter(prefix="/profile", tags=["profile"], dependencies=[Depends(current_user)])


class LoginIn(BaseModel):
    username: str
    password: str


@auth.post("/login")
def login(body: LoginIn, response: Response, db: Session = Depends(get_db)):
    user = db.scalar(select(m.User).where(m.User.username == body.username))
    if user is None or not verify_password(user.password_hash, body.password):
        raise DomainError("invalid_credentials", "Wrong username or password", status_code=401)
    settings = get_settings()
    response.set_cookie(COOKIE, make_session_token(str(user.id)), httponly=True, samesite="strict",
                        secure=settings.cookie_secure, max_age=settings.session_max_age_s, path="/")
    return {"username": user.username}


@auth.post("/logout")
def logout(response: Response):
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


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
