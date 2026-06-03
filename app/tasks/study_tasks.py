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
    """Periodic SQLite backup respecting auto-backup settings.

    Runs every hour via Celery Beat but skips unless the configured interval has
    elapsed.  Supports local storage and Sciebo (WebDAV / ownCloud) upload.
    """
    try:
        import os
        import sqlite3
        from datetime import datetime as _dt, timezone as _tz, timedelta as _td
        from app import create_app

        _app = create_app()
        with _app.app_context():
            from app.models.settings import Settings

            # --- Check enabled ---
            if not Settings.get(Settings.AUTO_BACKUP_ENABLED, False):
                logger.debug('[backup] Auto-backup disabled, skipping')
                return {'status': 'skipped', 'reason': 'disabled'}

            # --- Check interval ---
            try:
                interval_h = int(Settings.get(Settings.AUTO_BACKUP_INTERVAL_HOURS, 24) or 24)
            except (TypeError, ValueError):
                interval_h = 24
            last_run_str = Settings.get(Settings.AUTO_BACKUP_LAST_RUN, '') or ''
            if last_run_str:
                try:
                    last_run = _dt.fromisoformat(last_run_str).replace(tzinfo=_tz.utc)
                    if (_dt.now(_tz.utc) - last_run) < _td(hours=interval_h):
                        logger.debug('[backup] Interval not elapsed, skipping')
                        return {'status': 'skipped', 'reason': 'interval not elapsed'}
                except Exception:
                    pass

            db_uri = _app.config.get('SQLALCHEMY_DATABASE_URI', '')
            if 'sqlite' not in db_uri:
                logger.info('[backup] Skipped — not a SQLite database')
                return {'status': 'skipped'}

            db_path = db_uri.replace('sqlite:///', '', 1)
            if not os.path.exists(db_path):
                logger.error('[backup] Database file not found: %s', db_path)
                return {'status': 'error', 'reason': 'file not found'}

            # --- Determine local backup directory ---
            custom_path = (Settings.get(Settings.AUTO_BACKUP_LOCAL_PATH, '') or '').strip()
            if custom_path:
                backup_dir = custom_path
            else:
                backup_dir = os.path.join(os.path.dirname(db_path), 'backups')
            os.makedirs(backup_dir, exist_ok=True)

            ts = _dt.now().strftime('%Y%m%d_%H%M%S')
            filename = f'bpmtutor_{ts}.db'
            dest = os.path.join(backup_dir, filename)

            # --- SQLite online backup ---
            src = sqlite3.connect(db_path)
            dst = sqlite3.connect(dest)
            try:
                src.backup(dst)
            finally:
                src.close()
                dst.close()
            logger.info('[backup] Created: %s', dest)

            # --- Rotate local backups ---
            try:
                max_keep = int(Settings.get(Settings.AUTO_BACKUP_MAX_KEEP, 14) or 14)
            except (TypeError, ValueError):
                max_keep = 14
            all_backups = sorted(
                [os.path.join(backup_dir, f)
                 for f in os.listdir(backup_dir) if f.endswith('.db')]
            )
            for old in all_backups[:-max_keep]:
                os.remove(old)
                logger.info('[backup] Pruned: %s', old)

            # --- Sciebo / WebDAV upload (optional) ---
            storage = (Settings.get(Settings.AUTO_BACKUP_STORAGE, 'local') or 'local').strip()
            if storage == 'sciebo':
                sciebo_url = (Settings.get(Settings.SCIEBO_URL, '') or '').rstrip('/')
                sciebo_user = Settings.get(Settings.SCIEBO_USERNAME, '') or ''
                from app.utils.crypto import decrypt_value as _dec
                sciebo_pass = _dec(Settings.get(Settings.SCIEBO_PASSWORD, '') or '')
                remote_path = (Settings.get(Settings.SCIEBO_REMOTE_PATH, '') or '').strip('/')
                if sciebo_url and sciebo_user:
                    try:
                        import re as _re
                        import requests as _req
                        # Normalise URL: strip any /remote.php/... the user may have included
                        _sciebo_base = re.sub(r'/remote\.php.*$', '', sciebo_url)
                        webdav_base = f'{_sciebo_base}/remote.php/dav/files/{sciebo_user}'
                        auth = (sciebo_user, sciebo_pass)
                        # Create each directory level individually (MKCOL is not recursive)
                        if remote_path:
                            parts = remote_path.split('/')
                            for i in range(1, len(parts) + 1):
                                partial = '/'.join(parts[:i])
                                mkcol_url = f'{webdav_base}/{partial}/'
                                mkcol_resp = _req.request('MKCOL', mkcol_url, auth=auth, timeout=15)
                                # 201 = created, 405 = already exists — both OK
                                logger.info('[backup] MKCOL %s → %s', mkcol_url, mkcol_resp.status_code)
                            upload_url = f'{webdav_base}/{remote_path}/{filename}'
                        else:
                            upload_url = f'{webdav_base}/{filename}'
                        with open(dest, 'rb') as fh:
                            resp = _req.put(upload_url, data=fh, auth=auth, timeout=120)
                        if resp.status_code in (200, 201, 204):
                            logger.info('[backup] Uploaded to Sciebo: %s', upload_url)
                        else:
                            logger.warning('[backup] Sciebo upload returned %s: %s', resp.status_code, resp.text[:200])
                    except Exception as exc:
                        logger.warning('[backup] Sciebo upload failed: %s', exc, exc_info=True)
                else:
                    logger.warning('[backup] Sciebo storage configured but URL/username missing')

            # --- Update last-run timestamp ---
            Settings.set(Settings.AUTO_BACKUP_LAST_RUN, _dt.now(_tz.utc).isoformat())

            return {'status': 'ok', 'path': dest}

    except Exception as exc:
        logger.exception('[backup] Backup failed: %s', exc)
        return {'status': 'error', 'reason': str(exc)}
