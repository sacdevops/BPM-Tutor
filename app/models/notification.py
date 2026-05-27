"""Notification model (extracted from settings.py for clarity)."""
from datetime import datetime, timezone

from app.extensions import db


class Notification(db.Model):
    """User notification (grade, message, system, task_unlocked, account)."""
    __tablename__ = 'notifications'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)

    # Types: grade, message, system, task_unlocked, account
    notif_type = db.Column(db.String(50), nullable=False, default='system')

    title = db.Column(db.String(400), nullable=False)
    message = db.Column(db.Text, nullable=True)
    link = db.Column(db.String(500), nullable=True)

    is_read = db.Column(db.Boolean, default=False, nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False, index=True)

    def __repr__(self) -> str:
        return f'<Notification {self.id} user={self.user_id} read={self.is_read}>'
