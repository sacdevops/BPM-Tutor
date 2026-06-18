"""Admin — system settings, registration fields, mail, DB backup, notifications, API stats."""
import json

from flask import render_template, redirect, url_for, flash, request, jsonify, send_file, current_app
from flask_login import current_user

from app.blueprints.admin import admin_bp
from app.extensions import db
from app.models.user import User
from app.models.settings import Notification, RegistrationField, Settings, SystemSetting
from app.utils.decorators import admin_required, tutor_or_admin_required
from app.utils.stats import global_stats, since_from_period, chart_data_timeline


def _persist_registration_fields(fields_data: list) -> None:
    """Delete and rebuild all RegistrationField rows from the given list."""
    RegistrationField.query.delete()
    for i, fd in enumerate(fields_data):
        field = RegistrationField(
            name=fd.get('name', f'field_{i}'),
            label=fd.get('label', ''),
            label_de=fd.get('label_de', '') or None,
            field_type=fd.get('field_type', 'text'),
            required=fd.get('required', False),
            sort_order=i,
            is_active=True,
        )
        opts = fd.get('options', [])
        if opts:
            field.options = opts
        db.session.add(field)
    db.session.commit()


# ── Registration fields ───────────────────────────────────────────────────────

@admin_bp.route('/settings/registration-fields', methods=['GET', 'POST'])
@admin_required
def registration_fields():
    if request.method == 'POST':
        fields_json = request.form.get('fields_json', '[]')
        try:
            fields_data = json.loads(fields_json)
            _persist_registration_fields(fields_data)
            flash('Registrierungsfelder gespeichert.', 'success')
        except Exception as e:
            flash(f'Fehler beim Speichern: {e}', 'danger')
        return redirect(url_for('admin.registration_fields'))

    fields = RegistrationField.query.order_by(RegistrationField.sort_order).all()
    return render_template('cms/admin/registration_fields.html', fields=fields)


@admin_bp.route('/settings/registration-fields/api', methods=['POST'])
@admin_required
def registration_fields_api():
    """JSON endpoint used by the Settings tab reg-fields form."""
    fields_json = request.form.get('fields_json', '[]')
    try:
        fields_data = json.loads(fields_json)
        _persist_registration_fields(fields_data)
        return jsonify(ok=True)
    except Exception as e:
        db.session.rollback()
        return jsonify(ok=False, error=str(e)), 400


# ── System settings ───────────────────────────────────────────────────────────

