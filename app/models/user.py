"""CMS database models — User."""
import json
from datetime import datetime, timezone
from typing import TypedDict

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db


class ProfileData(TypedDict, total=False):
    """Typed schema for the JSON `profile_data` column."""
    study_program: str
    semester: str
    experience_level: str
    institution: str


class User(UserMixin, db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    username = db.Column(db.String(100), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)

    # Roles: admin, tutor, student
    role = db.Column(db.String(20), nullable=False, default='student', index=True)

    is_active = db.Column(db.Boolean, default=True, nullable=False)
    is_verified = db.Column(db.Boolean, default=False, nullable=False)
    is_locked = db.Column(db.Boolean, default=False, nullable=False)

    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    last_login = db.Column(db.DateTime, nullable=True)

    # Optional personal data
    first_name = db.Column(db.String(100), nullable=True)
    last_name = db.Column(db.String(100), nullable=True)

    # Extra profile fields from registration config (JSON)
    profile_data = db.Column(db.Text, nullable=True)

    # Personal OpenAI-compatible API key (stored encrypted, prefix 'enc:')
    personal_api_key = db.Column(db.String(1000), nullable=True)

    # Preferred AI model (e.g. "gpt-4o")
    preferred_model = db.Column(db.String(200), nullable=True)

    # UI language preference
    language = db.Column(db.String(10), nullable=False, default='de')

    # GDPR consent
    data_consent = db.Column(db.Boolean, default=False, nullable=False)

    # Leaderboard anonymization — if True, username is hidden on leaderboards
    leaderboard_anonymous = db.Column(db.Boolean, default=False, nullable=False)

    # Email notifications — if True, send email when a notification is created
    email_notifications = db.Column(db.Boolean, default=True, nullable=False)

    # Relationships
    submissions = db.relationship(
        'TaskSubmission', backref='user', lazy='dynamic',
        foreign_keys='TaskSubmission.user_id'
    )
    notifications = db.relationship('Notification', backref='user', lazy='dynamic', cascade='all, delete-orphan')
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
    def profile(self) -> ProfileData:
        if self.profile_data:
            try:
                return json.loads(self.profile_data)
            except (ValueError, TypeError):
                return {}
        return {}

    @profile.setter
    def profile(self, data: ProfileData) -> None:
        self.profile_data = json.dumps(data, ensure_ascii=False)

    @property
    def display_name(self) -> str:
        if self.first_name and self.last_name:
            return f'{self.first_name} {self.last_name}'
        if self.first_name:
            return self.first_name
        return self.username

    @staticmethod
    def unread_counts(user_ids: list[int]) -> dict[int, int]:
        """Return a mapping of user_id → unread notification count.

        Uses a single GROUP BY aggregate query instead of N individual
        COUNT queries, making it safe to call inside list-rendering loops.
        """
        from app.models.notification import Notification
        from sqlalchemy import func
        rows = (
            db.session.query(Notification.user_id, func.count(Notification.id))
            .filter(Notification.user_id.in_(user_ids), Notification.is_read == False)  # noqa: E712
            .group_by(Notification.user_id)
            .all()
        )
        return {uid: cnt for uid, cnt in rows}

    def has_role(self, *roles: str) -> bool:
        return self.role in roles

    def __repr__(self) -> str:
        return f'<User {self.username} ({self.role})>'
