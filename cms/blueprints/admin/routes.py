"""Admin blueprint — dashboard, user management, task management."""
import io
import json
import os
import uuid
import zipfile
from datetime import datetime

from flask import (Blueprint, render_template, redirect, url_for,
                   flash, request, jsonify, current_app, abort, send_file)
from flask_login import current_user
from werkzeug.utils import secure_filename

from cms.extensions import db
from cms.models.user import User
from cms.models.task import Task, TaskSubmission
from cms.models.survey import Survey, SurveyPage, SurveyQuestion, SurveyResponse
from cms.models.settings import Notification, RegistrationField, Settings, SystemSetting
from cms.models.audit import AuditLog
from cms.models.cohort import Cohort, CohortMembership
from cms.models.i18n import Language, LanguageString
from cms.models.level import LearningLevel, UserLevelProgress
from cms.utils.decorators import admin_required, instructor_or_admin_required
from cms.utils.stats import (global_stats, user_stats, since_from_period,
                              chart_data_timeline, bpmn_error_frequency,
                              phase_distribution, task_analytics, cohort_analytics)
from cms.utils.email import send_grade_notification_email
from cms.utils.audit import log_action
from cms.utils.i18n_helper import invalidate_cache

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')

ALLOWED_IMAGE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp', 'svg'}


def _allowed_image(filename: str) -> bool:
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_IMAGE_EXTENSIONS


def _save_upload(file, subfolder: str = 'uploads') -> str | None:
    """Save an uploaded file, return the path relative to static root."""
    if not file or not file.filename:
        return None
    if not _allowed_image(file.filename):
        return None
    filename = secure_filename(f'{uuid.uuid4().hex}_{file.filename}')
    upload_dir = os.path.join(current_app.root_path, '..', 'data', subfolder)
    os.makedirs(upload_dir, exist_ok=True)
    filepath = os.path.join(upload_dir, filename)
    file.save(filepath)
    return f'/data-uploads/{subfolder}/{filename}'


def _save_extra_translations(task, form) -> None:
    """Persist extra language fields (title_XX, description_XX) into task.extra_translations."""
    from cms.models.i18n import Language
    extra = task.extra_translations_dict  # preserve any existing entries
    langs = Language.query.filter(
        Language.is_active == True,
        Language.code.notin_(['en', 'de'])
    ).all()
    for lang in langs:
        t_val = form.get(f'title_{lang.code}', '').strip()
        d_val = form.get(f'description_{lang.code}', '').strip()
        if t_val or d_val:
            extra[lang.code] = {k: v for k, v in {'title': t_val, 'description': d_val}.items() if v}
        else:
            extra.pop(lang.code, None)
    task.extra_translations_dict = extra


# ── Dashboard ────────────────────────────────────────────────────────────────

@admin_bp.route('/')
@admin_required
def dashboard():
    stats = global_stats()
    recent_subs = TaskSubmission.query.order_by(
        TaskSubmission.started_at.desc()).limit(10).all()
    return render_template('cms/admin/dashboard.html',
                           stats=stats, recent_subs=recent_subs)


# ── Users ────────────────────────────────────────────────────────────────────

@admin_bp.route('/users')
@admin_required
def users_list():
    q = request.args.get('q', '').strip()
    role_filter = request.args.get('role', '')
    page = request.args.get('page', 1, type=int)

    query = User.query
    if q:
        like = f'%{q}%'
        query = query.filter(
            db.or_(User.email.ilike(like), User.username.ilike(like),
                   User.first_name.ilike(like), User.last_name.ilike(like))
        )
    if role_filter:
        query = query.filter(User.role == role_filter)

    pagination = query.order_by(User.created_at.desc()).paginate(
        page=page, per_page=25, error_out=False)
    return render_template('cms/admin/users_list.html',
                           pagination=pagination, q=q, role_filter=role_filter)


@admin_bp.route('/users/create', methods=['GET', 'POST'])
@admin_required
def user_create():
    errors: dict = {}
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        role = request.form.get('role', 'student')
        first_name = request.form.get('first_name', '').strip()
        last_name = request.form.get('last_name', '').strip()
        verified = bool(request.form.get('is_verified'))

        if not email:
            errors['email'] = 'E-Mail erforderlich.'
        elif User.query.filter_by(email=email).first():
            errors['email'] = 'E-Mail bereits registriert.'
        if not username or len(username) < 3:
            errors['username'] = 'Benutzername (min. 3 Zeichen) erforderlich.'
        elif User.query.filter_by(username=username).first():
            errors['username'] = 'Benutzername bereits vergeben.'
        if not password or len(password) < 8:
            errors['password'] = 'Passwort (min. 8 Zeichen) erforderlich.'
        if role not in ('admin', 'instructor', 'student'):
            errors['role'] = 'Ungültige Rolle.'

        if not errors:
            user = User(
                email=email, username=username, role=role,
                first_name=first_name or None, last_name=last_name or None,
                is_active=True, is_verified=verified, data_consent=True,
            )
            user.set_password(password)
            db.session.add(user)
            db.session.commit()

            # Send verification email if user is not yet verified and mail is enabled
            if not verified and Settings.get(Settings.MAIL_ENABLED):
                from cms.utils.tokens import generate_email_token
                from cms.utils.email import send_verification_email
                token = generate_email_token(email)
                send_verification_email(user, token)
                flash(f'Benutzer {username} erstellt. Bestätigungs-E-Mail wurde gesendet.', 'success')
            else:
                flash(f'Benutzer {username} erstellt.', 'success')
            return redirect(url_for('admin.user_detail', user_id=user.id))

    return render_template('cms/admin/user_create.html', errors=errors)


@admin_bp.route('/users/<int:user_id>')
@admin_required
def user_detail(user_id: int):
    user = User.query.get_or_404(user_id)
    period = request.args.get('period', '30d')
    since = since_from_period(period)
    stats = user_stats(user.id, since)
    chart = chart_data_timeline(user.id, since, period)
    tasks = Task.query.order_by(Task.sort_order).all()
    return render_template('cms/admin/user_detail.html',
                           target_user=user, stats=stats, chart=chart,
                           period=period, tasks=tasks)


@admin_bp.route('/users/<int:user_id>/edit', methods=['POST'])
@admin_required
def user_edit(user_id: int):
    user = User.query.get_or_404(user_id)
    field = request.form.get('field')
    value = request.form.get('value')

    allowed_fields = {
        'role': ('admin', 'instructor', 'student'),
        'is_active': ('true', 'false'),
        'is_verified': ('true', 'false'),
        'is_locked': ('true', 'false'),
    }

    if field not in allowed_fields:
        return jsonify({'ok': False, 'error': 'Unknown field'}), 400

    if isinstance(allowed_fields[field], tuple) and value not in allowed_fields[field]:
        return jsonify({'ok': False, 'error': 'Invalid value'}), 400

    if field == 'role':
        # Prevent removing the only admin
        if user.role == 'admin' and value != 'admin':
            if User.query.filter_by(role='admin').count() <= 1:
                return jsonify({'ok': False, 'error': 'Letzten Admin nicht degradieren'}), 400
        user.role = value
    elif field in ('is_active', 'is_verified', 'is_locked'):
        setattr(user, field, value == 'true')

    db.session.commit()
    return jsonify({'ok': True})


