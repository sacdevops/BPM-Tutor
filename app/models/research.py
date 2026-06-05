"""Research — top-level umbrella model grouping Studies into one program.

Hierarchy:
  Research                     ← single top-level research project
  ├── ResearchCondition[]      ← between-subjects conditions (optional)
  ├── ResearchParticipant[]    ← one enrollment record per user
  └── Study[]  (via Study.research_id FK)
                ├── StudyStep[]  ← existing per-Study steps (tasks / surveys)
                └── StudyParticipant[]  ← per-Study progress tracker (auto-created)
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.extensions import db


class Research(db.Model):
    __tablename__ = 'researches'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(300), nullable=False)
    description = db.Column(db.Text, nullable=True)

    # Master switches
    is_active = db.Column(db.Boolean, default=True, nullable=False)   # visible to students
    is_enabled = db.Column(db.Boolean, default=False, nullable=False)  # Research Mode on/off

    # Enrollment window
    enrollment_start = db.Column(db.DateTime, nullable=True)
    enrollment_end = db.Column(db.DateTime, nullable=True)
    allow_self_enrollment = db.Column(db.Boolean, default=True, nullable=False)
    max_participants = db.Column(db.Integer, nullable=True)

    # Informed consent
    require_consent = db.Column(db.Boolean, default=False, nullable=False)
    consent_text = db.Column(db.Text, nullable=True)

    # Survey shown at enrollment (before studies begin)
    enrollment_survey_id = db.Column(db.Integer, db.ForeignKey('surveys.id'), nullable=True)

    # Experimental design
    study_design = db.Column(db.String(20), default='within', nullable=False)
    one_time_only = db.Column(db.Boolean, default=True, nullable=False)
    anonymize_export = db.Column(db.Boolean, default=True, nullable=False)
    leaderboard_enabled = db.Column(db.Boolean, default=False, nullable=False)
    agent_display_name = db.Column(db.String(200), nullable=True)

    # Auto-dropout: if a Study's task_end is missed, drop participant from Research
    auto_dropout_on_miss = db.Column(db.Boolean, default=False, nullable=False)

    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

    # Relationships
    conditions = db.relationship(
        'ResearchCondition', back_populates='research',
        cascade='all, delete-orphan', lazy='select',
        foreign_keys='ResearchCondition.research_id',
    )
    participants = db.relationship(
        'ResearchParticipant', back_populates='research',
        cascade='all, delete-orphan', lazy='dynamic',
        foreign_keys='ResearchParticipant.research_id',
    )
    studies = db.relationship(
        'Study', back_populates='research', lazy='select',
        foreign_keys='Study.research_id',
    )
    enrollment_survey = db.relationship('Survey', foreign_keys=[enrollment_survey_id], lazy='select')
    creator = db.relationship('User', foreign_keys=[created_by_id])

    @property
    def enrollment_open(self) -> bool:
        """True if self-enrollment is currently allowed (day-level comparison)."""
        today = datetime.utcnow().date()
        if not self.allow_self_enrollment:
            return False
        if self.enrollment_start and today < self.enrollment_start.date():
            return False
        if self.enrollment_end and today > self.enrollment_end.date():
            return False
        return True

    def get_active_studies(self) -> list:
        """Return sub-Studies that are currently within their availability window."""
        now = datetime.utcnow()
        result = []
        for s in self.studies:
            if not s.is_active or getattr(s, 'is_archived', False):
                continue
            if s.task_start and now < s.task_start:
                continue
            if s.task_end and now > s.task_end:
                continue
            result.append(s)
        return result

    def assign_condition(self, participant: 'ResearchParticipant') -> None:
        """Assign the least-populated condition to *participant* (between-subjects)."""
        if self.study_design != 'between' or not self.conditions:
            return
        from sqlalchemy import func
        rows = (
            db.session.query(ResearchParticipant.condition_id, func.count(ResearchParticipant.id))
            .filter(ResearchParticipant.research_id == self.id)
            .group_by(ResearchParticipant.condition_id)
            .all()
        )
        counts = {c.id: 0 for c in self.conditions}
        for cond_id, cnt in rows:
            if cond_id in counts:
                counts[cond_id] = cnt
        chosen_id = min(counts, key=lambda cid: counts[cid])
        participant.condition_id = chosen_id

    def __repr__(self) -> str:
        return f'<Research {self.id}: {self.title}>'


class ResearchCondition(db.Model):
    """A between-subjects condition within a Research (e.g. different AI agents)."""
    __tablename__ = 'research_conditions'

    id = db.Column(db.Integer, primary_key=True)
    research_id = db.Column(
        db.Integer, db.ForeignKey('researches.id', ondelete='CASCADE'),
        nullable=False, index=True,
    )
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=True)
    target_size = db.Column(db.Integer, nullable=True)
    agent_id = db.Column(
        db.String(36), db.ForeignKey('ai_agents.id', ondelete='SET NULL'), nullable=True,
    )

    research = db.relationship('Research', back_populates='conditions', foreign_keys=[research_id])
    agent = db.relationship('AIAgent', foreign_keys=[agent_id])

    def __repr__(self) -> str:
        return f'<ResearchCondition {self.id}: {self.name}>'


class ResearchParticipant(db.Model):
    """Enrollment record for a user in a Research project."""
    __tablename__ = 'research_participants'

    id = db.Column(db.Integer, primary_key=True)
    research_id = db.Column(
        db.Integer, db.ForeignKey('researches.id', ondelete='CASCADE'),
        nullable=False, index=True,
    )
    user_id = db.Column(
        db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'),
        nullable=False, index=True,
    )

    enrolled_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    dropped_out_at = db.Column(db.DateTime, nullable=True)
    dropout_reason = db.Column(db.String(500), nullable=True)

    condition_id = db.Column(
        db.Integer, db.ForeignKey('research_conditions.id', ondelete='SET NULL'), nullable=True,
    )
    consent_given_at = db.Column(db.DateTime, nullable=True)
    active_agent_id = db.Column(
        db.String(36), db.ForeignKey('ai_agents.id', ondelete='SET NULL'), nullable=True,
    )
    notes = db.Column(db.Text, nullable=True)

    research = db.relationship('Research', back_populates='participants', foreign_keys=[research_id])
    user = db.relationship('User', foreign_keys=[user_id])
    condition = db.relationship('ResearchCondition', foreign_keys=[condition_id])
    active_agent = db.relationship('AIAgent', foreign_keys=[active_agent_id])

    __table_args__ = (
        db.UniqueConstraint('research_id', 'user_id', name='uq_research_participant'),
    )

    @property
    def is_dropped_out(self) -> bool:
        return self.dropped_out_at is not None

    def __repr__(self) -> str:
        return f'<ResearchParticipant research={self.research_id} user={self.user_id}>'
