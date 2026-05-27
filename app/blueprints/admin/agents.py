"""Admin — AI agent management routes."""
from flask import render_template, redirect, url_for, flash, request

from app.blueprints.admin import admin_bp
from app.extensions import db
from app.utils.decorators import admin_required
from app.utils.audit import log_action

_PROMPT_FIELDS = (
    'prompt_greeting_en', 'prompt_greeting_de',
    'prompt_analysis_en', 'prompt_analysis_de',
    'prompt_reaction_en', 'prompt_reaction_de',
)

_VALID_COMPLETION_CONTROLS = ('human', 'shared', 'agent')
_VALID_MODELING_MODES = ('none', 'collaborative', 'ai_then_human', 'ai_only')


def _get_prompt_defaults(agent_type: str) -> dict:
    """Return built-in default prompt strings for the given agent_type."""
    from app.services.prompts import get_system_prompt
    result = {}
    for pt in ('greeting', 'analysis', 'reaction'):
        for lang in ('en', 'de'):
            result[f'prompt_{pt}_{lang}'] = get_system_prompt(agent_type or 'mentor', pt, lang) or ''
    return result


def _apply_agent_form(agent, form) -> None:
    """Apply all form fields to an AIAgent. Handles is_default deduplication."""
    from app.models.agent import AIAgent
    is_default = bool(form.get('is_default'))
    if is_default and not agent.is_default:
        AIAgent.query.update({'is_default': False})
    agent.name = form.get('name', '').strip()
    agent.description = form.get('description', '').strip() or None
    agent.is_default = is_default

    control_mode = form.get('control_mode', 'human')
    if control_mode not in _VALID_COMPLETION_CONTROLS:
        control_mode = 'human'
    agent.control_mode = control_mode

    modeling_mode = form.get('modeling_mode', 'none')
    if modeling_mode not in _VALID_MODELING_MODES:
        modeling_mode = 'none'
    agent.modeling_mode = modeling_mode
    # Keep legacy can_model in sync
    agent.can_model = (modeling_mode != 'none')

    agent.use_standard = bool(form.get('use_standard'))
    agent.use_leveling = bool(form.get('use_leveling'))
    agent.use_research = bool(form.get('use_research'))
    for field in _PROMPT_FIELDS:
        setattr(agent, field, form.get(field, '').strip() or None)


@admin_bp.route('/agents')
@admin_required
def agents_list():
    from app.models.agent import AIAgent
    agents = AIAgent.query.order_by(AIAgent.sort_order, AIAgent.created_at).all()
    return render_template('cms/admin/agents_list.html', agents=agents)


@admin_bp.route('/agents/new', methods=['GET', 'POST'])
@admin_required
def agent_create():
    from app.models.agent import AIAgent
    errors: dict = {}
    if request.method == 'POST':
        if not request.form.get('name', '').strip():
            errors['name'] = 'Name ist erforderlich.'
        else:
            agent = AIAgent()
            agent.agent_type = 'custom'
            agent.is_system = False
            agent.sort_order = 99
            agent.is_active = True
            _apply_agent_form(agent, request.form)
            db.session.add(agent)
            db.session.commit()
            log_action('create_agent', 'AIAgent', agent.id, {'name': agent.name})
            flash(f'Agent "{agent.name}" erstellt.', 'success')
            return redirect(url_for('admin.agents_list'))
    return render_template('cms/admin/agent_edit.html', agent=None, errors=errors, mode='create',
                           prompt_defaults=_get_prompt_defaults('mentor'))


@admin_bp.route('/agents/<agent_id>/edit', methods=['GET', 'POST'])
@admin_required
def agent_edit(agent_id: str):
    from app.models.agent import AIAgent
    agent = AIAgent.query.get_or_404(agent_id)
    errors: dict = {}
    if request.method == 'POST':
        if not request.form.get('name', '').strip():
            errors['name'] = 'Name ist erforderlich.'
        else:
            _apply_agent_form(agent, request.form)
            db.session.commit()
            log_action('edit_agent', 'AIAgent', agent_id, {'name': agent.name})
            flash(f'Agent "{agent.name}" gespeichert.', 'success')
            return redirect(url_for('admin.agents_list'))
    return render_template('cms/admin/agent_edit.html', agent=agent, errors=errors, mode='edit',
                           prompt_defaults=_get_prompt_defaults(agent.agent_type))


