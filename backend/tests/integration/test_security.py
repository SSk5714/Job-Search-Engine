"""Phase 6 security review: sign-in limits, sessions, password change, headers, config checks."""

import time
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update

from jobpilot.config import Settings
from jobpilot.db import models as m
from jobpilot.db.session import SessionLocal
from jobpilot.security import InsecureConfig, check_settings

from tests.conftest import PASSWORD, USER, Api

GOOD_SECRET = "f" * 64


def _login(api: Api, user=USER, pw=PASSWORD):
    return api.post("/auth/login", {"username": user, "password": pw}, key=None)


@pytest.fixture
def anon(client):
    return Api(client)


def test_failed_sign_ins_are_limited_per_username(anon):
    for _ in range(5):
        assert _login(anon, pw="wrong").status_code == 401
    r = _login(anon)  # even the right password waits out the window
    assert r.status_code == 429 and r.json()["error"]["code"] == "too_many_attempts"
    assert r.json()["error"]["details"]["retry_after_s"] == 900
    with SessionLocal() as db:  # the window passes
        db.execute(update(m.LoginAttempt).values(at=datetime.now(UTC) - timedelta(minutes=16)))
        db.commit()
    assert _login(anon).status_code == 200


def test_password_spraying_across_usernames_is_limited(anon):
    for i in range(50):
        _login(anon, user=f"guess{i}", pw="wrong")
    assert _login(anon, user="someone-else", pw="x").status_code == 429


def test_unknown_user_and_wrong_password_look_the_same(anon):
    def timed(user):
        t = time.perf_counter()
        r = _login(anon, user=user, pw="wrong-password")
        return r, time.perf_counter() - t

    (r1, t1), (r2, t2) = timed("nobody-here"), timed(USER)
    assert r1.json() == r2.json() and r1.status_code == r2.status_code == 401
    assert abs(t1 - t2) < max(t1, t2) * 0.8  # both pay for an Argon2 check


def test_sign_out_ends_the_session_everywhere(client, api):
    stolen = client.cookies.get("jp_session")
    assert api.get("/auth/me").status_code == 200
    assert api.post("/auth/logout", key=None).status_code == 200
    client.cookies.set("jp_session", stolen)  # a copied cookie no longer works
    r = api.get("/auth/me")
    assert r.status_code == 401 and "ended" in r.json()["error"]["message"]


def test_change_password(client, api):
    other_device = client.cookies.get("jp_session")
    r = api.post("/auth/password", {"current_password": "nope", "new_password": "a-much-longer-password"}, key=None)
    assert r.status_code == 401
    r = api.post("/auth/password", {"current_password": PASSWORD, "new_password": "short"}, key=None)
    assert r.status_code == 422 and "12" in r.json()["error"]["message"]
    r = api.post("/auth/password", {"current_password": PASSWORD, "new_password": "a-much-longer-password"}, key=None)
    assert r.status_code == 200
    assert api.get("/auth/me").status_code == 200  # this browser got a fresh cookie
    fresh = client.cookies.get("jp_session")
    client.cookies.set("jp_session", other_device)
    assert api.get("/auth/me").status_code == 401  # other sessions ended
    client.cookies.set("jp_session", fresh)
    api.post("/auth/logout", key=None)
    assert _login(api, pw=PASSWORD).status_code == 401
    assert _login(api, pw="a-much-longer-password").status_code == 200


def test_security_headers_and_no_caching(api):
    r = api.get("/applications")
    for k, v in {"X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY", "Referrer-Policy": "no-referrer",
                 "Cache-Control": "no-store"}.items():
        assert r.headers[k] == v
    assert "default-src 'none'" in r.headers["Content-Security-Policy"]


def test_oversized_bodies_are_refused(api):
    r = api.post("/profile/import", {"format": "x", "facts": [{"value": "x" * 2_100_000}]}, key=None)
    assert r.status_code == 413 and r.json()["error"]["code"] == "payload_too_large"


def test_everything_except_login_needs_a_session(anon):
    for path in ("/applications", "/profile", "/notifications", "/usage", "/backups", "/health/details",
                 "/settings/notifications"):
        assert anon.get(path).status_code == 401, path


def test_writes_need_the_csrf_header(client, api):
    r = client.post("/api/v1/search-runs", json={"config_id": "x"}, headers={"Idempotency-Key": "k"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "csrf_failed"


def test_production_refuses_weak_settings():
    with pytest.raises(InsecureConfig, match="SECRET_KEY"):
        check_settings(Settings(env="production", secret_key="change-me-in-production"))
    with pytest.raises(InsecureConfig, match="ADMIN_PASSWORD"):
        check_settings(Settings(env="production", secret_key=GOOD_SECRET, admin_password="short"))
    assert check_settings(Settings(env="production", secret_key=GOOD_SECRET, admin_password="x" * 16,
                                   cookie_secure=True)) == []
    # development only warns
    assert check_settings(Settings(env="development", secret_key="change-me-in-production"))


def test_api_docs_are_off_in_production(monkeypatch, seeded):
    from jobpilot.config import get_settings
    from jobpilot.main import create_app

    monkeypatch.setenv("JOBPILOT_ENV", "production")
    monkeypatch.setenv("JOBPILOT_SECRET_KEY", GOOD_SECRET)
    get_settings.cache_clear()
    try:
        with TestClient(create_app(run_bootstrap=False)) as c:
            assert c.get("/docs").status_code == 404 and c.get("/openapi.json").status_code == 404
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()


def test_evidence_and_documents_cannot_escape_storage(api):
    import uuid

    with SessionLocal() as db:
        db.scalar(select(m.Job).limit(1))
    fake = uuid.uuid4()
    for f in ("../../etc/passwd", f"evidence/{fake}/../../x.png", "/etc/passwd"):
        assert api.get(f"/applications/{fake}/evidence", params={"file": f}).status_code == 404
