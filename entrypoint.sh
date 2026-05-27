#!/bin/sh
# BPM-Tutor container entrypoint
# Runs Flask-Migrate, then starts Gunicorn (web) or Celery (worker).
set -e

# ROLE defaults to 'web'; docker-compose overrides with 'worker' for Celery
ROLE="${ROLE:-web}"

if [ "$ROLE" = "worker" ]; then
    echo "[entrypoint] Starting Celery worker..."
    exec celery -A app.celery_app.celery worker \
        --loglevel=info \
        --concurrency=4 \
        --queues=llm,celery \
        --max-tasks-per-child=200
fi

if [ "$ROLE" = "beat" ]; then
    echo "[entrypoint] Starting Celery Beat scheduler..."
    # --schedule stores the beat state file in the shared data/ volume so it
    # survives container restarts (avoids re-firing tasks after a restart).
    exec celery -A app.celery_app.celery beat \
        --loglevel=info \
        --schedule=/app/data/celerybeat-schedule
fi

# Default: web role
echo "[entrypoint] Running database migrations..."
# 'flask db upgrade' applies pending migrations; it's a no-op if the DB is
# already up-to-date. Falls back gracefully if migrations/ does not exist yet.
if [ -d "migrations" ]; then
    flask db upgrade || echo "[entrypoint] Migration skipped or already up-to-date."
else
    echo "[entrypoint] No migrations/ folder found — skipping flask db upgrade."
fi

echo "[entrypoint] Starting Gunicorn..."
exec gunicorn \
    --worker-class gevent \
    --workers 1 \
    --worker-connections 1000 \
    --bind "0.0.0.0:${PORT:-8080}" \
    --timeout 300 \
    --keep-alive 5 \
    --access-logfile - \
    --error-logfile - \
    main:app