@admin_bp.route('/agents/<agent_id>/copy', methods=['POST'])
@admin_required
def agent_copy(agent_id: str):
    from app.models.agent import AIAgent
    source = AIAgent.query.get_or_404(agent_id)

    copy = AIAgent(
        name=f'{source.name} (Kopie)',
        agent_type='custom',
        description=source.description,
        is_system=False,
        is_default=False,
        sort_order=99,
        is_active=True,
        control_mode=source.control_mode,
        modeling_mode=source.modeling_mode,
        can_model=source.can_model,
        use_standard=source.use_standard,
        use_leveling=source.use_leveling,
        use_research=source.use_research,
        prompt_greeting_en=source.prompt_greeting_en,
        prompt_greeting_de=source.prompt_greeting_de,
        prompt_analysis_en=source.prompt_analysis_en,
        prompt_analysis_de=source.prompt_analysis_de,
        prompt_reaction_en=source.prompt_reaction_en,
        prompt_reaction_de=source.prompt_reaction_de,
    )
    db.session.add(copy)
    db.session.commit()
    log_action('copy_agent', 'AIAgent', copy.id, {'source_id': source.id, 'name': copy.name})
    flash(f'Agent "{source.name}" wurde kopiert.', 'success')
    return redirect(url_for('admin.agent_edit', agent_id=copy.id))


@admin_bp.route('/agents/<agent_id>/delete', methods=['POST'])
@admin_required
def agent_delete(agent_id: str):
    from app.models.agent import AIAgent
    agent = AIAgent.query.get_or_404(agent_id)
    if agent.is_system:
        flash('System-Agenten können nicht gelöscht werden.', 'danger')
        return redirect(url_for('admin.agents_list'))
    name = agent.name
    db.session.delete(agent)
    db.session.commit()
    log_action('delete_agent', 'AIAgent', agent_id, {'name': name})
    flash(f'Agent "{name}" gelöscht.', 'success')
    return redirect(url_for('admin.agents_list'))


@admin_bp.route('/agents/<agent_id>/reset-prompts', methods=['POST'])
@admin_required
def agent_reset_prompts(agent_id: str):
    from app.models.agent import AIAgent
    from app.models.agent import SYSTEM_AGENT_TYPES
    agent = AIAgent.query.get_or_404(agent_id)
    if agent.agent_type not in SYSTEM_AGENT_TYPES:
        flash('Nur System-Agenten können zurückgesetzt werden.', 'warning')
        return redirect(url_for('admin.agent_edit', agent_id=agent_id))
    from app.services.prompts import get_system_prompt
    for pt in ('greeting', 'analysis', 'reaction'):
        for lang in ('en', 'de'):
            field = f'prompt_{pt}_{lang}'
            setattr(agent, field, get_system_prompt(agent.agent_type, pt, lang))
    db.session.commit()
    log_action('reset_agent_prompts', 'AIAgent', agent_id, {'name': agent.name})
    flash('Prompts auf Standard zurückgesetzt.', 'success')
    return redirect(url_for('admin.agent_edit', agent_id=agent_id))


@admin_bp.route('/agents/reset-all-prompts', methods=['POST'])
@admin_required
def agents_reset_all_prompts():
    """Reset prompts of ALL system agents to the latest built-in definitions."""
    from app.utils.seeder import reset_system_agent_prompts
    count = reset_system_agent_prompts()
    if count:
        log_action('reset_all_agent_prompts', 'AIAgent', None, {'count': count})
        flash(f'{count} System-Agenten wurden auf die aktuellen Standard-Prompts zurückgesetzt.', 'success')
    else:
        flash('Keine System-Agenten gefunden oder Reset fehlgeschlagen.', 'warning')
    return redirect(url_for('admin.agents_list'))