@admin_bp.route('/settings', methods=['GET', 'POST'])
@admin_required
def settings():
    from app.models.i18n import Language as _Lang
    active_languages = _Lang.query.filter_by(is_active=True).order_by(_Lang.sort_order).all()

    if request.method == 'POST':
        import base64
        mapping = {
            Settings.AUTH_REQUIRED: bool(request.form.get('auth_required')),
            Settings.ALLOW_REGISTRATION: bool(request.form.get('allow_registration')),
            Settings.REQUIRE_EMAIL_VERIFICATION: bool(request.form.get('require_email_verification')),
            Settings.LEVEL_SYSTEM_ENABLED: bool(request.form.get('level_system_enabled')),
            Settings.COHORTS_ENABLED: bool(request.form.get('cohorts_enabled')),
            Settings.RESEARCH_MODE_ENABLED: bool(request.form.get('research_mode_enabled')),
            Settings.CUSTOM_MODE_ENABLED: bool(request.form.get('custom_mode_enabled')),
            Settings.MAINTENANCE_MODE: bool(request.form.get('maintenance_mode')),
            Settings.API_KEY_MODE: request.form.get('api_key_mode', 'per_user'),
            Settings.GLOBAL_API_KEY: request.form.get('global_api_key', '').strip(),
            Settings.API_ENDPOINT: request.form.get('api_endpoint', '').strip(),
            Settings.DEFAULT_MODEL: request.form.get('default_model', '').strip(),
            Settings.FEEDBACK_EMAIL: request.form.get('feedback_email', '').strip(),
            Settings.PRIVACY_POLICY: request.form.get('privacy_policy', '').strip(),
            Settings.MAIL_ENABLED: bool(request.form.get('mail_enabled')),
            Settings.MAIL_SERVER: request.form.get('mail_server', '').strip(),
            Settings.MAIL_PORT: request.form.get('mail_port', '587').strip(),
            Settings.MAIL_USE_TLS: request.form.get('mail_encryption') == 'starttls',
            Settings.MAIL_USE_SSL: request.form.get('mail_encryption') == 'ssl',
            Settings.MAIL_USERNAME: request.form.get('mail_username', '').strip(),
            Settings.MAIL_PASSWORD: request.form.get('mail_password', '').strip(),
            Settings.MAIL_DEFAULT_SENDER: request.form.get('mail_default_sender', '').strip(),
            Settings.MAIL_SEPARATE_INCOMING: bool(request.form.get('mail_separate_incoming')),
            Settings.MAIL_INCOMING_PROTOCOL: request.form.get('mail_incoming_protocol', 'imap').strip(),
            Settings.MAIL_INCOMING_SERVER: request.form.get('mail_incoming_server', '').strip(),
            Settings.MAIL_INCOMING_PORT: request.form.get('mail_incoming_port', '993').strip(),
            Settings.MAIL_INCOMING_USE_TLS: bool(request.form.get('mail_incoming_use_tls')),
            Settings.MAIL_INCOMING_USERNAME: request.form.get('mail_incoming_username', '').strip(),
            Settings.MAIL_INCOMING_PASSWORD: request.form.get('mail_incoming_password', '').strip(),
            Settings.SITE_NAME: request.form.get('site_name_en', request.form.get('site_name', 'BPM-Tutor')).strip(),
            Settings.BRAND_PRIMARY: request.form.get('brand_primary', '#84BD00').strip(),
            Settings.BRAND_SIDEBAR_BG: request.form.get('brand_sidebar_bg', '#162700').strip(),
            Settings.BRAND_LOGO_URL: request.form.get('brand_logo_url', '').strip(),
            Settings.BRAND_LOGO_LINK: request.form.get('brand_logo_link', '/').strip(),
            Settings.SITE_TAGLINE: request.form.get('site_tagline', '').strip(),
            Settings.SITE_TAGLINE_DE: request.form.get('site_tagline_de', '').strip(),
            Settings.MAIL_VERIFY_SUBJECT: request.form.get('mail_verify_subject', '').strip(),
            Settings.MAIL_VERIFY_BODY: request.form.get('mail_verify_body', '').strip(),
            Settings.MAIL_RESET_SUBJECT: request.form.get('mail_reset_subject', '').strip(),
            Settings.MAIL_RESET_BODY: request.form.get('mail_reset_body', '').strip(),
            Settings.BPMN_SYNTAX_RULES: request.form.get('bpmn_syntax_rules', '').strip(),
            Settings.BPMN_ELEMENTS: request.form.get('bpmn_elements', '').strip(),
            Settings.GENERAL_RULES: request.form.get('general_rules', '').strip(),
            Settings.GENERAL_RULES_DE: request.form.get('general_rules_de', '').strip(),
            Settings.LION_FORMAT_RULES: request.form.get('lion_format_rules', '').strip(),
            # Auto-backup
            Settings.AUTO_BACKUP_ENABLED: bool(request.form.get('auto_backup_enabled')),
            Settings.AUTO_BACKUP_INTERVAL_HOURS: request.form.get('auto_backup_interval_hours', '24').strip(),
            Settings.AUTO_BACKUP_STORAGE: request.form.get('auto_backup_storage', 'local').strip(),
            Settings.AUTO_BACKUP_LOCAL_PATH: request.form.get('auto_backup_local_path', '').strip(),
            Settings.AUTO_BACKUP_MAX_KEEP: request.form.get('auto_backup_max_keep', '14').strip(),
            Settings.SCIEBO_URL: request.form.get('sciebo_url', '').strip(),
            Settings.SCIEBO_USERNAME: request.form.get('sciebo_username', '').strip(),
            Settings.SCIEBO_PASSWORD: request.form.get('sciebo_password', '').strip(),
            Settings.SCIEBO_REMOTE_PATH: request.form.get('sciebo_remote_path', '').strip(),
        }

        # Per-language BPMN rules (skip English — stored in the base keys)
        for _al in active_languages:
            if _al.code == 'en':
                continue
            mapping[f'bpmn_syntax_rules_{_al.code}'] = request.form.get(f'bpmn_syntax_rules_{_al.code}', '').strip()
            mapping[f'bpmn_elements_{_al.code}'] = request.form.get(f'bpmn_elements_{_al.code}', '').strip()

        for _al in active_languages:
            _val = request.form.get(f'site_name_{_al.code}', '').strip()
            if _val:
                _key = Settings.SITE_NAME if _al.code == 'en' else f'site_name_{_al.code}'
                mapping[_key] = _val

        logo_file = request.files.get('brand_logo_file')
        if logo_file and logo_file.filename:
            allowed_mime = {'image/png', 'image/jpeg', 'image/gif', 'image/webp', 'image/svg+xml'}
            mime = logo_file.mimetype or 'image/png'
            if mime in allowed_mime and logo_file.content_length <= 2 * 1024 * 1024:
                logo_bytes = logo_file.read()
                if len(logo_bytes) <= 2 * 1024 * 1024:
                    mapping[Settings.BRAND_LOGO_DATA] = base64.b64encode(logo_bytes).decode('ascii')
                    mapping[Settings.BRAND_LOGO_MIME] = mime
                    mapping[Settings.BRAND_LOGO_URL] = ''
                else:
                    flash('Logo-Datei ist zu groß (max. 2 MB).', 'warning')
            else:
                flash('Ungültiges Logo-Format. Erlaubt: PNG, JPG, GIF, WEBP, SVG.', 'warning')
        elif request.form.get('logo_action') == 'clear':
            mapping[Settings.BRAND_LOGO_DATA] = ''
            mapping[Settings.BRAND_LOGO_MIME] = 'image/png'
            mapping[Settings.BRAND_LOGO_URL] = ''

        # Capture plaintext mail password before encryption (needed for live Flask-Mail config)
        _mail_pw_plain = str(mapping.get(Settings.MAIL_PASSWORD) or '')

        # Encrypt sensitive values; if field left blank, keep the existing encrypted value
        from app.utils.crypto import encrypt_value as _enc
        _SENSITIVE = (Settings.GLOBAL_API_KEY, Settings.MAIL_PASSWORD, Settings.MAIL_INCOMING_PASSWORD, Settings.SCIEBO_PASSWORD)
        for _key in _SENSITIVE:
            if _key in mapping:
                _raw = str(mapping[_key] or '')
                if _raw:
                    mapping[_key] = _enc(_raw)
                else:
                    del mapping[_key]  # empty → keep existing encrypted value

        Settings.set_many(mapping)
        enc = request.form.get('mail_encryption', 'starttls')
        current_app.config['MAIL_SERVER'] = mapping.get(Settings.MAIL_SERVER, '')
        current_app.config['MAIL_PORT'] = int(mapping.get(Settings.MAIL_PORT, 587) or 587)
        current_app.config['MAIL_USE_TLS'] = enc == 'starttls'
        current_app.config['MAIL_USE_SSL'] = enc == 'ssl'
        current_app.config['MAIL_USERNAME'] = mapping.get(Settings.MAIL_USERNAME, '')
        current_app.config['MAIL_PASSWORD'] = _mail_pw_plain  # plaintext for Flask-Mail
        current_app.config['MAIL_DEFAULT_SENDER'] = mapping.get(Settings.MAIL_DEFAULT_SENDER, '')
        from app.extensions import mail as _mail_ext
        _mail_ext.init_app(current_app)
        from app.utils.i18n_helper import _t
        flash(_t('admin.settings_saved', 'Settings saved.'), 'success')
        return redirect(url_for('admin.settings'))

    current_settings = {
        row.key: Settings._cast(row.value, row.value_type)
        for row in SystemSetting.query.all()
    }
    # Keys that exist in the DB (even if value is empty string)
    _db_keys = {row.key for row in SystemSetting.query.all()}
    # Decrypt sensitive values for display so the form doesn't show cipher text
    from app.utils.crypto import decrypt_value as _dec
    for _key in (Settings.GLOBAL_API_KEY, Settings.MAIL_PASSWORD, Settings.MAIL_INCOMING_PASSWORD, Settings.SCIEBO_PASSWORD):
        if _key in current_settings:
            current_settings[_key] = _dec(str(current_settings[_key] or ''))
    reg_fields = RegistrationField.query.order_by(RegistrationField.sort_order).all()
    reg_fields_data = [
        {'name': f.name, 'label': f.label, 'label_de': f.label_de or '',
         'field_type': f.field_type, 'required': f.required,
         'options': f.options or []}
        for f in reg_fields
    ]
    from app.services.prompts._base import BPMN_STANDARDS as _bpmn_std, BPMN_ELEMENTS_REFERENCE as _bpmn_el, GENERAL_RULES as _general_rules_default, GENERAL_RULES_DE as _general_rules_de_default, LION_FORMAT_RULES as _lion_format_default

    # Compute next backup time for display
    from datetime import datetime as _dt, timezone as _tz, timedelta as _td
    _last_run_str = current_settings.get(Settings.AUTO_BACKUP_LAST_RUN, '') or ''
    _backup_next_run = None
    if _last_run_str:
        try:
            _interval_h = int(current_settings.get(Settings.AUTO_BACKUP_INTERVAL_HOURS, 24) or 24)
            _last_dt = _dt.fromisoformat(_last_run_str).replace(tzinfo=_tz.utc)
            _backup_next_run = (_last_dt + _td(hours=_interval_h)).strftime('%Y-%m-%d %H:%M:%S')
        except Exception:
            pass

    return render_template('cms/admin/settings.html', s=current_settings, Settings=Settings,
                           active_languages=active_languages,
                           reg_fields_data=reg_fields_data,
                           db_keys=_db_keys,
                           bpmn_standards_default=_bpmn_std,
                           bpmn_elements_default=_bpmn_el,
                           general_rules_default=_general_rules_default,
                           general_rules_de_default=_general_rules_de_default,
                           lion_format_rules_default=_lion_format_default,
                           backup_next_run=_backup_next_run)


