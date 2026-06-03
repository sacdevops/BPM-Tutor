"""Domain enums — replaces magic strings throughout the codebase."""
from __future__ import annotations

from enum import Enum


class UserRole(str, Enum):
    ADMIN = 'admin'
    TUTOR = 'tutor'
    STUDENT = 'student'


class StudyDesign(str, Enum):
    WITHIN = 'within'
    BETWEEN = 'between'


class StepType(str, Enum):
    TASK = 'task'
    SURVEY = 'survey'


class GradingType(str, Enum):
    NONE = 'none'
    POINTS = 'points'
    PASS_FAIL = 'pass_fail'


class TaskMode(str, Enum):
    STANDARD = 'standard'
    LEVELING = 'leveling'
    RESEARCH = 'research'


class AgentType(str, Enum):
    MENTOR = 'mentor'
    ASSISTANT = 'assistant'
    COLLEAGUE = 'colleague'
    SUPERVISOR = 'supervisor'
    CUSTOM = 'custom'


class ModelingMode(str, Enum):
    NONE = 'none'
    COLLABORATIVE = 'collaborative'
    AI_THEN_HUMAN = 'ai_then_human'
    AI_ONLY = 'ai_only'


class ControlMode(str, Enum):
    HUMAN = 'human'
    SHARED = 'shared'
    AGENT = 'agent'


class ApiKeyMode(str, Enum):
    GLOBAL = 'global'
    PER_USER = 'per_user'
