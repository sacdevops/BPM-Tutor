"""CMS database models — SystemSetting / Settings accessor.

Notification and RegistrationField have been extracted to their own modules.
They are re-exported here so all existing imports remain unchanged.
"""
import json
import os
from datetime import datetime, timezone

from app.extensions import db

# Re-exports for backward compatibility (all existing imports still work)
from app.models.notification import Notification  # noqa: F401 – re-export
from app.models.registration_field import RegistrationField  # noqa: F401 – re-export

# ---------------------------------------------------------------------------
# Redis helper — optional, gracefully degrades when Redis is unavailable
# ---------------------------------------------------------------------------
_redis_client = None
_redis_checked = False

def _get_redis():
    """Return a Redis client or None if Redis is not configured / unavailable."""
    global _redis_client, _redis_checked
    if _redis_checked:
        return _redis_client
    _redis_checked = True
    redis_url = os.getenv('REDIS_URL', '')
    if not redis_url:
        return None
    try:
        import redis as _redis_lib
        client = _redis_lib.from_url(
            redis_url,
            decode_responses=True,
            socket_connect_timeout=1,
            socket_timeout=1,
        )
        client.ping()
        _redis_client = client
    except Exception:
        _redis_client = None
    return _redis_client

_SETTINGS_CACHE_TTL = 120  # seconds
_CACHE_PREFIX = 'bpmtutor:settings:'


class SystemSetting(db.Model):
    """Key-value store for system-wide configuration."""
    __tablename__ = 'system_settings'

    key = db.Column(db.String(100), primary_key=True)
    value = db.Column(db.Text, nullable=True)
    value_type = db.Column(db.String(20), default='string', nullable=False)
    # value_types: string, bool, int, float, json
    description = db.Column(db.Text, nullable=True)
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    def __repr__(self) -> str:
        return f'<SystemSetting {self.key}={self.value!r}>'