def _sciebo_base(url: str, username: str) -> str:
    """Build the WebDAV base URL, normalising whatever the user typed.

    Accepts both:
      • https://tu-dortmund.sciebo.de  (bare domain — recommended)
      • https://tu-dortmund.sciebo.de/remote.php/dav/files/user@...  (full path — tolerated)
    Always returns:  https://<host>/remote.php/dav/files/<username>
    """
    import re
    # Strip any /remote.php/... suffix the user may have included
    base = re.sub(r'/remote\.php.*$', '', url.rstrip('/'))
    return f'{base}/remote.php/dav/files/{username}'


# ── Manual backup trigger ─────────────────────────────────────────────────────

@admin_bp.route('/settings/backup-now', methods=['POST'])
@admin_required
def backup_now():
    """Run a backup immediately, bypassing the scheduled interval check."""
    import os
    import sqlite3
    from datetime import datetime as _dt, timezone as _tz

    try:
        db_uri = current_app.config.get('SQLALCHEMY_DATABASE_URI', '')
        if 'sqlite' not in db_uri:
            return jsonify(ok=False, error='Only SQLite databases are supported.'), 400

        db_path = db_uri.replace('sqlite:///', '', 1)
        if not os.path.exists(db_path):
            return jsonify(ok=False, error='Database file not found.'), 400

        custom_path = (Settings.get(Settings.AUTO_BACKUP_LOCAL_PATH, '') or '').strip()
        backup_dir = custom_path if custom_path else os.path.join(os.path.dirname(db_path), 'backups')
        os.makedirs(backup_dir, exist_ok=True)

        ts = _dt.now().strftime('%Y%m%d_%H%M%S')
        filename = f'bpmtutor_{ts}.db'
        dest = os.path.join(backup_dir, filename)

        # SQLite online backup
        src = sqlite3.connect(db_path)
        dst = sqlite3.connect(dest)
        try:
            src.backup(dst)
        finally:
            src.close()
            dst.close()
        current_app.logger.info('[backup_now] Created: %s', dest)

        # Rotate local backups
        try:
            max_keep = int(Settings.get(Settings.AUTO_BACKUP_MAX_KEEP, 14) or 14)
        except (TypeError, ValueError):
            max_keep = 14
        all_backups = sorted(
            [os.path.join(backup_dir, f) for f in os.listdir(backup_dir) if f.endswith('.db')]
        )
        for old in all_backups[:-max_keep]:
            os.remove(old)

        # Sciebo / WebDAV upload (if configured)
        sciebo_detail = None
        storage = (Settings.get(Settings.AUTO_BACKUP_STORAGE, 'local') or 'local').strip()
        if storage == 'sciebo':
            sciebo_url = (Settings.get(Settings.SCIEBO_URL, '') or '').rstrip('/')
            sciebo_user = Settings.get(Settings.SCIEBO_USERNAME, '') or ''
            from app.utils.crypto import decrypt_value as _dec
            sciebo_pass = _dec(Settings.get(Settings.SCIEBO_PASSWORD, '') or '')
            remote_path = (Settings.get(Settings.SCIEBO_REMOTE_PATH, '') or '').strip('/')
            if not sciebo_url or not sciebo_user:
                sciebo_detail = 'Sciebo URL or username not configured'
                current_app.logger.warning('[backup_now] %s', sciebo_detail)
            else:
                try:
                    import requests as _req
                    webdav_base = _sciebo_base(sciebo_url, sciebo_user)
                    auth = (sciebo_user, sciebo_pass)
                    if remote_path:
                        # Create each directory level individually (WebDAV MKCOL is not recursive)
                        parts = remote_path.split('/')
                        for i in range(1, len(parts) + 1):
                            partial = '/'.join(parts[:i])
                            mkcol_url = f'{webdav_base}/{partial}/'
                            mkcol_resp = _req.request('MKCOL', mkcol_url, auth=auth, timeout=15)
                            # 201 = created, 405 = already exists (both are fine)
                            current_app.logger.info('[backup_now] MKCOL %s → %s', mkcol_url, mkcol_resp.status_code)
                            if mkcol_resp.status_code not in (201, 405, 301, 302):
                                current_app.logger.warning('[backup_now] MKCOL unexpected status %s for %s',
                                                           mkcol_resp.status_code, mkcol_url)
                        upload_url = f'{webdav_base}/{remote_path}/{filename}'
                    else:
                        upload_url = f'{webdav_base}/{filename}'
                    with open(dest, 'rb') as fh:
                        resp = _req.put(upload_url, data=fh, auth=auth, timeout=120)
                    if resp.status_code in (200, 201, 204):
                        sciebo_detail = f'Uploaded to {upload_url}'
                        current_app.logger.info('[backup_now] Sciebo upload OK: %s', upload_url)
                    else:
                        sciebo_detail = f'Sciebo upload returned HTTP {resp.status_code}: {resp.text[:200]}'
                        current_app.logger.warning('[backup_now] %s', sciebo_detail)
                except Exception as sciebo_exc:
                    sciebo_detail = f'Sciebo upload error: {sciebo_exc}'
                    current_app.logger.warning('[backup_now] %s', sciebo_exc, exc_info=True)

        now_iso = _dt.now(_tz.utc).isoformat()
        Settings.set(Settings.AUTO_BACKUP_LAST_RUN, now_iso)

        return jsonify(
            ok=True,
            last_run=now_iso[:19].replace('T', ' '),
            local_path=dest,
            sciebo=sciebo_detail,
        )

    except Exception as exc:
        current_app.logger.exception('[backup_now] failed: %s', exc)
        return jsonify(ok=False, error=str(exc)), 500


