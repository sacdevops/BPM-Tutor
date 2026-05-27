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
            Settings.RESEARCH_MODE_ENABLED: bool(request.form.get('research_mode_enabled')),
            Settings.MAINTENANCE_MODE: bool(request.form.get('maintenance_mode')),
            Settings.API_KEY_MODE: request.form.get('api_key_mode', 'per_user'),
            Settings.GLOBAL_API_KEY: request.form.get('global_api_key', '').strip(),
            Settings.API_ENDPOINT: request.form.get('api_endpoint', '').strip(),
            Settings.DEFAULT_MODEL: request.form.get('default_model', '').strip(),
            Settings.FEEDBACK_EMAIL: request.form.get('feedback_email', '').strip(),
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
        }

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
        _SENSITIVE = (Settings.GLOBAL_API_KEY, Settings.MAIL_PASSWORD, Settings.MAIL_INCOMING_PASSWORD)
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
        flash('Einstellungen gespeichert.', 'success')
        return redirect(url_for('admin.settings'))

    current_settings = {
        row.key: Settings._cast(row.value, row.value_type)
        for row in SystemSetting.query.all()
    }
    # Keys that exist in the DB (even if value is empty string)
    _db_keys = {row.key for row in SystemSetting.query.all()}
    # Decrypt sensitive values for display so the form doesn't show cipher text
    from app.utils.crypto import decrypt_value as _dec
    for _key in (Settings.GLOBAL_API_KEY, Settings.MAIL_PASSWORD, Settings.MAIL_INCOMING_PASSWORD):
        if _key in current_settings:
            current_settings[_key] = _dec(str(current_settings[_key] or ''))
    reg_fields = RegistrationField.query.order_by(RegistrationField.sort_order).all()
    reg_fields_data = [
        {'name': f.name, 'label': f.label, 'label_de': f.label_de or '',
         'field_type': f.field_type, 'required': f.required,
         'options': f.options or []}
        for f in reg_fields
    ]
    return render_template('cms/admin/settings.html', s=current_settings, Settings=Settings,
                           active_languages=active_languages,
                           reg_fields_data=reg_fields_data,
                           db_keys=_db_keys,
                           bpmn_standards_default=__import__('app.services.prompts', fromlist=['BPMN_STANDARDS']).BPMN_STANDARDS,
                           bpmn_elements_default=__import__('app.services.prompts', fromlist=['BPMN_ELEMENTS_REFERENCE']).BPMN_ELEMENTS_REFERENCE)


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

        try:
            check = sqlite3.connect(tmp.name)
            check.execute('SELECT name FROM sqlite_master LIMIT 1').fetchall()
            check.close()
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
