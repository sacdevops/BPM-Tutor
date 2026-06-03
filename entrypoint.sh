#!/bin/sh
# BPM-Tutor container entrypoint
# Starts Gunicorn (web) or Celery (worker). Schema is managed by db.create_all() + _run_column_migrations() at startup.
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
echo "[entrypoint] Starting Gunicorn..."
exec gunicorn \
    --worker-class geventwebsocket.gunicorn.workers.GeventWebSocketWorker \
    --workers 1 \
    --worker-connections 1000 \
    --bind "0.0.0.0:${PORT:-5001}" \
    --timeout 300 \
    --keep-alive 5 \
    --access-logfile - \
    --error-logfile - \
    main:app
