"""CMS database models — User."""
import json
from datetime import datetime

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from cms.extensions import db


class User(UserMixin, db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    username = db.Column(db.String(100), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)

    # Roles: admin, instructor, student
    role = db.Column(db.String(20), nullable=False, default='student', index=True)

    is_active = db.Column(db.Boolean, default=True, nullable=False)
    is_verified = db.Column(db.Boolean, default=False, nullable=False)
    is_locked = db.Column(db.Boolean, default=False, nullable=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    last_login = db.Column(db.DateTime, nullable=True)

    # Optional personal data
    first_name = db.Column(db.String(100), nullable=True)
    last_name = db.Column(db.String(100), nullable=True)

    # Extra profile fields from registration config (JSON)
    profile_data = db.Column(db.Text, nullable=True)

    # Personal OpenAI-compatible API key (stored encrypted, prefix 'enc:')
    personal_api_key = db.Column(db.String(1000), nullable=True)

    # UI language preference
    language = db.Column(db.String(10), nullable=False, default='de')

    # GDPR consent
    data_consent = db.Column(db.Boolean, default=False, nullable=False)

    # Relationships
    submissions = db.relationship(
        'TaskSubmission', backref='user', lazy='dynamic',
        foreign_keys='TaskSubmission.user_id'
    )
    notifications = db.relationship('Notification', backref='user', lazy='dynamic')
    survey_responses = db.relationship('SurveyResponse', backref='user', lazy='dynamic')
    graded_submissions = db.relationship(
        'TaskSubmission', lazy='dynamic',
        foreign_keys='TaskSubmission.graded_by_id',
        overlaps='grader'
    )

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    @property
    def profile(self) -> dict:
        if self.profile_data:
            try:
                return json.loads(self.profile_data)
            except (ValueError, TypeError):
                return {}
        return {}

    @profile.setter
    def profile(self, data: dict) -> None:
        self.profile_data = json.dumps(data, ensure_ascii=False)

    @property
    def display_name(self) -> str:
        if self.first_name and self.last_name:
            return f'{self.first_name} {self.last_name}'
        if self.first_name:
            return self.first_name
        return self.username

    @property
    def unread_notifications_count(self) -> int:
        return self.notifications.filter_by(is_read=False).count()

    def has_role(self, *roles) -> bool:
        return self.role in roles

    def __repr__(self) -> str:
        return f'<User {self.username} ({self.role})>'