# ── Test Sciebo connection ────────────────────────────────────────────────────

@admin_bp.route('/settings/test-sciebo', methods=['POST'])
@admin_required
def test_sciebo():
    """Check whether Sciebo credentials are valid by doing a PROPFIND on the configured path."""
    try:
        import requests as _req
        sciebo_url = (Settings.get(Settings.SCIEBO_URL, '') or '').rstrip('/')
        sciebo_user = Settings.get(Settings.SCIEBO_USERNAME, '') or ''
        from app.utils.crypto import decrypt_value as _dec
        sciebo_pass = _dec(Settings.get(Settings.SCIEBO_PASSWORD, '') or '')
        remote_path = (Settings.get(Settings.SCIEBO_REMOTE_PATH, '') or '').strip('/')

        if not sciebo_url or not sciebo_user:
            return jsonify(ok=False, msg='URL or username not configured.')

        webdav_base = _sciebo_base(sciebo_url, sciebo_user)
        probe_url = f'{webdav_base}/{remote_path}/' if remote_path else f'{webdav_base}/'

        resp = _req.request('PROPFIND', probe_url,
                            auth=(sciebo_user, sciebo_pass),
                            headers={'Depth': '0'},
                            timeout=15)

        if resp.status_code in (200, 207):
            return jsonify(ok=True, msg=f'Verbindung OK (HTTP {resp.status_code}). Pfad "{remote_path or "/"}" ist erreichbar.')
        elif resp.status_code == 401:
            return jsonify(ok=False, msg=f'Authentifizierung fehlgeschlagen (HTTP 401). Benutzername oder Passwort prüfen.\nGeprüfte URL: {probe_url}')
        elif resp.status_code == 404:
            # Try root to distinguish wrong path vs wrong credentials
            root_resp = _req.request('PROPFIND', f'{webdav_base}/',
                                     auth=(sciebo_user, sciebo_pass),
                                     headers={'Depth': '0'}, timeout=15)
            if root_resp.status_code in (200, 207):
                return jsonify(ok=False, msg=(
                    f'Credentials sind korrekt, aber Pfad "{remote_path}" wurde nicht gefunden (HTTP 404).\n'
                    f'Geprüfte URL: {probe_url}\n'
                    f'Bitte prüfen: Existiert der Ordner in Sciebo genau so? Groß-/Kleinschreibung beachten.\n'
                    f'Beim nächsten Backup wird versucht den Ordner automatisch anzulegen.'
                ))
            elif root_resp.status_code == 401:
                return jsonify(ok=False, msg=f'Authentifizierung fehlgeschlagen (HTTP 401). Benutzername oder Passwort prüfen.\nGeprüfte URL: {probe_url}')
            else:
                return jsonify(ok=False, msg=f'Pfad nicht gefunden (HTTP 404) und Root nicht erreichbar (HTTP {root_resp.status_code}).\nGeprüfte URL: {probe_url}')
        else:
            return jsonify(ok=False, msg=f'Unerwartete Antwort: HTTP {resp.status_code}\nGeprüfte URL: {probe_url}')
    except Exception as exc:
        return jsonify(ok=False, msg=f'Verbindungsfehler: {exc}')


# ── Test mail connection ──────────────────────────────────────────────────────

