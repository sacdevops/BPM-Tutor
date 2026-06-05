"""Admin — survey management routes."""
import json

from flask import render_template, redirect, url_for, flash, request, current_app
from flask_login import current_user

from app.blueprints.admin import admin_bp
from app.extensions import db
from app.models.task import Task
from app.models.survey import Survey, SurveyPage, SurveyQuestion
from app.utils.decorators import admin_required, tutor_or_admin_required


def _apply_survey_pages(survey: Survey, pages_data: list) -> None:
    """Persist survey pages and questions from the JSON builder payload."""
    for page_data in pages_data:
        page = SurveyPage(
            survey_id=survey.id,
            page_order=page_data.get('page_order', 0),
            title=page_data.get('title', ''),
            description=page_data.get('description', ''),
        )
        db.session.add(page)
        db.session.flush()
        for q_data in page_data.get('questions', []):
            q = SurveyQuestion(
                page_id=page.id,
                sort_order=q_data.get('sort_order', 0),
                question_type=q_data.get('type') or q_data.get('question_type', 'text'),
                label=q_data.get('label', ''),
                description=q_data.get('description', ''),
                required=q_data.get('required', False),
            )
            options = q_data.get('options', [])
            if options:
                q.options = options
            cfg = q_data.get('config', {})
            if cfg:
                q.config = cfg
            db.session.add(q)


# ── Surveys ───────────────────────────────────────────────────────────────────

@admin_bp.route('/surveys')
@tutor_or_admin_required
def surveys_list():
    surveys = Survey.query.order_by(Survey.created_at.desc()).all()
    return render_template('cms/admin/surveys_list.html', surveys=surveys)


@admin_bp.route('/surveys/new', methods=['GET', 'POST'])
@tutor_or_admin_required
def survey_create():
    tasks = Task.query.order_by(Task.sort_order).all()
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        allow_skip = bool(request.form.get('allow_skip'))
        pages_json = request.form.get('pages_json', '[]')

        if not name:
            flash('Name erforderlich.', 'danger')
            return render_template('cms/admin/survey_edit.html',
                                   survey=None, tasks=tasks)

        survey = Survey(
            name=name, survey_type='research', task_id=None,
            allow_skip=allow_skip, is_active=True,
            created_by_id=current_user.id,
        )
        db.session.add(survey)
        db.session.flush()

        try:
            pages_data = json.loads(pages_json)
            _apply_survey_pages(survey, pages_data)
        except Exception as e:
            current_app.logger.warning('Survey pages parse error: %s', e)

        db.session.commit()
        flash(f'Umfrage "{name}" erstellt.', 'success')
        return redirect(url_for('admin.surveys_list'))

    return render_template('cms/admin/survey_edit.html', survey=None, tasks=tasks)


@admin_bp.route('/surveys/<int:survey_id>/edit', methods=['GET', 'POST'])
@tutor_or_admin_required
def survey_edit(survey_id: int):
    survey = Survey.query.get_or_404(survey_id)
    tasks = Task.query.order_by(Task.sort_order).all()

    if request.method == 'POST':
        survey.name = request.form.get('name', survey.name).strip()
        survey.allow_skip = bool(request.form.get('allow_skip'))
        survey.is_active = bool(request.form.get('is_active'))
        pages_json = request.form.get('pages_json', '[]')

        for page in list(survey.pages):
            db.session.delete(page)
        db.session.flush()

        try:
            pages_data = json.loads(pages_json)
            _apply_survey_pages(survey, pages_data)
        except Exception as e:
            current_app.logger.warning('Survey pages parse error: %s', e)

        db.session.commit()
        flash('Umfrage gespeichert.', 'success')
        return redirect(url_for('admin.surveys_list'))

    return render_template('cms/admin/survey_edit.html', survey=survey, tasks=tasks)


@admin_bp.route('/surveys/<int:survey_id>/delete', methods=['POST'])
@admin_required
def survey_delete(survey_id: int):
    survey = Survey.query.get_or_404(survey_id)
    db.session.delete(survey)
    db.session.commit()
    flash('Umfrage gelöscht.', 'success')
    return redirect(url_for('admin.surveys_list'))
