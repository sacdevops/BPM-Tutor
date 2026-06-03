"""Admin — task management routes."""
from flask import render_template, redirect, url_for, flash, request, jsonify
from flask_login import current_user

from app.blueprints.admin import admin_bp
from app.blueprints.admin._helpers import (
    _apply_task_form, _get_admin_api_key, _save_upload, _save_extra_translations,
)
from app.extensions import db
from app.models.task import Task
from app.models.cohort import Cohort
from app.utils.decorators import admin_required, tutor_or_admin_required
from app.utils.audit import log_action


def _task_form_context():
    from app.models.agent import AIAgent
    return {
        'all_tasks': [{'id': t.id, 'title': t.title} for t in Task.query.order_by(Task.sort_order).all()],
        'all_cohorts': [{'id': c.id, 'name': c.name} for c in Cohort.query.filter_by(is_active=True).all()],
        'agents': AIAgent.query.order_by(AIAgent.sort_order, AIAgent.name).all(),
    }


# ── Tasks ─────────────────────────────────────────────────────────────────────

@admin_bp.route('/tasks')
@tutor_or_admin_required
def tasks_list():
    q = request.args.get('q', '').strip()
    page = request.args.get('page', 1, type=int)
    query = Task.query.order_by(Task.sort_order, Task.created_at)
    if q:
        like = f'%{q}%'
        query = query.filter(db.or_(Task.title.ilike(like), Task.id.ilike(like)))
    pagination = query.paginate(page=page, per_page=50, error_out=False)
    return render_template('cms/admin/tasks_list.html', tasks=pagination.items, pagination=pagination, q=q)


@admin_bp.route('/tasks/new', methods=['GET', 'POST'])
@tutor_or_admin_required
def task_create():
    errors: dict = {}
    if request.method == 'POST':
        task_id = request.form.get('id', '').strip().lower().replace(' ', '_')
        title = request.form.get('title', '').strip()
        title_de = request.form.get('title_de', '').strip()
        description = request.form.get('description', '').strip()
        description_de = request.form.get('description_de', '').strip()
        bpmn_xml = request.form.get('bpmn_xml', '').strip()
        grading_type = request.form.get('grading_type', 'none')
        max_points_str = request.form.get('max_points', '').strip()
        available_from_str = request.form.get('available_from', '').strip()
        available_until_str = request.form.get('available_until', '').strip()
        sort_order = request.form.get('sort_order', 0, type=int)
        is_active = bool(request.form.get('is_active'))

        if not task_id:
            errors['id'] = 'ID erforderlich.'
        elif db.session.get(Task, task_id):
            errors['id'] = 'Diese Task-ID existiert bereits.'
        if not title:
            errors['title'] = 'Titel erforderlich.'
        if not description:
            errors['description'] = 'Beschreibung erforderlich.'

        available_from = None
        available_until = None
        if available_from_str:
            try:
                available_from = datetime.fromisoformat(available_from_str)
            except ValueError:
                errors['available_from'] = 'Ungültiges Datum.'
        if available_until_str:
            try:
                available_until = datetime.fromisoformat(available_until_str)
            except ValueError:
                errors['available_until'] = 'Ungültiges Datum.'

        max_points = None
        if grading_type == 'points' and max_points_str:
            try:
                max_points = float(max_points_str)
            except ValueError:
                errors['max_points'] = 'Ungültige Punktzahl.'

        image_path = None
        if 'image' in request.files:
            image_path = _save_upload(request.files['image'])

        if not errors:
            tl_str = request.form.get('time_limit_minutes', '').strip()
            time_limit_minutes = int(tl_str) if tl_str and tl_str.isdigit() else None
            hide_after_completion = bool(request.form.get('hide_after_completion'))
            agent_id = request.form.get('agent_id', '').strip() or None
            task = Task(
                id=task_id, title=title, title_de=title_de or None,
                description=description, description_de=description_de or None,
                bpmn_xml=bpmn_xml or None, image_path=image_path,
                grading_type=grading_type, max_points=max_points,
                available_from=available_from, available_until=available_until,
                time_limit_minutes=time_limit_minutes,
                hide_after_completion=hide_after_completion,
                sort_order=sort_order, is_active=is_active,
                agent_id=agent_id,
                task_mode=request.form.get('task_mode', 'standard') or 'standard',
                created_by_id=current_user.id,
            )
            _save_extra_translations(task, request.form)
            db.session.add(task)
            db.session.commit()
            flash(f'Aufgabe "{title}" erstellt.', 'success')
            return redirect(url_for('admin.tasks_list'))

    return render_template('cms/admin/task_edit.html', task=None, errors=errors,
                           **_task_form_context())


