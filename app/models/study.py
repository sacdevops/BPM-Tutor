"""Research Study models — Study, StudyCondition, StudyStep, StudyParticipant, StudyStepCompletion."""
from __future__ import annotations

from datetime import datetime, timezone

from app.extensions import db


# Study

class Study(db.Model):
    """A research study grouping tasks and surveys into a sequential flow."""
    __tablename__ = "studies"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(300), nullable=False)
    description = db.Column(db.Text, nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    # Archive — keeps all data, hides from active UI
    is_archived = db.Column(db.Boolean, default=False, nullable=False)
    archived_at = db.Column(db.DateTime, nullable=True)

    # Template / Clone support
    is_template = db.Column(db.Boolean, default=False, nullable=False)
    cloned_from_id = db.Column(db.Integer, db.ForeignKey("studies.id"), nullable=True)

    # Enrollment window
    enrollment_start = db.Column(db.DateTime, nullable=True)
    enrollment_end = db.Column(db.DateTime, nullable=True)
    allow_self_enrollment = db.Column(db.Boolean, default=True, nullable=False)
    max_participants = db.Column(db.Integer, nullable=True)

    # Global task availability window (overrides individual task dates when set)
    task_start = db.Column(db.DateTime, nullable=True)
    task_end = db.Column(db.DateTime, nullable=True)

    # One-time only: a participant can only complete this study once
    one_time_only = db.Column(db.Boolean, default=True, nullable=False)

    # Informed consent
    require_consent = db.Column(db.Boolean, default=False, nullable=False)
    consent_text = db.Column(db.Text, nullable=True)

    # Anonymization
    anonymize_export = db.Column(db.Boolean, default=True, nullable=False)

    # Leaderboard
    leaderboard_enabled = db.Column(db.Boolean, default=False, nullable=False)
    agent_display_name = db.Column(db.String(200), nullable=True)

    # Tracking config — JSON: {"enabled": bool, "events": ["mousemove", "click", ...]}
    tracking_config = db.Column(db.Text, nullable=True)

    # Experimental design: "within" or "between"
    study_design = db.Column(db.String(20), default="within", nullable=False)

    # Survey shown at enrollment (before study steps begin)
    enrollment_survey_id = db.Column(db.Integer, db.ForeignKey("surveys.id"), nullable=True)

    # Parent Research project (null = standalone study)
    research_id = db.Column(db.Integer, db.ForeignKey("researches.id", ondelete="SET NULL"), nullable=True, index=True)

    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)

    steps = db.relationship(
        "StudyStep", back_populates="study",
        order_by="StudyStep.step_order",
        cascade="all, delete-orphan", lazy="select",
        foreign_keys="StudyStep.study_id",
    )
    participants = db.relationship(
        "StudyParticipant", back_populates="study",
        cascade="all, delete-orphan", lazy="dynamic",
        foreign_keys="StudyParticipant.study_id",
    )
    conditions = db.relationship(
        "StudyCondition", back_populates="study",
        cascade="all, delete-orphan", lazy="select",
        foreign_keys="StudyCondition.study_id",
    )
    creator = db.relationship("User", foreign_keys=[created_by_id])
    clone_parent = db.relationship("Study", remote_side="Study.id", foreign_keys=[cloned_from_id])
    enrollment_survey = db.relationship("Survey", foreign_keys=[enrollment_survey_id], lazy="select")
    research = db.relationship("Research", foreign_keys=[research_id], back_populates="studies", lazy="select")

    @property
    def enrollment_open(self) -> bool:
        today = datetime.utcnow().date()
        if not self.allow_self_enrollment:
            return False
        if self.enrollment_start and today < self.enrollment_start.date():
            return False
        if self.enrollment_end and today > self.enrollment_end.date():
            return False
        return True

    @property
    def task_ids(self) -> list:
        return [s.task_id for s in self.steps if s.step_type == "task" and s.task_id]

    def get_effective_steps(self, participant):
        import json as _json
        cond_id = participant.condition_id if participant else None
        result = []
        for s in self.steps:
            # New multi-condition system
            if s.condition_ids is not None:
                try:
                    ids = _json.loads(s.condition_ids)
                except Exception:
                    ids = []
                if not ids or cond_id in ids:
                    result.append(s)
            # Legacy single condition_id
            elif s.condition_id is None or s.condition_id == cond_id:
                result.append(s)
        return result

    def get_step_for_participant(self, participant):
        effective = self.get_effective_steps(participant)
        if not effective:
            return None
        idx = participant.current_step
        if idx >= len(effective):
            return None
        return effective[idx]

    def get_step_count_for_participant(self, participant) -> int:
        return len(self.get_effective_steps(participant))

    def assign_condition(self, participant) -> None:
        if self.study_design != "between" or not self.conditions:
            return
        from sqlalchemy import func
        from app.models.study import StudyParticipant as SP
        # Single GROUP BY query instead of one COUNT per condition (O(1) vs O(k))
        rows = (
            db.session.query(SP.condition_id, func.count(SP.id))
            .filter(SP.study_id == self.id)
            .group_by(SP.condition_id)
            .all()
        )
        counts = {cond.id: 0 for cond in self.conditions}
        for cond_id, cnt in rows:
            if cond_id in counts:
                counts[cond_id] = cnt
        chosen_id = min(counts, key=lambda cid: counts[cid])
        participant.condition_id = chosen_id

    def __repr__(self):
        return f"<Study {self.id}: {self.title}>"