@admin_bp.route('/users/<int:user_id>/reset-password', methods=['POST'])
@admin_required
def user_reset_password(user_id: int):
    user = User.query.get_or_404(user_id)
    new_pw = request.form.get('new_password', '').strip()
    if len(new_pw) < 8:
        flash('Passwort muss mindestens 8 Zeichen haben.', 'danger')
        return redirect(url_for('admin.user_detail', user_id=user_id))
    user.set_password(new_pw)
    db.session.commit()
    flash('Passwort wurde zurückgesetzt.', 'success')
    return redirect(url_for('admin.user_detail', user_id=user_id))


@admin_bp.route('/users/<int:user_id>/delete', methods=['POST'])
@admin_required
def user_delete(user_id: int):
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        flash('Du kannst deinen eigenen Account nicht löschen.', 'danger')
        return redirect(url_for('admin.users_list'))
    if user.role == 'admin' and User.query.filter_by(role='admin').count() <= 1:
        flash('Letzten Admin nicht löschen.', 'danger')
        return redirect(url_for('admin.users_list'))
    db.session.delete(user)
    db.session.commit()
    flash(f'Benutzer {user.username} gelöscht.', 'success')
    return redirect(url_for('admin.users_list'))


@admin_bp.route('/users/<int:user_id>/notify', methods=['POST'])
@admin_required
def user_notify(user_id: int):
    user = User.query.get_or_404(user_id)
    title = request.form.get('title', '').strip()
    message = request.form.get('message', '').strip()
    if not title:
        flash('Titel erforderlich.', 'danger')
        return redirect(url_for('admin.user_detail', user_id=user_id))
    notif = Notification(user_id=user_id, title=title, message=message, notif_type='message')
    db.session.add(notif)
    db.session.commit()
    flash('Benachrichtigung gesendet.', 'success')
    return redirect(url_for('admin.user_detail', user_id=user_id))


# ── Tasks ────────────────────────────────────────────────────────────────────

@admin_bp.route('/tasks')
@instructor_or_admin_required
def tasks_list():
    tasks = Task.query.order_by(Task.sort_order, Task.created_at).all()
    return render_template('cms/admin/tasks_list.html', tasks=tasks)


@admin_bp.route('/tasks/new', methods=['GET', 'POST'])
@instructor_or_admin_required
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
        elif Task.query.get(task_id):
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
            task = Task(
                id=task_id, title=title, title_de=title_de or None,
                description=description, description_de=description_de or None,
                bpmn_xml=bpmn_xml or None, image_path=image_path,
                grading_type=grading_type, max_points=max_points,
                available_from=available_from, available_until=available_until,
                sort_order=sort_order, is_active=is_active,
                created_by_id=current_user.id,
            )
            # Save extra translations for languages beyond EN/DE
            _save_extra_translations(task, request.form)
            db.session.add(task)
            db.session.commit()
            flash(f'Aufgabe "{title}" erstellt.', 'success')
            return redirect(url_for('admin.tasks_list'))

    _all_tasks = [{'id': t.id, 'title': t.title} for t in Task.query.order_by(Task.sort_order).all()]
    _all_cohorts = [{'id': c.id, 'name': c.name} for c in Cohort.query.filter_by(is_active=True).all()]
    return render_template('cms/admin/task_edit.html', task=None, errors=errors,
                           all_tasks=_all_tasks, all_cohorts=_all_cohorts)


@admin_bp.route('/tasks/<task_id>/edit', methods=['GET', 'POST'])
@instructor_or_admin_required
def task_edit(task_id: str):
    task = Task.query.get_or_404(task_id)
    errors: dict = {}

    if request.method == 'POST':
        task.title = request.form.get('title', task.title).strip()
        task.title_de = request.form.get('title_de', '').strip() or None
        task.description = request.form.get('description', task.description).strip()
        task.description_de = request.form.get('description_de', '').strip() or None
        task.bpmn_xml = request.form.get('bpmn_xml', '').strip() or None
        task.grading_type = request.form.get('grading_type', 'none')
        task.sort_order = request.form.get('sort_order', task.sort_order, type=int)
        task.is_active = bool(request.form.get('is_active'))

        mp_str = request.form.get('max_points', '').strip()
        task.max_points = float(mp_str) if mp_str else None

        af_str = request.form.get('available_from', '').strip()
        au_str = request.form.get('available_until', '').strip()
        task.available_from = datetime.fromisoformat(af_str) if af_str else None
        task.available_until = datetime.fromisoformat(au_str) if au_str else None

        prereq_raw = request.form.get('prerequisites_json', '[]').strip()
        try:
            import json
            task.prerequisites = prereq_raw if prereq_raw else None
        except Exception:
            pass

        if 'image' in request.files and request.files['image'].filename:
            image_path = _save_upload(request.files['image'])
            if image_path:
                task.image_path = image_path

        if not task.title:
            errors['title'] = 'Titel erforderlich.'
        if not task.description:
            errors['description'] = 'Beschreibung erforderlich.'

        if not errors:
            _save_extra_translations(task, request.form)
            db.session.commit()
            flash('Aufgabe gespeichert.', 'success')
            return redirect(url_for('admin.tasks_list'))

    _all_tasks = [{'id': t.id, 'title': t.title} for t in Task.query.order_by(Task.sort_order).all()]
    _all_cohorts = [{'id': c.id, 'name': c.name} for c in Cohort.query.filter_by(is_active=True).all()]
    return render_template('cms/admin/task_edit.html', task=task, errors=errors,
                           all_tasks=_all_tasks, all_cohorts=_all_cohorts)


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
@instructor_or_admin_required
def tasks_reorder():
    order = request.json or []
    for item in order:
        task = Task.query.get(item.get('id'))
        if task:
            task.sort_order = item.get('order', 0)
    db.session.commit()
    return jsonify({'ok': True})


# ── Grading ──────────────────────────────────────────────────────────────────

