FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY backend/pyproject.toml ./
COPY backend/jobpilot ./jobpilot
RUN pip install --no-cache-dir .

COPY backend/alembic.ini ./
COPY backend/migrations ./migrations

RUN useradd --create-home --uid 10001 jobpilot && mkdir -p /app/storage/documents && chown -R jobpilot /app/storage
USER jobpilot
ENV JOBPILOT_DOCUMENTS_DIR=/app/storage/documents

EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && uvicorn jobpilot.main:app --host 0.0.0.0 --port 8000"]
