# API, worker, beat and monitor all run from this image.
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app

# pg_dump/pg_restore matching the PostgreSQL 16 server, for backups (Debian's own client is older)
ARG PG_MAJOR=16
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl gnupg \
 && install -d /usr/share/postgresql-common/pgdg \
 && curl -fsSL -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc https://www.postgresql.org/media/keys/ACCC4CF8.asc \
 && echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt bookworm-pgdg main" \
      > /etc/apt/sources.list.d/pgdg.list \
 && apt-get update \
 && apt-get install -y --no-install-recommends postgresql-client-${PG_MAJOR} \
 && apt-get purge -y gnupg && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*
ENV JOBPILOT_PG_DUMP_PATH=/usr/lib/postgresql/${PG_MAJOR}/bin/pg_dump \
    JOBPILOT_PG_RESTORE_PATH=/usr/lib/postgresql/${PG_MAJOR}/bin/pg_restore

COPY backend/pyproject.toml ./
COPY backend/jobpilot ./jobpilot
RUN pip install .
# Chromium for application-form preparation (isolated, headless contexts)
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
RUN playwright install --with-deps chromium && chmod -R a+rX /ms-playwright && rm -rf /var/lib/apt/lists/*

COPY backend/alembic.ini ./
COPY backend/migrations ./migrations

RUN useradd --create-home --uid 10001 jobpilot \
 && mkdir -p /app/storage/documents /app/storage/backups /app/storage/monitor \
 && chown -R jobpilot /app/storage && chmod 700 /app/storage/backups
USER jobpilot
ENV JOBPILOT_DOCUMENTS_DIR=/app/storage/documents JOBPILOT_BACKUP_DIR=/app/storage/backups

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=4).status == 200 else 1)" || exit 1
CMD ["sh", "-c", "alembic upgrade head && uvicorn jobpilot.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips='*'"]
