"""Prompts package — runtime utilities only.

Prompt data (seed values, defaults) live in deploy/prompts/.
At runtime all prompts are read from the DB.
"""
from app.services.prompts._base import get_prompt_with_standards  # noqa: F401