@admin_bp.route('/tasks/translate', methods=['POST'])
@tutor_or_admin_required
def task_translate():
    """LLM-powered translation of task content to a target language."""
    data = request.get_json(silent=True) or {}
    title_en = (data.get('title_en') or '').strip()
    desc_en = (data.get('desc_en') or '').strip()
    target_lang = (data.get('target_lang') or '').strip()
    target_lang_name = (data.get('target_lang_name') or target_lang).strip()

    if not target_lang or not (title_en or desc_en):
        return jsonify({'ok': False, 'error': 'Missing required fields'})

    try:
        from app.services.ai_service import AIService
        api_key, model, base_url = _get_admin_api_key()
        if not api_key:
            return jsonify({'ok': False, 'error': 'Kein API-Key konfiguriert.'})
        if not model:
            return jsonify({'ok': False, 'error': 'Kein Modell konfiguriert.'})

        results = {}
        for field, text in [('title', title_en), ('description', desc_en)]:
            if not text:
                results[field] = ''
                continue
            prompt = (
                f"Translate the following text 1:1 to {target_lang_name}. "
                f"Only translate, do not add, remove, or change any content. "
                f"Return ONLY the translation, no explanations.\n\n{text}"
            )
            resp = AIService._chat_completion(api_key, model,
                                              [{'role': 'user', 'content': prompt}], base_url)
            results[field] = resp['choices'][0]['message']['content'].strip()

        return jsonify({'ok': True, 'title': results.get('title', ''),
                        'description': results.get('description', '')})
    except Exception as exc:
        return jsonify({'ok': False, 'error': str(exc)})


@admin_bp.route('/tasks/<task_id>/edit', methods=['GET', 'POST'])
@tutor_or_admin_required
def task_edit(task_id: str):
    task = Task.query.get_or_404(task_id)
    errors: dict = {}
    if request.method == 'POST':
        errors = _apply_task_form(task, request.form)
        img = request.files.get('image')
        if img and img.filename:
            path = _save_upload(img)
            if path:
                task.image_path = path
        if not errors:
            _save_extra_translations(task, request.form)
            db.session.commit()
            flash('Aufgabe gespeichert.', 'success')
            return redirect(url_for('admin.tasks_list'))
    return render_template('cms/admin/task_edit.html', task=task, errors=errors,
                           **_task_form_context())


@admin_bp.route('/tasks/<task_id>/delete', methods=['POST'])
@admin_required
def task_delete(task_id: str):
    task = Task.query.get_or_404(task_id)
    title = task.title
    db.session.delete(task)
    db.session.commit()
    flash(f'Aufgabe "{title}" gelöscht.', 'success')
    return redirect(url_for('admin.tasks_list'))


@admin_bp.route('/tasks/reorder', methods=['POST'])
@tutor_or_admin_required
def tasks_reorder():
    order = request.json or []
    for item in order:
        task = db.session.get(Task, item.get('id'))
        if task:
            task.sort_order = item.get('order', 0)
    db.session.commit()
    return jsonify({'ok': True})


# ── Bulk task actions ─────────────────────────────────────────────────────────

@admin_bp.route('/tasks/bulk', methods=['POST'])
@admin_required
def tasks_bulk():
    task_ids = [int(i) for i in request.form.getlist('task_ids') if i.isdigit()]
    action = request.form.get('bulk_action', '')
    if not task_ids:
        flash('Keine Aufgaben ausgewählt.', 'warning')
        return redirect(url_for('admin.tasks_list'))
    tasks = Task.query.filter(Task.id.in_(task_ids)).all()
    if action == 'publish':
        for t in tasks:
            t.is_active = True
        db.session.commit()
        log_action('bulk_publish_tasks', 'Task', None, {'ids': task_ids})
        flash(f'{len(tasks)} Aufgaben veröffentlicht.', 'success')
    elif action == 'unpublish':
        for t in tasks:
            t.is_active = False
        db.session.commit()
        log_action('bulk_unpublish_tasks', 'Task', None, {'ids': task_ids})
        flash(f'{len(tasks)} Aufgaben versteckt.', 'success')
    elif action == 'delete':
        for t in tasks:
            db.session.delete(t)
        db.session.commit()
        log_action('bulk_delete_tasks', 'Task', None, {'ids': task_ids})
        flash(f'{len(tasks)} Aufgaben gelöscht.', 'success')
    else:
        flash('Unbekannte Aktion.', 'warning')
    return redirect(url_for('admin.tasks_list'))
