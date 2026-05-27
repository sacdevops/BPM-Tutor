"""Celery application factory for BPM-Tutor.

Usage
-----
Start the worker (inside Docker or locally):

    celery -A app.celery_app.celery worker --loglevel=info --queues=llm

The ``ROLE=worker`` environment variable triggers the Celery worker via
the entrypoint.sh script when using Docker Compose.
"""
from __future__ import annotations

import os

from celery import Celery
from celery.schedules import crontab

_BROKER_URL = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
_BACKEND_URL = os.getenv('REDIS_URL', 'redis://localhost:6379/0')


def make_celery(flask_app=None) -> Celery:
    """Create a Celery instance, optionally bound to a Flask app."""
    cel = Celery(
        'bpmtutor',
        broker=_BROKER_URL,
        backend=_BACKEND_URL,
        include=['app.tasks.llm_tasks', 'app.tasks.study_tasks'],
    )

    cel.conf.update(
        task_serializer='json',
        accept_content=['json'],
        result_serializer='json',
        timezone='UTC',
        enable_utc=True,
        task_routes={
            'app.tasks.llm_tasks.*': {'queue': 'llm'},
            # study_tasks (notifications, backups) go to the default 'celery' queue
            # so the worker can pick them up alongside LLM tasks
            'app.tasks.study_tasks.*': {'queue': 'celery'},
        },
        worker_prefetch_multiplier=1,
        task_acks_late=True,
        task_reject_on_worker_lost=True,
        # Beat schedule for periodic maintenance tasks
        beat_schedule={
            'study-email-notifications': {
                'task': 'app.tasks.study_tasks.send_study_notifications',
                'schedule': 3600.0,  # every hour
            },
            'sqlite-daily-backup': {
                'task': 'app.tasks.study_tasks.backup_database',
                'schedule': crontab(hour=3, minute=0),  # daily at 03:00 UTC
            },
        },
    )

    if flask_app is not None:
        # Wrap tasks so they run inside a Flask application context.
        class _ContextTask(cel.Task):
            def __call__(self, *args, **kwargs):
                with flask_app.app_context():
                    return self.run(*args, **kwargs)

        cel.Task = _ContextTask

    return cel


# Module-level instance (used by the Celery CLI worker process).
# The Flask app context is NOT attached here — tasks import it lazily.
celery = make_celery()
