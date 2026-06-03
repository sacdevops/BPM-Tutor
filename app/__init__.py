"""BPM-Tutor — Application Factory."""
from __future__ import annotations

import os
import time

import config as _cfg
from flask import Flask

# ── Language-list in-process cache ───────────────────────────────────────────
# The active language list is read on every request (context processor) but
# changes very rarely.  A 60-second TTL avoids the repeated DB round-trip while
# keeping the cache fresh after admin edits.
_lang_cache_data: list = []
_lang_cache_ts: float = 0.0
_LANG_CACHE_TTL: float = 60.0  # seconds


def _get_active_languages() -> list:
    """Return the active Language rows, served from a 60-second process cache."""
    global _lang_cache_data, _lang_cache_ts
    now = time.monotonic()
    if _lang_cache_data and (now - _lang_cache_ts) < _LANG_CACHE_TTL:
        return _lang_cache_data
    try:
        from app.models.i18n import Language
        rows = Language.query.filter_by(is_active=True).order_by(Language.sort_order).all()
        _lang_cache_data = rows
        _lang_cache_ts = now
        return rows
    except Exception:
        return _lang_cache_data  # stale is better than empty


def invalidate_language_cache() -> None:
    """Force the next request to re-query the language list from DB."""
    global _lang_cache_ts
    _lang_cache_ts = 0.0


def create_app() -> Flask:
    """Create and configure the Flask application."""
    app = Flask(
        __name__,
        template_folder='templates',
        static_folder='static',
    )

    # Must be set before any extension that depends on sessions/CSRF/login.
    app.config['SECRET_KEY'] = _cfg.SECRET_KEY

    _configure_database(app)
    _configure_session_security(app)
    _init_extensions(app)
    _register_blueprints(app)
    _configure_rate_limiting(app)
    _configure_security(app)
    _register_i18n_middleware(app)
    _register_cli(app)
    _register_context_processors(app)
    _register_error_handlers(app)
    _setup_file_serving(app)

    return app


# ── Private helpers ───────────────────────────────────────────────────────────

_sqlite_pragmas_registered = False


def _register_sqlite_pragmas() -> None:
    """Register a one-time SQLAlchemy connect event that applies WAL mode and
    performance PRAGMAs to every new SQLite connection.

    WAL (Write-Ahead Logging) is the key setting for concurrent users:
    - Readers never block writers; writers never block readers.
    - Only one writer at a time — but with busy_timeout they queue safely.
    - synchronous=NORMAL is crash-safe and ~2× faster than the default FULL.
    - cache_size=-65536 keeps 64 MB of pages in memory (avoids disk I/O).
    - mmap_size=268435456 uses 256 MB memory-mapped I/O for read-heavy pages.
    """
    global _sqlite_pragmas_registered
    if _sqlite_pragmas_registered:
        return

    import sqlite3 as _sqlite3
    from sqlalchemy import event as _sa_event
    from sqlalchemy.engine import Engine as _Engine

    @_sa_event.listens_for(_Engine, 'connect')
    def _set_sqlite_pragmas(dbapi_conn, _record):
        if not isinstance(dbapi_conn, _sqlite3.Connection):
            return
        cursor = dbapi_conn.cursor()
        cursor.execute('PRAGMA journal_mode=WAL')
        cursor.execute('PRAGMA synchronous=NORMAL')
        cursor.execute('PRAGMA cache_size=-65536')    # 64 MB page cache
        cursor.execute('PRAGMA temp_store=MEMORY')
        cursor.execute('PRAGMA mmap_size=268435456')  # 256 MB mmap I/O
        cursor.execute('PRAGMA foreign_keys=ON')
        cursor.execute('PRAGMA wal_autocheckpoint=1000')
        cursor.close()

    _sqlite_pragmas_registered = True


