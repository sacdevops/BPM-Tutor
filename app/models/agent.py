"""AI Agent model — configurable LLM agent definitions."""
from datetime import datetime, timezone
from uuid import uuid4

from app.extensions import db

# The five built-in system agent types — cannot be deleted by the admin.
SYSTEM_AGENT_TYPES = ('mentor', 'assistant', 'colleague', 'supervisor', 'delegant')


class AIAgent(db.Model):
    __tablename__ = 'ai_agents'

    id = db.Column(db.String(36), primary_key=True,
                   default=lambda: str(uuid4()))
    name = db.Column(db.String(100), nullable=False)
    agent_type = db.Column(db.String(50), nullable=False, default='custom')
    # ^ system types: 'mentor' | 'assistant' | 'colleague' | 'supervisor' | 'delegant'
    # ^ user-created copies: 'custom'
    description = db.Column(db.Text, nullable=True)
    is_system = db.Column(db.Boolean, default=False, nullable=False)
    # ^ True = built-in system agent, cannot be deleted
    is_default = db.Column(db.Boolean, default=False, nullable=False)
    sort_order = db.Column(db.Integer, default=0, nullable=False)

    # ── System prompts (EN / DE) ─────────────────────────────────────────────
    # greeting: system prompt used when the AI introduces itself at task start
    prompt_greeting_en = db.Column(db.Text, nullable=True)
    prompt_greeting_de = db.Column(db.Text, nullable=True)
    # analysis: system prompt used when the AI reviews the current BPMN model
    prompt_analysis_en = db.Column(db.Text, nullable=True)
    prompt_analysis_de = db.Column(db.Text, nullable=True)
    # reaction: system prompt used for follow-up chat messages
    prompt_reaction_en = db.Column(db.Text, nullable=True)
    prompt_reaction_de = db.Column(db.Text, nullable=True)

    # ── Capability flags ──────────────────────────────────────────────────────
    # modeling_mode: what the AI is allowed to do with the BPMN model
    #   'none'          – AI cannot model; student always drives the canvas
    #   'collaborative' – AI and student model together (shared canvas)
    #   'ai_then_human' – AI models first, student may then edit
    #   'ai_only'       – only the AI models; student watches
    modeling_mode = db.Column(db.String(20), default='none', nullable=False)

    # completion_control: who may close/submit the task
    #   'human'  – student decides when to submit
    #   'shared' – both student and AI must agree before submission
    #   'agent'  – AI decides when the task is complete
    control_mode = db.Column(db.String(20), default='human', nullable=False)

    # Legacy / kept for backwards-compat — not shown in the edit form
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    can_model = db.Column(db.Boolean, default=False, nullable=False)
    model_override = db.Column(db.String(100), nullable=True)

    # ── Mode assignment ──────────────────────────────────────────────────────
    # Which contexts this agent is used in (can select multiple)
    use_standard = db.Column(db.Boolean, default=True, nullable=False)   # regular task mode
    use_leveling = db.Column(db.Boolean, default=False, nullable=False)  # level system tasks
    use_research = db.Column(db.Boolean, default=False, nullable=False)  # research study tasks

    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc),
                           onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    def __repr__(self) -> str:
        return f'<AIAgent {self.agent_type}:{self.name}>'

    def get_prompt(self, prompt_type: str, lang: str = 'en') -> str | None:
        """Return the requested prompt for the given language, falling back to EN."""
        col = f'prompt_{prompt_type}_{lang}'
        val = getattr(self, col, None)
        if not val and lang != 'en':
            val = getattr(self, f'prompt_{prompt_type}_en', None)
        return val or None

    @classmethod
    def get_default(cls) -> 'AIAgent | None':
        """Return the default agent (prefers is_default=True, then first system agent, then any)."""
        agent = cls.query.filter_by(is_default=True).first()
        if agent is None:
            agent = cls.query.filter_by(is_system=True).order_by(
                cls.sort_order, cls.created_at).first()
        if agent is None:
            agent = cls.query.order_by(cls.sort_order, cls.created_at).first()
        return agent
