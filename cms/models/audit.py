"""CMS model — Audit log for tracking admin and user actions."""
import json
from datetime import datetime

from cms.extensions import db


class AuditLog(db.Model):
    __tablename__ = 'audit_logs'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True, index=True)
    action = db.Column(db.String(100), nullable=False, index=True)
    entity_type = db.Column(db.String(100), nullable=True, index=True)
    entity_id = db.Column(db.String(200), nullable=True)
    details_json = db.Column(db.Text, nullable=True)
    ip_address = db.Column(db.String(45), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)

    actor = db.relationship('User', foreign_keys=[user_id], lazy='joined')

    @property
    def details(self) -> dict:
        if self.details_json:
            try:
                return json.loads(self.details_json)
            except (ValueError, TypeError):
                return {}
        return {}

    @details.setter
    def details(self, data: dict) -> None:
        self.details_json = json.dumps(data, ensure_ascii=False) if data else None

    def __repr__(self) -> str:
        return f'<AuditLog {self.id} {self.action} user={self.user_id}>'
