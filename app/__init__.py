"""BPM-Tutor — Application Factory."""
from __future__ import annotations

import collections
import logging
import os
import threading
import time

import config as _cfg
from flask import Flask

# ── In-memory log buffer (used by the Admin Console tab) ─────────────────────
# A circular deque of the last 1 000 log records, protected by a lock.
# Each entry is a plain dict with keys: id, ts, level, name, msg.
_log_buffer: collections.deque = collections.deque(maxlen=10000)
_log_buffer_lock: threading.Lock = threading.Lock()
_log_buffer_counter: int = 0  # monotonically increasing record id


class _MemoryLogHandler(logging.Handler):
    """Thread-safe in-memory log handler — stores recent records in _log_buffer."""

    def emit(self, record: logging.LogRecord) -> None:
        global _log_buffer_counter
        try:
            msg = self.format(record)
            entry = {
                'id': 0,          # filled in below under the lock
                'ts': record.created,
                'level': record.levelname,
                'name': record.name,
                'msg': msg,
            }
            with _log_buffer_lock:
                _log_buffer_counter += 1
                entry['id'] = _log_buffer_counter
                _log_buffer.append(entry)
        except Exception:
            self.handleError(record)


# Language-list in-process cache ──────────────────────────────────────────────
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
    _setup_memory_log_handler(app)

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
    # 512 MB — allows large DB imports via the admin panel.
    # nginx is also configured to client_max_body_size 512M.
    app.config.setdefault('MAX_CONTENT_LENGTH', 512 * 1024 * 1024)


def _configure_session_security(app: Flask) -> None:
    from datetime import timedelta
    app.config.setdefault('PERMANENT_SESSION_LIFETIME', timedelta(hours=12))
    app.config.setdefault('SESSION_COOKIE_HTTPONLY', True)
    app.config.setdefault('SESSION_COOKIE_SAMESITE', 'Lax')
    is_production = os.getenv('FLASK_ENV', 'development') == 'production'
    app.config.setdefault('SESSION_COOKIE_SECURE', is_production)
    app.config.setdefault('SESSION_COOKIE_NAME', 'bpmtutor_session')
    # Remember-me cookie — must be configured explicitly so the cookie persists
    # across browser restarts and survives after the session cookie expires.
    app.config.setdefault('REMEMBER_COOKIE_DURATION', timedelta(days=30))
    app.config.setdefault('REMEMBER_COOKIE_HTTPONLY', True)
    app.config.setdefault('REMEMBER_COOKIE_SAMESITE', 'Lax')
    app.config.setdefault('REMEMBER_COOKIE_SECURE', is_production)
    app.config.setdefault('REMEMBER_COOKIE_NAME', 'bpmtutor_remember')


def _init_extensions(app: Flask) -> None:
    from app.extensions import db, login_manager, mail, csrf
    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)

    from app.models.user import User

    @login_manager.user_loader
    def load_user(user_id: str):
        return db.session.get(User, int(user_id))

    with app.app_context():
        _create_tables_and_seed(app)

    # Initialize Flask-Mail AFTER _create_tables_and_seed has applied DB mail
    # settings into app.config via _apply_mail_settings.  Calling init_app here
    # (outside the app-context block) ensures the final, DB-backed config is
    # used even when the in-context call inside _apply_mail_settings fails.
    mail.init_app(app)


