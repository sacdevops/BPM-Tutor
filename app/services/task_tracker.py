"""Task-level statistics tracker.

One tracker entry is created per session (keyed by socket sid).
Records: wall-clock duration, LLM interaction counts, token usage.
Stats are persisted to the database via chat_handler on task completion.

Memory-leak prevention
----------------------
Entries are removed by ``cleanup_task()`` or ``save_task_report()`` when the
session ends normally.  For abnormal disconnects (browser crash, network drop),
``evict_stale()`` sweeps entries older than *max_age_seconds* (default 4 h) and
should be called from a periodic Celery Beat task.
"""

import logging
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List

logger = logging.getLogger('bpmtutor.tracker')

_lock = threading.Lock()
_state: Dict[str, Dict[str, Any]] = {}

_DEFAULT_MAX_AGE_SECONDS = 4 * 3600


def start_task(key: str, task_id: str, session_id: str) -> None:
    with _lock:
        if key in _state:
            return
        _state[key] = {
            'task_id': task_id,
            'session_id': session_id,
            'started_at': datetime.now(timezone.utc),
            'finished_at': None,
            'interactions': 0,
            'tokens_in': 0,
            'tokens_out': 0,
        }
    logger.info('[TaskTracker] Started tracking task %s (session %s)', task_id, session_id)


def record_llm_call(
    key: str,
    prompt_tokens: int,
    completion_tokens: int,
) -> None:
    with _lock:
        if key not in _state:
            return
        s = _state[key]
        s['interactions'] += 1
        s['tokens_in'] += prompt_tokens
        s['tokens_out'] += completion_tokens


def snapshot_task(key: str, bpmn_xml: str = '') -> None:
    with _lock:
        if key not in _state:
            return
        _state[key]['finished_at'] = datetime.now(timezone.utc)
    logger.debug('[TaskTracker] Snapshot for key %s', key)


def save_task_report(key: str, bpmn_xml: str = '') -> None:
    with _lock:
        if key not in _state:
            return
        _state[key]['finished_at'] = datetime.now(timezone.utc)
        _state.pop(key)
    logger.info('[TaskTracker] Report finalised for key %s', key)


def cleanup_task(key: str) -> None:
    with _lock:
        _state.pop(key, None)


def get_task_stats(key: str) -> Dict[str, Any]:
    """Return current token/interaction stats for the given session key."""
    with _lock:
        s = _state.get(key)
        if s is None:
            return {}
        return {
            'tokens_in': s['tokens_in'],
            'tokens_out': s['tokens_out'],
            'interactions': s['interactions'],
        }


def stale_keys(max_age_seconds: int = _DEFAULT_MAX_AGE_SECONDS) -> List[str]:
    """Return tracker keys whose ``started_at`` is older than *max_age_seconds*."""
    now = datetime.now(timezone.utc)
    with _lock:
        return [
            key for key, s in _state.items()
            if (now - s['started_at']).total_seconds() > max_age_seconds
        ]


def evict_stale(max_age_seconds: int = _DEFAULT_MAX_AGE_SECONDS) -> int:
    """Remove tracker entries that have been running longer than *max_age_seconds*.

    Returns the number of evicted entries.  Safe to call from a Celery Beat
    periodic task to prevent unbounded growth of ``_state`` when disconnect
    handlers are skipped due to worker crashes or abrupt client drops.
    """
    keys = stale_keys(max_age_seconds)
    with _lock:
        for key in keys:
            _state.pop(key, None)
    if keys:
        logger.warning(
            '[TaskTracker] Evicted %d stale entries (age > %ds): %s',
            len(keys), max_age_seconds, keys,
        )
    return len(keys)