@admin_bp.route('/settings/test-mail', methods=['POST'])
@admin_required
def test_mail():
    import smtplib
    import socket as _socket

    server = Settings.get(Settings.MAIL_SERVER, '').strip()
    try:
        port = int(Settings.get(Settings.MAIL_PORT, 587) or 587)
    except (TypeError, ValueError):
        port = 587
    use_tls = bool(Settings.get(Settings.MAIL_USE_TLS, False))
    use_ssl = bool(Settings.get(Settings.MAIL_USE_SSL, False))
    username = Settings.get(Settings.MAIL_USERNAME, '') or ''
    from app.utils.crypto import decrypt_value as _dec
    password = _dec(Settings.get(Settings.MAIL_PASSWORD, '') or '')
    sender = Settings.get(Settings.MAIL_DEFAULT_SENDER, '') or username or 'noreply@bpmtutor.local'

    if not server:
        return jsonify(ok=False, msg='Kein SMTP-Server konfiguriert. Bitte zuerst speichern.')

    try:
        if use_ssl:
            conn = smtplib.SMTP_SSL(server, port, timeout=10)
        else:
            conn = smtplib.SMTP(server, port, timeout=10)
            if use_tls:
                conn.ehlo()
                conn.starttls()
                conn.ehlo()
        if username:
            conn.login(username, password)
        conn.quit()
    except _socket.timeout:
        return jsonify(ok=False,
                       msg=f'Verbindungs-Timeout zu {server}:{port}. '
                           'Prüfe Server-Adresse, Port und ob du im richtigen Netzwerk (VPN?) bist.')
    except ConnectionRefusedError as exc:
        enc_hint = 'STARTTLS (Port 587)' if not use_ssl else 'SSL/TLS (Port 465)'
        return jsonify(ok=False,
                       msg=f'Verbindung zu {server}:{port} verweigert. '
                           f'Port {port} ist möglicherweise durch eine Firewall blockiert. '
                           f'Versuche {enc_hint}. Details: {exc}')
    except smtplib.SMTPAuthenticationError as exc:
        return jsonify(ok=False,
                       msg=f'Verbindung erfolgreich, aber Anmeldung fehlgeschlagen. '
                           f'Benutzername oder Passwort falsch. Details: {exc}')
    except smtplib.SMTPException as exc:
        return jsonify(ok=False, msg=f'SMTP-Fehler: {exc}')
    except OSError as exc:
        return jsonify(ok=False,
                       msg=f'Netzwerkfehler beim Verbinden zu {server}:{port}: {exc}')

    try:
        from flask_mail import Message
        from app.extensions import mail as _mail
        msg = Message(
            subject='BPM-Tutor – Verbindungstest',
            sender=sender,
            recipients=[current_user.email],
            html=('<h2>Test erfolgreich</h2>'
                  '<p>Die SMTP-Konfiguration ist korrekt. '
                  'E-Mail-Versand funktioniert.</p>'),
            body='Test erfolgreich. Die SMTP-Konfiguration ist korrekt.',
        )
        _mail.send(msg)
    except Exception as exc:
        return jsonify(ok=False,
                       msg=f'SMTP-Verbindung OK, aber Senden fehlgeschlagen: {exc}')

    return jsonify(ok=True,
                   msg=f'Test-E-Mail erfolgreich an {current_user.email} gesendet.')


# ── AI translate ─────────────────────────────────────────────────────────────

@admin_bp.route('/api/translate-text', methods=['POST'])
@admin_required
def translate_text():
    """Translate text to a target language using the configured AI.

    Used by the BPMN Rules admin tab to auto-translate English rules into
    other active UI languages.  Requires a global API key to be configured.
    """
    import requests as _http
    data = request.get_json(force=True, silent=True) or {}
    text = (data.get('text') or '').strip()
    target_lang = (data.get('target_lang') or '').strip()
    target_lang_name = (data.get('target_lang_name') or target_lang).strip()

    if not text:
        return jsonify(ok=False, error='No text provided.'), 400
    if not target_lang:
        return jsonify(ok=False, error='No target language specified.'), 400

    from app.utils.crypto import decrypt_value as _dec
    api_key_raw = Settings.get(Settings.GLOBAL_API_KEY) or ''
    api_key = _dec(api_key_raw) if api_key_raw else ''
    if not api_key:
        return jsonify(ok=False, error='No global API key configured. Please add one in the AI API section first.'), 400

    endpoint = (Settings.get(Settings.API_ENDPOINT) or '').rstrip('/')
    if not endpoint:
        import config
        endpoint = config.CAMPUS_KI_BASE_URL.rstrip('/')
    model = Settings.get(Settings.DEFAULT_MODEL) or 'gpt-4o-mini'

    system_prompt = (
        f'Translate the following text to {target_lang_name} ({target_lang}). '
        'Preserve all formatting exactly: line breaks, bullet points, indentation, '
        'code-style rules, and technical terms (especially BPMN element names). '
        'Return ONLY the translated text with no preamble or explanation.'
    )
    try:
        resp = _http.post(
            f'{endpoint}/v1/chat/completions',
            headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
            json={
                'model': model,
                'messages': [
                    {'role': 'system', 'content': system_prompt},
                    {'role': 'user', 'content': text},
                ]
            },
            timeout=60,
        )
        resp.raise_for_status()
        result = resp.json()['choices'][0]['message']['content']
        return jsonify(ok=True, result=result)
    except Exception as exc:
        return jsonify(ok=False, error=str(exc)), 500


# ── Database export / import ─────────────────────────────────────────────────

@admin_bp.route('/settings/db-export')
@admin_required
def db_export():
    import os
    from datetime import datetime
    db_uri = current_app.config.get('SQLALCHEMY_DATABASE_URI', '')
    if not db_uri.startswith('sqlite:///'):
        flash('Database download requires a SQLite database.', 'warning')
        return redirect(url_for('admin.settings'))
    db_path = db_uri.replace('sqlite:///', '', 1)
    if not os.path.isfile(db_path):
        flash('Database file not found.', 'danger')
        return redirect(url_for('admin.settings'))
    filename = f'bpmtutor_backup_{datetime.now().strftime("%Y%m%d_%H%M%S")}.db'
    return send_file(db_path, as_attachment=True, download_name=filename,
                     mimetype='application/octet-stream')