def _create_tables_and_seed(flask_app: Flask) -> None:
    # Import ALL models before db.create_all() so every table is registered
    # in db.metadata — otherwise tables added in newer code would be missed.
    # NOTE: 'import app.models' would shadow the local 'flask_app' parameter if
    # that parameter were named 'app', so we use 'flask_app' throughout.
    import app.models  # noqa: F401 — side-effect import registers all ORM classes
    from app.extensions import db
    db.create_all()
    _run_column_migrations(db)
    from app.models.settings import Settings
    Settings.ensure_defaults()
    _apply_mail_settings(flask_app)
    try:
        from app.utils.i18n_helper import seed_languages, warm_cache
        seed_languages()
        warm_cache()
    except Exception as exc:
        flask_app.logger.warning('[App] i18n seed failed: %s', exc)

    try:
        from deploy.seed import step_tasks, step_admin, step_system_agents
        step_tasks()
        step_admin()
        step_system_agents()
    except Exception as exc:
        flask_app.logger.warning('[App] Deployment seed failed: %s', exc)


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
    """Load SMTP settings from DB into app.config (DB takes precedence over env).

    Each setting is read individually with a safe fallback so that a transient
    DB error on one value never prevents the rest from being applied.
    Flask-Mail is then (re-)initialized with the resulting config.
    """
    import logging
    _log = logging.getLogger('bpmtutor')

    try:
        from app.models.settings import Settings
    except Exception as exc:  # noqa: BLE001
        _log.warning('[App] mail setup skipped — import error: %s', exc)
        return

    def _safe(key, fallback):
        """Read one setting from DB; return *fallback* on any error."""
        try:
            v = Settings.get(key, fallback)
            return v if v is not None else fallback
        except Exception:  # noqa: BLE001
            return fallback

    def _db_or_env(db_key, env_key, default=''):
        val = _safe(db_key, '')
        return val if val else os.environ.get(env_key, default)

    # Read every value independently so one failure never blocks the others.
    server   = _db_or_env(Settings.MAIL_SERVER,         'MAIL_SERVER')
    if not server:
        return  # No mail server configured — nothing to apply.

    try:
        port = int(_db_or_env(Settings.MAIL_PORT, 'MAIL_PORT', 587) or 587)
    except (ValueError, TypeError):
        port = 587

    enc     = os.environ.get('MAIL_ENCRYPTION', '').lower()
    use_tls = bool(_safe(Settings.MAIL_USE_TLS, True))
    use_ssl = bool(_safe(Settings.MAIL_USE_SSL, False))

    if enc == 'ssl':
        use_tls, use_ssl = False, True
    elif enc == 'starttls':
        use_tls, use_ssl = True, False
    elif enc == 'none':
        use_tls, use_ssl = False, False
    elif not _safe(Settings.MAIL_SERVER, ''):  # server came from env, not DB
        use_tls = os.environ.get('MAIL_USE_TLS', 'true').lower() in ('1', 'true', 'yes')
        use_ssl = os.environ.get('MAIL_USE_SSL', 'false').lower() in ('1', 'true', 'yes')

    username = _db_or_env(Settings.MAIL_USERNAME,        'MAIL_USERNAME')
    sender   = _db_or_env(Settings.MAIL_DEFAULT_SENDER, 'MAIL_DEFAULT_SENDER')

    try:
        from app.utils.crypto import decrypt_value as _dec_pw
        password = _dec_pw(_db_or_env(Settings.MAIL_PASSWORD, 'MAIL_PASSWORD'))
    except Exception:  # noqa: BLE001
        password = os.environ.get('MAIL_PASSWORD', '')

    app.config['MAIL_SERVER']         = server
    app.config['MAIL_PORT']           = port
    app.config['MAIL_USE_TLS']        = use_tls
    app.config['MAIL_USE_SSL']        = use_ssl
    app.config['MAIL_USERNAME']       = username
    app.config['MAIL_PASSWORD']       = password
    app.config['MAIL_DEFAULT_SENDER'] = sender

    try:
        from app.extensions import mail
        mail.init_app(app)
        _log.info('[App] Mail settings applied from DB: server=%s port=%s tls=%s ssl=%s',
                  server, port, use_tls, use_ssl)
    except Exception as exc:  # noqa: BLE001
        _log.warning('[App] Failed to (re-)initialize Flask-Mail: %s', exc)

    if not _safe(Settings.MAIL_SERVER, ''):
        try:
            _persist_env_mail_settings(server, app.config)
        except Exception:  # noqa: BLE001
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
    """Auto-detect and add any model column missing from the live DB schema.

    Compares every column in db.metadata (= all imported SQLAlchemy models)
    against the live SQLite schema.  Any column present in the model but absent
    from the database is added automatically via ALTER TABLE.

    This means you NEVER need to maintain a manual migration list — just add
    a column to a model and it will be created on the next startup.

    Notes:
    - New *tables* are handled by db.create_all(), not here.
    - Primary-key columns are never altered.
    - Columns with a callable default (e.g. lambda: datetime.now()) are added
      as nullable; SQLite cannot express a Python lambda as a SQL DEFAULT.
    - All errors are swallowed per-column so one bad column never blocks others.
    """
    import logging
    from sqlalchemy import text, inspect as sa_inspect

    _log = logging.getLogger('bpmtutor.migrations')
    inspector = sa_inspect(db.engine)
    existing_tables = set(inspector.get_table_names())

    with db.engine.connect() as conn:
        for table in db.metadata.sorted_tables:
            tname = table.name
            if tname not in existing_tables:
                continue  # new tables: handled by db.create_all()

            existing_cols = {c['name'] for c in inspector.get_columns(tname)}

            for col in table.columns:
                if col.name in existing_cols or col.primary_key:
                    continue

                # Compile the SQLite type string from the SQLAlchemy column type
                try:
                    type_str = col.type.compile(dialect=db.engine.dialect)
                except Exception:
                    type_str = str(col.type)

                # Build NOT NULL + DEFAULT suffix from the column's static default
                suffix = ''
                has_static_default = (
                    col.default is not None
                    and hasattr(col.default, 'is_scalar')
                    and col.default.is_scalar
                )
                if has_static_default:
                    val = col.default.arg
                    if isinstance(val, bool):
                        suffix += f' DEFAULT {1 if val else 0}'
                    elif isinstance(val, (int, float)):
                        suffix += f' DEFAULT {val}'
                    elif isinstance(val, str):
                        escaped = val.replace("'", "''")
                        suffix += f" DEFAULT '{escaped}'"
                    if not col.nullable:
                        suffix = ' NOT NULL' + suffix
                # Columns without a static default are added nullable;
                # a NOT NULL without DEFAULT is rejected by SQLite on ALTER TABLE.

                ddl = f'ALTER TABLE "{tname}" ADD COLUMN "{col.name}" {type_str}{suffix}'
                try:
                    conn.execute(text(ddl))
                    conn.commit()
                    _log.info('[Migration] Added %s.%s (%s%s)', tname, col.name, type_str, suffix)
                except Exception as exc:
                    try:
                        conn.rollback()
                    except Exception:
                        pass
                    _log.debug('[Migration] Skip %s.%s: %s', tname, col.name, exc)

        # ── Data fixups (schema-change independent, kept here for convenience) ──

        # Rename legacy 'instructor' role to 'tutor'
        try:
            if 'users' in existing_tables:
                conn.execute(text("UPDATE users SET role='tutor' WHERE role='instructor'"))
                conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass

        # Fix Supervisor agent control_mode: was accidentally seeded as 'shared'
        try:
            if 'ai_agents' in existing_tables:
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
        # Always pass through health check — Docker probe must not be blocked by
        # maintenance mode, otherwise the container is marked unhealthy and
        # dependent services (nginx, worker) refuse to start.
        if req.endpoint in ('main.maintenance', 'main.health',
                            'auth.login', 'auth.logout', None):
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


