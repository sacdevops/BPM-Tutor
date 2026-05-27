"""CMS database models — Task & TaskSubmission."""
import json
from datetime import datetime, timezone

from app.extensions import db


class Task(db.Model):
    __tablename__ = 'tasks'

    id = db.Column(db.String(100), primary_key=True)   # slug, e.g. 'task_01'
    title = db.Column(db.String(500), nullable=False)
    title_de = db.Column(db.String(500), nullable=True)
    description = db.Column(db.Text, nullable=False)
    description_de = db.Column(db.Text, nullable=True)

    # Optional rich content
    image_path = db.Column(db.String(500), nullable=True)     # uploaded image
    bpmn_xml = db.Column(db.Text, nullable=True)              # pre-modeled BPMN

    # Availability window (null = always available)
    available_from = db.Column(db.DateTime, nullable=True)
    available_until = db.Column(db.DateTime, nullable=True)

    # Access control (JSON list of prerequisite rules)
    prerequisites = db.Column(db.Text, nullable=True)

    is_active = db.Column(db.Boolean, default=True, nullable=False)
    sort_order = db.Column(db.Integer, default=0, nullable=False)

    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # Grading configuration
    grading_type = db.Column(db.String(20), default='none', nullable=False)
    # values: 'none', 'points', 'pass_fail'
    max_points = db.Column(db.Float, nullable=True)

    # Extra language translations beyond EN/DE: {"fr": {"title": "...", "description": "..."}, ...}
    extra_translations = db.Column(db.Text, nullable=True)

    # Timed challenge mode (null = no limit)
    time_limit_minutes = db.Column(db.Integer, nullable=True)

    # Hide the task from the index once the student has a completed submission
    hide_after_completion = db.Column(db.Boolean, default=False, nullable=False)

    # Optional AI agent override for this task (null = use platform default)
    agent_id = db.Column(db.String(36), db.ForeignKey('ai_agents.id'), nullable=True)

    # Relationships
    submissions = db.relationship('TaskSubmission', backref='task', lazy='dynamic',
                                   foreign_keys='TaskSubmission.task_id')
    surveys = db.relationship('Survey', backref='task', lazy='dynamic',
                              foreign_keys='Survey.task_id')

    creator = db.relationship('User', foreign_keys=[created_by_id])

    @property
    def prerequisites_list(self) -> list:
        if self.prerequisites:
            try:
                return json.loads(self.prerequisites)
            except (ValueError, TypeError):
                return []
        return []

    @prerequisites_list.setter
    def prerequisites_list(self, data: list) -> None:
        self.prerequisites = json.dumps(data)

    @property
    def extra_translations_dict(self) -> dict:
        """Return extra_translations as dict, e.g. {'fr': {'title': '...', 'description': '...'}}."""
        if self.extra_translations:
            try:
                return json.loads(self.extra_translations)
            except (ValueError, TypeError):
                return {}
        return {}

    @extra_translations_dict.setter
    def extra_translations_dict(self, data: dict) -> None:
        self.extra_translations = json.dumps(data, ensure_ascii=False)

    def get_title(self, lang: str = 'en') -> str:
        """Return the title for the given language code, falling back to English."""
        if lang == 'en':
            return self.title
        if lang == 'de':
            return self.title_de or self.title
        return self.extra_translations_dict.get(lang, {}).get('title') or self.title

    def get_description(self, lang: str = 'en') -> str:
        """Return the description for the given language code, falling back to English."""
        if lang == 'en':
            return self.description
        if lang == 'de':
            return self.description_de or self.description
        return self.extra_translations_dict.get(lang, {}).get('description') or self.description

    def is_available_now(self) -> bool:
        now = datetime.now(timezone.utc)
        if self.available_from and now < self.available_from:
            return False
        if self.available_until and now > self.available_until:
            return False
        return True

    def as_dict(self) -> dict:
        return {
            'id': self.id,
            'title': self.title,
            'title_de': self.title_de or self.title,
            'description': self.description,
            'description_de': self.description_de or self.description,
            'image_path': self.image_path,
            'bpmn_xml': self.bpmn_xml,
            'grading_type': self.grading_type,
            'max_points': self.max_points,
            'sort_order': self.sort_order,
            'is_active': self.is_active,
            'available_from': self.available_from.isoformat() if self.available_from else None,
            'available_until': self.available_until.isoformat() if self.available_until else None,
        }

    def __repr__(self) -> str:
        return f'<Task {self.id}>'


