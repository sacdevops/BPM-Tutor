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
                'schedule': 3600.0,  # every hour; task checks configured interval internally
            },
        },
    )

    if flask_app is not None:
        # Wrap tasks so they run inside a Flask application context.
        class _ContextTask(cel.Task):
            def __call__(self, *args, **kwargs):
                with flask_app.app_context():
                    return self.run(*args, **kwargs)

            def on_failure(self, exc, task_id, args, kwargs, einfo):
                """Emit an error event over SocketIO when an LLM task fails."""
                _on_task_failure(self, exc, task_id, args, kwargs, einfo)

        cel.Task = _ContextTask
    else:
        # Worker process: attach error handler without Flask app context.
        class _ContextTask(cel.Task):  # type: ignore[no-redef]
            def on_failure(self, exc, task_id, args, kwargs, einfo):
                _on_task_failure(self, exc, task_id, args, kwargs, einfo)

        cel.Task = _ContextTask

    return cel


def _on_task_failure(task, exc, task_id, args, kwargs, einfo) -> None:
    """Shared failure handler: log the error and optionally notify the client."""
    import logging
    logger = logging.getLogger('bpmtutor.celery')
    logger.error(
        '[Celery] Task %s (%s) failed after %d retries: %s',
        task.name, task_id, task.max_retries, exc,
        exc_info=einfo.exc_info if einfo else None,
    )

    # Attempt to emit an error to the originating SocketIO session so the UI
    # can display a meaningful message instead of hanging indefinitely.
    # Uses the same Redis message-queue emitter pattern as llm_tasks._emit().
    sid = kwargs.get('sid') or (args[0] if args else None)
    if not sid:
        return
    try:
        import os
        from flask_socketio import SocketIO
        redis_url = os.getenv('REDIS_URL', '')
        if not redis_url:
            return
        emitter = SocketIO(message_queue=redis_url)
        emitter.emit('error', {'message': str(exc)}, room=sid, namespace='/')
    except Exception as emit_exc:
        logger.debug('[Celery] Could not emit error to sid %s: %s', sid, emit_exc)


# Module-level instance (used by the Celery CLI worker process).
# The Flask app context is NOT attached here — tasks import it lazily.
celery = make_celery()
