"""Deployment prompt data — used only for initial seeding and admin prompt resets.

NOT imported at request time. All runtime prompts come from the DB.
"""
from __future__ import annotations

import deploy.prompts.mentor     as _mentor
import deploy.prompts.assistant  as _assistant
import deploy.prompts.colleague  as _colleague
import deploy.prompts.supervisor as _supervisor
import deploy.prompts.delegant   as _delegant

# Fully-resolved system prompts (greeting / analysis / reaction) per agent type
_SYSTEM_PROMPTS: dict = {
    'mentor': {
        'greeting': {'en': _mentor.MENTOR_PROMPT_GREETING_FINAL,       'de': _mentor.MENTOR_PROMPT_GREETING_FINAL_DE},
        'analysis': {'en': _mentor.MENTOR_PROMPT_ANALYSIS_FINAL,       'de': _mentor.MENTOR_PROMPT_ANALYSIS_FINAL_DE},
        'reaction': {'en': _mentor.MENTOR_PROMPT_REACTION_FINAL,       'de': _mentor.MENTOR_PROMPT_REACTION_FINAL_DE},
    },
    'assistant': {
        'greeting': {'en': _assistant.ASSISTANT_PROMPT_GREETING_FINAL, 'de': _assistant.ASSISTANT_PROMPT_GREETING_FINAL_DE},
        'analysis': {'en': _assistant.ASSISTANT_PROMPT_ANALYSIS_FINAL, 'de': _assistant.ASSISTANT_PROMPT_ANALYSIS_FINAL_DE},
        'reaction': {'en': _assistant.ASSISTANT_PROMPT_REACTION_FINAL, 'de': _assistant.ASSISTANT_PROMPT_REACTION_FINAL_DE},
    },
    'colleague': {
        'greeting': {'en': _colleague.COLLEAGUE_PROMPT_GREETING_FINAL, 'de': _colleague.COLLEAGUE_PROMPT_GREETING_FINAL_DE},
        'analysis': {'en': _colleague.COLLEAGUE_PROMPT_ANALYSIS_FINAL, 'de': _colleague.COLLEAGUE_PROMPT_ANALYSIS_FINAL_DE},
        'reaction': {'en': _colleague.COLLEAGUE_PROMPT_REACTION_FINAL, 'de': _colleague.COLLEAGUE_PROMPT_REACTION_FINAL_DE},
    },
    'supervisor': {
        'greeting': {'en': _supervisor.SUPERVISOR_PROMPT_GREETING_FINAL, 'de': _supervisor.SUPERVISOR_PROMPT_GREETING_FINAL_DE},
        'analysis': {'en': _supervisor.SUPERVISOR_PROMPT_ANALYSIS_FINAL, 'de': _supervisor.SUPERVISOR_PROMPT_ANALYSIS_FINAL_DE},
        'reaction': {'en': _supervisor.SUPERVISOR_PROMPT_REACTION_FINAL, 'de': _supervisor.SUPERVISOR_PROMPT_REACTION_FINAL_DE},
    },
    'delegant': {
        'greeting': {'en': _delegant.DELEGANT_PROMPT_GREETING_FINAL, 'de': _delegant.DELEGANT_PROMPT_GREETING_FINAL_DE},
        'analysis': {'en': _delegant.DELEGANT_PROMPT_ANALYSIS_FINAL, 'de': _delegant.DELEGANT_PROMPT_ANALYSIS_FINAL_DE},
        'reaction': {'en': _delegant.DELEGANT_PROMPT_REACTION_FINAL, 'de': _delegant.DELEGANT_PROMPT_REACTION_FINAL_DE},
    },
}


def get_system_prompt(agent_type: str, prompt_type: str, lang: str = 'en') -> str | None:
    """Return the built-in resolved prompt for a system agent type."""
    type_map = _SYSTEM_PROMPTS.get(agent_type, {})
    lang_map = type_map.get(prompt_type, {})
    return lang_map.get(lang) or lang_map.get('en')


def get_all_defaults(agent_type: str) -> dict[tuple[str, str], str]:
    """Return all interaction prompt defaults for agent_type as {(prompt_type, lang): content}."""
    from deploy.prompts.defaults import get_all_defaults as _get
    return _get(agent_type)
