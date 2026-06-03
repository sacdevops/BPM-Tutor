"""Email sending utilities — wraps Flask-Mail with graceful fallback.

All public send_* functions are non-blocking: they spawn a daemon thread
so that the calling request returns immediately regardless of SMTP latency.
"""
import threading

from flask_mail import Message

from app.extensions import mail


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


def send_feedback_email(sender_name: str, sender_email: str, category: str,
                        message: str, timestamp: str, page_context: str = '') -> bool:
    """Send a student feedback/bug-report to the configured feedback address."""
    from app.models.settings import Settings
    if not Settings.get(Settings.MAIL_ENABLED):
        return False
    feedback_addr = (Settings.get(Settings.FEEDBACK_EMAIL, '') or '').strip()
    if not feedback_addr:
        return False
    subject = f'[BPM-Tutor Feedback] {category}'
    ctx_row = (
        f'<tr><td style="padding:5px 0;color:#666;width:130px"><strong>Seite</strong></td>'
        f'<td style="padding:5px 0">{page_context}</td></tr>'
    ) if page_context else ''
    safe_msg = message.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('\n', '<br>')
    html_body = f"""\
<div style="font-family:sans-serif;max-width:600px;margin:0 auto">
  <h2 style="color:#162700;border-bottom:3px solid #84BD00;padding-bottom:8px;margin-top:0">
    &#128203; Neue Feedback-Meldung
  </h2>
  <table style="width:100%;border-collapse:collapse;margin:16px 0;font-size:14px">
    <tr><td style="padding:5px 0;color:#666;width:130px"><strong>Zeitstempel</strong></td>
        <td style="padding:5px 0">{timestamp}</td></tr>
    <tr><td style="padding:5px 0;color:#666"><strong>Name</strong></td>
        <td style="padding:5px 0">{sender_name or '(anonym)'}</td></tr>
    <tr><td style="padding:5px 0;color:#666"><strong>E-Mail</strong></td>
        <td style="padding:5px 0">{sender_email or '(keine Angabe)'}</td></tr>
    <tr><td style="padding:5px 0;color:#666"><strong>Kategorie</strong></td>
        <td style="padding:5px 0"><span style="background:#84BD00;color:#fff;padding:2px 8px;border-radius:12px;font-size:13px">{category}</span></td></tr>
    {ctx_row}
  </table>
  <div style="background:#f8f9fa;border-left:4px solid #84BD00;padding:16px;border-radius:0 4px 4px 0;margin:16px 0;font-size:14px">
    <strong>Beschreibung:</strong><br><br>
    {safe_msg}
  </div>
  <hr style="border:none;border-top:1px solid #eee;margin:20px 0">
  <p style="color:#aaa;font-size:11px">Diese E-Mail wurde automatisch von BPM-Tutor generiert.</p>
</div>"""
    app = _get_app()
    _send_async(app, subject, [feedback_addr], html_body)
    return True


def _nl2br(text: str) -> str:
    """Convert plain-text newlines to HTML <br> tags.

    Applied only when the body template contains no HTML tags — so that
    templates written in plain text with line breaks are rendered correctly
    in email clients, while templates already containing HTML are left as-is.
    """
    if '<' in text:
        return text  # already HTML — leave untouched
    import html as _html_lib
    escaped = _html_lib.escape(text)
    return escaped.replace('\n', '<br>\n')


def send_verification_email(user, token: str) -> bool:
    from flask import url_for
    from app.models.settings import Settings
    if not Settings.get(Settings.MAIL_ENABLED):
        return False
    verify_url = url_for('auth.verify_email', token=token, _external=True)
    subject = Settings.get(Settings.MAIL_VERIFY_SUBJECT, '') or _DEFAULT_VERIFY_SUBJECT
    body_tpl = Settings.get(Settings.MAIL_VERIFY_BODY, '') or _DEFAULT_VERIFY_BODY
    html = _nl2br(body_tpl.replace('{verify_url}', verify_url))
    _send_async(_get_app(), subject, [user.email], html,
                f'Bestätige deine E-Mail: {verify_url}')
    return True


def send_password_reset_email(user, token: str) -> None:
    from flask import url_for
    reset_url = url_for('auth.reset_password', token=token, _external=True)
    subject = ''
    body_tpl = ''
    try:
        from app.models.settings import Settings
        subject = Settings.get(Settings.MAIL_RESET_SUBJECT, '') or _DEFAULT_RESET_SUBJECT
        body_tpl = Settings.get(Settings.MAIL_RESET_BODY, '') or _DEFAULT_RESET_BODY
    except Exception:
        subject = _DEFAULT_RESET_SUBJECT
        body_tpl = _DEFAULT_RESET_BODY
    html = _nl2br(body_tpl.replace('{reset_url}', reset_url))
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


# ─── Study lifecycle emails ────────────────────────────────────────────────────

def _study_btn(url: str, label: str) -> str:
    return (
        f'<p style="margin:20px 0"><a href="{url}" style="background:#84BD00;color:#fff;'
        f'padding:12px 28px;text-decoration:none;border-radius:8px;font-weight:600">'
        f'{label}</a></p>'
    )


