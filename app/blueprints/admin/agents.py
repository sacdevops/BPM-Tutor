"""Admin — AI agent management routes."""
from flask import jsonify, render_template, redirect, url_for, flash, request

from app.blueprints.admin import admin_bp
from app.extensions import db
from app.utils.decorators import admin_required
from app.utils.audit import log_action

from app.models.agent_prompt import ALL_PROMPT_TYPES, SYSTEM_PROMPT_TYPES, INTERACTION_PROMPT_TYPES

_VALID_COMPLETION_CONTROLS = ('human', 'shared', 'agent')
_VALID_MODELING_MODES = ('none', 'reactive', 'collaborative', 'ai_then_human', 'ai_only')

# Human-readable labels for each prompt type (used in the template)
PROMPT_TYPE_LABELS: dict = {
    'greeting':               {'label': 'Greeting (System)',          'hint': 'System role sent to the LLM when generating the opening task greeting.'},
    'analysis':               {'label': 'Analysis (System)',          'hint': 'System role used when the AI performs a BPMN model analysis.'},
    'reaction':               {'label': 'Reaction (System)',          'hint': 'System role used for every regular chat reply and routing decision.'},
    'modeling':               {'label': 'Modeling (System)',          'hint': 'System role used when the agent performs BPMN modeling operations. Called by the backend when Reaction routes to modeling.'},
    'completion':             {'label': 'Completion (System)',        'hint': 'System role used when the student requests task completion review.'},
    'greeting_user':          {'label': 'Greeting User Prompt',       'hint': 'User message template that drives greeting generation. Supports {task_description}.'},
    'reaction_user':          {'label': 'Reaction User Prompt',       'hint': 'User message template for regular chat calls. Placeholders are substituted only when explicitly present: {user_message}, {bpmn_lion}, {task_description}, {lion_context}.'},
    'analysis_user':          {'label': 'Analysis User Prompt',       'hint': 'User message template for analysis calls. Placeholders are substituted only when explicitly present: {user_message}, {bpmn_lion}, {task_description}, {lion_context}.'},
    'modeling_user':          {'label': 'Modeling User Prompt',       'hint': 'User message template for modeling calls. Placeholders are substituted only when explicitly present: {user_message}, {bpmn_lion}, {task_description}, {lion_context}.'},
    'completion_user':        {'label': 'Completion User Prompt',     'hint': 'User message template for completion review calls. Placeholders are substituted only when explicitly present: {user_message}, {bpmn_lion}, {task_description}, {lion_context}.'},
    'instruction_completion': {'label': 'Completion Instruction (legacy)', 'hint': 'Legacy: replaced by the Completion tab. Instruction used when the student submits a task-completion request.'},
    'modeling_hint':          {'label': 'Modeling Hint (legacy)',     'hint': 'Legacy: replaced by the Modeling tab. Appended to the instruction when modeling_mode is not none.'},
}


def _get_active_languages():
    from app.models.i18n import Language
    return Language.query.filter_by(is_active=True).order_by(Language.sort_order).all()


def _get_all_languages():
    from app.models.i18n import Language
    return Language.query.order_by(Language.sort_order).all()


def _get_prompt_map(agent) -> dict:
    """Return {(prompt_type, lang): content} for the given agent."""
    if agent is None:
        return {}
    return agent.get_prompts_dict()


def _get_default_prompt_map(agent_type: str) -> dict:
    """Return all built-in defaults as {(prompt_type, lang): content}."""
    from deploy.prompts import get_system_prompt
    from deploy.prompts import get_all_defaults
    result: dict = {}
    for pt in SYSTEM_PROMPT_TYPES:
        for lang in ('en', 'de'):
            val = get_system_prompt(agent_type or 'mentor', pt, lang)
            if val:
                result[(pt, lang)] = val
    result.update(get_all_defaults(agent_type or 'mentor'))
    return result


def _apply_agent_form(agent, form) -> None:
    """Apply identity/capability fields to an AIAgent. Does NOT touch prompts."""
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
    agent.can_model = (modeling_mode != 'none')

    agent.memory_enabled = 'memory_enabled' in form
    try:
        agent.memory_window = max(1, int(form.get('memory_window', 10) or 10))
    except (ValueError, TypeError):
        agent.memory_window = 10


def _apply_prompt_form(agent, form) -> None:
    """Upsert AgentPrompt rows from form fields named prompt__{lang}__{type}."""
    for key, value in form.items():
        if not key.startswith('prompt__'):
            continue
        parts = key.split('__', 2)
        if len(parts) != 3:
            continue
        _, lang, ptype = parts
        lang = lang.strip()
        ptype = ptype.strip()
        if not lang or ptype not in ALL_PROMPT_TYPES:
            continue
        agent.set_prompt(ptype, lang, value.strip() or None)


@admin_bp.route('/agents')
@admin_required
def agents_list():
    from app.models.agent import AIAgent
    agents = AIAgent.query.order_by(AIAgent.sort_order, AIAgent.created_at).all()
    return render_template('cms/admin/agents_list.html', agents=agents)


