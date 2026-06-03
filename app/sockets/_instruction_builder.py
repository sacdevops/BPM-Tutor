"""Build the AI instruction string for a given agent session.

The instruction is read from the agent's DB configuration, making it
fully configurable from the admin panel without code changes.
"""
from __future__ import annotations

import logging

logger = logging.getLogger('bpmtutor.instruction')


def build_instruction(
    agent_id: str,
    is_completion_review: bool,
    lang: str,
) -> str:
    """Return the per-request instruction string passed to AIService.get_mentor_response().

    Reads 'instruction_completion' or 'instruction' from the agent's DB record.
    Falls back to an empty string if the agent or prompt is not found.

    Args:
        agent_id: The UUID of the AIAgent for this session.
        is_completion_review: True when the student submits a completion request.
        lang: 'de' or 'en'.
    """
    try:
        from app.extensions import db
        from app.models.agent import AIAgent
        agent = db.session.get(AIAgent, agent_id) if agent_id else None
        if agent:
            key = 'instruction_completion' if is_completion_review else 'instruction'
            prompt = agent.get_prompt(key, lang)
            if prompt:
                return prompt
    except Exception as exc:
        logger.warning('build_instruction error for agent_id=%s: %s', agent_id, exc)
    return ''
