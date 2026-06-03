"""AgentPrompt model — per-language prompt storage for AI agents.

Using a separate table (instead of per-language columns on AIAgent) means the
schema never changes when a new language is added.  The admin can configure
prompts for any language that is active in the system.
"""
from app.extensions import db


# All recognized prompt type identifiers.
# Grouped for display purposes:
#   System prompts  → used as the LLM "system" role message
#   Interaction prompts → used at runtime to shape agent behaviour
SYSTEM_PROMPT_TYPES = ('greeting', 'analysis', 'reaction', 'modeling', 'completion')
INTERACTION_PROMPT_TYPES = (
    'greeting_user',            # user message template to drive greeting generation
    'reaction_user',            # optional user message prefix for regular chat calls
    'analysis_user',            # optional user message prefix for analysis calls
    'modeling_user',            # optional user message prefix for modeling calls
    'completion_user',          # optional user message prefix for completion review calls
    'instruction_completion',   # kept for backward compat (replaced by completion tab)
    'modeling_hint',            # kept for backward compat (replaced by modeling tab)
)
ALL_PROMPT_TYPES = SYSTEM_PROMPT_TYPES + INTERACTION_PROMPT_TYPES


class AgentPrompt(db.Model):
    """Stores one prompt string for a given (agent, prompt_type, language) triple."""
    __tablename__ = 'agent_prompts'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    agent_id = db.Column(
        db.String(36),
        db.ForeignKey('ai_agents.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    prompt_type = db.Column(db.String(50), nullable=False)
    lang = db.Column(db.String(10), nullable=False)
    content = db.Column(db.Text, nullable=True)

    __table_args__ = (
        db.UniqueConstraint('agent_id', 'prompt_type', 'lang', name='uq_agent_prompt'),
    )

    def __repr__(self) -> str:
        return f'<AgentPrompt {self.agent_id}/{self.prompt_type}/{self.lang}>'