@admin_bp.route('/agents/prompt-preview', methods=['POST'])
@admin_required
def agent_prompt_preview():
    """Compile a prompt template with all variables resolved — used by the Vorschau modal."""
    from app.services.prompts._base import get_prompt_with_standards
    from app.models.agent_prompt import SYSTEM_PROMPT_TYPES

    data = request.get_json(silent=True) or {}
    text = data.get('text', '')
    lang = data.get('lang', 'en')
    ptype = data.get('ptype', 'reaction')

    is_runtime_only = ptype not in SYSTEM_PROMPT_TYPES

    try:
        if not is_runtime_only:
            compiled = get_prompt_with_standards(text, lang)
            # Ensure LION rules are always present for prompts requiring structured output
            if ptype in ('reaction', 'analysis') and 'Output Format -- LION Notation' not in compiled:
                from app.services.prompts._base import get_lion_format_rules
                compiled = compiled.rstrip() + '\n\n' + get_lion_format_rules()
        else:
            compiled = text
    except Exception as exc:
        return jsonify(error=str(exc)), 200  # return 200 so JS can display the error message

    tokens = -1
    try:
        import tiktoken
        enc = tiktoken.get_encoding('o200k_base')
        tokens = len(enc.encode(compiled))
    except Exception:
        pass

    return jsonify(compiled=compiled, tokens=tokens, chars=len(compiled),
                   is_runtime_only=is_runtime_only)


@admin_bp.route('/agents/new', methods=['GET', 'POST'])
@admin_required
def agent_create():
    from app.models.agent import AIAgent
    errors: dict = {}
    active_langs = _get_active_languages()
    all_langs = _get_all_languages()
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
            db.session.flush()
            _apply_prompt_form(agent, request.form)
            db.session.commit()
            log_action('create_agent', 'AIAgent', agent.id, {'name': agent.name})
            flash(f'Agent "{agent.name}" erstellt.', 'success')
            return redirect(url_for('admin.agents_list'))
    return render_template(
        'cms/admin/agent_edit.html',
        agent=None,
        errors=errors,
        mode='create',
        prompt_map={},
        default_prompt_map=_get_default_prompt_map('mentor'),
        active_langs=active_langs,
        all_langs=all_langs,
        prompt_type_labels=PROMPT_TYPE_LABELS,
        all_prompt_types=ALL_PROMPT_TYPES,
        system_prompt_types=SYSTEM_PROMPT_TYPES,
        interaction_prompt_types=INTERACTION_PROMPT_TYPES,
    )


@admin_bp.route('/agents/<agent_id>/edit', methods=['GET', 'POST'])
@admin_required
def agent_edit(agent_id: str):
    from app.models.agent import AIAgent
    agent = AIAgent.query.get_or_404(agent_id)
    errors: dict = {}
    active_langs = _get_active_languages()
    all_langs = _get_all_languages()
    if request.method == 'POST':
        if not request.form.get('name', '').strip():
            errors['name'] = 'Name ist erforderlich.'
        else:
            _apply_agent_form(agent, request.form)
            _apply_prompt_form(agent, request.form)
            db.session.commit()
            log_action('edit_agent', 'AIAgent', agent_id, {'name': agent.name})
            flash(f'Agent "{agent.name}" gespeichert.', 'success')
            return redirect(url_for('admin.agents_list'))
    return render_template(
        'cms/admin/agent_edit.html',
        agent=agent,
        errors=errors,
        mode='edit',
        prompt_map=_get_prompt_map(agent),
        default_prompt_map=_get_default_prompt_map(agent.agent_type),
        active_langs=active_langs,
        all_langs=all_langs,
        prompt_type_labels=PROMPT_TYPE_LABELS,
        all_prompt_types=ALL_PROMPT_TYPES,
        system_prompt_types=SYSTEM_PROMPT_TYPES,
        interaction_prompt_types=INTERACTION_PROMPT_TYPES,
    )


@admin_bp.route('/agents/<agent_id>/copy', methods=['POST'])
@admin_required
def agent_copy(agent_id: str):
    from app.models.agent import AIAgent
    from app.models.agent_prompt import AgentPrompt
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
    )
    db.session.add(copy)
    db.session.flush()

    for ap in AgentPrompt.query.filter_by(agent_id=source.id).all():
        db.session.add(AgentPrompt(
            agent_id=copy.id,
            prompt_type=ap.prompt_type,
            lang=ap.lang,
            content=ap.content,
        ))

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
    db.session.delete(agent)  # cascade deletes agent_prompts
    db.session.commit()
    log_action('delete_agent', 'AIAgent', agent_id, {'name': name})
    flash(f'Agent "{name}" gelöscht.', 'success')
    return redirect(url_for('admin.agents_list'))


@admin_bp.route('/agents/<agent_id>/reset-prompts', methods=['POST'])
@admin_required
def agent_reset_prompts(agent_id: str):
    from app.models.agent import AIAgent, SYSTEM_AGENT_TYPES
    agent = AIAgent.query.get_or_404(agent_id)
    if agent.agent_type not in SYSTEM_AGENT_TYPES:
        flash('Nur System-Agenten können zurückgesetzt werden.', 'warning')
        return redirect(url_for('admin.agent_edit', agent_id=agent_id))
    from deploy.prompts import get_system_prompt
    from deploy.prompts import get_all_defaults
    from deploy.prompts.defaults import GRADING_PROMPT

    for pt in SYSTEM_PROMPT_TYPES:
        for lang in ('en', 'de'):
            val = get_system_prompt(agent.agent_type, pt, lang)
            if val:
                agent.set_prompt(pt, lang, val)
    for (pt, lang), content in get_all_defaults(agent.agent_type).items():
        agent.set_prompt(pt, lang, content)
    for lang, content in GRADING_PROMPT.items():
        agent.set_prompt('grading', lang, content)

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