def _compute_research_badge(current_user, research_mode_enabled: bool) -> bool:
    """Return True when the user is enrolled in the active Research and has
    at least one sub-Study that is currently available but not yet completed."""
    import logging
    _log = logging.getLogger(__name__)
    if not research_mode_enabled:
        _log.debug('research_badge: research_mode_enabled is False')
        return False
    try:
        if not current_user.is_authenticated:
            _log.debug('research_badge: user not authenticated')
            return False
        from datetime import datetime as _dt
        from app.models.research import Research, ResearchParticipant
        from app.models.study import StudyParticipant
        research = Research.query.filter_by(is_active=True, is_enabled=True).first()
        if not research:
            _log.debug('research_badge: no active+enabled Research found')
            return False
        rp = ResearchParticipant.query.filter_by(
            research_id=research.id, user_id=current_user.id
        ).first()
        if rp and rp.is_dropped_out:
            _log.debug('research_badge: user %s is dropped out', current_user.id)
            return False
        now = _dt.now()

        def _naive(dt):
            if dt is None:
                return None
            return dt.replace(tzinfo=None) if getattr(dt, 'tzinfo', None) else dt

        for study in research.studies:
            if not study.is_active or getattr(study, 'is_archived', False):
                continue
            if study.task_start and now < _naive(study.task_start):
                continue
            if study.task_end and now > _naive(study.task_end):
                continue
            sp = StudyParticipant.query.filter_by(
                study_id=study.id, user_id=current_user.id
            ).first()
            if not sp or not sp.completed_at:
                _log.debug('research_badge: study %s not completed for user %s → badge=True',
                           study.id, current_user.id)
                return True
        _log.debug('research_badge: all studies completed or unavailable → badge=False')
        return False
    except Exception as exc:
        _log.warning('research_badge: exception → %s', exc, exc_info=True)
        return False


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

        # API key gate: True when mode=per_user AND authenticated user has no key
        api_key_mode = Settings.get(Settings.API_KEY_MODE, 'per_user')
        needs_api_key = (
            api_key_mode == 'per_user'
            and current_user.is_authenticated
            and not getattr(current_user, 'personal_api_key', None)
        )

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
            'research_pending_badge': _compute_research_badge(current_user, research_mode_enabled),
            'needs_api_key': needs_api_key,
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


def _setup_memory_log_handler(app: Flask) -> None:
    """Attach _MemoryLogHandler to both the root logger and the app logger.

    This captures log output from all libraries (SQLAlchemy, Flask-SocketIO, …)
    as well as application-level messages and makes them available via the
    /admin/settings/logs endpoint (the Admin Console tab).
    """
    handler = _MemoryLogHandler()
    handler.setFormatter(logging.Formatter(
        '%(asctime)s  %(levelname)-8s  [%(name)s]  %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
    ))
    handler.setLevel(logging.INFO)

    # Root logger — picks up werkzeug, SQLAlchemy, etc.
    root_logger = logging.getLogger()
    root_logger.addHandler(handler)

    # Flask app logger (may already propagate to root, but add directly too)
    if handler not in app.logger.handlers:
        app.logger.addHandler(handler)