@admin_bp.route('/grading')
@instructor_or_admin_required
def grading_list():
    task_filter = request.args.get('task_id', '')
    graded_filter = request.args.get('graded', '')
    page = request.args.get('page', 1, type=int)

    query = TaskSubmission.query.filter(TaskSubmission.completed_at.isnot(None))
    if task_filter:
        query = query.filter(TaskSubmission.task_id == task_filter)
    if graded_filter == 'yes':
        query = query.filter(
            db.or_(TaskSubmission.grade_value.isnot(None),
                   TaskSubmission.grade_passed.isnot(None))
        )
    elif graded_filter == 'no':
        query = query.filter(
            TaskSubmission.grade_value.is_(None),
            TaskSubmission.grade_passed.is_(None)
        )

    pagination = query.order_by(TaskSubmission.completed_at.desc()).paginate(
        page=page, per_page=25, error_out=False)
    tasks = Task.query.order_by(Task.sort_order).all()
    return render_template('cms/admin/grading_list.html',
                           pagination=pagination, tasks=tasks,
                           task_filter=task_filter, graded_filter=graded_filter)


@admin_bp.route('/grading/<int:sub_id>', methods=['GET', 'POST'])
@instructor_or_admin_required
def grading_detail(sub_id: int):
    submission = TaskSubmission.query.get_or_404(sub_id)
    task = Task.query.get(submission.task_id)

    if request.method == 'POST':
        grading_type = request.form.get('grading_type', 'none')
        comment = request.form.get('comment', '').strip()
        send_notif = bool(request.form.get('send_notification'))

        if grading_type == 'points':
            grade_val = request.form.get('grade_value', '')
            try:
                submission.grade_value = float(grade_val)
            except ValueError:
                flash('Ungültiger Punktwert.', 'danger')
                return redirect(request.url)
            submission.grade_passed = None
        elif grading_type == 'pass_fail':
            submission.grade_passed = request.form.get('grade_passed') == 'true'
            submission.grade_value = None
        else:
            submission.grade_value = None
            submission.grade_passed = None

        submission.grade_comment = comment or None
        submission.graded_by_id = current_user.id
        submission.graded_at = datetime.utcnow()

        # Save BPMN annotations (validated JSON from hidden field)
        raw_annots = request.form.get('grade_annotations', '[]').strip()
        try:
            json.loads(raw_annots)  # validate
            submission.grade_annotations = raw_annots
        except Exception:
            pass  # keep existing value if invalid

        db.session.commit()

        # Notification
        if submission.user_id and send_notif:
            grade_info = ''
            if submission.grade_value is not None:
                grade_info = f'{submission.grade_value} / {task.max_points or "?"} Punkte'
            elif submission.grade_passed is not None:
                grade_info = 'Bestanden' if submission.grade_passed else 'Nicht bestanden'

            notif = Notification(
                user_id=submission.user_id,
                notif_type='grade',
                title=f'Aufgabe bewertet: {task.title if task else submission.task_id}',
                message=f'{grade_info}\n{comment}' if comment else grade_info,
                link=url_for('user_bp.my_submissions'),
            )
            db.session.add(notif)
            db.session.commit()

            if submission.user and task:
                send_grade_notification_email(submission.user, task.title, grade_info)

        flash('Bewertung gespeichert.', 'success')
        return redirect(url_for('admin.grading_list'))

    return render_template('cms/admin/grading_detail.html',
                           submission=submission, task=task)


# ── Surveys ──────────────────────────────────────────────────────────────────

@admin_bp.route('/surveys')
@instructor_or_admin_required
def surveys_list():
    surveys = Survey.query.order_by(Survey.created_at.desc()).all()
    return render_template('cms/admin/surveys_list.html', surveys=surveys)


