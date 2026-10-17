"""Shared API dependencies: auth, CSRF, idempotency."""

import hashlib
import json
from collections.abc import Callable
from typing import Any

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import Depends, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from jobpilot.config import get_settings
from jobpilot.db import models as m
from jobpilot.db.session import get_db
from jobpilot.domain.errors import DomainError

COOKIE = "jp_session"
CSRF_HEADER = "x-requested-with"
CSRF_VALUE = "jobpilot"
_hasher = PasswordHasher()


def hash_password(pw: str) -> str:
    return _hasher.hash(pw)


def verify_password(hashed: str, pw: str) -> bool:
    try:
        return _hasher.verify(hashed, pw)
    except VerifyMismatchError:
        return False


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(get_settings().secret_key, salt="jp-session")


def make_session_token(user_id: str) -> str:
    return _serializer().dumps({"uid": user_id})


def current_user(request: Request, db: Session = Depends(get_db)) -> m.User:
    token = request.cookies.get(COOKIE)
    if not token:
        raise DomainError("unauthenticated", "Sign in first", status_code=401)
    try:
        data = _serializer().loads(token, max_age=get_settings().session_max_age_s)
    except (BadSignature, SignatureExpired):
        raise DomainError("unauthenticated", "Session expired; sign in again", status_code=401)
    user = db.get(m.User, data.get("uid"))
    if user is None:
        raise DomainError("unauthenticated", "Unknown session", status_code=401)
    return user


def csrf_protect(request: Request) -> None:
    """SameSite=Strict cookies plus a custom header that cross-site forms cannot set."""
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        if request.headers.get(CSRF_HEADER) != CSRF_VALUE:
            raise DomainError("csrf_failed", f"Missing {CSRF_HEADER} header", status_code=403)


def _request_hash(endpoint: str, body: Any) -> str:
    return hashlib.sha256(json.dumps([endpoint, jsonable_encoder(body)], sort_keys=True).encode()).hexdigest()


def run_idempotent(
    db: Session,
    request: Request,
    endpoint: str,
    body: Any,
    handler: Callable[[], tuple[int, Any]],
    after_commit: Callable[[Any], None] | None = None,
) -> JSONResponse:
    """Execute a state-changing handler exactly once per Idempotency-Key.

    The handler must flush, not commit. The stored response and the handler's
    changes commit in ONE transaction, so a retry either sees both or neither.
    """
    key = request.headers.get("idempotency-key")
    if not key or len(key) > 128:
        raise DomainError("idempotency_key_required", "Send an Idempotency-Key header (max 128 chars)",
                          status_code=400)
    req_hash = _request_hash(endpoint, body)
    stored = db.get(m.IdempotencyKey, key)
    if stored is not None:
        if stored.request_hash != req_hash:
            raise DomainError("idempotency_key_reused", "This key was used for a different request",
                              status_code=422)
        return JSONResponse(stored.response, status_code=stored.status_code, headers={"Idempotent-Replay": "true"})

    status, payload = handler()
    encoded = jsonable_encoder(payload)
    db.add(m.IdempotencyKey(key=key, endpoint=endpoint, request_hash=req_hash, status_code=status,
                            response=encoded))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        stored = db.get(m.IdempotencyKey, key)
        if stored is not None:  # a concurrent duplicate won the race
            return JSONResponse(stored.response, status_code=stored.status_code,
                                headers={"Idempotent-Replay": "true"})
        raise
    if after_commit:
        after_commit(payload)
    return JSONResponse(encoded, status_code=status)
