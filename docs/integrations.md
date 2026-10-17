# Integrations: implemented, mocked, pending

Nothing in this list is reported as working unless a test exercises it.

| Integration | Status | Evidence |
| --- | --- | --- |
| PostgreSQL 16 | Implemented | All tests run on Postgres via the Alembic migration |
| Redis + Celery worker | Implemented | Manual smoke test: run queued, executed by worker, 7 jobs classified |
| In-process runs (no Redis) | Implemented | Integration tests |
| Mock job board (3 feed formats) | Mocked | `tests/integration/test_discovery.py` |
| Broken-source simulation | Mocked | `test_one_broken_source_does_not_stop_the_others` |
| Rule-based matching `rules-v0` | Implemented (placeholder for Claude) | `tests/unit/test_scoring.py` |
| Bundesagentur für Arbeit Jobsuche | Pending (Phase 2) | Shown as Planned; enabling is refused |
| Greenhouse / Lever / Personio | Pending (Phase 2) | Shown as Planned |
| StepStone, Indeed, XING, LinkedIn, GermanTechJobs | Manual only (Phase 2 URL import) | Shown as Manual |
| Claude API | Pending (Phase 2) | Health shows `not_configured` |
| DOCX/PDF generation | Pending (Phase 3) | — |
| Playwright form preparation | Pending (Phase 4) | — |
| Scheduler (Celery beat) | Pending (Phase 5) | Health shows `not_implemented` |
| Independent monitor + alerts | Pending (Phase 5) | Health shows `not_implemented` |
| Email notifications | Pending (Phase 5) | — |
| Docker images | Written, not built here | No Docker daemon in the build environment; `docker compose config` validates |