@admin_bp.route('/settings/db-import', methods=['POST'])
@admin_required
def db_import():
    import os
    import shutil
    import sqlite3
    import tempfile
    db_uri = current_app.config.get('SQLALCHEMY_DATABASE_URI', '')
    if not db_uri.startswith('sqlite:///'):
        flash('Database import requires a SQLite database.', 'warning')
        return redirect(url_for('admin.settings'))

    uploaded = request.files.get('db_file')
    if not uploaded or not uploaded.filename:
        flash('No file selected.', 'warning')
        return redirect(url_for('admin.settings'))

    db_path = db_uri.replace('sqlite:///', '', 1)
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.db')
    try:
        uploaded.save(tmp.name)
        tmp.close()

        with open(tmp.name, 'rb') as fh:
            magic = fh.read(16)
        if not magic.startswith(b'SQLite format 3\x00'):
            flash('Invalid file — not a valid SQLite database.', 'danger')
            return redirect(url_for('admin.settings'))

        # Full integrity check — catches partial uploads and bit-rot
        try:
            check = sqlite3.connect(tmp.name)
            result = check.execute('PRAGMA integrity_check(10)').fetchall()
            check.close()
            if result != [('ok',)]:
                problems = '; '.join(r[0] for r in result[:5])
                flash(f'Database file is corrupt (integrity_check failed): {problems}', 'danger')
                return redirect(url_for('admin.settings'))
        except sqlite3.DatabaseError as exc:
            flash(f'Database file is corrupt: {exc}', 'danger')
            return redirect(url_for('admin.settings'))

        if os.path.isfile(db_path):
            shutil.copy2(db_path, db_path + '.bak')

        from app.extensions import db as _db
        _db.session.remove()
        _db.engine.dispose()
        shutil.copy2(tmp.name, db_path)
        flash('Database imported successfully. Please restart the server.', 'success')
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass

    return redirect(url_for('admin.settings'))


# ── DB integrity check ────────────────────────────────────────────────────────

@admin_bp.route('/settings/db-integrity', methods=['POST'])
@admin_required
def db_integrity():
    """Run PRAGMA integrity_check on the live database and return results."""
    import sqlite3
    db_uri = current_app.config.get('SQLALCHEMY_DATABASE_URI', '')
    if 'sqlite' not in db_uri:
        return jsonify(ok=False, error='Only SQLite databases are supported.'), 400
    db_path = db_uri.replace('sqlite:///', '', 1)
    try:
        conn = sqlite3.connect(db_path)
        rows = conn.execute('PRAGMA integrity_check(50)').fetchall()
        conn.close()
        issues = [r[0] for r in rows]
        ok = issues == ['ok']
        return jsonify(ok=ok, issues=issues)
    except Exception as exc:
        return jsonify(ok=False, issues=[str(exc)]), 500


# ── Restore from .bak ─────────────────────────────────────────────────────────

@admin_bp.route('/settings/db-restore-bak', methods=['POST'])
@admin_required
def db_restore_bak():
    """Restore the database from the automatic .bak file created on last import."""
    import os
    import shutil
    import sqlite3
    db_uri = current_app.config.get('SQLALCHEMY_DATABASE_URI', '')
    if 'sqlite' not in db_uri:
        flash('Only SQLite databases are supported.', 'warning')
        return redirect(url_for('admin.settings'))
    db_path = db_uri.replace('sqlite:///', '', 1)
    bak_path = db_path + '.bak'
    if not os.path.isfile(bak_path):
        flash('No backup file (.bak) found. Cannot restore.', 'danger')
        return redirect(url_for('admin.settings'))

    # Validate the backup before restoring
    try:
        conn = sqlite3.connect(bak_path)
        result = conn.execute('PRAGMA integrity_check(10)').fetchall()
        conn.close()
        if result != [('ok',)]:
            problems = '; '.join(r[0] for r in result[:5])
            flash(f'Backup file is also corrupt and cannot be used: {problems}', 'danger')
            return redirect(url_for('admin.settings'))
    except Exception as exc:
        flash(f'Backup file is not a valid SQLite database: {exc}', 'danger')
        return redirect(url_for('admin.settings'))

    try:
        from app.extensions import db as _db
        _db.session.remove()
        _db.engine.dispose()
        # Save the current (broken) DB as .broken so nothing is lost
        if os.path.isfile(db_path):
            shutil.copy2(db_path, db_path + '.broken')
        shutil.copy2(bak_path, db_path)
        current_app.logger.warning('[db_restore_bak] Restored from .bak (admin: %s)', current_user.email)
        flash('Database restored from backup (.bak). Please restart the server.', 'success')
    except Exception as exc:
        current_app.logger.exception('[db_restore_bak] failed: %s', exc)
        flash(f'Restore failed: {exc}', 'danger')

    return redirect(url_for('admin.settings'))


# ── Factory reset (drop all tables, recreate, seed) ──────────────────────────

@admin_bp.route('/settings/db-reset', methods=['POST'])
@admin_required
def db_reset():
    """Drop all tables and recreate the database as a fresh deployment."""
    if request.form.get('confirm') != 'RESET':
        flash('Bestätigung fehlt — Zurücksetzen abgebrochen.', 'warning')
        return redirect(url_for('admin.settings'))

    try:
        from app.extensions import db as _db

        # Dispose open connections before drop
        _db.session.remove()
        _db.engine.dispose()

        _db.drop_all()
        _db.create_all()

        # Re-seed default data (agents, tasks, etc.)
        from deploy.seed import step_languages, step_tasks, step_admin, step_system_agents
        step_languages()
        step_tasks()
        step_system_agents()

        flash('Datenbank wurde zurückgesetzt. Bitte neu anmelden.', 'success')
    except Exception as exc:
        current_app.logger.exception('db_reset failed: %s', exc)
        flash(f'Fehler beim Zurücksetzen: {exc}', 'danger')

    # Force logout since all sessions are gone
    from flask_login import logout_user
    logout_user()
    return redirect(url_for('auth.login'))