def _configure_database(app: Flask) -> None:
    # Resolve the SQLite file path (DATABASE_URL env var overrides the default)
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    data_dir = os.path.join(base_dir, 'data')
    os.makedirs(data_dir, exist_ok=True)
    default_url = f'sqlite:///{os.path.join(data_dir, "bpmtutor.db")}'
    db_url = os.getenv('DATABASE_URL', default_url)

    app.config['SQLALCHEMY_DATABASE_URI'] = db_url
    if os.getenv('ROLE') == 'worker':
        # Celery worker: NullPool — connection opened/closed per-use.
        # With --concurrency=4 a full pool_size=20 per process would hold 80
        # idle file handles to the SQLite file between tasks. Workers execute
        # long-running LLM jobs, not rapid-fire queries, so pooling adds no
        # benefit and only wastes resources.
        from sqlalchemy.pool import NullPool
        app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
            'poolclass': NullPool,
            'connect_args': {
                'check_same_thread': False,
                'timeout': 30,
            },
        }
    else:
        # Web worker: gevent handles 200-300 users as greenlets in one process.
        # 20 base connections + 30 overflow covers all concurrent DB operations
        # comfortably; pool_timeout lets greenlets queue instead of crashing.
        app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
            'pool_pre_ping': True,
            'connect_args': {
                'check_same_thread': False,  # required for multi-threaded/gevent use
                'timeout': 30,               # seconds to wait when DB is locked
            },
            'pool_size': 20,
            'max_overflow': 30,
            'pool_timeout': 30,
            'pool_recycle': 600,
        }
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    # Register WAL-mode and performance PRAGMAs on every new SQLite connection.
    # WAL allows concurrent readers alongside a single writer, eliminating the
    # "database is locked" errors that would otherwise occur at 200+ users.
    _register_sqlite_pragmas()
    app.config.setdefault('MAIL_SERVER', os.getenv('MAIL_SERVER', 'localhost'))
    app.config.setdefault('MAIL_PORT', int(os.getenv('MAIL_PORT', 587)))
    app.config.setdefault('MAIL_USE_TLS', os.getenv('MAIL_USE_TLS', 'true').lower() == 'true')
    app.config.setdefault('MAIL_USERNAME', os.getenv('MAIL_USERNAME', ''))
    app.config.setdefault('MAIL_PASSWORD', os.getenv('MAIL_PASSWORD', ''))
    app.config.setdefault('MAIL_DEFAULT_SENDER', os.getenv('MAIL_DEFAULT_SENDER', 'noreply@bpmtutor.local'))
    # SMTP connection timeout — prevents daemon threads from hanging indefinitely
    app.config.setdefault('MAIL_TIMEOUT', int(os.getenv('MAIL_TIMEOUT', 30)))
    app.config.setdefault('WTF_CSRF_TIME_LIMIT', 3600)
    app.config.setdefault('MAX_CONTENT_LENGTH', 16 * 1024 * 1024)


def _configure_session_security(app: Flask) -> None:
    from datetime import timedelta
    app.config.setdefault('PERMANENT_SESSION_LIFETIME', timedelta(hours=12))
    app.config.setdefault('SESSION_COOKIE_HTTPONLY', True)
    app.config.setdefault('SESSION_COOKIE_SAMESITE', 'Lax')
    is_production = os.getenv('FLASK_ENV', 'development') == 'production'
    app.config.setdefault('SESSION_COOKIE_SECURE', is_production)
    app.config.setdefault('SESSION_COOKIE_NAME', 'bpmtutor_session')


def _init_extensions(app: Flask) -> None:
    from app.extensions import db, login_manager, mail, csrf
    db.init_app(app)
    login_manager.init_app(app)
    mail.init_app(app)
    csrf.init_app(app)

    from app.models.user import User

    @login_manager.user_loader
    def load_user(user_id: str):
        return db.session.get(User, int(user_id))

    with app.app_context():
        _create_tables_and_seed(app)


def _create_tables_and_seed(app: Flask) -> None:
    from app.extensions import db
    db.create_all()
    _run_column_migrations(db)
    from app.models.settings import Settings
    Settings.ensure_defaults()
    _apply_mail_settings(app)
    try:
        from app.utils.i18n_helper import seed_languages, warm_cache
        seed_languages()
        warm_cache()
    except Exception as exc:
        app.logger.warning('[App] i18n seed failed: %s', exc)


def _configure_rate_limiting(app: Flask) -> None:
    from app.extensions import limiter
    _redis_url = os.getenv('REDIS_URL', '')
    app.config['RATELIMIT_STORAGE_URI'] = _redis_url if _redis_url else 'memory://'
    app.config['RATELIMIT_STRATEGY'] = 'fixed-window'
    limiter.init_app(app)
    # Apply brute-force protection on all auth routes (login, register, reset)
    from app.blueprints.auth import auth_bp
    limiter.limit('20 per minute')(auth_bp)


