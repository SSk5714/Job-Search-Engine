# Integrations: implemented, mocked, pending

Nothing here is reported as working unless a test exercises it. Source labels in the app follow
the same rule: **Untested** adapters become **Automated** only after their first successful live run.

| Integration | Status | Evidence |
| --- | --- | --- |
| PostgreSQL 16 | Implemented | All tests run on Postgres via the Alembic migrations |
| Redis + Celery worker | Implemented | Live stack in the browser walkthrough |
| Mock job board (3 feed formats) | Mocked | `test_discovery.py` |
| Bundesagentur für Arbeit Jobsuche | Implemented, **live-untested** | `test_adapters.py` with recorded responses. Endpoints and the public key come from the community docs at github.com/bundesAPI/jobsuche-api; the agency publishes no official API terms. |
| Greenhouse Job Board API | Implemented, **live-untested** | Recorded responses matching the real API shape (fetched 2026-10-17) |
| Lever Postings API (global and EU) | Implemented, **live-untested** | Recorded responses matching the real API shape |
| Personio XML feed | Implemented, **live-untested** | Recorded feed; parsed with defusedxml |
| Manual URL import | Implemented | `test_phase2_api.py`; LinkedIn, StepStone, Indeed, XING and GermanTechJobs pages are never fetched |
| Availability recheck | Implemented for BA, Greenhouse, Lever, Personio | `test_phase2_api.py` |
| Claude API (structured outputs, `claude-haiku-5-5` default) | Implemented, **live-untested** | Fake provider plus stubbed SDK client; set `JOBPILOT_ANTHROPIC_API_KEY` to activate |
| Rule-based matching `rules-v0` | Implemented | Fallback whenever Claude is off, over budget or failing |
| DOCX/PDF generation (python-docx, ReportLab) | Implemented | `test_documents.py`: PDFs text-extracted, DOCX re-opened |
| Claude document writing | Implemented, **live-untested** | Fake provider that fabricates a claim; the verifier catches it |
| Playwright form preparation | Implemented, **tested against the mock portal only** | `test_preparation.py`, `test_field_classifier.py`, e2e walkthrough; real employer sites untested |
| Browser submission after approval | Implemented, **tested against the mock portal only** | Success, validation failure, unclear result, HTTP 500, CAPTCHA, sign-in, off-site, retries |
| Scheduler (Celery beat, or `python -m jobpilot.scheduler`) | Implemented | `test_scheduler.py`; `test_live_processes.py` runs real Redis + Celery worker + beat |
| Independent monitor + alerts | Implemented | `test_monitor.py` (simulated failures, own process, DB outage); live-stack run |
| Email notifications (SMTP) | Implemented, **live-untested with a real provider** | `test_notifications.py` against a local SMTP server (aiosmtpd): send, 4xx retry, 5xx stop, crash recovery |
| Docker images and full stack | Built and smoke-tested in CI | `infra/smoke-test.sh` in GitHub Actions: build, start, sign-in, search, heartbeats, backup, restore drill |

## Setting up the real sources

In **Job Discovery**, tick a source and fill in its options:

- **Bundesagentur für Arbeit**: works with no setup. Uses your keywords (or track defaults such as "Android Entwickler"), your cities and a radius. Germany only.
- **Greenhouse**: board tokens, the part after `job-boards.greenhouse.io/` in a company's careers URL.
- **Lever**: site names from `jobs.lever.co/<site>`; choose EU for `jobs.eu.lever.co`.
- **Personio**: company subdomains from `<company>.jobs.personio.de`.

Company boards return all of a company's openings. JobPilot keeps technical roles in your
countries (and your keywords, if set).
