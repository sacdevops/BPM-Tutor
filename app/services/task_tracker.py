"""Task-level statistics tracker.

One tracker entry is created per session (keyed by socket sid).
Records: wall-clock duration, LLM interaction counts, token usage.
Stats are persisted to the database via chat_handler on task completion.
"""

import logging
import threading
from datetime import datetime
from typing import Dict, Any

logger = logging.getLogger('bpmtutor.tracker')

_lock = threading.Lock()
_state: Dict[str, Dict[str, Any]] = {}


def start_task(key: str, task_id: str, session_id: str) -> None:
    with _lock:
        if key in _state:
            return
        _state[key] = {
            'task_id': task_id,
            'session_id': session_id,
            'started_at': datetime.now(),
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
        _state[key]['finished_at'] = datetime.now()
    logger.debug('[TaskTracker] Snapshot for key %s', key)


def save_task_report(key: str, bpmn_xml: str = '') -> None:
    with _lock:
        if key not in _state:
            return
        _state[key]['finished_at'] = datetime.now()
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