def _configure_security(app: Flask) -> None:
    """Configure HTTP security headers via Flask-Talisman.

    CSP allows the external CDNs used by the task editor (bpmn-js, Socket.IO,
    Bootstrap) and preserves inline scripts required by the templates.
    HTTPS enforcement is disabled for local development.
    """
    from app.extensions import talisman

    force_https = os.getenv('FORCE_HTTPS', '').lower() in ('1', 'true', 'yes')

    csp = {
        'default-src': "'self'",
        'script-src': [
            "'self'",
            "'unsafe-inline'",   # Required for config JSON blocks in task.html
            'cdn.jsdelivr.net',
            'cdn.socket.io',
            'unpkg.com',
        ],
        'style-src': [
            "'self'",
            "'unsafe-inline'",
            'cdn.jsdelivr.net',
            'unpkg.com',
            'fonts.googleapis.com',
        ],
        'font-src': [
            "'self'",
            'data:',
            'cdn.jsdelivr.net',
            'unpkg.com',
            'fonts.gstatic.com',
        ],
        'img-src': ["'self'", 'data:', 'flagcdn.com', 'https:'],
        'connect-src': ["'self'", 'ws:', 'wss:'],
        'frame-ancestors': "'none'",
        'object-src': "'none'",
        'base-uri': "'self'",
    }

    talisman.init_app(
        app,
        force_https=force_https,
        strict_transport_security=force_https,
        strict_transport_security_max_age=31536000,
        frame_options='DENY',
        content_security_policy=csp,
        referrer_policy='strict-origin-when-cross-origin',
        content_security_policy_nonce_in=None,
    )


def _apply_mail_settings(app: Flask) -> None:
    """Load SMTP settings: DB value takes precedence, env variable is fallback."""
    from app.models.settings import Settings

    def _db_or_env(db_key, env_key, default=''):
        try:
            val = Settings.get(db_key, '')
            return val if val else os.environ.get(env_key, default)
        except Exception:
            return os.environ.get(env_key, default)

    try:
        server = _db_or_env(Settings.MAIL_SERVER, 'MAIL_SERVER')
        if server:
            app.config['MAIL_SERVER'] = server
            app.config['MAIL_PORT'] = int(_db_or_env(Settings.MAIL_PORT, 'MAIL_PORT', 587) or 587)
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
                use_tls = os.environ.get('MAIL_USE_TLS', 'true').lower() in ('1', 'true', 'yes')
                use_ssl = os.environ.get('MAIL_USE_SSL', 'false').lower() in ('1', 'true', 'yes')
            app.config['MAIL_USE_TLS'] = use_tls
            app.config['MAIL_USE_SSL'] = use_ssl
            app.config['MAIL_USERNAME'] = _db_or_env(Settings.MAIL_USERNAME, 'MAIL_USERNAME')
            from app.utils.crypto import decrypt_value as _dec_pw
            app.config['MAIL_PASSWORD'] = _dec_pw(_db_or_env(Settings.MAIL_PASSWORD, 'MAIL_PASSWORD'))
            app.config['MAIL_DEFAULT_SENDER'] = _db_or_env(
                Settings.MAIL_DEFAULT_SENDER, 'MAIL_DEFAULT_SENDER'
            )
            from app.extensions import mail
            mail.init_app(app)
            if not Settings.get(Settings.MAIL_SERVER, ''):
                _persist_env_mail_settings(server, app.config)
    except Exception:
        pass


def _persist_env_mail_settings(server: str, cfg) -> None:
    try:
        from app.models.settings import Settings
        from app.utils.crypto import encrypt_value as _enc_pw
        Settings.set_many({
            Settings.MAIL_SERVER:         server,
            Settings.MAIL_PORT:           str(cfg.get('MAIL_PORT', 587)),
            Settings.MAIL_USE_TLS:        cfg.get('MAIL_USE_TLS', True),
            Settings.MAIL_USE_SSL:        cfg.get('MAIL_USE_SSL', False),
            Settings.MAIL_USERNAME:       cfg.get('MAIL_USERNAME', ''),
            Settings.MAIL_PASSWORD:       (_enc_pw(cfg['MAIL_PASSWORD']) if cfg.get('MAIL_PASSWORD') else ''),
            Settings.MAIL_DEFAULT_SENDER: cfg.get('MAIL_DEFAULT_SENDER', ''),
            Settings.MAIL_ENABLED:        True,
        })
    except Exception:
        pass


