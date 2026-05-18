"""Backward-compatibility shim — canonical code is now in lib/bpmn/validator.py."""
from lib.bpmn.validator import *  # noqa: F401, F403
from lib.bpmn.validator import BPMNValidator, ValidationIssue, Severity  # explicit re-export