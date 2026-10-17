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


# ── Phase 2 helpers ─────────────────────────────────────────────────────────

import base64 as _b64  # noqa: E402
import json as _json  # noqa: E402
import pathlib as _pl  # noqa: E402

import httpx  # noqa: E402

FIXTURES = _pl.Path(__file__).parent / "fixtures" / "sources"


class FakeSources:
    """httpx transport serving recorded source responses. Records every request;
    any URL not routed returns 599 so an unexpected live call fails loudly."""

    def __init__(self):
        self.calls: list[str] = []
        self.overrides: dict[str, list[httpx.Response]] = {}
        self.ba_detail_ok: set[str] = {"10001-1001234567-S"}
        self.gh_open: set[str] = {"7001001", "7001002", "7001003", "7001004"}

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.calls.append(url)
        for prefix, queue in self.overrides.items():
            if url.startswith(prefix) and queue:
                return queue.pop(0)
        path = request.url.path
        host = request.url.host
        if host == "rest.arbeitsagentur.de":
            if request.headers.get("x-api-key") != "jobboerse-jobsuche":
                return httpx.Response(403)
            if path.endswith("/pc/v4/jobs"):
                return httpx.Response(200, json=_json.loads((FIXTURES / "ba_search.json").read_text()))
            if "/pc/v4/jobdetails/" in path:
                refnr = _b64.b64decode(path.rsplit("/", 1)[1]).decode()
                if refnr in self.ba_detail_ok:
                    return httpx.Response(200, json=_json.loads((FIXTURES / "ba_detail.json").read_text()))
                return httpx.Response(404)
        if host == "boards-api.greenhouse.io":
            parts = path.strip("/").split("/")  # v1 boards {board} jobs [id]
            data = _json.loads((FIXTURES / "greenhouse_jobs.json").read_text())
            if len(parts) == 4:
                return httpx.Response(200, json=data)
            if len(parts) == 5:
                job = next((j for j in data["jobs"] if str(j["id"]) == parts[4]), None)
                return httpx.Response(200, json=job) if job and parts[4] in self.gh_open else httpx.Response(404)
        if host in ("api.eu.lever.co", "api.lever.co"):
            data = _json.loads((FIXTURES / "lever_postings.json").read_text())
            parts = path.strip("/").split("/")  # v0 postings {site} [id]
            if len(parts) == 3:
                return httpx.Response(200, json=data)
            post = next((p for p in data if p["id"] == parts[3]), None)
            return httpx.Response(200, json=post) if post else httpx.Response(404)
        if host.endswith(".jobs.personio.de"):
            return httpx.Response(200, content=(FIXTURES / "personio.xml").read_bytes(),
                                  headers={"content-type": "application/xml"})
        return httpx.Response(599, text=f"unrouted test URL {url}")


@pytest.fixture
def fake_sources():
    from jobpilot.agents.discovery import http as source_http

    fs = FakeSources()
    source_http.set_transport(httpx.MockTransport(fs.handler))
    yield fs
    source_http.set_transport(None)


class FakeProvider:
    """Deterministic stand-in for Claude. `respond(job_text, facts)` builds the output."""

    name = "fake"
    model = "fake-model"

    def __init__(self, respond=None, error=None, cost=0.002):
        self.respond = respond
        self.error = error
        self.cost = cost
        self.calls: list[dict] = []

    def structured(self, *, system, user, schema, max_tokens=2048):
        from jobpilot.ai.provider import AIResult, AIUsage

        self.calls.append({"system": system, "user": user, "schema": schema})
        if self.error:
            raise self.error
        facts = _json.loads(user.split("<verified_facts>\n", 1)[1].split("\n</verified_facts>", 1)[0])
        posting = user.split("<job_posting>\n", 1)[1]
        out = self.respond(posting, facts) if self.respond else default_match(posting, facts)
        return AIResult(output=schema(**out), usage=AIUsage(self.model, 1200, 300, self.cost))


def default_match(posting: str, facts: list[dict]) -> dict:
    """Maps any verified skill whose name appears in the posting, quoting it verbatim."""
    low = posting.lower()
    matches = []
    for f in facts:
        if f["category"] == "skill" and f["value"].lower() in low:
            i = low.index(f["value"].lower())
            matches.append({"skill": f["value"].lower(), "fact_id": f["id"],
                            "job_quote": posting[i:i + len(f["value"])]})
    return {"track": "A" if "android" in low else "B", "seniority": "junior",
            "required_skills": [m["skill"] for m in matches] + ["docker"],
            "skill_matches": matches, "language_requirements": [], "requirements": [],
            "summary": "Fits the verified Android and Java experience."}
