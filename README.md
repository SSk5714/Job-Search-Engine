# JobPilot Europe

A job-application pipeline for Germany and Europe. It discovers jobs, scores them against
a **verified** candidate profile, and tracks every application. Nothing is ever submitted
without your explicit approval.

One deterministic orchestrator owns all workflow state in PostgreSQL. Specialized workers
(discovery, matching, and later documents and form preparation) only return validated
results, and AI is used only where language understanding helps.

**Status: Phase 2 of 6 (real sources and Claude matching) complete.** See [what works today](#what-works-today)
and [docs/integrations.md](docs/integrations.md) for what is mocked or pending.

![Job Review](docs/screenshots/04-job-review.png)

## What works today

- Job sources: Bundesagentur für Arbeit, Greenhouse, Lever and Personio adapters, plus a mock board for development
- **Add job from URL**: API-backed links are fetched; LinkedIn, StepStone, Indeed and XING links are never fetched, so you paste the details
- Claude-assisted matching (`claude-haiku-5-5` by default). Claude extracts skills and requirements with verbatim quotes, mapped to your verified facts; code computes the score and eligibility. Invented facts and quotes are discarded.
- Per-run and daily AI budgets, token and cost records, and a visible fallback to rule-based scoring
- Editable score weights and thresholds, and re-scoring that keeps old evaluations for comparison
- Availability rechecks: approving a job rechecks the listing first, and closed listings are marked expired
- URL normalization and cross-source dedup
- The full application state machine with guards, history, optimistic locking and idempotent writes
- Approval binding to document and form-value hashes, with invalidation on any change (backend)
- Profile editor with versioning and per-fact verification
- Dashboard, Job Discovery, Job Review, Tracker with history drawer, CSV export, Settings & Health
- Honest status: sources and services that aren't built are labelled Planned, Manual or not implemented

Not yet: CV and cover letter generation (Phase 3), form preparation and submission (4),
scheduler, monitor and notifications (5), production hardening (6).

> The real sources and Claude were tested against recorded responses and a fake model, because the
> build environment has no outbound access or API key. The app labels them **Untested** until your
> first live run succeeds. See [docs/integrations.md](docs/integrations.md).

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

1. **Settings & Health**: fill in and verify your facts. Scores use verified facts only, and eligibility (enrolment, work authorization, language levels) stays "uncertain" until verified. Set matching weights and AI limits there too.
2. **Job Discovery**: tick Bundesagentur für Arbeit (no setup needed) and add Greenhouse, Lever or Personio company names, then press **Run search**.
3. **Job Review**: approve, keep for later, or reject.
4. **Tracker**: follow-ups, outcomes, full history, CSV export.

## Tests

```bash
cd backend
createdb jobpilot_test
pytest                                   # 112 tests on a real Postgres via the migrations

# Browser walkthrough against a running, freshly migrated stack
JOBPILOT_E2E_BASE_URL=http://localhost:3000 JOBPILOT_E2E_PASSWORD=... pytest tests/e2e
```

Latest results: [docs/test-results/phase-2.md](docs/test-results/phase-2.md).

## Configuration

| Variable | Required | Purpose |
| --- | --- | --- |
| `JOBPILOT_DATABASE_URL` | yes | SQLAlchemy URL (`postgresql+psycopg://…`) |
| `JOBPILOT_SECRET_KEY` | yes | Signs session cookies (16+ chars) |
| `JOBPILOT_ADMIN_USERNAME`, `JOBPILOT_ADMIN_PASSWORD` | first run | Creates the login if no user exists |
| `JOBPILOT_REDIS_URL` | no | Enables the Celery queue |
| `JOBPILOT_COOKIE_SECURE` | prod | `true` behind HTTPS |
| `JOBPILOT_CORS_ORIGINS` | no | JSON list, default `["http://localhost:3000"]` |
| `JOBPILOT_ANTHROPIC_API_KEY` | for Claude | Server-side only; without it, rule-based matching is used |
| `JOBPILOT_CLAUDE_MODEL` | no | Default `claude-haiku-5-5` |
| `JOBPILOT_AI_PRICES` | no | JSON price override, e.g. `{"claude-haiku-5-5": [0.10, 0.50]}` (USD per MTok) |
| `JOBPILOT_HTTP_USER_AGENT` | no | Sent to job sources |
| `JOBPILOT_API_URL` (frontend) | yes | Where Next.js proxies `/api/v1` |

## Repository layout

```
backend/
  jobpilot/
    domain/        states.py (transition table), transitions.py (only state writer),
                   approvals.py, dedup.py, scoring.py (rules-v0), profile.py
    orchestrator/  runs.py: plans runs, isolates sources, persists results
    agents/        discovery adapters (BA, Greenhouse, Lever, Personio, mock), Claude matcher
    ai/            provider interface, Claude client (structured outputs, pricing)
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

- The Bundesagentur für Arbeit API is community-documented, with no official terms; it may change without notice.
- Greenhouse, Lever and Personio need the company identifiers you add. There is no cross-company search.
- StepStone, Indeed, XING and LinkedIn only support manual URL import, because their terms restrict automated access.
- Re-scoring runs inside the request; with Claude on, large re-scores take a while (about 50 jobs per run by default).
- `rules-v0` (the fallback) is keyword matching and misses synonyms and context.
- Single user. No password change or login rate limiting yet (Phase 6).
- No scheduler or independent monitor yet (Phase 5); runs are started by hand.
- The seed profile is unverified on purpose. Fill in eligibility, languages and the period since August 2025 before relying on scores.

## Next steps

Phase 3: master CV handling, tailored CV and cover letter generation with Claude, DOCX and PDF
output, version history, and a factual verification report tying every claim to a verified
profile fact.
