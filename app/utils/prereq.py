"""Task prerequisites — evaluation logic.

Prerequisite JSON format stored in Task.prerequisites:

    {
      "connector": "AND",    // "AND" or "OR" (default AND)
      "rules": [
        {"field": "task_completed",  "operator": "eq",  "value": "task_01"},
        {"field": "task_submitted",  "operator": "eq",  "value": "task_02"},
        {"field": "cohort_member",   "operator": "eq",  "value": "3"},
        {"field": "role",            "operator": "neq", "value": "admin"}
      ]
    }

Supported fields:
  task_completed  – user has a completed TaskSubmission for given task_id
  task_submitted  – user has *any* TaskSubmission for given task_id
  cohort_member   – user is a member of cohort with given id
  role            – user has the given role

Supported operators:
  eq          – equals / is true for boolean checks
  neq         – not equals
"""
from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.task import Task


def check_prerequisites(task: 'Task', user: 'User | None') -> tuple[bool, str]:
    """Return ``(passed, reason_if_failed)``.

    If ``user`` is None the function returns ``(False, 'not_logged_in')``.
    """
    raw = task.prerequisites
    if not raw:
        return True, ''

    try:
        prereq_data = json.loads(raw)
    except (ValueError, TypeError):
        return True, ''   # invalid JSON — ignore

    if not prereq_data:
        return True, ''

    if user is None:
        return False, 'not_logged_in'

    # Normalise legacy list format (plain list of rules without connector)
    if isinstance(prereq_data, list):
        prereq_data = {'connector': 'AND', 'rules': prereq_data}

    rules = prereq_data.get('rules', [])
    connector = prereq_data.get('connector', 'AND').upper()

    if not rules:
        return True, ''

    results = [_evaluate_rule(rule, user) for rule in rules]

    if connector == 'OR':
        passed = any(r[0] for r in results)
    else:
        passed = all(r[0] for r in results)

    if passed:
        return True, ''

    failed_msgs = [r[1] for r in results if not r[0]]
    return False, '; '.join(failed_msgs)


def _evaluate_rule(rule: dict, user: 'User') -> tuple[bool, str]:
    field = rule.get('field', '')
    operator = rule.get('operator', 'eq')
    value = str(rule.get('value', ''))

    if field == 'task_completed':
        return _check_task_completed(operator, value, user)
    if field == 'task_submitted':
        return _check_task_submitted(operator, value, user)
    if field == 'cohort_member':
        return _check_cohort_member(operator, value, user)
    if field == 'role':
        return _check_role(operator, value, user)

    # Unknown field — silently pass
    return True, ''


def _check_task_completed(operator: str, task_id: str, user: 'User') -> tuple[bool, str]:
    from app.models.task import TaskSubmission
    completed = TaskSubmission.query.filter_by(
        user_id=user.id, task_id=task_id
    ).filter(TaskSubmission.completed_at.isnot(None)).first()
    is_completed = completed is not None
    if operator == 'eq':
        ok = is_completed
        msg = f'Aufgabe {task_id!r} muss abgeschlossen sein'
    else:  # neq
        ok = not is_completed
        msg = f'Aufgabe {task_id!r} darf nicht abgeschlossen sein'
    return ok, '' if ok else msg


def _check_task_submitted(operator: str, task_id: str, user: 'User') -> tuple[bool, str]:
    from app.models.task import TaskSubmission
    submitted = TaskSubmission.query.filter_by(
        user_id=user.id, task_id=task_id
    ).first()
    is_submitted = submitted is not None
    if operator == 'eq':
        ok = is_submitted
        msg = f'Aufgabe {task_id!r} muss eingereicht sein'
    else:
        ok = not is_submitted
        msg = f'Aufgabe {task_id!r} darf nicht eingereicht sein'
    return ok, '' if ok else msg


def _check_cohort_member(operator: str, cohort_id_str: str, user: 'User') -> tuple[bool, str]:
    try:
        cohort_id = int(cohort_id_str)
    except ValueError:
        return True, ''
    from app.models.cohort import CohortMembership
    is_member = CohortMembership.query.filter_by(
        user_id=user.id, cohort_id=cohort_id
    ).first() is not None
    if operator == 'eq':
        ok = is_member
        msg = f'Muss Mitglied von Kohorte {cohort_id} sein'
    else:
        ok = not is_member
        msg = f'Darf nicht Mitglied von Kohorte {cohort_id} sein'
    return ok, '' if ok else msg


def _check_role(operator: str, role: str, user: 'User') -> tuple[bool, str]:
    user_role = user.role
    if operator == 'eq':
        ok = user_role == role
        msg = f'Rolle muss "{role}" sein'
    else:
        ok = user_role != role
        msg = f'Rolle darf nicht "{role}" sein'
    return ok, '' if ok else msg
