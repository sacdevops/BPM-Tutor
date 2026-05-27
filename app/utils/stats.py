"""Statistics helpers — aggregate task submission data."""
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import func, and_

from app.extensions import db
from app.models.task import TaskSubmission
from app.models.user import User


def _date_filter(since: Optional[datetime]):
    if since is None:
        return True
    return TaskSubmission.started_at >= since


def since_from_period(period: str) -> Optional[datetime]:
    """Map a period string to a datetime cutoff."""
    now = datetime.now(timezone.utc)
    mapping = {
        '24h': now - timedelta(hours=24),
        '7d': now - timedelta(days=7),
        '30d': now - timedelta(days=30),
        '90d': now - timedelta(days=90),
        '1y': now - timedelta(days=365),
        'all': None,
    }
    return mapping.get(period, None)


def user_stats(user_id: int, since: Optional[datetime] = None) -> dict:
    """Aggregate stats for a single user."""
    q = TaskSubmission.query.filter(TaskSubmission.user_id == user_id)
    if since:
        q = q.filter(TaskSubmission.started_at >= since)

    submissions = q.all()
    completed = [s for s in submissions if s.completed_at is not None]
    graded = [s for s in submissions if s.grade_value is not None or s.grade_passed is not None]

    total_tokens = sum(s.tokens_in + s.tokens_out for s in submissions)
    total_interactions = sum(s.interactions for s in submissions)
    avg_duration = (
        sum(s.duration_seconds for s in completed) / len(completed)
        if completed else 0
    )

    task_ids_completed = list({s.task_id for s in completed})

    return {
        'total_submissions': len(submissions),
        'completed': len(completed),
        'graded': len(graded),
        'total_tokens': total_tokens,
        'total_interactions': total_interactions,
        'avg_duration_seconds': avg_duration,
        'tasks_attempted': len({s.task_id for s in submissions}),
        'tasks_completed': len(task_ids_completed),
        'submissions': [_submission_summary(s) for s in submissions],
    }


def global_stats(since: Optional[datetime] = None) -> dict:
    """Platform-wide stats for the admin dashboard."""
    q = TaskSubmission.query
    if since:
        q = q.filter(TaskSubmission.started_at >= since)

    submissions = q.all()
    completed = [s for s in submissions if s.completed_at]

    active_users = db.session.query(func.count(func.distinct(TaskSubmission.user_id))).scalar() or 0
    total_users = User.query.count()
    verified_users = User.query.filter_by(is_verified=True).count()

    total_tokens = sum(s.tokens_in + s.tokens_out for s in submissions)

    # Submissions per task
    per_task: dict = {}
    for s in submissions:
        per_task.setdefault(s.task_id, 0)
        per_task[s.task_id] += 1

    avg_interactions = (
        sum(s.interactions for s in submissions) / len(submissions)
        if submissions else 0
    )
    return {
        'total_users': total_users,
        'verified_users': verified_users,
        'active_users': active_users,
        'total_submissions': len(submissions),
        'completed': len(completed),
        'completed_submissions': len(completed),
        'avg_interactions': avg_interactions,
        'total_tokens': total_tokens,
        'submissions_per_task': per_task,
    }


def _submission_summary(s: TaskSubmission) -> dict:
    return {
        'id': s.id,
        'task_id': s.task_id,
        'started_at': s.started_at.strftime('%d.%m.%Y %H:%M') if s.started_at else None,
        'completed_at': s.completed_at.strftime('%d.%m.%Y %H:%M') if s.completed_at else None,
        'interactions': s.interactions,
        'tokens': s.tokens_in + s.tokens_out,
        'duration_seconds': s.duration_seconds,
        'grade_value': s.grade_value,
        'grade_passed': s.grade_passed,
        'grade_comment': s.grade_comment,
    }


