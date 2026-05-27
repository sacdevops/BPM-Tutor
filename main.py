"""BPM-Tutor — WSGI entry point.

Gunicorn targets this module as ``main:app``.
SocketIO is initialised here so the ``socketio`` object is available
for gunicorn's gevent worker and for the ``if __name__ == '__main__'``
dev server path.
"""
import logging
import os
import signal
import sys

import config
from flask_socketio import SocketIO

from app import create_app
from app.services.session_store import store
from app.services import task_tracker

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.DEBUG if config.FLASK_DEBUG else logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)
logger = logging.getLogger('bpmtutor')

# ── Application ───────────────────────────────────────────────────────────────
app = create_app()

# ── Flask-SocketIO ────────────────────────────────────────────────────────────
_redis_url = os.getenv('REDIS_URL', '')
_cors_origins_raw = os.getenv('CORS_ALLOWED_ORIGINS', '')
_cors_origins = [o.strip() for o in _cors_origins_raw.split(',') if o.strip()] or '*'

socketio = SocketIO(
    app,
    cors_allowed_origins=_cors_origins,
    ping_timeout=300,
    ping_interval=25,
    async_mode='gevent',
    message_queue=_redis_url if _redis_url else None,
)
if _redis_url:
    logger.info('[Backend] SocketIO using Redis message queue: %s', _redis_url.split('@')[-1])
else:
    logger.info('[Backend] REDIS_URL not set — SocketIO running in single-worker mode (no message queue)')

# ── WebSocket handlers ────────────────────────────────────────────────────────
from app.sockets import chat_handler  # noqa: E402
chat_handler.register_handlers(socketio)

# ── Session cleanup background task ──────────────────────────────────────────
SESSION_TIMEOUT_SECONDS = 30 * 60  # 30 minutes
CLEANUP_INTERVAL_SECONDS = 5 * 60  # check every 5 minutes


def _session_cleanup_loop():
    """Periodically remove stale sessions."""
    import gevent
    while True:
        gevent.sleep(CLEANUP_INTERVAL_SECONDS)
        try:
            stale = store.stale_sids(SESSION_TIMEOUT_SECONDS)
            for sid in stale:
                session = store.remove(sid)
                if session:
                    task_tracker.cleanup_task(sid)
                    logger.info('[Cleanup] Removed stale session %s (task %s)', sid, session['task_id'])
        except Exception as exc:
            logger.error('[Cleanup] Error during session cleanup: %s', exc)


socketio.start_background_task(_session_cleanup_loop)

# ── Graceful shutdown ─────────────────────────────────────────────────────────

def _graceful_shutdown(signum, frame):
    logger.info('[Backend] Received signal %s, shutting down...', signum)
    sys.exit(0)


signal.signal(signal.SIGINT, _graceful_shutdown)
signal.signal(signal.SIGTERM, _graceful_shutdown)

if __name__ == '__main__':
    socketio.run(app, debug=config.FLASK_DEBUG, host='127.0.0.1', port=8080)