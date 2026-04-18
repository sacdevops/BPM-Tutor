"""Re-exports from central prompts module (app-only)."""

import sys
import os

_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from prompts import (
    GENERAL_RULES,
    GENERAL_RULES_DE,
    BPMN_STANDARDS,
    get_prompt_with_standards,
    MENTOR_PROMPT_GREETING_FINAL,
    MENTOR_PROMPT_ANALYSIS_FINAL,
    MENTOR_PROMPT_REACTION_FINAL,
    MENTOR_PROMPT_GREETING_FINAL_DE,
    MENTOR_PROMPT_ANALYSIS_FINAL_DE,
    MENTOR_PROMPT_REACTION_FINAL_DE,
)

__all__ = [
    'GENERAL_RULES',
    'GENERAL_RULES_DE',
    'BPMN_STANDARDS',
    'get_prompt_with_standards',
    'MENTOR_PROMPT_GREETING_FINAL',
    'MENTOR_PROMPT_ANALYSIS_FINAL',
    'MENTOR_PROMPT_REACTION_FINAL',
    'MENTOR_PROMPT_GREETING_FINAL_DE',
    'MENTOR_PROMPT_ANALYSIS_FINAL_DE',
    'MENTOR_PROMPT_REACTION_FINAL_DE',
]
