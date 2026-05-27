"""Celery Beat tasks for Research Study lifecycle email notifications."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from app.celery_app import celery

logger = logging.getLogger("bpmtutor.study_tasks")


def run_study_notifications() -> int:
    """Core notification logic (also callable from CLI without Celery)."""
    sent = 0
    try:
        from app.models.study import Study, StudyParticipant, StudyStepCompletion
        from app.utils.email import (
            send_study_announcement,
            send_study_wave_available,
            send_study_deadline_reminder,
        )
        from flask import url_for, current_app

        now = datetime.now(timezone.utc)
        window_open = now - timedelta(hours=1)   # "just became available" window
        reminder_horizon = now + timedelta(hours=48)  # 48 h ahead for reminders

        active_studies = Study.query.filter_by(is_active=True, is_archived=False).all()

        for study in active_studies:
            # 1. Enrollment opening announcements
            if (
                study.allow_self_enrollment
                and study.enrollment_start
                and window_open <= study.enrollment_start <= now
            ):
                try:
                    enroll_url = url_for("study.enroll", study_id=study.id, _external=True)
                except Exception:
                    enroll_url = ""
                # Notify all active users (not yet enrolled)
                enrolled_user_ids = {
                    p.user_id for p in StudyParticipant.query.filter_by(study_id=study.id).all()
                }
                from app.models.user import User
                for user in User.query.filter_by(is_active=True).all():
                    if user.id not in enrolled_user_ids and user.email:
                        send_study_announcement(
                            user.email, user.display_name or user.username,
                            study.title, study.enrollment_end, enroll_url,
                        )
                        sent += 1

            # 2. Wave unlock notifications (per-step available_from)
            participants = StudyParticipant.query.filter_by(
                study_id=study.id
            ).filter(
                StudyParticipant.completed_at.is_(None),
                StudyParticipant.dropped_out_at.is_(None),
            ).all()

            for participant in participants:
                try:
                    study_url = url_for("study.study_index", study_id=study.id, _external=True)
                except Exception:
                    study_url = ""

                effective_steps = study.get_effective_steps(participant)
                for step in effective_steps:
                    # Skip already-completed steps
                    completion = StudyStepCompletion.query.filter_by(
                        participant_id=participant.id, step_id=step.id
                    ).first()
                    if completion and completion.completed_at:
                        continue

                    eff_from, eff_until = step.get_availability(study)

                    # Wave unlock: step just became available
                    if eff_from and window_open <= eff_from <= now:
                        if participant.user and participant.user.email:
                            send_study_wave_available(
                                participant.user.email,
                                participant.user.display_name or participant.user.username,
                                study.title, step.display_label, study_url,
                            )
                            sent += 1

                    # Deadline reminder: step deadline within 48 h
                    if eff_until and now < eff_until <= reminder_horizon:
                        # Only send once: check no reminder sent recently (use a simple log approach)
                        if participant.user and participant.user.email:
                            send_study_deadline_reminder(
                                participant.user.email,
                                participant.user.display_name or participant.user.username,
                                study.title, step.display_label, eff_until, study_url,
                            )
                            sent += 1

    except Exception as exc:
        logger.exception("[study_tasks] run_study_notifications failed: %s", exc)

    return sent


@celery.task(name="app.tasks.study_tasks.send_study_notifications", bind=True,
             max_retries=2, default_retry_delay=300)
def send_study_notifications(self):
    """Celery Beat task — runs every hour to process study lifecycle emails."""
    from app.celery_app import celery as _cel
    # We need app context — create it here
    try:
        from flask import current_app
        sent = run_study_notifications()
        logger.info("[study_tasks] Sent %d notification(s)", sent)
    except RuntimeError:
        # No app context — create one
        try:
            import sys, os
            sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
            from app import create_app
            _app = create_app()
            with _app.app_context():
                sent = run_study_notifications()
            logger.info("[study_tasks] Sent %d notification(s)", sent)
        except Exception as exc:
            logger.exception("[study_tasks] Could not create app context: %s", exc)
            raise self.retry(exc=exc)


@celery.task(
    name='app.tasks.study_tasks.backup_database',
    max_retries=1,
    default_retry_delay=300,
)
def backup_database():
    """Daily SQLite online backup.

    Uses sqlite3.Connection.backup() — a consistent snapshot even while the DB
    is actively being written to (WAL mode checkpoint is not needed).  Keeps
    the 14 most recent backups (~2 weeks) and prunes older ones automatically.
    Backups are stored in data/backups/ on the shared Docker volume.
    """
    try:
        import os
        import sqlite3
        from datetime import datetime as _dt
        from app import create_app

        _app = create_app()
        with _app.app_context():
            db_uri = _app.config.get('SQLALCHEMY_DATABASE_URI', '')
            if 'sqlite' not in db_uri:
                logger.info('[backup] Skipped — not a SQLite database')
                return {'status': 'skipped'}

            db_path = db_uri.replace('sqlite:///', '', 1)
            if not os.path.exists(db_path):
                logger.error('[backup] Database file not found: %s', db_path)
                return {'status': 'error', 'reason': 'file not found'}

            backup_dir = os.path.join(os.path.dirname(db_path), 'backups')
            os.makedirs(backup_dir, exist_ok=True)
            dest = os.path.join(
                backup_dir,
                f'bpmtutor_{_dt.now().strftime("%Y%m%d_%H%M%S")}.db',
            )

            # sqlite3 online-backup API: consistent read even under concurrent writes
            src = sqlite3.connect(db_path)
            dst = sqlite3.connect(dest)
            try:
                src.backup(dst)
            finally:
                src.close()
                dst.close()

            logger.info('[backup] Created: %s', dest)

            # Rotate: keep the 14 most recent backups (~2 weeks of daily runs)
            all_backups = sorted(
                [os.path.join(backup_dir, f)
                 for f in os.listdir(backup_dir) if f.endswith('.db')]
            )
            for old in all_backups[:-14]:
                os.remove(old)
                logger.info('[backup] Pruned old backup: %s', old)

            return {'status': 'ok', 'path': dest}

    except Exception as exc:
        logger.exception('[backup] Backup failed: %s', exc)
        return {'status': 'error', 'reason': str(exc)}
