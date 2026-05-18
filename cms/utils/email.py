"""Email sending utilities — wraps Flask-Mail with graceful fallback.

All public send_* functions are non-blocking: they spawn a daemon thread
so that the calling request returns immediately regardless of SMTP latency.
"""
import threading

from flask_mail import Message

from cms.extensions import mail


def _send(subject: str, recipients: list[str], html_body: str, text_body: str = '') -> bool:
    """Send a mail **synchronously** inside an app-context.

    Returns True on success, False if mail is disabled or fails.
    Called from background thread — never from a request handler directly.
    """
    try:
        msg = Message(
            subject=subject,
            recipients=recipients,
            html=html_body,
            body=text_body or html_body,
        )
        mail.send(msg)
        return True
    except Exception as exc:  # noqa: BLE001
        try:
            from flask import current_app
            current_app.logger.warning('Email send failed: %s', exc)
        except Exception:
            pass
        return False


def _send_async(app, subject: str, recipients: list[str],
                html_body: str, text_body: str = '') -> None:
    """Spawn a daemon thread to send *subject* without blocking the request."""
    def _worker():
        with app.app_context():
            _send(subject, recipients, html_body, text_body)

    t = threading.Thread(target=_worker, daemon=True)
    t.start()


def _get_app():
    from flask import current_app
    return current_app._get_current_object()  # noqa: SLF001


_DEFAULT_VERIFY_SUBJECT = 'BPM-Tutor \u2013 E-Mail best\u00e4tigen'
_DEFAULT_VERIFY_BODY = """\
<h2>Willkommen bei BPM-Tutor!</h2>
<p>Bitte bestätige deine E-Mail-Adresse, indem du auf den folgenden Link klickst:</p>
<p><a href="{verify_url}" style="background:#4f46e5;color:#fff;padding:12px 24px;
text-decoration:none;border-radius:6px;">E-Mail bestätigen</a></p>
<p>Der Link ist 24 Stunden gültig.</p>
<hr>
<p style="color:#666;font-size:12px;">Falls du dich nicht registriert hast, ignoriere diese E-Mail.</p>
"""

_DEFAULT_RESET_SUBJECT = 'BPM-Tutor \u2013 Passwort zur\u00fccksetzen'
_DEFAULT_RESET_BODY = """\
<h2>Passwort zurücksetzen</h2>
<p>Du hast das Zurücksetzen deines Passworts angefordert.</p>
<p><a href="{reset_url}" style="background:#4f46e5;color:#fff;padding:12px 24px;
text-decoration:none;border-radius:6px;">Passwort zurücksetzen</a></p>
<p>Der Link ist 1 Stunde gültig.</p>
<hr>
<p style="color:#666;font-size:12px;">Falls du kein Zurücksetzen angefordert hast, ignoriere diese E-Mail.</p>
"""


def send_verification_email(user, token: str) -> bool:
    from flask import url_for
    from cms.models.settings import Settings
    if not Settings.get(Settings.MAIL_ENABLED):
        return False
    verify_url = url_for('auth.verify_email', token=token, _external=True)
    subject = Settings.get(Settings.MAIL_VERIFY_SUBJECT, '') or _DEFAULT_VERIFY_SUBJECT
    body_tpl = Settings.get(Settings.MAIL_VERIFY_BODY, '') or _DEFAULT_VERIFY_BODY
    html = body_tpl.replace('{verify_url}', verify_url)
    _send_async(_get_app(), subject, [user.email], html,
                f'Bestätige deine E-Mail: {verify_url}')
    return True


def send_password_reset_email(user, token: str) -> None:
    from flask import url_for
    reset_url = url_for('auth.reset_password', token=token, _external=True)
    subject = ''
    body_tpl = ''
    try:
        from cms.models.settings import Settings
        subject = Settings.get(Settings.MAIL_RESET_SUBJECT, '') or _DEFAULT_RESET_SUBJECT
        body_tpl = Settings.get(Settings.MAIL_RESET_BODY, '') or _DEFAULT_RESET_BODY
    except Exception:
        subject = _DEFAULT_RESET_SUBJECT
        body_tpl = _DEFAULT_RESET_BODY
    html = body_tpl.replace('{reset_url}', reset_url)
    _send_async(_get_app(), subject, [user.email], html,
                f'Passwort zurücksetzen: {reset_url}')


def send_grade_notification_email(user, task_title: str, grade_info: str) -> None:
    html = f"""
    <h2>Aufgabe bewertet</h2>
    <p>Deine Aufgabe <strong>{task_title}</strong> wurde bewertet.</p>
    <p><strong>Ergebnis:</strong> {grade_info}</p>
    <p>Melde dich an, um dein Feedback zu sehen.</p>
    """
    _send_async(_get_app(), f'BPM-Tutor \u2013 Aufgabe bewertet: {task_title}',
                [user.email], html)

