"""Tests run against a real PostgreSQL database built by the Alembic migrations,
so partial unique indexes and transactions behave exactly as in production."""

import os
import uuid

os.environ.setdefault("JOBPILOT_DATABASE_URL", "postgresql+psycopg://postgres@localhost:5432/jobpilot_test")
os.environ["JOBPILOT_REDIS_URL"] = ""
os.environ.setdefault("JOBPILOT_SECRET_KEY", "test-secret-key-0123456789")

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import text

from jobpilot.config import get_settings
from jobpilot.db.models import Base
from jobpilot.db.session import SessionLocal, get_engine, reset_engine

BACKEND = os.path.dirname(os.path.dirname(__file__))
USER, PASSWORD = "shubham", "correct horse battery staple"


@pytest.fixture(scope="session", autouse=True)
def migrated_db():
    get_settings.cache_clear()
    reset_engine()
    cfg = Config(os.path.join(BACKEND, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(BACKEND, "migrations"))
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    yield
    reset_engine()


@pytest.fixture(autouse=True)
def clean_tables():
    engine = get_engine()
    names = ", ".join(t.name for t in reversed(Base.metadata.sorted_tables))
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {names} RESTART IDENTITY CASCADE"))
    yield


@pytest.fixture
def db():
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture
def seeded(db):
    from jobpilot.bootstrap import bootstrap, ensure_user

    ensure_user(db, USER, PASSWORD)
    bootstrap(db)
    return db


class Api:
    """Thin client that always sends the CSRF header and fresh idempotency keys."""

    def __init__(self, client: TestClient):
        self.c = client

    def get(self, path, **kw):
        return self.c.get(f"/api/v1{path}", **kw)

    def _write(self, method, path, json=None, key: str | None = "auto", headers=None):
        h = {"X-Requested-With": "jobpilot", **(headers or {})}
        if key == "auto":
            key = str(uuid.uuid4())
        if key:
            h["Idempotency-Key"] = key
        return self.c.request(method, f"/api/v1{path}", json=json, headers=h)

    def post(self, path, json=None, **kw):
        return self._write("POST", path, json, **kw)

    def put(self, path, json=None, **kw):
        return self._write("PUT", path, json, **kw)

    def patch(self, path, json=None, **kw):
        return self._write("PATCH", path, json, **kw)


@pytest.fixture
def client(seeded):
    from jobpilot.main import create_app

    with TestClient(create_app(run_bootstrap=False)) as c:
        yield c


@pytest.fixture
def api(client):
    a = Api(client)
    r = a.post("/auth/login", {"username": USER, "password": PASSWORD}, key=None)
    assert r.status_code == 200, r.text
    return a


def verify_facts(api: Api, *, skills=("Java", "Kotlin", "Android", "Spring Boot", "C++", "AOSP", "JNI", "AIDL",
                                      "REST", "JPA", "MySQL", "Gradle", "Python")) -> dict:
    """Give skill facts a context and verify them, as the user would in Settings."""
    prof = api.get("/profile").json()
    facts = []
    for f in prof["facts"]:
        f = {k: f[k] for k in ("category", "key", "value", "context", "source_note")}
        if f["category"] == "skill":
            f["context"] = "professional"
        facts.append(f)
    prof = api.put("/profile", {"facts": facts, "note": "contexts set"}).json()
    for f in prof["facts"]:
        if f["category"] == "skill" and f["value"] in skills:
            assert api.post(f"/profile/facts/{f['id']}/verify", {"verified": True}, key=None).status_code == 200
    return api.get("/profile").json()


def run_mock_search(api: Api) -> dict:
    cfg = api.get("/search-configs").json()[0]
    r = api.post("/search-runs", {"config_id": cfg["id"]})
    assert r.status_code == 202, r.text
    return api.get(f"/search-runs/{r.json()['id']}").json()
