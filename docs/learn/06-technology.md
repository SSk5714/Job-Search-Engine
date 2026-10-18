# 6. Technology used

| Layer | Technology | Version | Why this choice |
| --- | --- | --- | --- |
| Frontend | **Next.js** (App Router) + **React** + **TypeScript** | 15.5.28 · 19.1.10 · 5.9 | Required by the brief. One origin for the browser: Next.js forwards `/api/v1` to the backend, so the session cookie stays same-site |
| Backend API | **FastAPI** on **Uvicorn**, Python | 0.143.5 · 0.32 · 3.12 | Required. Typed request/response models (Pydantic), automatic validation, fast |
| Background jobs | **Celery** with **Redis** as broker | 5.4 · Redis 7 | Searches and the minute tick run outside web requests; `acks_late` so a crashed worker's task is redelivered |
| Scheduler | **Celery beat** (or `python -m jobpilot.scheduler` without Redis) | 5.4 | Sends one tick a minute; all schedule logic is our own deterministic code |
| Database | **PostgreSQL** | 16 | Transactions, row locks, partial unique indexes and JSONB, which the safety rules rely on |
| ORM and migrations | **SQLAlchemy 2** + **Alembic** | 2.0.55 · 1.14 | Typed models; versioned schema changes (`0001`–`0006`) |
| AI | **Anthropic Claude API** (official Python SDK), structured outputs | default model `claude-haiku-5-5` | Language understanding for matching and writing; output forced into a schema; code verifies everything |
| Browser automation | **Playwright** with Chromium | 1.56 | Reads and fills employer forms in isolated, headless contexts |
| Documents | **python-docx** (DOCX) + **ReportLab** (PDF) | 1.1.2 · 4.2.5 | ATS-friendly single-column files with real text |
| Email | Python `smtplib` | stdlib | Plain SMTP, any provider |
| Containers | **Docker** + **Docker Compose** | Engine 24+ · Compose 2.24+ | The whole stack starts with one command, identical on every machine |
| HTTPS (server) | **Caddy** | 2 | Automatic Let's Encrypt certificates, simple config |
| CI | **GitHub Actions** | — | Tests, lint, audits, image build and full-stack smoke test on every push |

## Why these patterns

| Pattern | Where | Benefit |
| --- | --- | --- |
| Deterministic orchestrator + agents | `domain/`, `orchestrator/`, `agents/` | AI can never change workflow state; every decision is reproducible |
| State machine with guards | `domain/states.py`, `transitions.py` | Impossible moves (e.g. submit without approval) are rejected by code and by the database |
| Idempotency keys | `api/deps.py::run_idempotent` | Double clicks and retries never act twice |
| Hash-bound approval | `domain/approvals.py` | What you approved is exactly what gets sent |
| Structured outputs + verification | `ai/claude.py`, `documents/verify.py` | Claude's answers must fit a schema; invented facts are caught |
| Heartbeats | `db/heartbeat.py` | Scheduler and monitor detect each other stopping |
| Append-only history | `application_state_history`, document versions, profile versions | Nothing is silently overwritten |
| 12-factor configuration | `config.py` (pydantic-settings, `JOBPILOT_*`) | All settings from environment variables / `.env` |

## Runtime numbers

| Item | Value |
| --- | --- |
| Containers | 7 (+ Caddy on a server, + mock portal for demos) |
| API endpoints | 67 under `/api/v1` |
| Database tables | 29 |
| Monitor checks | 17, every 60 s |
| Automated tests | 241 backend + browser walkthrough + Docker smoke test |
| First Docker build | about 5–10 minutes; later builds seconds (layer cache) |

Next: [7. Special libraries](07-libraries.md)
