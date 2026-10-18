# Operations and troubleshooting

Commands below assume the Docker setup and use `./jp`, a shortcut in the repository root for `docker compose` with the right files and `.env`; prefix them with
`./jp exec api` (shortened to `exec api` here).
Without Docker, run the same `python -m ...` commands in `backend/` with your environment loaded.

## Daily health at a glance

- **Notifications → Open alerts**: everything the monitor found, each with cause and what to do. Alerts close
  themselves once the problem is gone; "Got it" only marks that you have seen one.
- **Settings & Health → Service health**: database, task queue, scheduler, system monitor, email, Claude API.
- **Settings & Health → Usage and cost**: Claude spend against the daily budget, searches, applications.
- Logs: `./jp logs --since 1h api worker beat monitor`. The monitor logs one
  JSON line per cycle (`"event": "monitor_cycle"`) and per new alert (`"alert_opened"`).

## Backups

What a backup contains: the whole database (`pg_dump` custom format) and every generated document and evidence
screenshot, plus `manifest.json` with checksums, row counts and the schema version. Backups are written to a
hidden temporary folder and renamed only when complete. They contain personal data.

| Task | Command |
| --- | --- |
| Make one now | `exec api python -m jobpilot.ops backup` (or Settings & Health → Back up now) |
| List | `exec api python -m jobpilot.ops list` |
| Check one | `exec api python -m jobpilot.ops verify NAME` (checksums, dump readable, archive complete) |

Daily backups run at `JOBPILOT_BACKUP_AT` (default 03:15 Berlin); the newest `JOBPILOT_BACKUP_KEEP` (14) scheduled
backups are kept. Manual and pre-restore backups are never deleted automatically. The monitor alerts when the last
good backup is older than 26 hours, and the scheduler alerts when a backup fails.

### Copy backups off the server

A backup on the same disk does not survive losing the server. Copy the volume regularly, e.g. from your laptop:

```bash
ssh server 'docker run --rm -v jobpilot_backups:/b alpine tar -C /b -cz .' > jobpilot-backups-$(date +%F).tar.gz
```

(The volume is named `<project>_backups`; `docker volume ls | grep backups` shows it.) Keep the copies encrypted
(e.g. on an encrypted disk or with `age`/`gpg`).

### Restore

Restoring replaces **all** current data with the backup. A `pre_restore` backup of the current state is made first,
the backup is verified before anything is touched, and row counts are compared afterwards.

```bash
./jp stop worker beat monitor
exec api python -m jobpilot.ops list
exec api python -m jobpilot.ops restore NAME --yes
./jp start worker beat monitor
```

Then sign in again. To restore from a copy you made off the server, put the backup folder back into the volume
first (`docker run --rm -i -v jobpilot_backups:/b alpine tar -C /b -xz < copy.tar.gz`).

A full restore drill (back up, delete data and a document, restore, compare every row and file) runs in the test
suite (`test_restore_drill_brings_back_identical_data`) and in CI against the real containers
(`infra/smoke-test.sh`).

## Accounts

- **Forgot the password:** `exec api python -c "from jobpilot.db.session import SessionLocal; from jobpilot.db import models as m; from jobpilot.api.deps import hash_password; db=SessionLocal(); u=db.query(m.User).first(); u.password_hash=hash_password('NEW-PASSWORD-12+'); u.session_version+=1; db.commit()"`
- **Locked out after wrong passwords:** wait 15 minutes (`JOBPILOT_LOGIN_WINDOW_MINUTES`).
- **Sign out everywhere:** the Sign out button already ends every session.

## Troubleshooting by alert

| Alert | What it means | What to do |
| --- | --- | --- |
| The scheduler has stopped / Scheduled searches are not running | No scheduler heartbeat | `./jp up -d beat worker`; check `logs beat worker`. Missed searches run once when it is back. |
| The system monitor has stopped | Raised by the scheduler | `./jp up -d monitor`; `logs monitor` |
| The task queue is unreachable / Scheduled searches cannot be queued | Redis down | `./jp up -d redis` |
| Tasks are piling up | Worker missing or overloaded | `up -d worker`; check `logs worker` |
| A search run looks stuck | Running > 20 min | It is failed automatically at 30 min; or press Stop on the run. Check `logs worker`. |
| Scheduled search … paused | 3 failed scheduled runs in a row | Run it by hand to see the error, fix the source settings, press Resume |
| … failed N times in a row | One source keeps failing | 404: wrong board/company name. 403: the source blocks access; disable it. 429: search less often. |
| Unusually many errors | Error spike | Settings & Health → Recent errors shows the component |
| Claude rejected the API key | 401 from Claude | Fix `JOBPILOT_ANTHROPIC_API_KEY`, restart api and worker. Rules and templates are used meanwhile. |
| Claude API rate limits / calls failing | 429 / timeouts | Usually temporary; lower "AI jobs per run" |
| Daily Claude budget almost/used up | Spend ≥ 80 % / 100 % | Nothing breaks; raise the budget if you want more Claude evaluations |
| The application browser had problems | Playwright errors | Retry; if one site keeps failing, apply there yourself. If all fail, the image lacks Chromium: rebuild. |
| Your CV/cover letter file is damaged | File missing or corrupt | Regenerate in Application Review; check the documents volume |
| Listing closed | The job you are preparing disappeared | Check the employer site; withdraw if gone |
| Waiting … in "<state>" | Application stuck past its threshold | Open it and continue, or withdraw. Thresholds: `PUT /api/v1/settings/monitor` |
| Possible duplicate submission / A submission never finished / outcome unclear | Submission safety | Do not submit again. Check the portal or your email, then record the outcome in Application Review. |
| Two applications for the same role | Same job listed twice | Withdraw one in the Tracker |
| Email notifications are failing | SMTP problem | Check `JOBPILOT_SMTP_*`, send a test email, press Retry email |
| The daily backup failed / No recent backup | Backups | Run `exec api python -m jobpilot.ops backup` to see the error; check disk space (`df -h`) |
| The database was unreachable | Past outage | Check recent runs and anything in "needs manual input", then Resolve |

## Common problems

- **API restarts with "Refusing to start: JOBPILOT_SECRET_KEY…"**: production mode found a placeholder secret or a
  short admin password. Fix `.env` and `up -d` again.
- **`POSTGRES_PASSWORD` required**: compose refuses to start without it; set it in `.env`.
- **Changed `POSTGRES_PASSWORD` after the first start**: PostgreSQL keeps the original password in its volume.
  Change it inside the database (`ALTER USER jobpilot PASSWORD '…'`) or keep the old one.
- **Cannot sign in after moving to HTTPS, or the other way round**: `JOBPILOT_COOKIE_SECURE=true` needs HTTPS. The
  production compose file sets it; on plain `http://localhost` it must be false.
- **Disk full**: `docker system df`; prune old images (`docker image prune`), check the backups volume size and
  `JOBPILOT_BACKUP_KEEP`.
- **Emails link to localhost**: set `JOBPILOT_PUBLIC_BASE_URL`.

## Data retention

The scheduler prunes operational records hourly: idempotency keys after 7 days, sign-in attempts after 30, error
events and health history after 90, resolved notifications after 180. Applications, jobs, documents, history and
your profile are never pruned.