# ── Broadcast notification ────────────────────────────────────────────────────

@admin_bp.route('/notify-all', methods=['POST'])
@admin_required
def notify_all():
    title = request.form.get('title', '').strip()
    message = request.form.get('message', '').strip()
    role_filter = request.form.get('role', '')

    if not title:
        flash('Titel erforderlich.', 'danger')
        return redirect(url_for('admin.dashboard'))

    query = User.query.filter_by(is_active=True)
    if role_filter:
        query = query.filter_by(role=role_filter)

    notifs = [
        Notification(user_id=u.id, title=title, message=message, notif_type='system')
        for u in query.all()
    ]
    db.session.bulk_save_objects(notifs)
    db.session.commit()
    flash(f'{len(notifs)} Benachrichtigungen gesendet.', 'success')
    return redirect(url_for('admin.dashboard'))


# ── API endpoints ─────────────────────────────────────────────────────────────

@admin_bp.route('/api/stats')
@tutor_or_admin_required
def api_stats():
    period = request.args.get('period', '30d')
    since = since_from_period(period)
    stats = global_stats(since)
    chart = chart_data_timeline(None, since, period)
    return jsonify({'stats': stats, 'chart': chart})


@admin_bp.route('/api/user-stats/<int:user_id>')
@tutor_or_admin_required
def api_user_stats(user_id: int):
    period = request.args.get('period', '30d')
    since = since_from_period(period)
    from app.utils.stats import user_stats
    stats = user_stats(user_id, since)
    chart = chart_data_timeline(user_id, since, period)
    return jsonify({'stats': stats, 'chart': chart})


# ── Admin Console — server log stream ────────────────────────────────────────

@admin_bp.route('/settings/logs')
@admin_required
def settings_logs():
    """Return buffered server log entries as JSON.

    Query parameters:
      after   — only return entries with id > this value (for polling)
      level   — filter by level name (INFO, WARNING, ERROR, CRITICAL); omit for all
      limit   — max entries to return (default 200, max 500)
    """
    from app import _log_buffer, _log_buffer_lock, _log_buffer_counter

    after = int(request.args.get('after', 0))
    level_filter = request.args.get('level', '').upper().strip()
    try:
        limit = min(int(request.args.get('limit', 200)), 500)
    except (TypeError, ValueError):
        limit = 200

    with _log_buffer_lock:
        entries = list(_log_buffer)
        latest_id = _log_buffer_counter

    if after:
        entries = [e for e in entries if e['id'] > after]
    if level_filter and level_filter != 'ALL':
        entries = [e for e in entries if e['level'] == level_filter]

    # Newest-first for the tail view; return at most `limit`
    entries = entries[-limit:]

    return jsonify(entries=entries, latest_id=latest_id)


# ── DB Inspector ──────────────────────────────────────────────────────────────

@admin_bp.route('/settings/db-inspector/tables')
@admin_required
def db_inspector_tables():
    """Return a list of all table names in the SQLite database."""
    import sqlite3
    db_uri = current_app.config.get('SQLALCHEMY_DATABASE_URI', '')
    if 'sqlite' not in db_uri:
        return jsonify(ok=False, error='Only SQLite databases are supported.'), 400
    db_path = db_uri.replace('sqlite:///', '', 1)
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = [row[0] for row in cur.fetchall()]
        conn.close()
        return jsonify(ok=True, tables=tables)
    except Exception as exc:
        current_app.logger.exception('[db_inspector_tables] %s', exc)
        return jsonify(ok=False, error=str(exc)), 500


@admin_bp.route('/settings/db-inspector/query', methods=['POST'])
@admin_required
def db_inspector_query():
    """Execute a read-only SELECT query and return rows + column names.

    Body (JSON):
      table   — table name to inspect  (used for PRAGMA / auto-query)
      sql     — optional custom SQL to run instead; must be a SELECT statement
      page    — page number (1-based, default 1)
      per_page — rows per page (default 50, max 200)
    """
    import sqlite3
    import re as _re

    data = request.get_json(force=True, silent=True) or {}
    table = (data.get('table') or '').strip()
    sql_raw = (data.get('sql') or '').strip()
    try:
        page = max(1, int(data.get('page', 1)))
        per_page = min(200, max(1, int(data.get('per_page', 50))))
    except (TypeError, ValueError):
        page, per_page = 1, 50

    db_uri = current_app.config.get('SQLALCHEMY_DATABASE_URI', '')
    if 'sqlite' not in db_uri:
        return jsonify(ok=False, error='Only SQLite databases are supported.'), 400
    db_path = db_uri.replace('sqlite:///', '', 1)

    if sql_raw:
        # Security: only allow SELECT statements
        stmt = sql_raw.lstrip()
        if not _re.match(r'(?i)\s*SELECT\b', stmt):
            return jsonify(ok=False, error='Only SELECT statements are allowed.'), 400
        # Strip trailing semicolons before adding LIMIT/OFFSET
        stmt = stmt.rstrip(';').strip()
        sql = f'{stmt} LIMIT {per_page} OFFSET {(page - 1) * per_page}'
        count_sql = f'SELECT COUNT(*) FROM ({stmt})'
    elif table:
        # Validate table name (alphanumeric + underscore only)
        if not _re.match(r'^[A-Za-z_][A-Za-z0-9_]*$', table):
            return jsonify(ok=False, error='Invalid table name.'), 400
        sql = f'SELECT * FROM "{table}" LIMIT {per_page} OFFSET {(page - 1) * per_page}'
        count_sql = f'SELECT COUNT(*) FROM "{table}"'
    else:
        return jsonify(ok=False, error='Provide table or sql.'), 400

    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row

        total = conn.execute(count_sql).fetchone()[0]

        cur = conn.execute(sql)
        cols = [d[0] for d in cur.description] if cur.description else []
        rows = [list(row) for row in cur.fetchall()]

        # PRAGMA for column info (only for single-table browse)
        schema_cols = []
        if table and not sql_raw:
            schema_cur = conn.execute(f'PRAGMA table_info("{table}")')
            schema_cols = [
                {'cid': r[0], 'name': r[1], 'type': r[2], 'notnull': r[3],
                 'dflt_value': r[4], 'pk': r[5]}
                for r in schema_cur.fetchall()
            ]

        conn.close()
        return jsonify(
            ok=True,
            columns=cols,
            rows=rows,
            total=total,
            page=page,
            per_page=per_page,
            schema=schema_cols,
        )
    except Exception as exc:
        current_app.logger.exception('[db_inspector_query] %s', exc)
        return jsonify(ok=False, error=str(exc)), 500


