"""CMS database models — Notification, RegistrationField, SystemSetting."""
import json
from datetime import datetime

from cms.extensions import db


class Notification(db.Model):
    __tablename__ = 'notifications'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)

    # Types: grade, message, system, task_unlocked, account
    notif_type = db.Column(db.String(50), nullable=False, default='system')

    title = db.Column(db.String(400), nullable=False)
    message = db.Column(db.Text, nullable=True)
    link = db.Column(db.String(500), nullable=True)

    is_read = db.Column(db.Boolean, default=False, nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)

    def __repr__(self) -> str:
        return f'<Notification {self.id} user={self.user_id} read={self.is_read}>'


class RegistrationField(db.Model):
    """Extra fields shown on the registration form (configurable by admin)."""
    __tablename__ = 'registration_fields'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)      # internal key
    label = db.Column(db.String(300), nullable=False)                  # English label
    label_de = db.Column(db.String(300), nullable=True)                # German label

    # Types: text, textarea, select, number, date, checkbox
    field_type = db.Column(db.String(30), nullable=False, default='text')

    # JSON list for select: [{"value": "...", "label": "..."}]
    options_data = db.Column(db.Text, nullable=True)

    required = db.Column(db.Boolean, default=False, nullable=False)
    sort_order = db.Column(db.Integer, default=0, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    @property
    def options(self) -> list:
        if self.options_data:
            try:
                return json.loads(self.options_data)
            except (ValueError, TypeError):
                return []
        return []

    @options.setter
    def options(self, data: list) -> None:
        self.options_data = json.dumps(data, ensure_ascii=False)

    def __repr__(self) -> str:
        return f'<RegistrationField {self.name}>'


class SystemSetting(db.Model):
    """Key-value store for system-wide configuration."""
    __tablename__ = 'system_settings'

    key = db.Column(db.String(100), primary_key=True)
    value = db.Column(db.Text, nullable=True)
    value_type = db.Column(db.String(20), default='string', nullable=False)
    # value_types: string, bool, int, float, json
    description = db.Column(db.Text, nullable=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

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

    _DEFAULTS: dict = {
        AUTH_REQUIRED: (False, 'bool'),
        API_KEY_MODE: ('per_user', 'string'),
        GLOBAL_API_KEY: ('', 'string'),
        API_ENDPOINT: ('', 'string'),
        DEFAULT_MODEL: ('gpt-4o', 'string'),
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
    }

    @classmethod
    def get(cls, key: str, default=None):
        """Get a setting value, type-cast according to value_type."""
        row: SystemSetting | None = SystemSetting.query.get(key)
        if row is None:
            if key in cls._DEFAULTS:
                return cls._DEFAULTS[key][0]
            return default
        return cls._cast(row.value, row.value_type)

    @classmethod
    def set(cls, key: str, value) -> None:
        """Persist a setting value."""
        vtype = cls._DEFAULTS.get(key, (None, 'string'))[1]
        row: SystemSetting | None = SystemSetting.query.get(key)
        if row is None:
            row = SystemSetting(key=key, value_type=vtype)
            db.session.add(row)
        row.value = str(value) if value is not None else None
        row.value_type = vtype
        db.session.commit()

    @classmethod
    def set_many(cls, mapping: dict) -> None:
        """Persist multiple settings at once."""
        for key, value in mapping.items():
            vtype = cls._DEFAULTS.get(key, (None, 'string'))[1]
            row: SystemSetting | None = SystemSetting.query.get(key)
            if row is None:
                row = SystemSetting(key=key, value_type=vtype)
                db.session.add(row)
            row.value = str(value) if value is not None else None
            row.value_type = vtype
        db.session.commit()

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
            if SystemSetting.query.get(key) is None:
                db.session.add(SystemSetting(
                    key=key,
                    value=str(default_val),
                    value_type=vtype,
                ))
        db.session.commit()