class TaskSubmission(db.Model):
    __tablename__ = 'task_submissions'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True, index=True)
    task_id = db.Column(db.String(100), db.ForeignKey('tasks.id'), nullable=False, index=True)
    session_id = db.Column(db.String(100), nullable=True)  # socket session UUID

    bpmn_xml = db.Column(db.Text, nullable=True)          # final submitted BPMN
    bpmn_draft = db.Column(db.Text, nullable=True)        # auto-saved draft BPMN
    chat_log = db.Column(db.Text, nullable=True)           # JSON chat history

    started_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    completed_at = db.Column(db.DateTime, nullable=True)

    # Research study this submission belongs to (null = normal mode)
    study_id = db.Column(db.Integer, db.ForeignKey('studies.id', ondelete='SET NULL'), nullable=True, index=True)

    interactions = db.Column(db.Integer, default=0, nullable=False)
    tokens_in = db.Column(db.Integer, default=0, nullable=False)
    tokens_out = db.Column(db.Integer, default=0, nullable=False)

    # Grading fields (instructor-finalized — student-visible)
    grade_value = db.Column(db.Float, nullable=True)       # points or null
    grade_passed = db.Column(db.Boolean, nullable=True)    # pass/fail or null
    grade_comment = db.Column(db.Text, nullable=True)      # instructor comment
    grade_annotations = db.Column(db.Text, nullable=True)  # JSON [{element_id, comment, type}]
    graded_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    graded_at = db.Column(db.DateTime, nullable=True)

    # AI-generated grade suggestion (instructor must review & save before student sees it)
    ai_grade_value = db.Column(db.Float, nullable=True)
    ai_grade_passed = db.Column(db.Boolean, nullable=True)
    ai_grade_comment = db.Column(db.Text, nullable=True)
    ai_grade_annotations = db.Column(db.Text, nullable=True)  # JSON
    ai_grade_generated_at = db.Column(db.DateTime, nullable=True)

    # Persisted AI mentor memory (JSON list of {role, content} messages)
    mentor_memory = db.Column(db.Text, nullable=True)

    # Analytics
    phase_counts = db.Column(db.Text, nullable=True)          # JSON {GREETING:1, ANALYSIS:3, ...}
    validation_error_keys = db.Column(db.Text, nullable=True)  # JSON ["missing_label", ...]

    # Composite indexes for the hottest query patterns:
    #   (user_id, task_id) — finding open submissions for a specific user+task
    #   (task_id, started_at) — admin analytics sorted by time per task
    __table_args__ = (
        db.Index('ix_task_sub_user_task', 'user_id', 'task_id'),
        db.Index('ix_task_sub_task_started', 'task_id', 'started_at'),
    )

    grader = db.relationship('User', foreign_keys=[graded_by_id], overlaps='graded_submissions')

    @property
    def chat_history(self) -> list:
        if self.chat_log:
            try:
                return json.loads(self.chat_log)
            except (ValueError, TypeError):
                return []
        return []

    @chat_history.setter
    def chat_history(self, data: list) -> None:
        self.chat_log = json.dumps(data, ensure_ascii=False)

    @property
    def mentor_memory_list(self) -> list:
        if self.mentor_memory:
            try:
                return json.loads(self.mentor_memory)
            except (ValueError, TypeError):
                return []
        return []

    @mentor_memory_list.setter
    def mentor_memory_list(self, data: list) -> None:
        self.mentor_memory = json.dumps(data, ensure_ascii=False)

    @property
    def grade_annotations_list(self) -> list:
        if self.grade_annotations:
            try:
                return json.loads(self.grade_annotations)
            except (ValueError, TypeError):
                return []
        return []

    @grade_annotations_list.setter
    def grade_annotations_list(self, data: list) -> None:
        self.grade_annotations = json.dumps(data, ensure_ascii=False)

    @property
    def ai_grade_annotations_list(self) -> list:
        if self.ai_grade_annotations:
            try:
                return json.loads(self.ai_grade_annotations)
            except (ValueError, TypeError):
                return []
        return []

    @property
    def phase_counts_dict(self) -> dict:
        if self.phase_counts:
            try:
                return json.loads(self.phase_counts)
            except (ValueError, TypeError):
                return {}
        return {}

    @property
    def validation_errors_list(self) -> list:
        if self.validation_error_keys:
            try:
                return json.loads(self.validation_error_keys)
            except (ValueError, TypeError):
                return []
        return []

    @property
    def duration_seconds(self) -> float:
        if self.completed_at and self.started_at:
            return (self.completed_at - self.started_at).total_seconds()
        if self.started_at:
            now = datetime.now(timezone.utc)
            started = self.started_at
            # SQLite returns naive datetimes; treat them as UTC
            if started.tzinfo is None:
                started = started.replace(tzinfo=timezone.utc)
            return (now - started).total_seconds()
        return 0.0

    def __repr__(self) -> str:
        return f'<TaskSubmission {self.id} task={self.task_id} user={self.user_id}>'


class TaskBPMNSnapshot(db.Model):
    """Version history entry — one row per auto-save or manual save event."""
    __tablename__ = 'task_bpmn_snapshots'

    id = db.Column(db.Integer, primary_key=True)
    submission_id = db.Column(db.Integer, db.ForeignKey('task_submissions.id',
                              ondelete='CASCADE'), nullable=False, index=True)
    bpmn_xml = db.Column(db.Text, nullable=False)
    source = db.Column(db.String(20), default='auto', nullable=False)  # 'auto' | 'submit'
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    submission = db.relationship('TaskSubmission',
                                 backref=db.backref('snapshots', lazy='dynamic',
                                                    cascade='all, delete-orphan'))

    def __repr__(self) -> str:
        return f'<TaskBPMNSnapshot {self.id} sub={self.submission_id} src={self.source}>'