def chart_data_timeline(user_id: Optional[int], since: Optional[datetime], period: str) -> dict:
    """Return daily submission counts for a timeline chart."""
    q = TaskSubmission.query
    if user_id:
        q = q.filter(TaskSubmission.user_id == user_id)
    if since:
        q = q.filter(TaskSubmission.started_at >= since)

    submissions = q.order_by(TaskSubmission.started_at).all()

    # Group by date
    by_date: dict = {}
    for s in submissions:
        day = s.started_at.strftime('%Y-%m-%d')
        by_date.setdefault(day, 0)
        by_date[day] += 1

    return {
        'labels': list(by_date.keys()),
        'data': list(by_date.values()),
    }


# ── Extended analytics ───────────────────────────────────────────────────────

def bpmn_error_frequency(since: Optional[datetime] = None) -> list[dict]:
    """Return top BPMN validation error types across all submissions."""
    import json as _json
    q = TaskSubmission.query
    if since:
        q = q.filter(TaskSubmission.started_at >= since)

    error_counts: dict[str, int] = {}
    for sub in q.filter(TaskSubmission.validation_error_keys.isnot(None)).all():
        try:
            keys = _json.loads(sub.validation_error_keys)
            for k in keys:
                error_counts[k] = error_counts.get(k, 0) + 1
        except Exception:
            pass

    return sorted(
        [{'key': k, 'count': v} for k, v in error_counts.items()],
        key=lambda x: x['count'], reverse=True
    )[:20]


def phase_distribution(since: Optional[datetime] = None) -> dict[str, int]:
    """Return aggregate AI interaction phase counts across all submissions."""
    import json as _json
    q = TaskSubmission.query
    if since:
        q = q.filter(TaskSubmission.started_at >= since)

    totals: dict[str, int] = {}
    for sub in q.filter(TaskSubmission.phase_counts.isnot(None)).all():
        try:
            counts = _json.loads(sub.phase_counts)
            for phase, n in counts.items():
                totals[phase] = totals.get(phase, 0) + int(n)
        except Exception:
            pass
    return totals


def task_analytics(since: Optional[datetime] = None) -> list[dict]:
    """Per-task aggregated statistics."""
    from app.models.task import Task
    tasks = Task.query.order_by(Task.sort_order).all()
    result = []
    for task in tasks:
        q = TaskSubmission.query.filter_by(task_id=task.id)
        if since:
            q = q.filter(TaskSubmission.started_at >= since)
        subs = q.all()
        completed = [s for s in subs if s.completed_at]
        graded = [s for s in subs if s.grade_value is not None or s.grade_passed is not None]
        total_tokens = sum(s.tokens_in + s.tokens_out for s in subs)
        avg_dur = (sum(s.duration_seconds for s in completed) / len(completed)
                   if completed else 0)
        result.append({
            'task_id': task.id,
            'title': task.title,
            'submissions': len(subs),
            'completed': len(completed),
            'graded': len(graded),
            'total_tokens': total_tokens,
            'avg_duration_seconds': avg_dur,
        })
    return result


def cohort_analytics(since: Optional[datetime] = None) -> list[dict]:
    """Per-cohort aggregated statistics."""
    from app.models.cohort import Cohort, CohortMembership
    cohorts = Cohort.query.filter_by(is_active=True).all()
    result = []
    for cohort in cohorts:
        user_ids = [m.user_id for m in cohort.memberships.all()]
        if not user_ids:
            result.append({'cohort_id': cohort.id, 'name': cohort.name,
                           'members': 0, 'submissions': 0, 'completed': 0})
            continue
        q = TaskSubmission.query.filter(TaskSubmission.user_id.in_(user_ids))
        if since:
            q = q.filter(TaskSubmission.started_at >= since)
        subs = q.all()
        completed = [s for s in subs if s.completed_at]
        result.append({
            'cohort_id': cohort.id,
            'name': cohort.name,
            'members': len(user_ids),
            'submissions': len(subs),
            'completed': len(completed),
        })
    return result

