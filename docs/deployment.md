# Deployment

JobPilot runs as one Docker Compose stack: PostgreSQL, Redis, the API, a Celery worker, Celery beat
(the scheduler), the independent monitor and the web app. For a server, Caddy sits in front and gets
HTTPS certificates automatically.

## What you need

- A Linux server or VM with 2 GB RAM (4 GB is comfortable, since Chromium runs for form preparation) and 20 GB disk.
  A small VPS in the EU works, e.g. Hetzner CX22 or similar.
- Docker Engine 24+ with the Compose plugin (`docker compose version` ≥ 2.24).
- For HTTPS: a domain (or subdomain) whose DNS A/AAAA record points to the server, and ports 80 and 443 open.

Running on your own laptop works the same way without the production file; it is then reachable only on
`http://localhost:3000`.

## 1. Get the code and create `.env`

```bash
git clone https://github.com/SSk5714/Job-Search-Engine.git jobpilot && cd jobpilot
cp .env.example .env
python3 -c "import secrets;print('JOBPILOT_SECRET_KEY='+secrets.token_hex(32));print('POSTGRES_PASSWORD='+secrets.token_hex(16))"
```

Put those two values into `.env`, and set `JOBPILOT_ADMIN_PASSWORD` (12+ characters). In production mode
(the Docker default) the API refuses to start with an empty or placeholder secret or a short admin password.
Keep `.env` private (`chmod 600 .env`); it is in `.gitignore`.

For a server also set:

```
JOBPILOT_DOMAIN=jobs.example.org
JOBPILOT_PUBLIC_BASE_URL=https://jobs.example.org
```

Optional: `JOBPILOT_ANTHROPIC_API_KEY` (Claude matching and writing), `JOBPILOT_SMTP_*`, `JOBPILOT_EMAIL_FROM`,
`JOBPILOT_NOTIFY_EMAIL_TO` (email notifications). Everything else has sensible defaults (see `.env.example`).

## 2. Start

Laptop (localhost only):

```bash
./jp up -d --build
```

Server with HTTPS:

```bash
./jp up -d --build
```

The first build takes 5–10 minutes (Chromium and its system libraries). Migrations run automatically when
the API starts. Check:

```bash
./jp ps        # all services "healthy" or "running"
./jp logs -f api
```

Open the site, sign in with the admin user, and go to **Settings & Health**: database, task queue, scheduler and
system monitor should all show *ok* within two minutes.

## 3. First things to do

1. **Change the admin password** (Settings & Health → Account), then remove `JOBPILOT_ADMIN_PASSWORD` from `.env`
   (it is only used to create the first user).
2. Import and verify your profile.
3. Turn off the *Mock job board* in Job Discovery and pick real sources; set a schedule.
4. **Backups:** a backup runs daily at 03:15 Berlin time into the `backups` volume. Copy them off the server
   (see [operations.md](operations.md#copy-backups-off-the-server)). Make one now: Settings & Health → Back up now.
5. Optional: send a test email from Settings & Health.

## What is exposed

| Port | Who listens | Reachable from |
| --- | --- | --- |
| 443, 80 | Caddy (production file only) | the internet; 80 only redirects to HTTPS |
| 3000 | web | `127.0.0.1` only (laptop setup); not published with the production file |
| 8000 | API | `127.0.0.1` only (laptop setup); not published with the production file |
| 5432, 6379 | PostgreSQL, Redis | never published; compose network only |

API docs (`/docs`) are off in production and additionally blocked by Caddy.

## Upgrading

```bash
cd jobpilot
./jp exec api python -m jobpilot.ops backup   # safety first
git pull
./jp up -d --build
```

Migrations run on API start. If an upgrade goes wrong, restore the backup you just made
([operations.md](operations.md#restore)).

## Running without Docker

See "Local development" in the README. For a long-running setup without Docker, run five processes under a
supervisor (systemd): `uvicorn jobpilot.main:app`, `celery -A jobpilot.worker worker`, `celery -A jobpilot.worker
beat`, `python -m jobpilot.monitor`, and the Next.js server, plus PostgreSQL 16, Redis 7 and the PostgreSQL 16
client tools (`pg_dump`) for backups.
