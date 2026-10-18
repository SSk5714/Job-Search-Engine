# 7. Special libraries and how they are used

All versions are pinned (`backend/pyproject.toml`, `frontend/package.json`) so every build is identical.

## Backend (Python)

| Library | Version | What it does here | Where |
| --- | --- | --- | --- |
| `fastapi` / `starlette` | 0.143.5 / 1.8.0 | HTTP API, routing, dependency injection (auth, DB session), middleware | `main.py`, `api/` |
| `uvicorn[standard]` | 0.32.1 | ASGI server that runs FastAPI | Docker `CMD` |
| `pydantic` / `pydantic-settings` | 2.10.6 / 2.6.1 | Validates every request body, agent output and setting; reads `JOBPILOT_*` env vars | `schemas/`, `config.py`, `domain/settings.py` |
| `sqlalchemy` | 2.0.55 | ORM: models, transactions, `SELECT … FOR UPDATE` row locks, `SKIP LOCKED` queues | `db/models.py`, everywhere |
| `alembic` | 1.14.1 | Database migrations, run on API start (`alembic upgrade head`) | `migrations/` |
| `psycopg[binary]` | 3.2.13 | PostgreSQL driver | `db/session.py` |
| `celery[redis]` | 5.4.0 | Background worker and beat clock | `worker.py` |
| `anthropic` | 1.15.0 | Official Claude SDK; `messages.parse(output_format=Model)` returns schema-checked objects | `ai/claude.py` |
| `httpx` | 0.28.1 | HTTP client for job sources with timeouts, rate limit, retry on 429/5xx | `agents/discovery/http.py` |
| `playwright` | 1.56.0 | Headless Chromium: read form fields, fill, attach files, screenshot, submit after approval | `agents/preparation/browser.py` |
| `python-docx` | 1.1.2 | Writes the CV and letter as DOCX | `documents/render.py` |
| `reportlab` | 4.2.5 | Writes the CV and letter as PDF (real, selectable text) | `documents/render.py` |
| `argon2-cffi` | 23.1.0 | Password hashing (Argon2id) | `api/deps.py` |
| `itsdangerous` | 2.2.0 | Signs and time-limits the session cookie | `api/deps.py` |
| `defusedxml` | 0.7.1 | Safe XML parsing of Personio feeds (blocks XML bombs and external entities) | `adapters/personio.py` |
| `croniter` | 6.0.0 | Next run times of schedules; we compute on wall-clock time so daylight-saving changes are correct | `domain/schedule.py` |

Standard library highlights: `smtplib` (email), `tarfile` + `hashlib` (backups with SHA-256 checksums),
`zoneinfo` (Europe/Berlin), `subprocess` (`pg_dump` / `pg_restore`).

## Backend test and tooling

| Library | Use |
| --- | --- |
| `pytest` 9.1.1 | 241 tests on a real PostgreSQL built by the migrations |
| `pypdf` 6.21.1 | Tests read the generated PDFs back to check their text |
| `aiosmtpd` 1.4.6 | A real local SMTP server in tests (send, 4xx retry, 5xx stop) |
| `python-multipart` 0.0.32 | Form uploads for the mock employer portal used in tests |
| `ruff` 0.12.11 | Lint in CI |
| `pip-audit` 2.9.0 | Known-vulnerability scan in CI |

## Frontend

| Package | Use |
| --- | --- |
| `next` 15.5.28 | App Router pages, server, `/api/v1` rewrite, security headers (`next.config.ts`), standalone build for Docker |
| `react` / `react-dom` 19.1.10 | UI components |
| `typescript` 5.9 | Types for every API call (`src/lib/api.ts`) |

No UI framework or state library: plain React with one small CSS file, which keeps the bundle small (about
110 KB per page).

## Outside the code

| Tool | Use |
| --- | --- |
| `pg_dump` / `pg_restore` 16 | Backups and restores (installed in the backend image from the PostgreSQL apt repository) |
| Chromium (via `playwright install --with-deps`) | Browser for form preparation |
| Caddy 2 | HTTPS reverse proxy on a server |

Next: [8. Commands](08-commands.md)
