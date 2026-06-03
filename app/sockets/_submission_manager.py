"""Persist chat and mentor-state data to the TaskSubmission row.

Extracted from chat_handler.py to reduce DB-write boilerplate in the
SocketIO handlers.
"""
from __future__ import annotations

import json
import logging

logger = logging.getLogger('bpmtutor.chat')


def persist_chat_log(sub_id: int | str | None, chat_history: list) -> None:
    """Write the current chat history to ``TaskSubmission.chat_log``."""
    if not sub_id:
        return
    try:
        from app.extensions import db
        from app.models.task import TaskSubmission
        sub = db.session.get(TaskSubmission, sub_id)
        if sub:
            sub.chat_log = json.dumps(chat_history, ensure_ascii=False)
            db.session.commit()
    except Exception as exc:
        logger.warning('[chat_handler] chat_log persist error: %s', exc)


def persist_mentor_state(sub_id: int | str | None, state: dict, chat_history: list) -> None:
    """Write mentor memory, phase counts, and chat log to the DB row."""
    if not sub_id:
        return
    try:
        from app.extensions import db
        from app.models.task import TaskSubmission
        sub = db.session.get(TaskSubmission, sub_id)
        if sub:
            sub.mentor_memory = json.dumps(state['memory'])
            sub.phase_counts = json.dumps(state.get('phase_counts', {}))
            sub.chat_log = json.dumps(chat_history, ensure_ascii=False)
            db.session.commit()
    except Exception as exc:
        logger.warning('[chat_handler] memory persist error: %s', exc)
