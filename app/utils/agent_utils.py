"""Shared agent-resolution logic used by chat_handler and study routes."""
from __future__ import annotations

import logging

logger = logging.getLogger('bpmtutor.agent')


def resolve_agent(agent_id: str, task_id: str) -> tuple[str, str, str, str, str]:
    """Return (agent_id, agent_name, modeling_mode, control_mode, agent_type) for a session.

    Resolution order:
      1. Explicit *agent_id* supplied by the caller (e.g. study condition override).
      2. Agent assigned to the task in the database.
      3. Platform-wide default agent.
      4. Hard-coded fallback ('', 'Mentor', 'none', 'human', 'mentor').
    """
    try:
        from app.extensions import db
        from app.models.agent import AIAgent

        if agent_id:
            a = db.session.get(AIAgent, agent_id)
            if a:
                return a.id, a.name, a.modeling_mode, a.control_mode, a.agent_type

        if task_id and task_id != 'custom':
            from app.models.task import Task
            t = db.session.get(Task, task_id)
            if t and t.agent_id:
                a = db.session.get(AIAgent, t.agent_id)
                if a:
                    return a.id, a.name, a.modeling_mode, a.control_mode, a.agent_type

        a = AIAgent.get_default()
        if a:
            return a.id, a.name, a.modeling_mode, a.control_mode, a.agent_type

    except Exception as exc:
        logger.warning('[agent_utils] resolve_agent error: %s', exc)

    return '', 'Mentor', 'none', 'human', 'mentor'
