"""Celery tasks for asynchronous LLM processing.

These tasks run in a separate Celery worker process so that long-running
LLM calls (up to 5 minutes) never block the Gunicorn/gevent web workers.

After the LLM call completes the task emits the result back to the
browser via Flask-SocketIO's Redis message queue, which means the web
worker is completely free during the entire LLM round-trip.
"""
from __future__ import annotations

import logging
import os
from typing import Any

from app.celery_app import celery

logger = logging.getLogger('bpmtutor.tasks')

# SocketIO emitter used by the Celery worker to push events to clients.
# Lazily initialised so that the module can be imported without Redis.
_socketio_emitter = None


def _get_emitter():
    """Return a Flask-SocketIO server instance connected to the Redis queue."""
    global _socketio_emitter
    if _socketio_emitter is not None:
        return _socketio_emitter

    redis_url = os.getenv('REDIS_URL', '')
    if not redis_url:
        return None

    try:
        from flask_socketio import SocketIO
        _socketio_emitter = SocketIO(message_queue=redis_url)
    except Exception as exc:
        logger.warning('[tasks] Could not create SocketIO emitter: %s', exc)
        _socketio_emitter = None

    return _socketio_emitter


def _emit(event: str, data: dict, room: str) -> None:
    """Emit a SocketIO event to a specific client room (sid)."""
    emitter = _get_emitter()
    if emitter is None:
        logger.warning('[tasks] SocketIO emitter not available, cannot emit %s', event)
        return
    try:
        emitter.emit(event, data, room=room, namespace='/')
    except Exception as exc:
        logger.warning('[tasks] emit %s failed: %s', event, exc)


@celery.task(
    name='app.tasks.llm_tasks.process_mentor_message',
    bind=True,
    max_retries=2,
    default_retry_delay=5,
    queue='llm',
)
def process_mentor_message(
    self,
    *,
    sid: str,
    task_id: str,
    session_uuid: str,
    task_description: str,
    memory: list[dict],
    current_bpmn: str,
    user_message: str,
    previous_issues: list[dict],
    api_key: str,
    model: str,
    lang: str,
    tracker_key: str,
    submission_id: int | None,
) -> dict[str, Any]:
    """Process a user message through the LLM and emit the response via SocketIO.

    Returns the full response dict so that the caller can also use
    `AsyncResult.get()` if running in synchronous (non-Redis) mode.
    """
    try:
        from app import create_app
        app = create_app()

        with app.app_context():
            from app.services.ai_service import AIService, AIServiceError

            mentor = AIService(
                task_id,
                session_id=session_uuid,
                api_key=api_key,
                model=model,
                lang=lang,
                tracker_key=tracker_key,
            )

            response = mentor.get_mentor_response(
                task_description,
                memory,
                current_bpmn,
                user_message=user_message,
                previous_issues=previous_issues,
            )

            # Persist mentor memory to DB
            if submission_id is not None:
                try:
                    import json as _j
                    from app.extensions import db as _db
                    from app.models.task import TaskSubmission as _Sub

                    resp_message = response.get('message', '')
                    updated_memory = memory + (
                        [{'role': 'assistant', 'content': resp_message}]
                        if resp_message else []
                    )
                    sub = _db.session.get(_Sub, submission_id)
                    if sub:
                        sub.mentor_memory = _j.dumps(updated_memory)
                        _db.session.commit()
                except Exception as _pe:
                    logger.warning('[tasks] memory persist error: %s', _pe)

            # Emit result to the client
            _emit('ai_response', {
                'sender': 'ai',
                'message': response.get('message', ''),
                'complete': response.get('complete', False),
                'phase': response.get('phase', 'FEEDBACK'),
                'issues': response.get('issues', []),
            }, room=sid)
            _emit('ai_typing', {'typing': False}, room=sid)

            return response

    except Exception as exc:
        logger.exception('[tasks] process_mentor_message failed for sid=%s', sid)

        # Retry transient errors (e.g. network timeouts)
        try:
            raise self.retry(exc=exc)
        except self.MaxRetriesExceededError:
            _emit('ai_typing', {'typing': False}, room=sid)
            _emit('error', {
                'message': str(exc),
                'error_type': 'api_error',
            }, room=sid)
            raise


@celery.task(
    name='app.tasks.llm_tasks.process_mentor_greeting',
    bind=True,
    max_retries=1,
    queue='llm',
)
def process_mentor_greeting(
    self,
    *,
    sid: str,
    task_id: str,
    session_uuid: str,
    task_description: str,
    api_key: str,
    model: str,
    lang: str,
    tracker_key: str,
    fallback_greeting: str,
    agent_id: str = '',
) -> str:
    """Generate the initial mentor greeting asynchronously."""
    try:
        from app import create_app
        app = create_app()

        with app.app_context():
            from app.services.ai_service import AIService

            mentor = AIService(
                task_id,
                session_id=session_uuid,
                api_key=api_key,
                model=model,
                lang=lang,
                tracker_key=tracker_key,
                agent_id=agent_id,
            )
            result = mentor.generate_greeting(task_description)
            greeting = result.get('message', fallback_greeting)

    except Exception as exc:
        logger.warning('[tasks] greeting generation failed: %s', exc)
        greeting = fallback_greeting

    _emit('ai_response', {
        'sender': 'ai',
        'message': greeting,
        'complete': False,
        'phase': 'GREETING',
        'issues': [],
    }, room=sid)
    _emit('ai_typing', {'typing': False}, room=sid)

    return greeting