@admin_bp.route('/surveys/new', methods=['GET', 'POST'])
@instructor_or_admin_required
def survey_create():
    tasks = Task.query.order_by(Task.sort_order).all()
    if request.method == 'POST':
        import json
        name = request.form.get('name', '').strip()
        survey_type = request.form.get('survey_type', 'pre_all')
        task_id = request.form.get('task_id', '') or None
        allow_skip = bool(request.form.get('allow_skip'))
        pages_json = request.form.get('pages_json', '[]')

        if not name:
            flash('Name erforderlich.', 'danger')
            return render_template('cms/admin/survey_edit.html',
                                   survey=None, tasks=tasks)

        survey = Survey(
            name=name, survey_type=survey_type, task_id=task_id,
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
@instructor_or_admin_required
def survey_edit(survey_id: int):
    survey = Survey.query.get_or_404(survey_id)
    tasks = Task.query.order_by(Task.sort_order).all()

    if request.method == 'POST':
        import json
        survey.name = request.form.get('name', survey.name).strip()
        survey.survey_type = request.form.get('survey_type', survey.survey_type)
        survey.task_id = request.form.get('task_id', '') or None
        survey.allow_skip = bool(request.form.get('allow_skip'))
        survey.is_active = bool(request.form.get('is_active'))
        pages_json = request.form.get('pages_json', '[]')

        # Clear and re-apply pages
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


def _apply_survey_pages(survey: Survey, pages_data: list) -> None:
    """Persist survey pages and questions from the JSON builder payload."""
    import json
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


# ── Registration Fields ──────────────────────────────────────────────────────

@admin_bp.route('/settings/registration-fields', methods=['GET', 'POST'])
@admin_required
def registration_fields():
    if request.method == 'POST':
        import json
        fields_json = request.form.get('fields_json', '[]')
        try:
            fields_data = json.loads(fields_json)
            # Replace all fields
            RegistrationField.query.delete()
            for i, fd in enumerate(fields_data):
                field = RegistrationField(
                    name=fd.get('name', f'field_{i}'),
                    label=fd.get('label', ''),
                    label_de=fd.get('label_de', '') or None,
                    field_type=fd.get('field_type', 'text'),
                    required=fd.get('required', False),
                    sort_order=i,
                    is_active=True,
                )
                opts = fd.get('options', [])
                if opts:
                    field.options = opts
                db.session.add(field)
            db.session.commit()
            flash('Registrierungsfelder gespeichert.', 'success')
        except Exception as e:
            flash(f'Fehler beim Speichern: {e}', 'danger')
        return redirect(url_for('admin.registration_fields'))

    fields = RegistrationField.query.order_by(RegistrationField.sort_order).all()
    return render_template('cms/admin/registration_fields.html', fields=fields)


# ── System Settings ──────────────────────────────────────────────────────────

@admin_bp.route('/settings', methods=['GET', 'POST'])
@admin_required
def settings():
    from cms.models.i18n import Language as _Lang
    active_languages = _Lang.query.filter_by(is_active=True).order_by(_Lang.sort_order).all()
    if request.method == 'POST':
        import base64
        mapping = {
            Settings.AUTH_REQUIRED: bool(request.form.get('auth_required')),
            Settings.ALLOW_REGISTRATION: bool(request.form.get('allow_registration')),
            Settings.REQUIRE_EMAIL_VERIFICATION: bool(request.form.get('require_email_verification')),
            Settings.LEVEL_SYSTEM_ENABLED: bool(request.form.get('level_system_enabled')),
            Settings.API_KEY_MODE: request.form.get('api_key_mode', 'per_user'),
            Settings.GLOBAL_API_KEY: request.form.get('global_api_key', '').strip(),
            Settings.API_ENDPOINT: request.form.get('api_endpoint', '').strip(),
            Settings.DEFAULT_MODEL: request.form.get('default_model', '').strip(),
            Settings.MAIL_ENABLED: bool(request.form.get('mail_enabled')),
            Settings.MAIL_SERVER: request.form.get('mail_server', '').strip(),
            Settings.MAIL_PORT: request.form.get('mail_port', '587').strip(),
            Settings.MAIL_USE_TLS: request.form.get('mail_encryption') == 'starttls',
            Settings.MAIL_USE_SSL: request.form.get('mail_encryption') == 'ssl',
            Settings.MAIL_USERNAME: request.form.get('mail_username', '').strip(),
            Settings.MAIL_PASSWORD: request.form.get('mail_password', '').strip(),
            Settings.MAIL_DEFAULT_SENDER: request.form.get('mail_default_sender', '').strip(),
            Settings.MAIL_SEPARATE_INCOMING: bool(request.form.get('mail_separate_incoming')),
            Settings.MAIL_INCOMING_PROTOCOL: request.form.get('mail_incoming_protocol', 'imap').strip(),
            Settings.MAIL_INCOMING_SERVER: request.form.get('mail_incoming_server', '').strip(),
            Settings.MAIL_INCOMING_PORT: request.form.get('mail_incoming_port', '993').strip(),
            Settings.MAIL_INCOMING_USE_TLS: bool(request.form.get('mail_incoming_use_tls')),
            Settings.MAIL_INCOMING_USERNAME: request.form.get('mail_incoming_username', '').strip(),
            Settings.MAIL_INCOMING_PASSWORD: request.form.get('mail_incoming_password', '').strip(),
            Settings.SITE_NAME: request.form.get('site_name_en', request.form.get('site_name', 'BPM-Tutor')).strip(),
            Settings.BRAND_PRIMARY: request.form.get('brand_primary', '#84BD00').strip(),
            Settings.BRAND_SIDEBAR_BG: request.form.get('brand_sidebar_bg', '#162700').strip(),
            Settings.BRAND_LOGO_URL: request.form.get('brand_logo_url', '').strip(),
            Settings.BRAND_LOGO_LINK: request.form.get('brand_logo_link', '/').strip(),
            Settings.SITE_TAGLINE: request.form.get('site_tagline', '').strip(),
            Settings.SITE_TAGLINE_DE: request.form.get('site_tagline_de', '').strip(),
            Settings.MAIL_VERIFY_SUBJECT: request.form.get('mail_verify_subject', '').strip(),
            Settings.MAIL_VERIFY_BODY: request.form.get('mail_verify_body', '').strip(),
            Settings.MAIL_RESET_SUBJECT: request.form.get('mail_reset_subject', '').strip(),
            Settings.MAIL_RESET_BODY: request.form.get('mail_reset_body', '').strip(),
        }

        # Dynamic site names per active language
        for _al in active_languages:
            _val = request.form.get(f'site_name_{_al.code}', '').strip()
            if _val:
                _key = Settings.SITE_NAME if _al.code == 'en' else f'site_name_{_al.code}'
                mapping[_key] = _val

        # Handle logo file upload (takes precedence over URL if provided)
        logo_file = request.files.get('brand_logo_file')
        if logo_file and logo_file.filename:
            allowed_mime = {'image/png', 'image/jpeg', 'image/gif', 'image/webp', 'image/svg+xml'}
            mime = logo_file.mimetype or 'image/png'
            if mime in allowed_mime and logo_file.content_length <= 2 * 1024 * 1024:
                logo_bytes = logo_file.read()
                if len(logo_bytes) <= 2 * 1024 * 1024:
                    mapping[Settings.BRAND_LOGO_DATA] = base64.b64encode(logo_bytes).decode('ascii')
                    mapping[Settings.BRAND_LOGO_MIME] = mime
                    mapping[Settings.BRAND_LOGO_URL] = ''  # clear URL when file uploaded
                else:
                    flash('Logo-Datei ist zu groß (max. 2 MB).', 'warning')
            else:
                flash('Ungültiges Logo-Format. Erlaubt: PNG, JPG, GIF, WEBP, SVG.', 'warning')
        elif request.form.get('logo_action') == 'clear':
            mapping[Settings.BRAND_LOGO_DATA] = ''
            mapping[Settings.BRAND_LOGO_MIME] = 'image/png'

        Settings.set_many(mapping)
        # Apply mail settings to live app config and re-init Flask-Mail
        from flask import current_app
        enc = request.form.get('mail_encryption', 'starttls')
        current_app.config['MAIL_SERVER'] = mapping.get(Settings.MAIL_SERVER, '')
        current_app.config['MAIL_PORT'] = int(mapping.get(Settings.MAIL_PORT, 587) or 587)
        current_app.config['MAIL_USE_TLS'] = enc == 'starttls'
        current_app.config['MAIL_USE_SSL'] = enc == 'ssl'
        current_app.config['MAIL_USERNAME'] = mapping.get(Settings.MAIL_USERNAME, '')
        current_app.config['MAIL_PASSWORD'] = mapping.get(Settings.MAIL_PASSWORD, '')
        current_app.config['MAIL_DEFAULT_SENDER'] = mapping.get(Settings.MAIL_DEFAULT_SENDER, '')
        from cms.extensions import mail as _mail_ext
        _mail_ext.init_app(current_app)
        flash('Einstellungen gespeichert.', 'success')
        return redirect(url_for('admin.settings'))

    current_settings = {
        row.key: Settings._cast(row.value, row.value_type)
        for row in SystemSetting.query.all()
    }
    return render_template('cms/admin/settings.html', s=current_settings, Settings=Settings,
                           active_languages=active_languages)


# ── Test mail connection ──────────────────────────────────────────────────────

@admin_bp.route('/settings/test-mail', methods=['POST'])
@admin_required
def test_mail():
    """AJAX endpoint: test SMTP connectivity and send a test email to the current admin."""
    import smtplib
    import socket
    from flask import jsonify
    from flask_login import current_user

    server = Settings.get(Settings.MAIL_SERVER, '').strip()
    try:
        port = int(Settings.get(Settings.MAIL_PORT, 587) or 587)
    except (TypeError, ValueError):
        port = 587
    use_tls = bool(Settings.get(Settings.MAIL_USE_TLS, False))
    use_ssl = bool(Settings.get(Settings.MAIL_USE_SSL, False))
    username = Settings.get(Settings.MAIL_USERNAME, '') or ''
    password = Settings.get(Settings.MAIL_PASSWORD, '') or ''
    sender = Settings.get(Settings.MAIL_DEFAULT_SENDER, '') or username or 'noreply@bpmtutor.local'

    if not server:
        return jsonify(ok=False, msg='Kein SMTP-Server konfiguriert. Bitte zuerst speichern.')

    # Step 1: test raw TCP + SMTP handshake via smtplib
    try:
        if use_ssl:
            conn = smtplib.SMTP_SSL(server, port, timeout=10)
        else:
            conn = smtplib.SMTP(server, port, timeout=10)
            if use_tls:
                conn.ehlo()
                conn.starttls()
                conn.ehlo()
        if username:
            conn.login(username, password)
        conn.quit()
    except socket.timeout:
        return jsonify(ok=False,
                       msg=f'Verbindungs-Timeout zu {server}:{port}. '
                           f'Prüfe Server-Adresse, Port und ob du im richtigen Netzwerk (VPN?) bist.')
    except ConnectionRefusedError as exc:
        enc_hint = 'STARTTLS (Port 587)' if not use_ssl else 'SSL/TLS (Port 465)'
        return jsonify(ok=False,
                       msg=f'Verbindung zu {server}:{port} verweigert. '
                           f'Port {port} ist möglicherweise durch eine Firewall blockiert. '
                           f'Versuche {enc_hint} oder prüfe ob VPN benötigt wird. '
                           f'Details: {exc}')
    except smtplib.SMTPAuthenticationError as exc:
        return jsonify(ok=False,
                       msg=f'Verbindung erfolgreich, aber Anmeldung fehlgeschlagen. '
                           f'Benutzername oder Passwort falsch. Details: {exc}')
    except smtplib.SMTPException as exc:
        return jsonify(ok=False, msg=f'SMTP-Fehler: {exc}')
    except OSError as exc:
        return jsonify(ok=False,
                       msg=f'Netzwerkfehler beim Verbinden zu {server}:{port}: {exc}')

    # Step 2: send actual test email via Flask-Mail
    try:
        from flask_mail import Message
        from cms.extensions import mail as _mail
        msg = Message(
            subject='BPM-Tutor – Verbindungstest',
            sender=sender,
            recipients=[current_user.email],
            html=('<h2>Test erfolgreich</h2>'
                  '<p>Die SMTP-Konfiguration ist korrekt. '
                  'E-Mail-Versand funktioniert.</p>'),
            body='Test erfolgreich. Die SMTP-Konfiguration ist korrekt.',
        )
        _mail.send(msg)
    except Exception as exc:  # noqa: BLE001
        return jsonify(ok=False,
                       msg=f'SMTP-Verbindung OK, aber Senden fehlgeschlagen: {exc}')

    return jsonify(ok=True,
                   msg=f'Test-E-Mail erfolgreich an {current_user.email} gesendet.')


# ── Database export / import ─────────────────────────────────────────────────

@admin_bp.route('/settings/db-export')
@admin_required
def db_export():
    """Download the current SQLite database file."""
    import os
    from flask import send_file, current_app
    db_uri = current_app.config.get('SQLALCHEMY_DATABASE_URI', '')
    # Strip 'sqlite:///' prefix
    db_path = db_uri.replace('sqlite:///', '', 1) if db_uri.startswith('sqlite:///') else ''
    if not db_path or not os.path.isfile(db_path):
        flash('Datenbankdatei nicht gefunden.', 'danger')
        return redirect(url_for('admin.settings'))
    from datetime import datetime
    filename = f'bpmtutor_backup_{datetime.now().strftime("%Y%m%d_%H%M%S")}.db'
    return send_file(db_path, as_attachment=True, download_name=filename,
                     mimetype='application/octet-stream')


@admin_bp.route('/settings/db-import', methods=['POST'])
@admin_required
def db_import():
    """Replace the database with an uploaded SQLite file."""
    import os, shutil, sqlite3, tempfile
    from flask import current_app
    uploaded = request.files.get('db_file')
    if not uploaded or not uploaded.filename:
        flash('Keine Datei ausgewählt.', 'warning')
        return redirect(url_for('admin.settings'))

    db_uri = current_app.config.get('SQLALCHEMY_DATABASE_URI', '')
    db_path = db_uri.replace('sqlite:///', '', 1) if db_uri.startswith('sqlite:///') else ''
    if not db_path:
        flash('Datenbankpfad konnte nicht ermittelt werden.', 'danger')
        return redirect(url_for('admin.settings'))

    # Save upload to a temp file for validation
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.db')
    try:
        uploaded.save(tmp.name)
        tmp.close()

        # Validate: check SQLite magic bytes
        with open(tmp.name, 'rb') as fh:
            magic = fh.read(16)
        if not magic.startswith(b'SQLite format 3\x00'):
            flash('Ungültige Datei — keine gültige SQLite-Datenbank.', 'danger')
            return redirect(url_for('admin.settings'))

        # Validate: try to open and read
        try:
            check = sqlite3.connect(tmp.name)
            check.execute('SELECT name FROM sqlite_master LIMIT 1').fetchall()
            check.close()
        except sqlite3.DatabaseError as exc:
            flash(f'Datenbankdatei ist beschädigt: {exc}', 'danger')
            return redirect(url_for('admin.settings'))

        # Backup current DB before replacing
        if os.path.isfile(db_path):
            shutil.copy2(db_path, db_path + '.bak')

        # Replace DB (close all connections first via SQLAlchemy)
        from cms.extensions import db as _db
        _db.session.remove()
        _db.engine.dispose()
        shutil.copy2(tmp.name, db_path)

        flash('Datenbank erfolgreich importiert. Bitte starte den Server neu, um alle Änderungen zu übernehmen.', 'success')
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass

    return redirect(url_for('admin.settings'))


# ── Broadcast notification ───────────────────────────────────────────────────

@admin_bp.route('/notify-all', methods=['POST'])
@admin_required
def notify_all():
    title = request.form.get('title', '').strip()
    message = request.form.get('message', '').strip()
    role_filter = request.form.get('role', '')

    if not title:
        flash('Titel erforderlich.', 'danger')
        return redirect(url_for('admin.dashboard'))

    query = User.query.filter_by(is_active=True)
    if role_filter:
        query = query.filter_by(role=role_filter)

    notifs = [
        Notification(user_id=u.id, title=title, message=message, notif_type='system')
        for u in query.all()
    ]
    db.session.bulk_save_objects(notifs)
    db.session.commit()
    flash(f'{len(notifs)} Benachrichtigungen gesendet.', 'success')
    return redirect(url_for('admin.dashboard'))


# ── API endpoints for admin JS ───────────────────────────────────────────────

@admin_bp.route('/api/stats')
@instructor_or_admin_required
def api_stats():
    period = request.args.get('period', '30d')
    since = since_from_period(period)
    stats = global_stats(since)
    chart = chart_data_timeline(None, since, period)
    return jsonify({'stats': stats, 'chart': chart})


@admin_bp.route('/api/user-stats/<int:user_id>')
@instructor_or_admin_required
def api_user_stats(user_id: int):
    period = request.args.get('period', '30d')
    since = since_from_period(period)
    stats = user_stats(user_id, since)
    chart = chart_data_timeline(user_id, since, period)
    return jsonify({'stats': stats, 'chart': chart})


# ── AI-grading suggestion ─────────────────────────────────────────────────────

@admin_bp.route('/grading/<int:sub_id>/ai-suggest', methods=['POST'])
@instructor_or_admin_required
def grading_ai_suggest(sub_id: int):
    sub = TaskSubmission.query.get_or_404(sub_id)
    task = Task.query.get(sub.task_id)
    if not task:
        return jsonify({'error': 'Task not found'}), 404
    try:
        from app.ai_service import AIService
        ai = AIService()
        result = ai.generate_grade_suggestion(
            task_description=task.description or task.title,
            bpmn_xml=sub.bpmn_xml or '',
            grading_type=task.grading_type or 'pass_fail',
            max_points=task.max_points or 100,
        )
        sub.ai_grade_value = result.get('grade_value')
        sub.ai_grade_passed = result.get('grade_passed')
        sub.ai_grade_comment = result.get('comment', '')
        annotations = result.get('annotations', [])
        sub.ai_grade_annotations = json.dumps(annotations) if annotations else None
        sub.ai_grade_generated_at = datetime.utcnow()
        db.session.commit()
        log_action('ai_grade_suggest', 'TaskSubmission', sub_id,
                   {'grade_value': result.get('grade_value'),
                    'grade_passed': result.get('grade_passed')})
        return jsonify({'ok': True, 'result': result})
    except Exception as exc:
        current_app.logger.exception('[admin] AI grading failed for sub %s', sub_id)
        return jsonify({'error': str(exc)}), 500


# ── Bulk user/task actions ────────────────────────────────────────────────────

@admin_bp.route('/users/bulk', methods=['POST'])
@admin_required
def users_bulk():
    user_ids = [int(i) for i in request.form.getlist('user_ids') if i.isdigit()]
    action = request.form.get('bulk_action', '')
    if not user_ids:
        flash('Keine Nutzer ausgewählt.', 'warning')
        return redirect(url_for('admin.users_list'))
    users = User.query.filter(User.id.in_(user_ids)).all()
    if action == 'activate':
        for u in users:
            u.is_active = True
        db.session.commit()
        log_action('bulk_activate_users', 'User', None, {'ids': user_ids})
        flash(f'{len(users)} Nutzer aktiviert.', 'success')
    elif action == 'deactivate':
        if any(u.id == current_user.id or u.role == 'admin' for u in users):
            flash('Eigener Account oder Admin kann nicht deaktiviert werden.', 'danger')
            return redirect(url_for('admin.users_list'))
        for u in users:
            u.is_active = False
        db.session.commit()
        log_action('bulk_deactivate_users', 'User', None, {'ids': user_ids})
        flash(f'{len(users)} Nutzer deaktiviert.', 'success')
    elif action == 'delete':
        if any(u.id == current_user.id or u.role == 'admin' for u in users):
            flash('Eigener Account oder Admin kann nicht gelöscht werden.', 'danger')
            return redirect(url_for('admin.users_list'))
        for u in users:
            db.session.delete(u)
        db.session.commit()
        log_action('bulk_delete_users', 'User', None, {'ids': user_ids})
        flash(f'{len(users)} Nutzer gelöscht.', 'success')
    else:
        flash('Unbekannte Aktion.', 'warning')
    return redirect(url_for('admin.users_list'))


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


# ── Cohorts ───────────────────────────────────────────────────────────────────

@admin_bp.route('/cohorts')
@instructor_or_admin_required
def cohorts_list():
    cohorts = Cohort.query.order_by(Cohort.created_at.desc()).all()
    return render_template('cms/admin/cohorts_list.html', cohorts=cohorts)


@admin_bp.route('/cohorts/new', methods=['GET', 'POST'])
@instructor_or_admin_required
def cohort_new():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        if not name:
            flash('Name erforderlich.', 'danger')
            return redirect(request.referrer or url_for('admin.cohorts_list'))
        cohort = Cohort(
            name=name,
            description=request.form.get('description', ''),
            is_active=bool(request.form.get('is_active')),
            created_by_id=current_user.id,
        )
        db.session.add(cohort)
        db.session.commit()
        log_action('create_cohort', 'Cohort', cohort.id, {'name': name})
        flash(f'Gruppe \u201e{name}\u201c erstellt.', 'success')
        return redirect(url_for('admin.cohort_detail', cohort_id=cohort.id))
    return render_template('cms/admin/cohort_detail.html', cohort=None, members=[],
                           member_ids=set(),
                           all_users=User.query.order_by(User.username).all())


@admin_bp.route('/cohorts/<int:cohort_id>', methods=['GET', 'POST'])
@instructor_or_admin_required
def cohort_detail(cohort_id: int):
    cohort = Cohort.query.get_or_404(cohort_id)
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'update':
            cohort.name = request.form.get('name', cohort.name).strip()
            cohort.description = request.form.get('description', cohort.description)
            cohort.is_active = bool(request.form.get('is_active'))
            db.session.commit()
            log_action('update_cohort', 'Cohort', cohort.id, {'name': cohort.name})
            flash('Gruppe aktualisiert.', 'success')
        elif action == 'add_member':
            user_id = int(request.form.get('user_id', 0))
            if user_id and not CohortMembership.query.filter_by(
                    cohort_id=cohort_id, user_id=user_id).first():
                db.session.add(CohortMembership(cohort_id=cohort_id, user_id=user_id))
                db.session.commit()
                log_action('add_cohort_member', 'Cohort', cohort_id,
                           {'user_id': user_id})
                flash('Mitglied hinzugef\u00fcgt.', 'success')
        elif action == 'remove_member':
            user_id = int(request.form.get('user_id', 0))
            m = CohortMembership.query.filter_by(
                cohort_id=cohort_id, user_id=user_id).first()
            if m:
                db.session.delete(m)
                db.session.commit()
                log_action('remove_cohort_member', 'Cohort', cohort_id,
                           {'user_id': user_id})
                flash('Mitglied entfernt.', 'success')
        elif action == 'delete':
            db.session.delete(cohort)
            db.session.commit()
            log_action('delete_cohort', 'Cohort', cohort_id, {'name': cohort.name})
            flash('Gruppe gel\u00f6scht.', 'success')
            return redirect(url_for('admin.cohorts_list'))
        return redirect(url_for('admin.cohort_detail', cohort_id=cohort_id))

    members = (User.query
               .join(CohortMembership, CohortMembership.user_id == User.id)
               .filter(CohortMembership.cohort_id == cohort_id)
               .all())
    member_ids = {u.id for u in members}
    all_users = User.query.order_by(User.username).all()
    return render_template('cms/admin/cohort_detail.html',
                           cohort=cohort, members=members,
                           member_ids=member_ids, all_users=all_users)


# ── Audit log ─────────────────────────────────────────────────────────────────

@admin_bp.route('/audit-log')
@admin_required
def audit_log():
    page = request.args.get('page', 1, type=int)
    q = AuditLog.query.order_by(AuditLog.created_at.desc())
    action_filter = request.args.get('action', '').strip()
    user_filter = request.args.get('user_id', '')
    if action_filter:
        q = q.filter(AuditLog.action.ilike(f'%{action_filter}%'))
    if user_filter.isdigit():
        q = q.filter(AuditLog.user_id == int(user_filter))
    pagination = q.paginate(page=page, per_page=50, error_out=False)
    return render_template('cms/admin/audit_log.html',
                           pagination=pagination, entries=pagination.items,
                           action_filter=action_filter, user_filter=user_filter)


# ── Analytics ─────────────────────────────────────────────────────────────────

@admin_bp.route('/analytics')
@instructor_or_admin_required
def analytics():
    period = request.args.get('period', '30d')
    since = since_from_period(period)
    gs = global_stats(since)
    chart = chart_data_timeline(None, since, period)
    errors = bpmn_error_frequency(since)
    phases = phase_distribution(since)
    tasks = task_analytics(since)
    cohorts = cohort_analytics(since)
    return render_template('cms/admin/analytics.html',
                           period=period, global_stats=gs, chart=chart,
                           bpmn_errors=errors, phases=phases,
                           task_analytics=tasks, cohort_analytics=cohorts)


# ── Research data export ──────────────────────────────────────────────────────

@admin_bp.route('/export')
@admin_required
def export_page():
    return render_template('cms/admin/export.html')


@admin_bp.route('/export/generate', methods=['POST'])
@admin_required
def export_generate():
    import csv
    timestamp = datetime.utcnow().strftime('%Y-%m-%d_%H%M%S')
    folder = f'export_{timestamp}'

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:

        # submissions.csv — outerjoin to handle deleted tasks/users
        sub_csv = io.StringIO()
        w = csv.writer(sub_csv)
        w.writerow(['id', 'user_id', 'username', 'task_id', 'task_title',
                    'started_at', 'completed_at', 'interactions', 'tokens_in',
                    'tokens_out', 'grade_value', 'grade_passed', 'grade_comment',
                    'ai_grade_value', 'ai_grade_passed'])
        for s in TaskSubmission.query.outerjoin(User, TaskSubmission.user_id == User.id).outerjoin(Task, TaskSubmission.task_id == Task.id).all():
            w.writerow([
                s.id, s.user_id,
                s.user.username if s.user else '',
                s.task_id,
                s.task.title if s.task else s.task_id,
                s.started_at.isoformat() if s.started_at else '',
                s.completed_at.isoformat() if s.completed_at else '',
                s.interactions or 0, s.tokens_in or 0, s.tokens_out or 0,
                s.grade_value, s.grade_passed, s.grade_comment or '',
                s.ai_grade_value, s.ai_grade_passed,
            ])
        zf.writestr(f'{folder}/submissions.csv', sub_csv.getvalue())

        # users.csv
        user_csv = io.StringIO()
        w = csv.writer(user_csv)
        w.writerow(['id', 'username', 'email', 'role', 'created_at', 'is_active'])
        for u in User.query.order_by(User.id).all():
            w.writerow([u.id, u.username, u.email, u.role,
                        u.created_at.isoformat() if u.created_at else '',
                        u.is_active])
        zf.writestr(f'{folder}/users.csv', user_csv.getvalue())

        # tasks.csv
        task_csv = io.StringIO()
        w = csv.writer(task_csv)
        w.writerow(['id', 'title', 'grading_type', 'max_points', 'is_active',
                    'sort_order'])
        for t in Task.query.order_by(Task.sort_order).all():
            w.writerow([t.id, t.title, t.grading_type, t.max_points,
                        t.is_active, t.sort_order])
        zf.writestr(f'{folder}/tasks.csv', task_csv.getvalue())

        # BPMN files
        for s in TaskSubmission.query.filter(
                TaskSubmission.bpmn_xml.isnot(None)).all():
            username = s.user.username if s.user else 'unknown'
            fname = secure_filename(
                f'submission_{s.id}_{username}_{s.task_id}.bpmn')
            zf.writestr(f'{folder}/bpmn/{fname}', s.bpmn_xml or '')

        # Chat logs
        for s in TaskSubmission.query.filter(
                TaskSubmission.chat_log.isnot(None)).all():
            fname = f'submission_{s.id}.json'
            zf.writestr(f'{folder}/chat_logs/{fname}', s.chat_log or '[]')

    buf.seek(0)
    log_action('export_research_data', 'System', None, {'timestamp': timestamp})
    return send_file(
        buf,
        mimetype='application/zip',
        as_attachment=True,
        download_name=f'{folder}.zip',
    )


# ── i18n / Language Admin ─────────────────────────────────────────────────────

@admin_bp.route('/languages')
@admin_required
def languages_list():
    langs = Language.query.order_by(Language.sort_order).all()
    return render_template('cms/admin/i18n_admin.html', languages=langs,
                           selected_lang=None, strings=[])


@admin_bp.route('/languages/new', methods=['POST'])
@admin_required
def language_new():
    code = request.form.get('code', '').strip().lower()
    name = request.form.get('name', '').strip()
    if not code or not name:
        flash('Code und Name erforderlich.', 'danger')
        return redirect(url_for('admin.languages_list'))
    if Language.query.get(code):
        flash('Sprachcode existiert bereits.', 'warning')
        return redirect(url_for('admin.languages_list'))
    lang = Language(
        code=code, name=name,
        flag=request.form.get('flag', ''),
        is_active=bool(request.form.get('is_active')),
        is_default=bool(request.form.get('is_default')),
        sort_order=int(request.form.get('sort_order', 99)),
    )
    if lang.is_default:
        Language.query.filter_by(is_default=True).update({'is_default': False})
    db.session.add(lang)
    db.session.commit()
    invalidate_cache()
    log_action('create_language', 'Language', None, {'code': code, 'name': name})
    flash(f'Sprache \u201e{name}\u201c ({code}) erstellt.', 'success')
    return redirect(url_for('admin.language_strings', lang_code=code))


@admin_bp.route('/languages/<lang_code>', methods=['GET', 'POST'])
@admin_required
def language_strings(lang_code: str):
    lang = Language.query.get_or_404(lang_code)
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'update_meta':
            lang.name = request.form.get('name', lang.name)
            lang.flag = request.form.get('flag', lang.flag)
            lang.is_active = bool(request.form.get('is_active'))
            lang.sort_order = int(request.form.get('sort_order', lang.sort_order))
            if request.form.get('is_default'):
                Language.query.filter_by(is_default=True).update({'is_default': False})
                lang.is_default = True
            db.session.commit()
            invalidate_cache()
            log_action('update_language', 'Language', None, {'code': lang_code})
            flash('Sprache aktualisiert.', 'success')
        elif action == 'save_string':
            key = request.form.get('key', '').strip()
            value = request.form.get('value', '')
            if key:
                existing = LanguageString.query.filter_by(
                    language_code=lang_code, key=key).first()
                if existing:
                    existing.value = value
                else:
                    db.session.add(LanguageString(
                        language_code=lang_code, key=key, value=value))
                db.session.commit()
                invalidate_cache()
        elif action == 'delete_string':
            key = request.form.get('key', '')
            LanguageString.query.filter_by(
                language_code=lang_code, key=key).delete()
            db.session.commit()
            invalidate_cache()
        elif action == 'bulk_save':
            try:
                raw = request.form.get('strings_json', '{}')
                data = json.loads(raw)
                for k, v in data.items():
                    existing = LanguageString.query.filter_by(
                        language_code=lang_code, key=k).first()
                    if existing:
                        existing.value = v
                    else:
                        db.session.add(LanguageString(
                            language_code=lang_code, key=k, value=v))
                db.session.commit()
                invalidate_cache()
                log_action('bulk_save_strings', 'Language', None,
                           {'code': lang_code, 'count': len(data)})
                flash(f'{len(data)} Texte gespeichert.', 'success')
            except json.JSONDecodeError:
                flash('Ung\u00fcltiges JSON.', 'danger')
        elif action == 'delete_language':
            db.session.delete(lang)
            db.session.commit()
            invalidate_cache()
            log_action('delete_language', 'Language', None, {'code': lang_code})
            flash('Sprache gel\u00f6scht.', 'success')
            return redirect(url_for('admin.languages_list'))
        return redirect(url_for('admin.language_strings', lang_code=lang_code))

    strings = (LanguageString.query
               .filter_by(language_code=lang_code)
               .order_by(LanguageString.key)
               .all())
    all_langs = Language.query.order_by(Language.sort_order).all()
    return render_template('cms/admin/i18n_admin.html',
                           languages=all_langs,
                           selected_lang=lang,
                           strings=strings)



# -- Level System Admin --------------------------------------------------------

@admin_bp.route('/levels')
@admin_required
def levels_list():
    levels = LearningLevel.query.order_by(LearningLevel.level_number).all()
    tasks = Task.query.filter_by(is_active=True).order_by(Task.sort_order).all()
    level_enabled = Settings.get(Settings.LEVEL_SYSTEM_ENABLED, False)
    return render_template('cms/admin/levels.html',
                           levels=levels, tasks=tasks,
                           level_enabled=level_enabled)


@admin_bp.route('/levels/toggle', methods=['POST'])
@admin_required
def levels_toggle():
    current = Settings.get(Settings.LEVEL_SYSTEM_ENABLED, False)
    Settings.set(Settings.LEVEL_SYSTEM_ENABLED, not current)
    db.session.commit()
    state = 'aktiviert' if not current else 'deaktiviert'
    flash(f'Level-System {state}.', 'success')
    return redirect(url_for('admin.levels_list'))


@admin_bp.route('/levels/new', methods=['POST'])
@admin_required
def level_new():
    title = request.form.get('title', '').strip()
    if not title:
        flash('Titel ist erforderlich.', 'danger')
        return redirect(url_for('admin.levels_list'))
    max_num = db.session.query(db.func.max(LearningLevel.level_number)).scalar() or 0
    level = LearningLevel(
        level_number=max_num + 1,
        title=title,
        title_de=request.form.get('title_de', '').strip() or None,
        description=request.form.get('description', '').strip() or None,
        description_de=request.form.get('description_de', '').strip() or None,
        difficulty=request.form.get('difficulty', 'beginner'),
        is_active=True,
        sort_order=max_num,
    )
    db.session.add(level)
    db.session.commit()
    log_action('create_level', 'LearningLevel', level.id, {'title': title})
    flash(f'Level {level.level_number} "{title}" erstellt.', 'success')
    return redirect(url_for('admin.level_edit', level_id=level.id))


@admin_bp.route('/levels/<int:level_id>', methods=['GET', 'POST'])
@admin_required
def level_edit(level_id: int):
    level = LearningLevel.query.get_or_404(level_id)
    tasks_all = Task.query.filter_by(is_active=True).order_by(Task.sort_order).all()
    level_task_ids = {t.id for t in level.tasks.all()}
    if request.method == 'POST':
        action = request.form.get('action', 'save')
        if action == 'save':
            level.title = request.form.get('title', level.title)
            level.title_de = request.form.get('title_de', '') or None
            level.description = request.form.get('description', '') or None
            level.description_de = request.form.get('description_de', '') or None
            level.difficulty = request.form.get('difficulty', level.difficulty)
            level.is_active = bool(request.form.get('is_active'))
            # Update task assignments
            selected_ids = set(request.form.getlist('task_ids'))
            # Remove tasks not selected
            for t in level.tasks.all():
                if t.id not in selected_ids:
                    level.tasks.remove(t)
            # Add newly selected tasks
            for tid in selected_ids:
                task = Task.query.get(tid)
                if task and tid not in level_task_ids:
                    level.tasks.append(task)
            db.session.commit()
            log_action('update_level', 'LearningLevel', level.id, {'title': level.title})
            flash('Level aktualisiert.', 'success')
        elif action == 'delete':
            db.session.delete(level)
            db.session.commit()
            # Re-number remaining levels
            remaining = LearningLevel.query.order_by(LearningLevel.level_number).all()
            for i, lv in enumerate(remaining, start=1):
                lv.level_number = i
            db.session.commit()
            log_action('delete_level', 'LearningLevel', level_id, {})
            flash('Level gel�scht und Nummerierung aktualisiert.', 'success')
            return redirect(url_for('admin.levels_list'))
        return redirect(url_for('admin.level_edit', level_id=level_id))

    levels = LearningLevel.query.order_by(LearningLevel.level_number).all()
    return render_template('cms/admin/level_edit.html',
                           level=level, tasks_all=tasks_all,
                           level_task_ids=level_task_ids,
                           levels=levels)
