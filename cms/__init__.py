"""
CMS factory — initialises all extensions, registers blueprints and CLI commands.
"""
from __future__ import annotations
import os
from datetime import timedelta


def init_cms(app) -> None:
    _configure_database(app)
    _configure_session_security(app)
    _init_extensions(app)
    _register_blueprints(app)
    _register_i18n_middleware(app)
    _register_cli(app)
    _register_context_processors(app)
    _register_error_handlers(app)
    _setup_file_serving(app)


def _configure_database(app) -> None:
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    data_dir = os.path.join(base_dir, 'data')
    os.makedirs(data_dir, exist_ok=True)
    db_path = os.path.join(data_dir, 'bpmtutor.db')
    app.config.setdefault('SQLALCHEMY_DATABASE_URI', f'sqlite:///{db_path}')
    app.config.setdefault('SQLALCHEMY_TRACK_MODIFICATIONS', False)
    app.config.setdefault('SQLALCHEMY_ENGINE_OPTIONS', {
        'pool_pre_ping': True, 'connect_args': {'check_same_thread': False},
    })
    app.config.setdefault('MAIL_SERVER', os.getenv('MAIL_SERVER', 'localhost'))
    app.config.setdefault('MAIL_PORT', int(os.getenv('MAIL_PORT', 587)))
    app.config.setdefault('MAIL_USE_TLS', os.getenv('MAIL_USE_TLS', 'true').lower() == 'true')
    app.config.setdefault('MAIL_USERNAME', os.getenv('MAIL_USERNAME', ''))
    app.config.setdefault('MAIL_PASSWORD', os.getenv('MAIL_PASSWORD', ''))
    app.config.setdefault('MAIL_DEFAULT_SENDER', os.getenv('MAIL_DEFAULT_SENDER', 'noreply@bpmtutor.local'))
    app.config.setdefault('WTF_CSRF_TIME_LIMIT', 3600)
    app.config.setdefault('MAX_CONTENT_LENGTH', 16 * 1024 * 1024)


def _configure_session_security(app) -> None:
    app.config.setdefault('PERMANENT_SESSION_LIFETIME', timedelta(hours=12))
    app.config.setdefault('SESSION_COOKIE_HTTPONLY', True)
    app.config.setdefault('SESSION_COOKIE_SAMESITE', 'Lax')
    is_production = os.getenv('FLASK_ENV', 'development') == 'production'
    app.config.setdefault('SESSION_COOKIE_SECURE', is_production)
    app.config.setdefault('SESSION_COOKIE_NAME', 'bpmtutor_session')


def _init_extensions(app) -> None:
    from cms.extensions import db, login_manager, mail, migrate, csrf
    db.init_app(app); login_manager.init_app(app); mail.init_app(app)
    migrate.init_app(app, db); csrf.init_app(app)
    from cms.models.user import User
    @login_manager.user_loader
    def load_user(user_id: str):
        return User.query.get(int(user_id))
    with app.app_context():
        _create_tables_and_seed(app)


def _create_tables_and_seed(app) -> None:
    from cms.extensions import db
    db.create_all()
    # Run incremental column migrations for new columns added to existing tables
    _run_column_migrations(db)
    from cms.models.settings import Settings
    Settings.ensure_defaults()
    # Apply DB mail settings to app.config so Flask-Mail uses them immediately
    _apply_mail_settings(app)
    from cms.utils.seeder import seed_tasks_from_config, create_default_admin
    n = seed_tasks_from_config()
    if n: app.logger.info('[CMS] Seeded %d tasks from config.TASKS', n)
    created = create_default_admin()
    if created: app.logger.warning('[CMS] Default admin created — change the password!')
    try:
        from cms.utils.i18n_helper import seed_languages, warm_cache
        seed_languages(); warm_cache()
    except Exception as exc:
        app.logger.warning('[CMS] i18n seed failed: %s', exc)


