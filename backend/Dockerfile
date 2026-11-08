# syntax=docker/dockerfile:1

# ---------------------------------------------------------------------------
# OrderFlow backend image
#   FastAPI + SQLAlchemy 2 + Alembic, served by uvicorn.
#   Production DB is PostgreSQL (psycopg 3). SQLite also works for local runs.
# ---------------------------------------------------------------------------
FROM python:3.13-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# psycopg[binary] ships its own libpq, but curl is needed for the healthcheck
# and tini gives us proper signal handling / zombie reaping as PID 1.
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl tini \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# --- Dependencies first (better layer caching) ---
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# --- Application code ---
COPY alembic.ini ./
COPY migrations ./migrations
COPY app ./app
COPY scripts ./scripts

# --- Non-root runtime ---
# Uploads live on a named volume; the directory must exist and be writable.
RUN useradd --create-home --uid 10001 appuser \
 && mkdir -p /data/uploads \
 && chmod 755 /app/scripts/docker-entrypoint.sh \
 && chown -R appuser:appuser /app /data
USER appuser

ENV LOCAL_STORAGE_PATH=/data/uploads \
    APP_ENV=production \
    PORT=8000

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS "http://127.0.0.1:${PORT}/health" || exit 1

ENTRYPOINT ["/usr/bin/tini", "--", "/app/scripts/docker-entrypoint.sh"]
CMD ["serve"]