# StudyCondition

class StudyCondition(db.Model):
    __tablename__ = "study_conditions"

    id = db.Column(db.Integer, primary_key=True)
    study_id = db.Column(db.Integer, db.ForeignKey("studies.id", ondelete="CASCADE"),
                         nullable=False, index=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=True)
    target_size = db.Column(db.Integer, nullable=True)
    # AI agent assigned to this condition (between-subjects: each condition gets its own agent)
    agent_id = db.Column(db.String(36), db.ForeignKey("ai_agents.id", ondelete="SET NULL"),
                         nullable=True)

    study = db.relationship("Study", back_populates="conditions", foreign_keys=[study_id])
    agent = db.relationship("AIAgent", foreign_keys=[agent_id])

    def __repr__(self):
        return f"<StudyCondition {self.id}: {self.name}>"


# StudyStep

class StudyStep(db.Model):
    __tablename__ = "study_steps"

    id = db.Column(db.Integer, primary_key=True)
    study_id = db.Column(db.Integer, db.ForeignKey("studies.id", ondelete="CASCADE"),
                         nullable=False, index=True)
    step_order = db.Column(db.Integer, nullable=False, default=0)
    step_type = db.Column(db.String(20), nullable=False)
    survey_id = db.Column(db.Integer, db.ForeignKey("surveys.id", ondelete="SET NULL"), nullable=True)
    task_id = db.Column(db.String(100), db.ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True)
    label = db.Column(db.String(300), nullable=True)

    # Wave grouping (for timeline display, 0 = ungrouped)
    wave_number = db.Column(db.Integer, default=0, nullable=False)

    # Per-step availability window (overrides study-level when set)
    available_from = db.Column(db.DateTime, nullable=True)
    available_until = db.Column(db.DateTime, nullable=True)

    # Soft deadline
    allow_late_submission = db.Column(db.Boolean, default=False, nullable=False)
    late_penalty_note = db.Column(db.String(500), nullable=True)

    # Between-subjects: null = all conditions, set = only that condition (legacy single FK)
    condition_id = db.Column(db.Integer, db.ForeignKey("study_conditions.id", ondelete="SET NULL"),
                             nullable=True)
    # Multi-condition assignment: JSON list of condition IDs, empty/null = all conditions
    condition_ids = db.Column(db.Text, nullable=True)

    # Agent-choice step configuration
    available_agents = db.Column(db.Text, nullable=True)   # JSON [agent_id, ...]
    agent_choice_intro = db.Column(db.Text, nullable=True)

    study = db.relationship("Study", back_populates="steps", foreign_keys=[study_id])
    survey = db.relationship("Survey", foreign_keys=[survey_id])
    task = db.relationship("Task", foreign_keys=[task_id])
    condition = db.relationship("StudyCondition", foreign_keys=[condition_id])
    completions = db.relationship(
        "StudyStepCompletion", back_populates="step",
        cascade="all, delete-orphan", lazy="dynamic",
    )

    @property
    def display_label(self) -> str:
        if self.label:
            return self.label
        if self.step_type == "survey" and self.survey:
            return self.survey.name
        if self.step_type == "task" and self.task:
            return self.task.title
        if self.step_type == 'agent_choice':
            return 'Agenten-Auswahl'
        return f"Schritt {self.step_order + 1}"

    def get_availability(self, study):
        eff_from = self.available_from or study.task_start
        eff_until = self.available_until or study.task_end
        return eff_from, eff_until

    def is_available_now(self, study) -> bool:
        eff_from, eff_until = self.get_availability(study)
        now = datetime.utcnow()
        if eff_from and now < eff_from:
            return False
        if eff_until and now > eff_until:
            return self.allow_late_submission
        return True

    def is_past_deadline(self, study) -> bool:
        _, eff_until = self.get_availability(study)
        if not eff_until:
            return False
        return datetime.utcnow() > eff_until

    def __repr__(self):
        return f"<StudyStep study={self.study_id} order={self.step_order} type={self.step_type}>"


# StudyParticipant