def _apply_mail_settings(app) -> None:
    """Load SMTP settings: DB value takes precedence, env variable is fallback.
    This ensures Railway / Docker deployments work without a pre-populated DB."""
    import os
    from cms.models.settings import Settings

    def _db_or_env(db_key, env_key, default=''):
        """Return DB value if non-empty, otherwise the env variable, otherwise default."""
        try:
            val = Settings.get(db_key, '')
            return val if val else os.environ.get(env_key, default)
        except Exception:
            return os.environ.get(env_key, default)

    try:
        server = _db_or_env(Settings.MAIL_SERVER, 'MAIL_SERVER')
        if server:
            app.config['MAIL_SERVER']  = server
            app.config['MAIL_PORT']    = int(_db_or_env(Settings.MAIL_PORT, 'MAIL_PORT', 587) or 587)
            # Encryption: env var MAIL_ENCRYPTION accepts 'ssl', 'starttls', or 'none'
            enc = os.environ.get('MAIL_ENCRYPTION', '').lower()
            use_tls = bool(Settings.get(Settings.MAIL_USE_TLS, ''))
            use_ssl = bool(Settings.get(Settings.MAIL_USE_SSL, ''))
            if enc == 'ssl':
                use_tls, use_ssl = False, True
            elif enc == 'starttls':
                use_tls, use_ssl = True, False
            elif enc == 'none':
                use_tls, use_ssl = False, False
            elif not Settings.get(Settings.MAIL_SERVER, ''):
                # No DB setting → derive from env booleans
                use_tls = os.environ.get('MAIL_USE_TLS', 'true').lower() in ('1', 'true', 'yes')
                use_ssl = os.environ.get('MAIL_USE_SSL', 'false').lower() in ('1', 'true', 'yes')
            app.config['MAIL_USE_TLS'] = use_tls
            app.config['MAIL_USE_SSL'] = use_ssl
            app.config['MAIL_USERNAME']       = _db_or_env(Settings.MAIL_USERNAME, 'MAIL_USERNAME')
            app.config['MAIL_PASSWORD']       = _db_or_env(Settings.MAIL_PASSWORD, 'MAIL_PASSWORD')
            app.config['MAIL_DEFAULT_SENDER'] = _db_or_env(Settings.MAIL_DEFAULT_SENDER,
                                                            'MAIL_DEFAULT_SENDER')
            # Re-initialise Flask-Mail so it picks up the updated config immediately
            from cms.extensions import mail
            mail.init_app(app)
            # Persist env-sourced values into DB so the settings UI shows them
            if not Settings.get(Settings.MAIL_SERVER, ''):
                _persist_env_mail_settings(server, app.config)
    except Exception:
        pass  # DB may not be ready yet; settings form will apply on save


def _persist_env_mail_settings(server, cfg) -> None:
    """Write env-sourced mail settings into the DB on first startup."""
    try:
        from cms.models.settings import Settings
        Settings.set_many({
            Settings.MAIL_SERVER:         server,
            Settings.MAIL_PORT:           str(cfg.get('MAIL_PORT', 587)),
            Settings.MAIL_USE_TLS:        cfg.get('MAIL_USE_TLS', True),
            Settings.MAIL_USE_SSL:        cfg.get('MAIL_USE_SSL', False),
            Settings.MAIL_USERNAME:       cfg.get('MAIL_USERNAME', ''),
            Settings.MAIL_PASSWORD:       cfg.get('MAIL_PASSWORD', ''),
            Settings.MAIL_DEFAULT_SENDER: cfg.get('MAIL_DEFAULT_SENDER', ''),
            Settings.MAIL_ENABLED:        True,
        })
    except Exception:
        pass


