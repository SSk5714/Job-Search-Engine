# JobPilot Europe

A job-application pipeline for Germany and Europe. It discovers jobs, scores them against
a **verified** candidate profile, and tracks every application. Nothing is ever submitted
without your explicit approval.

One deterministic orchestrator owns all workflow state in PostgreSQL. Specialized workers
(discovery, matching, and later documents and form preparation) only return validated
results, and AI is used only where language understanding helps.

**Status: Phase 1 of 6 (foundation) complete.** See [what works today](#what-works-today)
and [docs/integrations.md](docs/integrations.md) for what is mocked or pending.

![Job Review](docs/screenshots/04-job-review.png)

## What works today

- Mock job discovery from three feed formats, URL normalization, and cross-source dedup
- Rule-based scoring `rules-v0` over verified facts, with evidence and separate hard eligibility rules
- The full application state machine with guards, history, optimistic locking and idempotent writes
- Approval binding to document and form-value hashes, with invalidation on any change (backend)
- Profile editor with versioning and per-fact verification
- Dashboard, Job Discovery, Job Review, Tracker with history drawer, CSV export, Settings & Health
- Honest status: sources and services that aren't built are labelled Planned, Manual or not implemented

Not yet: Claude matching (Phase 2), CV and cover letter generation (3), form preparation and
submission (4), scheduler, monitor and notifications (5), production hardening (6).

## Quick start (Docker)

```bash
cp .env.example .env        # set JOBPILOT_SECRET_KEY and the admin password
docker compose -f infra/docker-compose.yml --env-file .env up --build
```

Open http://localhost:3000 and sign in with the admin user from `.env`. API docs are at
http://localhost:8000/docs.

> The Docker files were written and validated with `docker compose config`, but not built in
> the environment where Phase 1 was developed. If a build fails, use the local setup below
> and open an issue.

## Local development

Requirements: Python 3.12+, Node 22, PostgreSQL 16, optionally Redis 7.

```bash
# Backend
cd backend
pip install -e ".[dev]"
createdb jobpilot
export JOBPILOT_DATABASE_URL=postgresql+psycopg://postgres@localhost:5432/jobpilot
export JOBPILOT_SECRET_KEY=$(python -c "import secrets;print(secrets.token_hex(32))")
export JOBPILOT_ADMIN_USERNAME=shubham JOBPILOT_ADMIN_PASSWORD=change-me
alembic upgrade head
uvicorn jobpilot.main:app --reload --port 8000
# Optional queue: export JOBPILOT_REDIS_URL=redis://localhost:6379/0
#                 celery -A jobpilot.worker worker -l info

# Frontend (second terminal)
cd frontend
npm install
JOBPILOT_API_URL=http://localhost:8000 npm run dev
```

Without `JOBPILOT_REDIS_URL`, search runs execute inside the API process.

### First steps in the app

1. **Settings & Health**: fill in and verify your facts. Scores use verified facts only, and eligibility (enrolment, work authorization, language levels) stays "uncertain" until verified.
2. **Job Discovery**: adjust the search and press **Run search**.
3. **Job Review**: approve, keep for later, or reject.
4. **Tracker**: follow-ups, outcomes, full history, CSV export.

## Tests

```bash
cd backend
createdb jobpilot_test
pytest                                   # 66 tests on a real Postgres via the migrations

# Browser walkthrough against a running, freshly migrated stack
JOBPILOT_E2E_BASE_URL=http://localhost:3000 JOBPILOT_E2E_PASSWORD=... pytest tests/e2e
```

Latest results: [docs/test-results/phase-1.md](docs/test-results/phase-1.md).

## Configuration

| Variable | Required | Purpose |
| --- | --- | --- |
| `JOBPILOT_DATABASE_URL` | yes | SQLAlchemy URL (`postgresql+psycopg://…`) |
| `JOBPILOT_SECRET_KEY` | yes | Signs session cookies (16+ chars) |
| `JOBPILOT_ADMIN_USERNAME`, `JOBPILOT_ADMIN_PASSWORD` | first run | Creates the login if no user exists |
| `JOBPILOT_REDIS_URL` | no | Enables the Celery queue |
| `JOBPILOT_COOKIE_SECURE` | prod | `true` behind HTTPS |
| `JOBPILOT_CORS_ORIGINS` | no | JSON list, default `["http://localhost:3000"]` |
| `JOBPILOT_ANTHROPIC_API_KEY`, `JOBPILOT_CLAUDE_MODEL` | Phase 2 | Server-side only |
| `JOBPILOT_API_URL` (frontend) | yes | Where Next.js proxies `/api/v1` |

## Repository layout

```
backend/
  jobpilot/
    domain/        states.py (transition table), transitions.py (only state writer),
                   approvals.py, dedup.py, scoring.py (rules-v0), profile.py
    orchestrator/  runs.py: plans runs, isolates sources, persists results
    agents/        discovery adapters (mock + registry of planned sources)
    api/           routers, auth, CSRF, idempotency
    db/            models (23 tables), session
    worker.py      Celery app
    bootstrap.py   sources, seed profile, default search, admin user
  migrations/      Alembic
  tests/           unit/, integration/, e2e/
frontend/src/      Next.js App Router pages, typed API client
infra/             docker-compose.yml, Dockerfiles
docs/              design pack, integrations, test results, screenshots
```

## Design

The full design pack (architecture, schema, API contracts, agent schemas, state machine,
wireframes, security model, acceptance-test plan) is in
[docs/design-pack.md](docs/design-pack.md), with diagrams in the
[editable version](https://claude.ai/code/artifact/6d621ef4-65c5-4beb-8a93-897cd651f005).

## Known limitations

- Only the mock source is automated. Real adapters (Bundesagentur für Arbeit, Greenhouse, Lever, Personio) come in Phase 2, after checking each source's terms.
- StepStone, Indeed, XING and LinkedIn will only ever support manual URL import, because their terms restrict automated access.
- `rules-v0` is keyword matching. It misses synonyms and context; Phase 2 adds Claude for the judgment parts.
- Single user. No password change or login rate limiting yet (Phase 6).
- No scheduler or independent monitor yet (Phase 5); runs are started by hand.
- The seed profile is unverified on purpose. Fill in eligibility, languages and the period since August 2025 before relying on scores.

## Next steps

Phase 2: Bundesagentur für Arbeit adapter, Greenhouse/Lever/Personio adapters, manual URL
import, Claude-based matching behind a provider interface with token budgets, editable
scoring weights.
