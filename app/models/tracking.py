"""Task Session Tracking — stores user interaction events during a task session."""
from datetime import datetime, timezone

from app.extensions import db


class TaskSessionTracking(db.Model):
    """Batched interaction events for a task session (cursor, clicks, BPMN, chat focus)."""
    __tablename__ = 'task_session_tracking'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True, index=True)
    study_id = db.Column(db.Integer, db.ForeignKey('studies.id', ondelete='SET NULL'), nullable=True, index=True)
    task_id = db.Column(db.String(100), nullable=False, index=True)
    submission_id = db.Column(db.Integer, db.ForeignKey('task_submissions.id', ondelete='SET NULL'), nullable=True)

    # ISO timestamp of session start (set client-side when tracking begins)
    session_start = db.Column(db.String(30), nullable=True)

    # Batch sequence number — clients send batches numbered from 0
    batch_seq = db.Column(db.Integer, default=0, nullable=False)

    # JSON array of event objects:
    # {t: ms_since_session_start, ts: iso_string, type: event_type, ...type-specific fields}
    events_data = db.Column(db.Text, nullable=False, default='[]')

    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    def __repr__(self) -> str:
        return f'<TaskSessionTracking user={self.user_id} task={self.task_id} batch={self.batch_seq}>'
