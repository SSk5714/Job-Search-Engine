# 8. Commands

Run everything from the repository folder (`cd ~/Job-Search-Engine`). `./jp` is a shortcut for
`docker compose` with the right files and `.env`, so every Docker Compose command works after it.

## First-time setup (WSL / Linux)

```bash
# Docker permission (once)
sudo usermod -aG docker $USER && exec su -l $USER
sudo service docker start

# Code and settings
cd ~ && git clone https://github.com/SSk5714/Job-Search-Engine.git && cd Job-Search-Engine
cp .env.example .env            # then set JOBPILOT_SECRET_KEY, POSTGRES_PASSWORD, JOBPILOT_ADMIN_PASSWORD

# Build and start (first time 5–10 min)
./jp up -d --build
```

Open http://localhost:3000.

## Start, stop, status

| Task | Command |
| --- | --- |
| Status of all 7 parts | `./jp ps` |
| Stop everything (data kept) | `./jp stop` |
| Start again | `./jp start` |
| Run in the foreground; Ctrl+C stops all | `./jp up` |
| Remove containers, keep data | `./jp down` |
| **Erase everything (data too)** | `./jp down -v` |
| After Windows restart | `sudo service docker start` then `./jp up -d` |
| Stop WSL completely (PowerShell) | `wsl --shutdown` |

## Logs

| Task | Command |
| --- | --- |
| All logs, live | `./jp logs -f` |
| One service | `./jp logs -f api` (or `worker`, `beat`, `monitor`, `web`, `postgres`, `redis`) |
| Last hour, backend only | `./jp logs --since 1h api worker beat monitor` |

## Update to the newest code

```bash
./jp exec api python -m jobpilot.ops backup   # safety first
git pull
./jp up -d --build
```

## Database and Redis

| Task | Command |
| --- | --- |
| SQL shell | `./jp exec postgres psql -U jobpilot jobpilot` |
| Inside psql: list tables / quit | `\dt` · `\q` |
| Example query | `select title, company from jobs order by created_at desc limit 10;` |
| Redis shell | `./jp exec redis redis-cli` (`ping`, `llen celery`) |
| Database password | `grep POSTGRES_PASSWORD .env` |
| Use your own folders + reach DB from Windows tools | `cp infra/docker-compose.local.example.yml infra/docker-compose.local.yml` (see `docs/operations.md`) |

## Backups

| Task | Command |
| --- | --- |
| Back up now | `./jp exec api python -m jobpilot.ops backup` |
| List | `./jp exec api python -m jobpilot.ops list` |
| Verify one | `./jp exec api python -m jobpilot.ops verify NAME` |
| Restore | `./jp stop worker beat monitor` → `./jp exec api python -m jobpilot.ops restore NAME --yes` → `./jp start worker beat monitor` |
| Is the scheduler / monitor alive? | `./jp exec api python -m jobpilot.ops alive scheduler` (or `monitor`) |

## Inside a container

| Task | Command |
| --- | --- |
| Shell in the API container | `./jp exec api sh` (`exit` to leave) |
| Processes of a container | `docker top infra-postgres-1` |
| Disk used by Docker | `docker system df` |
| Clear old build cache | `docker builder prune` |

## Development without Docker (backend)

```bash
cd backend
pip install -e ".[dev]"
createdb jobpilot_test
pytest                                  # 241 tests
export JOBPILOT_DATABASE_URL=postgresql+psycopg://postgres@localhost:5432/jobpilot
alembic upgrade head
uvicorn jobpilot.main:app --reload      # API on :8000
celery -A jobpilot.worker worker -l info
celery -A jobpilot.worker beat -l info
python -m jobpilot.monitor
cd ../frontend && npm install && JOBPILOT_API_URL=http://localhost:8000 npm run dev   # web on :3000
```

## Server with HTTPS

Set `JOBPILOT_DOMAIN` and `JOBPILOT_PUBLIC_BASE_URL` in `.env`; `./jp` then adds the Caddy file automatically:

```bash
./jp up -d --build
```

Full guide: [`docs/deployment.md`](../deployment.md). Troubleshooting by alert: [`docs/operations.md`](../operations.md).