@admin_bp.route('/settings/db-inspector/update', methods=['POST'])
@admin_required
def db_inspector_update():
    """Update a single cell value in a table row.

    Body (JSON):
      table   — table name
      pk_col  — name of the primary key column
      pk_val  — value of the primary key
      col     — column to update
      value   — new value (string; cast happens in SQLite)
    """
    import sqlite3
    import re as _re

    data = request.get_json(force=True, silent=True) or {}
    table   = (data.get('table') or '').strip()
    pk_col  = (data.get('pk_col') or '').strip()
    pk_val  = data.get('pk_val')
    col     = (data.get('col') or '').strip()
    value   = data.get('value')

    # Validate identifiers
    ident_re = r'^[A-Za-z_][A-Za-z0-9_]*$'
    for ident in (table, pk_col, col):
        if not _re.match(ident_re, ident):
            return jsonify(ok=False, error=f'Invalid identifier: {ident!r}'), 400

    db_uri = current_app.config.get('SQLALCHEMY_DATABASE_URI', '')
    if 'sqlite' not in db_uri:
        return jsonify(ok=False, error='Only SQLite databases are supported.'), 400
    db_path = db_uri.replace('sqlite:///', '', 1)

    try:
        conn = sqlite3.connect(db_path)
        conn.execute(
            f'UPDATE "{table}" SET "{col}" = ? WHERE "{pk_col}" = ?',
            (value, pk_val),
        )
        conn.commit()
        conn.close()
        current_app.logger.info(
            '[db_inspector_update] %s.%s=%r where %s=%r (admin: %s)',
            table, col, value, pk_col, pk_val, current_user.email,
        )
        return jsonify(ok=True)
    except Exception as exc:
        current_app.logger.exception('[db_inspector_update] %s', exc)
        return jsonify(ok=False, error=str(exc)), 500


@admin_bp.route('/settings/db-inspector/insert-row', methods=['POST'])
@admin_required
def db_inspector_insert_row():
    """Insert a new row into a table.

    Body (JSON):
      table   — table name
      values  — dict of {column: value} (omit PK / auto-increment columns)
    """
    import sqlite3
    import re as _re

    data   = request.get_json(force=True, silent=True) or {}
    table  = (data.get('table') or '').strip()
    values = data.get('values') or {}

    ident_re = r'^[A-Za-z_][A-Za-z0-9_]*$'
    if not _re.match(ident_re, table):
        return jsonify(ok=False, error=f'Invalid table name: {table!r}'), 400
    for col in values:
        if not _re.match(ident_re, col):
            return jsonify(ok=False, error=f'Invalid column name: {col!r}'), 400
    if not values:
        return jsonify(ok=False, error='No values provided.'), 400

    db_uri = current_app.config.get('SQLALCHEMY_DATABASE_URI', '')
    if 'sqlite' not in db_uri:
        return jsonify(ok=False, error='Only SQLite databases are supported.'), 400
    db_path = db_uri.replace('sqlite:///', '', 1)

    try:
        cols_sql  = ', '.join(f'"{c}"' for c in values)
        placeholders = ', '.join('?' for _ in values)
        sql = f'INSERT INTO "{table}" ({cols_sql}) VALUES ({placeholders})'
        conn = sqlite3.connect(db_path)
        cur = conn.execute(sql, list(values.values()))
        new_id = cur.lastrowid
        conn.commit()
        conn.close()
        current_app.logger.info(
            '[db_inspector_insert] %s (new id=%s) (admin: %s)',
            table, new_id, current_user.email,
        )
        return jsonify(ok=True, new_id=new_id)
    except Exception as exc:
        current_app.logger.exception('[db_inspector_insert] %s', exc)
        return jsonify(ok=False, error=str(exc)), 500


@admin_bp.route('/settings/db-inspector/delete-row', methods=['POST'])
@admin_required
def db_inspector_delete_row():
    """Delete a single row identified by its primary key.

    Body (JSON):
      table   — table name
      pk_col  — primary key column name
      pk_val  — primary key value
    """
    import sqlite3
    import re as _re

    data = request.get_json(force=True, silent=True) or {}
    table  = (data.get('table') or '').strip()
    pk_col = (data.get('pk_col') or '').strip()
    pk_val = data.get('pk_val')

    ident_re = r'^[A-Za-z_][A-Za-z0-9_]*$'
    for ident in (table, pk_col):
        if not _re.match(ident_re, ident):
            return jsonify(ok=False, error=f'Invalid identifier: {ident!r}'), 400

    db_uri = current_app.config.get('SQLALCHEMY_DATABASE_URI', '')
    if 'sqlite' not in db_uri:
        return jsonify(ok=False, error='Only SQLite databases are supported.'), 400
    db_path = db_uri.replace('sqlite:///', '', 1)

    try:
        conn = sqlite3.connect(db_path)
        conn.execute(f'DELETE FROM "{table}" WHERE "{pk_col}" = ?', (pk_val,))
        conn.commit()
        conn.close()
        current_app.logger.warning(
            '[db_inspector_delete] %s where %s=%r (admin: %s)',
            table, pk_col, pk_val, current_user.email,
        )
        return jsonify(ok=True)
    except Exception as exc:
        current_app.logger.exception('[db_inspector_delete] %s', exc)
        return jsonify(ok=False, error=str(exc)), 500