class StudyParticipant(db.Model):
    __tablename__ = "study_participants"

    id = db.Column(db.Integer, primary_key=True)
    study_id = db.Column(db.Integer, db.ForeignKey("studies.id", ondelete="CASCADE"),
                         nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"),
                        nullable=False, index=True)

    enrolled_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    completed_at = db.Column(db.DateTime, nullable=True)
    dropped_out_at = db.Column(db.DateTime, nullable=True)
    dropout_reason = db.Column(db.String(500), nullable=True)

    current_step = db.Column(db.Integer, default=0, nullable=False)

    consent_given_at = db.Column(db.DateTime, nullable=True)
    condition_id = db.Column(db.Integer, db.ForeignKey("study_conditions.id", ondelete="SET NULL"),
                             nullable=True)
    notes = db.Column(db.Text, nullable=True)

    # Currently active agent chosen by participant via an agent_choice step
    active_agent_id = db.Column(db.String(36), db.ForeignKey("ai_agents.id", ondelete="SET NULL"), nullable=True)
    active_agent = db.relationship("AIAgent", foreign_keys=[active_agent_id])

    study = db.relationship("Study", back_populates="participants", foreign_keys=[study_id])
    user = db.relationship("User", foreign_keys=[user_id])
    condition = db.relationship("StudyCondition", foreign_keys=[condition_id])
    completions = db.relationship(
        "StudyStepCompletion", back_populates="participant",
        cascade="all, delete-orphan", lazy="dynamic",
    )

    __table_args__ = (
        db.UniqueConstraint("study_id", "user_id", name="uq_study_participant"),
    )

    @property
    def is_completed(self) -> bool:
        return self.completed_at is not None

    @property
    def is_dropped_out(self) -> bool:
        return self.dropped_out_at is not None

    @property
    def is_active(self) -> bool:
        return not self.is_completed and not self.is_dropped_out

    @property
    def progress_pct(self) -> int:
        if not self.study:
            return 0
        total = self.study.get_step_count_for_participant(self)
        if total == 0:
            return 0
        if self.is_completed:
            return 100
        return int(self.current_step / total * 100)

    @property
    def has_consent(self) -> bool:
        return self.consent_given_at is not None

    def __repr__(self):
        return f"<StudyParticipant study={self.study_id} user={self.user_id} step={self.current_step}>"


# StudyStepCompletion

class StudyStepCompletion(db.Model):
    """Records when a participant started and completed each individual step."""
    __tablename__ = "study_step_completions"

    id = db.Column(db.Integer, primary_key=True)
    participant_id = db.Column(
        db.Integer, db.ForeignKey("study_participants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    step_id = db.Column(
        db.Integer, db.ForeignKey("study_steps.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )

    started_at = db.Column(db.DateTime, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)
    time_spent_seconds = db.Column(db.Integer, nullable=True)
    is_late = db.Column(db.Boolean, default=False, nullable=False)

    participant = db.relationship("StudyParticipant", back_populates="completions",
                                  foreign_keys=[participant_id])
    step = db.relationship("StudyStep", back_populates="completions", foreign_keys=[step_id])

    __table_args__ = (
        db.UniqueConstraint("participant_id", "step_id", name="uq_step_completion"),
    )

    @property
    def time_spent_human(self) -> str:
        if not self.time_spent_seconds:
            return "-"
        secs = self.time_spent_seconds
        if secs < 60:
            return f"{secs}s"
        mins = secs // 60
        rem = secs % 60
        return f"{mins}m {rem}s" if rem else f"{mins}m"

    def __repr__(self):
        return f"<StudyStepCompletion participant={self.participant_id} step={self.step_id}>"


# AgentSwitchHistory

class AgentSwitchHistory(db.Model):
    """Records every agent choice made by a participant during a study."""
    __tablename__ = "agent_switch_history"

    id = db.Column(db.Integer, primary_key=True)
    participant_id = db.Column(
        db.Integer, db.ForeignKey("study_participants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    agent_id = db.Column(db.String(36), db.ForeignKey("ai_agents.id", ondelete="SET NULL"), nullable=True)
    previous_agent_id = db.Column(db.String(36), db.ForeignKey("ai_agents.id", ondelete="SET NULL"), nullable=True)
    step_id = db.Column(db.Integer, db.ForeignKey("study_steps.id", ondelete="SET NULL"), nullable=True)
    wave_number = db.Column(db.Integer, default=0, nullable=False)
    chosen_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    participant = db.relationship("StudyParticipant", foreign_keys=[participant_id],
                                  backref="agent_switches")
    agent = db.relationship("AIAgent", foreign_keys=[agent_id])
    previous_agent = db.relationship("AIAgent", foreign_keys=[previous_agent_id])
    step = db.relationship("StudyStep", foreign_keys=[step_id])

    def __repr__(self):
        return f"<AgentSwitchHistory participant={self.participant_id} agent={self.agent_id}>"