def send_study_announcement(user_email: str, user_name: str, study_title: str,
                            enrollment_end, study_url: str) -> None:
    """Announce that enrollment for a study is now open."""
    from app.models.settings import Settings
    if not Settings.get(Settings.MAIL_ENABLED):
        return
    deadline = (enrollment_end.strftime('%d.%m.%Y') if enrollment_end else 'offen')
    html = f"""
<div style="font-family:sans-serif;max-width:580px;margin:0 auto">
  <h2 style="color:#162700;border-bottom:3px solid #84BD00;padding-bottom:8px">
    &#128202; Neue Studie: {study_title}
  </h2>
  <p>Hallo {user_name},</p>
  <p>eine neue Research Study steht zur Anmeldung offen:</p>
  <p style="font-size:1.1em"><strong>{study_title}</strong></p>
  <p>Anmeldefrist: <strong>{deadline}</strong></p>
  {_study_btn(study_url, 'Jetzt anmelden')}
  <hr style="border:none;border-top:1px solid #eee;margin:20px 0">
  <p style="color:#aaa;font-size:11px">BPM-Tutor &mdash; automatische Benachrichtigung</p>
</div>"""
    _send_async(_get_app(), f'BPM-Tutor \u2013 Studie offen: {study_title}',
                [user_email], html)


def send_study_wave_available(user_email: str, user_name: str, study_title: str,
                               wave_label: str, study_url: str) -> None:
    """Notify participant that a new wave of tasks/surveys is now available."""
    from app.models.settings import Settings
    if not Settings.get(Settings.MAIL_ENABLED):
        return
    html = f"""
<div style="font-family:sans-serif;max-width:580px;margin:0 auto">
  <h2 style="color:#162700;border-bottom:3px solid #84BD00;padding-bottom:8px">
    &#128196; Neue Aufgaben bereit: {study_title}
  </h2>
  <p>Hallo {user_name},</p>
  <p>in der Studie <strong>{study_title}</strong> sind neue Schritte f&uuml;r dich freigeschalten:</p>
  <p style="font-size:1.1em"><strong>{wave_label}</strong></p>
  {_study_btn(study_url, 'Zur Studie')}
  <hr style="border:none;border-top:1px solid #eee;margin:20px 0">
  <p style="color:#aaa;font-size:11px">BPM-Tutor &mdash; automatische Benachrichtigung</p>
</div>"""
    _send_async(_get_app(), f'BPM-Tutor \u2013 Neue Aufgaben: {study_title}',
                [user_email], html)


def send_study_deadline_reminder(user_email: str, user_name: str, study_title: str,
                                  step_label: str, due_date, study_url: str) -> None:
    """Remind participant about an upcoming step deadline."""
    from app.models.settings import Settings
    if not Settings.get(Settings.MAIL_ENABLED):
        return
    due_str = due_date.strftime('%d.%m.%Y %H:%M') if due_date else ''
    html = f"""
<div style="font-family:sans-serif;max-width:580px;margin:0 auto">
  <h2 style="color:#c0392b;border-bottom:3px solid #c0392b;padding-bottom:8px">
    &#9201; Erinnerung: Abgabefrist n&auml;hert sich
  </h2>
  <p>Hallo {user_name},</p>
  <p>der folgende Schritt in der Studie <strong>{study_title}</strong> l&auml;uft bald ab:</p>
  <p style="font-size:1.1em"><strong>{step_label}</strong></p>
  <p>Frist: <strong>{due_str}</strong></p>
  {_study_btn(study_url, 'Jetzt erledigen')}
  <hr style="border:none;border-top:1px solid #eee;margin:20px 0">
  <p style="color:#aaa;font-size:11px">BPM-Tutor &mdash; automatische Erinnerung</p>
</div>"""
    _send_async(_get_app(), f'BPM-Tutor \u2013 Erinnerung: {study_title}',
                [user_email], html)


def send_study_completed(user_email: str, user_name: str, study_title: str) -> None:
    """Thank participant for completing a study."""
    from app.models.settings import Settings
    if not Settings.get(Settings.MAIL_ENABLED):
        return
    html = f"""
<div style="font-family:sans-serif;max-width:580px;margin:0 auto">
  <h2 style="color:#162700;border-bottom:3px solid #84BD00;padding-bottom:8px">
    &#9989; Studie abgeschlossen!
  </h2>
  <p>Hallo {user_name},</p>
  <p>herzlichen Gl&uuml;ckwunsch! Du hast die Studie <strong>{study_title}</strong> erfolgreich abgeschlossen.</p>
  <p>Vielen Dank f&uuml;r deine Teilnahme!</p>
  <hr style="border:none;border-top:1px solid #eee;margin:20px 0">
  <p style="color:#aaa;font-size:11px">BPM-Tutor &mdash; automatische Best&auml;tigung</p>
</div>"""
    _send_async(_get_app(), f'BPM-Tutor \u2013 Studie abgeschlossen: {study_title}',
                [user_email], html)


def send_notification_email(user, title: str, message: str, link: str = '') -> None:
    """Send an in-app notification also as an email to the user."""
    from app.models.settings import Settings
    if not Settings.get(Settings.MAIL_ENABLED):
        return
    link_html = _study_btn(link, 'Ansehen') if link else ''
    html = f"""
<div style="font-family:sans-serif;max-width:580px;margin:0 auto">
  <h2 style="color:#162700;border-bottom:3px solid #84BD00;padding-bottom:8px">
    &#128276; {title}
  </h2>
  <p>Hallo {user.username},</p>
  <p>{message}</p>
  {link_html}
  <hr style="border:none;border-top:1px solid #eee;margin:20px 0">
  <p style="color:#aaa;font-size:11px">BPM-Tutor &mdash; automatische Benachrichtigung.
    Du kannst E-Mail-Benachrichtigungen in deinem Profil deaktivieren.</p>
</div>"""
    _send_async(_get_app(), f'BPM-Tutor \u2013 {title}', [user.email], html)