class Settings:
    """Typed accessor for SystemSetting records with in-memory caching."""

    # Known setting keys
    AUTH_REQUIRED = 'auth_required'
    API_KEY_MODE = 'api_key_mode'          # 'global' or 'per_user'
    GLOBAL_API_KEY = 'global_api_key'
    API_ENDPOINT = 'api_endpoint'
    DEFAULT_MODEL = 'default_model'
    MAIL_ENABLED = 'mail_enabled'
    SITE_NAME = 'site_name'
    SITE_NAME_DE = 'site_name_de'
    ALLOW_REGISTRATION = 'allow_registration'
    REQUIRE_EMAIL_VERIFICATION = 'require_email_verification'
    MAX_FILE_UPLOAD_MB = 'max_file_upload_mb'

    # Branding
    BRAND_PRIMARY = 'brand_primary_color'    # hex e.g. #84BD00
    BRAND_SIDEBAR_BG = 'brand_sidebar_bg'    # hex e.g. #162700
    BRAND_LOGO_URL = 'brand_logo_url'        # URL to logo image
    BRAND_LOGO_DATA = 'brand_logo_data'      # base64-encoded image data
    BRAND_LOGO_MIME = 'brand_logo_mime'      # MIME type of uploaded logo
    BRAND_LOGO_LINK = 'brand_logo_link'      # clickable target of logo
    SITE_TAGLINE = 'site_tagline'
    SITE_TAGLINE_DE = 'site_tagline_de'

    # Level system
    LEVEL_SYSTEM_ENABLED = 'level_system_enabled'

    # Cohorts
    COHORTS_ENABLED = 'cohorts_enabled'

    # Research mode
    RESEARCH_MODE_ENABLED = 'research_mode_enabled'

    # Maintenance
    MAINTENANCE_MODE = 'maintenance_mode'

    # Feedback / bug reports
    FEEDBACK_EMAIL = 'feedback_email'

    # Legal / privacy
    PRIVACY_POLICY = 'privacy_policy'              # HTML/text shown in the registration privacy policy popup

    # AI prompt rules — editable global content injected into all agent system prompts
    BPMN_SYNTAX_RULES = 'bpmn_syntax_rules'       # replaces {bpmn_standards}
    BPMN_ELEMENTS = 'bpmn_elements'                # replaces {bpmn_elements}
    GENERAL_RULES = 'general_rules'                # replaces {general_rules} (en)
    GENERAL_RULES_DE = 'general_rules_de'          # replaces {general_rules} (de)
    LION_FORMAT_RULES = 'lion_format_rules'        # replaces {lion_rules}

    # Mail configuration (outgoing SMTP)
    MAIL_SERVER = 'mail_server'
    MAIL_PORT = 'mail_port'
    MAIL_USE_TLS = 'mail_use_tls'
    MAIL_USE_SSL = 'mail_use_ssl'
    MAIL_USERNAME = 'mail_username'
    MAIL_PASSWORD = 'mail_password'
    MAIL_DEFAULT_SENDER = 'mail_default_sender'

    # Mail configuration (incoming IMAP/POP3 — optional separate settings)
    MAIL_SEPARATE_INCOMING = 'mail_separate_incoming'
    MAIL_INCOMING_PROTOCOL = 'mail_incoming_protocol'   # 'imap' or 'pop3'
    MAIL_INCOMING_SERVER = 'mail_incoming_server'
    MAIL_INCOMING_PORT = 'mail_incoming_port'
    MAIL_INCOMING_USE_TLS = 'mail_incoming_use_tls'
    MAIL_INCOMING_USERNAME = 'mail_incoming_username'
    MAIL_INCOMING_PASSWORD = 'mail_incoming_password'

    # Customisable email templates (empty = use built-in default)
    MAIL_VERIFY_SUBJECT = 'mail_verify_subject'
    MAIL_VERIFY_BODY = 'mail_verify_body'
    MAIL_RESET_SUBJECT = 'mail_reset_subject'
    MAIL_RESET_BODY = 'mail_reset_body'

    # Automatic backups
    AUTO_BACKUP_ENABLED = 'auto_backup_enabled'
    AUTO_BACKUP_INTERVAL_HOURS = 'auto_backup_interval_hours'
    AUTO_BACKUP_STORAGE = 'auto_backup_storage'     # 'local' or 'sciebo'
    AUTO_BACKUP_LOCAL_PATH = 'auto_backup_local_path'
    AUTO_BACKUP_MAX_KEEP = 'auto_backup_max_keep'
    AUTO_BACKUP_LAST_RUN = 'auto_backup_last_run'   # ISO timestamp, managed by task
    SCIEBO_URL = 'sciebo_url'
    SCIEBO_USERNAME = 'sciebo_username'
    SCIEBO_PASSWORD = 'sciebo_password'             # stored encrypted
    SCIEBO_REMOTE_PATH = 'sciebo_remote_path'

    _DEFAULTS: dict = {
        AUTH_REQUIRED: (False, 'bool'),
        API_KEY_MODE: ('per_user', 'string'),
        GLOBAL_API_KEY: ('', 'string'),
        API_ENDPOINT: ('', 'string'),
        DEFAULT_MODEL: ('gpt-5', 'string'),
        MAIL_ENABLED: (False, 'bool'),
        MAIL_SERVER: ('', 'string'),
        MAIL_PORT: ('587', 'string'),
        MAIL_USE_TLS: (True, 'bool'),
        MAIL_USE_SSL: (False, 'bool'),
        MAIL_USERNAME: ('', 'string'),
        MAIL_PASSWORD: ('', 'string'),
        MAIL_DEFAULT_SENDER: ('', 'string'),
        MAIL_SEPARATE_INCOMING: (False, 'bool'),
        MAIL_INCOMING_PROTOCOL: ('imap', 'string'),
        MAIL_INCOMING_SERVER: ('', 'string'),
        MAIL_INCOMING_PORT: ('993', 'string'),
        MAIL_INCOMING_USE_TLS: (True, 'bool'),
        MAIL_INCOMING_USERNAME: ('', 'string'),
        MAIL_INCOMING_PASSWORD: ('', 'string'),
        MAIL_VERIFY_SUBJECT: ('', 'string'),
        MAIL_VERIFY_BODY: ('', 'string'),
        MAIL_RESET_SUBJECT: ('', 'string'),
        MAIL_RESET_BODY: ('', 'string'),
        SITE_NAME: ('BPM-Tutor', 'string'),
        SITE_NAME_DE: ('BPM-Tutor', 'string'),
        ALLOW_REGISTRATION: (True, 'bool'),
        REQUIRE_EMAIL_VERIFICATION: (True, 'bool'),
        MAX_FILE_UPLOAD_MB: (10, 'int'),
        BRAND_PRIMARY: ('#84BD00', 'string'),
        BRAND_SIDEBAR_BG: ('#162700', 'string'),
        BRAND_LOGO_URL: ('', 'string'),
        BRAND_LOGO_DATA: ('', 'string'),
        BRAND_LOGO_MIME: ('image/png', 'string'),
        BRAND_LOGO_LINK: ('/', 'string'),
        SITE_TAGLINE: ('BPMN Modeling Learning Environment', 'string'),
        SITE_TAGLINE_DE: ('BPMN-Modellierungs-Lernumgebung', 'string'),
        LEVEL_SYSTEM_ENABLED: (False, 'bool'),
        RESEARCH_MODE_ENABLED: (False, 'bool'),
        COHORTS_ENABLED: (True, 'bool'),
        MAINTENANCE_MODE: (False, 'bool'),
        FEEDBACK_EMAIL: ('', 'string'),
        PRIVACY_POLICY: ('', 'string'),
        BPMN_SYNTAX_RULES: ('', 'string'),   # empty = use built-in Python fallback
        BPMN_ELEMENTS: ('', 'string'),        # empty = use built-in Python fallback
        GENERAL_RULES: ('', 'string'),        # empty = use built-in Python fallback
        GENERAL_RULES_DE: ('', 'string'),     # empty = use built-in Python fallback
        LION_FORMAT_RULES: ('', 'string'),    # empty = use built-in Python fallback
        # Auto-backup
        AUTO_BACKUP_ENABLED: (False, 'bool'),
        AUTO_BACKUP_INTERVAL_HOURS: (24, 'int'),
        AUTO_BACKUP_STORAGE: ('local', 'string'),
        AUTO_BACKUP_LOCAL_PATH: ('', 'string'),
        AUTO_BACKUP_MAX_KEEP: (14, 'int'),
        AUTO_BACKUP_LAST_RUN: ('', 'string'),
        SCIEBO_URL: ('', 'string'),
        SCIEBO_USERNAME: ('', 'string'),
        SCIEBO_PASSWORD: ('', 'string'),
        SCIEBO_REMOTE_PATH: ('', 'string'),
    }

    @classmethod
    def get(cls, key: str, default=None):
        """Get a setting value, type-cast according to value_type.

        Checks Redis cache first (TTL=120s), falls back to the database.
        """
        r = _get_redis()
        vtype = cls._DEFAULTS.get(key, (None, 'string'))[1]

        # 1. Try Redis cache
        if r is not None:
            try:
                cached = r.get(f'{_CACHE_PREFIX}{key}')
                if cached is not None:
                    return cls._cast(cached, vtype)
            except Exception:
                pass

        # 2. DB lookup
        row: SystemSetting | None = db.session.get(SystemSetting, key)
        if row is None:
            if key in cls._DEFAULTS:
                val = cls._DEFAULTS[key][0]
                # Cache the default so we don't repeat the DB miss
                if r is not None:
                    try:
                        r.setex(f'{_CACHE_PREFIX}{key}', _SETTINGS_CACHE_TTL, str(val))
                    except Exception:
                        pass
                return val
            return default

        # 3. Store in Redis and return
        if r is not None:
            try:
                r.setex(f'{_CACHE_PREFIX}{key}', _SETTINGS_CACHE_TTL,
                        row.value if row.value is not None else '')
            except Exception:
                pass
        return cls._cast(row.value, row.value_type)

    @classmethod
    def set(cls, key: str, value) -> None:
        """Persist a setting value and invalidate its cache entry."""
        vtype = cls._DEFAULTS.get(key, (None, 'string'))[1]
        row: SystemSetting | None = db.session.get(SystemSetting, key)
        if row is None:
            row = SystemSetting(key=key, value_type=vtype)
            db.session.add(row)
        row.value = str(value) if value is not None else None
        row.value_type = vtype
        db.session.commit()
        # Invalidate cache
        r = _get_redis()
        if r is not None:
            try:
                r.delete(f'{_CACHE_PREFIX}{key}')
            except Exception:
                pass

    @classmethod
    def set_many(cls, mapping: dict) -> None:
        """Persist multiple settings at once and invalidate their cache entries."""
        for key, value in mapping.items():
            vtype = cls._DEFAULTS.get(key, (None, 'string'))[1]
            row: SystemSetting | None = db.session.get(SystemSetting, key)
            if row is None:
                row = SystemSetting(key=key, value_type=vtype)
                db.session.add(row)
            row.value = str(value) if value is not None else None
            row.value_type = vtype
        db.session.commit()
        # Invalidate all changed keys in one pipeline
        r = _get_redis()
        if r is not None:
            try:
                pipe = r.pipeline()
                for key in mapping:
                    pipe.delete(f'{_CACHE_PREFIX}{key}')
                pipe.execute()
            except Exception:
                pass

    @staticmethod
    def _cast(value: str | None, vtype: str):
        if value is None:
            return None
        if vtype == 'bool':
            return value.lower() in ('true', '1', 'yes')
        if vtype == 'int':
            try:
                return int(value)
            except (ValueError, TypeError):
                return 0
        if vtype == 'float':
            try:
                return float(value)
            except (ValueError, TypeError):
                return 0.0
        if vtype == 'json':
            try:
                return json.loads(value)
            except (ValueError, TypeError):
                return {}
        return value

    @classmethod
    def ensure_defaults(cls) -> None:
        """Insert default rows for any missing settings."""
        for key, (default_val, vtype) in cls._DEFAULTS.items():
            if db.session.get(SystemSetting, key) is None:
                db.session.add(SystemSetting(
                    key=key,
                    value=str(default_val),
                    value_type=vtype,
                ))
        db.session.commit()