def _run_column_migrations(db) -> None:
    """Add new columns to existing tables without dropping data."""
    migrations = [
        ("tasks", "extra_translations", "TEXT"),
        ("tasks", "time_limit_minutes", "INTEGER"),
        ("tasks", "hide_after_completion", "BOOLEAN NOT NULL DEFAULT 0"),
        ("task_submissions", "bpmn_draft", "TEXT"),
        ("task_submissions", "study_id", "INTEGER"),
        # AI agent mode flags
        ("ai_agents", "use_standard", "BOOLEAN NOT NULL DEFAULT 1"),
        ("ai_agents", "use_leveling", "BOOLEAN NOT NULL DEFAULT 0"),
        ("ai_agents", "use_research", "BOOLEAN NOT NULL DEFAULT 0"),
        # AI agent: system-agent lock and modeling mode
        ("ai_agents", "is_system", "BOOLEAN NOT NULL DEFAULT 0"),
        ("ai_agents", "modeling_mode", "VARCHAR(20) NOT NULL DEFAULT 'none'"),
        # Task: optional per-task agent override
        ("tasks", "agent_id", "VARCHAR(36)"),
        # Study question image path
        ("survey_questions", "image_path", "TEXT"),
        # Study: new columns
        ("studies", "is_archived", "BOOLEAN NOT NULL DEFAULT 0"),
        ("studies", "archived_at", "DATETIME"),
        ("studies", "is_template", "BOOLEAN NOT NULL DEFAULT 0"),
        ("studies", "cloned_from_id", "INTEGER"),
        ("studies", "require_consent", "BOOLEAN NOT NULL DEFAULT 0"),
        ("studies", "consent_text", "TEXT"),
        ("studies", "anonymize_export", "BOOLEAN NOT NULL DEFAULT 1"),
        ("studies", "study_design", "VARCHAR(20) NOT NULL DEFAULT 'within'"),
        ("studies", "enrollment_survey_id", "INTEGER"),
        # StudyStep: new columns
        ("study_steps", "wave_number", "INTEGER NOT NULL DEFAULT 0"),
        ("study_steps", "available_from", "DATETIME"),
        ("study_steps", "available_until", "DATETIME"),
        ("study_steps", "allow_late_submission", "BOOLEAN NOT NULL DEFAULT 0"),
        ("study_steps", "late_penalty_note", "VARCHAR(500)"),
        ("study_steps", "condition_id", "INTEGER"),
        # StudyCondition: AI agent per condition (between-subjects)
        ("study_conditions", "agent_id", "VARCHAR(36)"),
        # StudyStep: multi-condition assignment (JSON list)
        ("study_steps", "condition_ids", "TEXT"),
        # StudyParticipant: new columns
        ("study_participants", "consent_given_at", "DATETIME"),
        ("study_participants", "condition_id", "INTEGER"),
        ("study_participants", "dropped_out_at", "DATETIME"),
        ("study_participants", "dropout_reason", "VARCHAR(500)"),
        # Study: leaderboard + tracking
        ("studies", "leaderboard_enabled", "BOOLEAN NOT NULL DEFAULT 0"),
        ("studies", "tracking_config", "TEXT"),
        # User: leaderboard anonymization + notification email
        ("users", "leaderboard_anonymous", "BOOLEAN NOT NULL DEFAULT 0"),
        ("users", "email_notifications", "BOOLEAN NOT NULL DEFAULT 1"),
        # Task: mode
        ("tasks", "task_mode", "VARCHAR(20) NOT NULL DEFAULT 'standard'"),
        # Study: agent display name override
        ("studies", "agent_display_name", "VARCHAR(200)"),
    ]
    with db.engine.connect() as conn:
        from sqlalchemy import text, inspect
        inspector = inspect(db.engine)
        for table, column, col_type in migrations:
            try:
                if table not in inspector.get_table_names():
                    continue
                cols = [c['name'] for c in inspector.get_columns(table)]
                if column not in cols:
                    conn.execute(text(f'ALTER TABLE {table} ADD COLUMN {column} {col_type}'))
                    conn.commit()
            except Exception:
                try:
                    conn.rollback()
                except Exception:
                    pass
        # Rename legacy 'instructor' role to 'tutor'
        try:
            if 'users' in inspector.get_table_names():
                conn.execute(text("UPDATE users SET role='tutor' WHERE role='instructor'"))
                conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
        # Fix Supervisor agent control_mode: was accidentally seeded as 'shared'
        try:
            if 'ai_agents' in inspector.get_table_names():
                conn.execute(text(
                    "UPDATE ai_agents SET control_mode='agent' "
                    "WHERE agent_type='supervisor' AND control_mode='shared'"
                ))
                conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
    # Idempotent indexes — run on every startup, safe on existing DBs
    _index_ddl = [
        "CREATE INDEX IF NOT EXISTS ix_task_sub_user_task       ON task_submissions     (user_id, task_id)",
        "CREATE INDEX IF NOT EXISTS ix_task_sub_task_started    ON task_submissions     (task_id, started_at)",
        "CREATE INDEX IF NOT EXISTS ix_task_sub_completed       ON task_submissions     (completed_at)",
        "CREATE INDEX IF NOT EXISTS ix_study_part_study_user    ON study_participants   (study_id, user_id)",
        "CREATE INDEX IF NOT EXISTS ix_survey_resp_survey_user  ON survey_responses     (survey_id, user_id)",
        "CREATE INDEX IF NOT EXISTS ix_notifications_user_read  ON notifications        (user_id, is_read)",
    ]
    try:
        with db.engine.connect() as _ic:
            for _sql in _index_ddl:
                _ic.execute(text(_sql))
            _ic.commit()
    except Exception:
        pass