def _run_column_migrations(db) -> None:
    """Add new columns to existing tables that SQLite won't auto-create via create_all."""
    with db.engine.connect() as conn:
        migrations = [
            ("tasks", "extra_translations", "ALTER TABLE tasks ADD COLUMN extra_translations TEXT"),
        ]
        for table, column, sql in migrations:
            try:
                from sqlalchemy import text, inspect
                inspector = inspect(db.engine)
                cols = [c['name'] for c in inspector.get_columns(table)]
                if column not in cols:
                    conn.execute(text(sql))
                    conn.commit()
            except Exception:
                pass  # column may already exist or table doesn't exist yet


def _register_blueprints(app) -> None:
    from cms.blueprints.auth import auth_bp
    from cms.blueprints.admin import admin_bp
    from cms.blueprints.user import user_bp
    from cms.blueprints.survey import survey_bp
    app.register_blueprint(auth_bp); app.register_blueprint(admin_bp)
    app.register_blueprint(user_bp); app.register_blueprint(survey_bp)


def _register_i18n_middleware(app) -> None:
    from flask import g, request as flask_request
    @app.before_request
    def set_user_lang():
        lang = 'en'
        try:
            from flask_login import current_user
            if current_user.is_authenticated and current_user.language:
                lang = current_user.language
            else:
                lang = flask_request.cookies.get('bpmtutor_lang', 'en')
        except Exception:
            pass
        g.user_lang = lang
    from cms.utils.i18n_helper import _t
    app.jinja_env.globals['_t'] = _t
    app.jinja_env.globals['_tl'] = _t


def _register_cli(app) -> None:
    import click
    @app.cli.command('create-admin')
    @click.option('--email', prompt='Admin E-Mail')
    @click.option('--username', prompt='Benutzername')
    @click.option('--password', prompt=True, hide_input=True, confirmation_prompt=True)
    def create_admin(email: str, username: str, password: str):
        from cms.extensions import db; from cms.models.user import User
        if User.query.filter_by(email=email).first():
            click.echo('E-Mail bereits registriert.'); return
        u = User(email=email, username=username, role='admin', is_active=True, is_verified=True, data_consent=True)
        u.set_password(password); db.session.add(u); db.session.commit()
        click.echo(f'Admin {username} erstellt.')
    @app.cli.command('seed-tasks')
    def seed_tasks():
        from cms.utils.seeder import seed_tasks_from_config
        click.echo(f'{seed_tasks_from_config()} tasks seeded.')
    @app.cli.command('encrypt-api-keys')
    def encrypt_api_keys():
        from cms.extensions import db; from cms.models.user import User
        from cms.utils.crypto import encrypt_api_key
        count = 0
        for user in User.query.filter(User.personal_api_key.isnot(None)).all():
            if user.personal_api_key and not user.personal_api_key.startswith('enc:'):
                user.personal_api_key = encrypt_api_key(user.personal_api_key); count += 1
        db.session.commit(); click.echo(f'Encrypted {count} API keys.')


def _register_context_processors(app) -> None:
    # Flag emoji lookup for language codes (ISO 639-1 → country flag)
    _FLAG_MAP = {
        'de': '🇩🇪', 'en': '🇬🇧', 'fr': '🇫🇷', 'es': '🇪🇸', 'it': '🇮🇹',
        'pt': '🇵🇹', 'nl': '🇳🇱', 'pl': '🇵🇱', 'ru': '🇷🇺', 'zh': '🇨🇳',
        'ja': '🇯🇵', 'ko': '🇰🇷', 'ar': '🇸🇦', 'tr': '🇹🇷', 'sv': '🇸🇪',
        'da': '🇩🇰', 'fi': '🇫🇮', 'nb': '🇳🇴', 'cs': '🇨🇿', 'sk': '🇸🇰',
        'hu': '🇭🇺', 'ro': '🇷🇴', 'uk': '🇺🇦', 'el': '🇬🇷', 'bg': '🇧🇬',
        'hr': '🇭🇷', 'sr': '🇷🇸', 'us': '🇺🇸', 'gb': '🇬🇧',
    }

    @app.template_global()
    def flag_for_lang(code: str) -> str:
        """Return flag emoji for a language/country code, or '' if unknown."""
        return _FLAG_MAP.get((code or '').lower(), '')

    @app.context_processor
    def cms_globals():
        from flask import g
        from flask_login import current_user
        from cms.models.settings import Settings
        import re as _re

        auth_required = Settings.get(Settings.AUTH_REQUIRED)
        # Language-aware site name: try site_name_{lang}, fall back to English
        user_lang = getattr(g, 'user_lang', 'en')
        if user_lang == 'en':
            site_name = Settings.get(Settings.SITE_NAME, 'BPM-Tutor')
        else:
            site_name = (Settings.get(f'site_name_{user_lang}') or
                         Settings.get(Settings.SITE_NAME, 'BPM-Tutor'))

        unread_count = 0
        if current_user.is_authenticated:
            unread_count = current_user.unread_notifications_count

        active_languages = []
        try:
            from cms.models.i18n import Language
            active_languages = Language.query.filter_by(is_active=True).order_by(Language.sort_order).all()
        except Exception:
            pass

        _hex_re = _re.compile(r'^#[0-9a-fA-F]{3,8}$')
        raw_primary = Settings.get(Settings.BRAND_PRIMARY, '#84BD00')
        raw_sidebar = Settings.get(Settings.BRAND_SIDEBAR_BG, '#162700')
        brand_primary = raw_primary if _hex_re.match(str(raw_primary)) else '#84BD00'
        brand_sidebar_bg = raw_sidebar if _hex_re.match(str(raw_sidebar)) else '#162700'

        brand_logo_data = Settings.get(Settings.BRAND_LOGO_DATA, '')
        brand_logo_url = Settings.get(Settings.BRAND_LOGO_URL, '')
        brand_logo_mime = Settings.get(Settings.BRAND_LOGO_MIME, 'image/png')
        if brand_logo_data:
            brand_logo_src = f'data:{brand_logo_mime};base64,{brand_logo_data}'
        elif brand_logo_url:
            brand_logo_src = brand_logo_url
        else:
            brand_logo_src = ''

        brand_logo_link = Settings.get(Settings.BRAND_LOGO_LINK, '/')
        site_tagline = Settings.get(Settings.SITE_TAGLINE, 'BPMN Modeling Learning Environment')
        site_tagline_de = Settings.get(Settings.SITE_TAGLINE_DE, 'BPMN-Modellierungs-Lernumgebung')
        allow_reg = Settings.get(Settings.ALLOW_REGISTRATION, True)
        level_system_enabled = Settings.get(Settings.LEVEL_SYSTEM_ENABLED, False)

        return {
            'cms_auth_required': auth_required, 'cms_site_name': site_name,
            'cms_unread_count': unread_count, 'cms_active_languages': active_languages,
            'cms_user_lang': getattr(g, 'user_lang', 'en'),
            'brand_primary': brand_primary, 'brand_sidebar_bg': brand_sidebar_bg,
            'brand_logo_src': brand_logo_src, 'brand_logo_url': brand_logo_url,
            'brand_logo_link': brand_logo_link, 'site_name': site_name,
            'site_tagline': site_tagline, 'site_tagline_de': site_tagline_de,
            'allow_registration': allow_reg,
            'level_system_enabled': level_system_enabled,
        }


def _register_error_handlers(app) -> None:
    @app.errorhandler(403)
    def forbidden(e):
        from flask import render_template
        return render_template('cms/errors/403.html'), 403
    @app.errorhandler(404)
    def not_found(e):
        from flask import render_template
        return render_template('cms/errors/404.html'), 404


def _setup_file_serving(app) -> None:
    import os; from flask import send_from_directory
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    @app.route('/data-uploads/<path:filename>')
    def serve_upload(filename: str):
        return send_from_directory(os.path.join(base_dir, 'data'), filename)