def _register_blueprints(app: Flask) -> None:
    from app.blueprints.auth import auth_bp
    from app.blueprints.admin import admin_bp
    from app.blueprints.user import user_bp
    from app.blueprints.survey import survey_bp
    from app.blueprints.main import main_bp
    from app.blueprints.study.routes import study_bp
    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(user_bp)
    app.register_blueprint(survey_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(study_bp)


def _register_i18n_middleware(app: Flask) -> None:
    from flask import g, request as flask_request

    @app.before_request
    def maintenance_gate():
        from flask import request as req
        # Allow static files, the maintenance page itself, auth routes, and admins
        if req.path.startswith('/static'):
            return
        if req.endpoint in ('main.maintenance', 'auth.login', 'auth.logout', None):
            return
        try:
            from app.models.settings import Settings
            if Settings.get(Settings.MAINTENANCE_MODE, False):
                from flask_login import current_user
                if not (current_user.is_authenticated and current_user.role == 'admin'):
                    from flask import redirect, url_for
                    return redirect(url_for('main.maintenance'))
        except Exception:
            pass

    @app.before_request
    def set_user_lang():
        lang = 'en'
        try:
            from flask_login import current_user
            # Cookie always takes priority (explicit selection in the frontend)
            cookie_lang = flask_request.cookies.get('bpmtutor_lang', '')
            if cookie_lang:
                lang = cookie_lang
            elif current_user.is_authenticated and current_user.language:
                lang = current_user.language
        except Exception:
            pass
        g.user_lang = lang

    from app.utils.i18n_helper import _t
    app.jinja_env.globals['_t'] = _t
    app.jinja_env.globals['_tl'] = _t


def _register_cli(app: Flask) -> None:
    import click

    @app.cli.command('create-admin')
    @click.option('--email', prompt='Admin E-Mail')
    @click.option('--username', prompt='Benutzername')
    @click.option('--password', prompt=True, hide_input=True, confirmation_prompt=True)
    def create_admin(email: str, username: str, password: str):
        from app.extensions import db
        from app.models.user import User
        if User.query.filter_by(email=email).first():
            click.echo('E-Mail bereits registriert.')
            return
        u = User(
            email=email, username=username, role='admin',
            is_active=True, is_verified=True, data_consent=True,
        )
        u.set_password(password)
        db.session.add(u)
        db.session.commit()
        click.echo(f'Admin {username} erstellt.')

    @app.cli.command('seed-tasks')
    def seed_tasks():
        from deploy.seed import step_tasks
        step_tasks()

    @app.cli.command('encrypt-api-keys')
    def encrypt_api_keys():
        from app.extensions import db
        from app.models.user import User
        from app.utils.crypto import encrypt_api_key
        count = 0
        for user in User.query.filter(User.personal_api_key.isnot(None)).all():
            if user.personal_api_key and not user.personal_api_key.startswith('enc:'):
                user.personal_api_key = encrypt_api_key(user.personal_api_key)
                count += 1
        db.session.commit()
        click.echo(f'Encrypted {count} API keys.')

    @app.cli.command('encrypt-settings')
    def encrypt_settings():
        """Migrate plaintext GLOBAL_API_KEY / MAIL_PASSWORD / MAIL_INCOMING_PASSWORD to encrypted form."""
        from app.models.settings import Settings
        from app.utils.crypto import encrypt_value as _enc
        count = 0
        for key in (Settings.GLOBAL_API_KEY, Settings.MAIL_PASSWORD, Settings.MAIL_INCOMING_PASSWORD):
            val = Settings.get(key, '') or ''
            if val and not str(val).startswith('enc:'):
                Settings.set(key, _enc(str(val)))
                count += 1
        click.echo(f'Encrypted {count} sensitive setting(s).')

    @app.cli.command('backup-db')
    def backup_db():
        """Create a timestamped backup of the SQLite database (safe to run while app is live)."""
        import shutil
        from datetime import datetime as _dt
        db_uri = app.config.get('SQLALCHEMY_DATABASE_URI', '')
        if 'sqlite' not in db_uri:
            click.echo('backup-db requires a SQLite database.')
            return
        db_path = db_uri.replace('sqlite:///', '')
        if not os.path.exists(db_path):
            click.echo(f'Database not found: {db_path}')
            return
        backup_dir = os.path.join(os.path.dirname(db_path), 'backups')
        os.makedirs(backup_dir, exist_ok=True)
        ts = _dt.now().strftime('%Y%m%d_%H%M%S')
        dest = os.path.join(backup_dir, f'bpmtutor_{ts}.db')
        # Use SQLite's online backup API via a second connection for consistency
        try:
            import sqlite3
            src_conn = sqlite3.connect(db_path)
            dst_conn = sqlite3.connect(dest)
            src_conn.backup(dst_conn)
            src_conn.close()
            dst_conn.close()
        except Exception:
            shutil.copy2(db_path, dest)
        click.echo(f'Backup created: {dest}')
        # Keep last 30 backups, prune older ones
        all_backups = sorted(
            [os.path.join(backup_dir, f) for f in os.listdir(backup_dir) if f.endswith('.db')]
        )
        for old in all_backups[:-30]:
            os.remove(old)
            click.echo(f'Pruned old backup: {old}')

    @app.cli.command('study-notifications')
    def study_notifications():
        """Send pending study lifecycle emails (enrollment open, wave unlock, reminders)."""
        try:
            from app.tasks.study_tasks import run_study_notifications
            sent = run_study_notifications()
            click.echo(f'Sent {sent} study notification(s).')
        except Exception as exc:
            click.echo(f'Error: {exc}', err=True)


def _register_context_processors(app: Flask) -> None:
    # Maps language code → ISO 3166-1 alpha-2 country code for flagcdn.com
    _LANG_TO_CC = {
        'de': 'de', 'en': 'gb', 'fr': 'fr', 'es': 'es', 'it': 'it',
        'pt': 'pt', 'nl': 'nl', 'pl': 'pl', 'ru': 'ru', 'zh': 'cn',
        'ja': 'jp', 'ko': 'kr', 'ar': 'sa', 'tr': 'tr', 'sv': 'se',
        'da': 'dk', 'fi': 'fi', 'nb': 'no', 'cs': 'cz', 'sk': 'sk',
        'hu': 'hu', 'ro': 'ro', 'uk': 'ua', 'el': 'gr', 'bg': 'bg',
        'hr': 'hr', 'sr': 'rs', 'us': 'us', 'gb': 'gb',
    }
    # Keep emoji map for backward compat / text-only contexts
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

    @app.template_global()
    def flag_img_for_lang(code: str, size: str = '20x15') -> str:
        """Return an <img> HTML tag for the country flag via flagcdn.com."""
        from markupsafe import Markup
        cc = _LANG_TO_CC.get((code or '').lower(), '')
        if not cc:
            return Markup('')
        url = f'https://flagcdn.com/{size}/{cc}.png'
        return Markup(
            f'<img src="{url}" alt="{code.upper()}" '
            f'class="lang-flag-img" width="{size.split("x")[0]}" '
            f'height="{size.split("x")[1]}" '
            f'onerror="this.style.display=\'none\'">'
        )

    @app.context_processor
    def app_globals():
        from flask import g
        from flask_login import current_user
        from app.models.settings import Settings
        import re as _re

        auth_required = Settings.get(Settings.AUTH_REQUIRED)
        user_lang = getattr(g, 'user_lang', 'en')
        if user_lang == 'en':
            site_name = Settings.get(Settings.SITE_NAME, 'BPM-Tutor')
        else:
            site_name = (Settings.get(f'site_name_{user_lang}') or
                         Settings.get(Settings.SITE_NAME, 'BPM-Tutor'))

        unread_count = 0
        if current_user.is_authenticated:
            from app.extensions import db
            from app.models.notification import Notification
            from sqlalchemy import func
            unread_count = (
                db.session.query(func.count(Notification.id))
                .filter(Notification.user_id == current_user.id, Notification.is_read == False)  # noqa: E712
                .scalar()
            ) or 0

        active_languages = []
        try:
            active_languages = _get_active_languages()
        except Exception:
            pass

        _hex_re = _re.compile(r'^#[0-9a-fA-F]{3,8}$')
        raw_primary = Settings.get(Settings.BRAND_PRIMARY, '#84BD00')
        raw_sidebar = Settings.get(Settings.BRAND_SIDEBAR_BG, '#162700')
        brand_primary = raw_primary if _hex_re.match(str(raw_primary)) else '#84BD00'
        brand_sidebar_bg = raw_sidebar if _hex_re.match(str(raw_sidebar)) else '#162700'

        brand_logo_data = (Settings.get(Settings.BRAND_LOGO_DATA, '') or '').strip()
        brand_logo_url = (Settings.get(Settings.BRAND_LOGO_URL, '') or '').strip()
        if brand_logo_data:
            brand_logo_src = '/brand/logo'
        elif brand_logo_url:
            brand_logo_src = brand_logo_url
        else:
            brand_logo_src = ''

        brand_logo_link = Settings.get(Settings.BRAND_LOGO_LINK, '/')
        site_tagline = Settings.get(Settings.SITE_TAGLINE, 'BPMN Modeling Learning Environment')
        site_tagline_de = Settings.get(Settings.SITE_TAGLINE_DE, 'BPMN-Modellierungs-Lernumgebung')
        allow_reg = Settings.get(Settings.ALLOW_REGISTRATION, True)
        level_system_enabled = Settings.get(Settings.LEVEL_SYSTEM_ENABLED, False)
        research_mode_enabled = Settings.get(Settings.RESEARCH_MODE_ENABLED, False)
        cohorts_enabled = Settings.get(Settings.COHORTS_ENABLED, True)

        return {
            'cms_auth_required': auth_required, 'cms_site_name': site_name,
            'cms_unread_count': unread_count, 'cms_active_languages': active_languages,
            'cms_user_lang': user_lang,
            'brand_primary': brand_primary, 'brand_sidebar_bg': brand_sidebar_bg,
            'brand_logo_src': brand_logo_src, 'brand_logo_url': brand_logo_url,
            'brand_logo_link': brand_logo_link, 'site_name': site_name,
            'site_tagline': site_tagline, 'site_tagline_de': site_tagline_de,
            'allow_registration': allow_reg,
            'level_system_enabled': level_system_enabled,
            'research_mode_enabled': research_mode_enabled,
            'cohorts_enabled': cohorts_enabled,
        }


def _register_error_handlers(app: Flask) -> None:
    @app.errorhandler(403)
    def forbidden(e):
        from flask import render_template
        return render_template('cms/errors/403.html'), 403

    @app.errorhandler(404)
    def not_found(e):
        from flask import render_template
        return render_template('cms/errors/404.html'), 404


def _setup_file_serving(app: Flask) -> None:
    from flask import send_from_directory
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    @app.route('/data-uploads/<path:filename>')
    def serve_upload(filename: str):
        return send_from_directory(os.path.join(base_dir, 'data'), filename)
