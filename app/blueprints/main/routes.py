"""Main blueprint — public routes: index, task pages, API endpoints."""
import io
import logging

import config
import requests as http_requests
from flask import Blueprint, jsonify, make_response, redirect, render_template, request, url_for
from flask_login import current_user

from app.extensions import csrf, limiter, db

main_bp = Blueprint('main', __name__)
logger = logging.getLogger('bpmtutor.main')


# ── Health ────────────────────────────────────────────────────────────────────

@main_bp.route('/health')
def health():
    """Health check — also verifies DB connectivity."""
    try:
        from app.extensions import db
        db.session.execute(db.text('SELECT 1'))
        return jsonify(status='ok', database='ok'), 200
    except Exception as exc:
        logger.error('[Health] DB check failed: %s', exc)
        return jsonify(status='degraded', database='error'), 503


# ── Brand Logo ────────────────────────────────────────────────────────────────

@main_bp.route('/brand/logo')
def brand_logo():
    """Serve the brand logo image stored in DB settings."""
    import base64
    from app.models.settings import Settings
    logo_data = (Settings.get(Settings.BRAND_LOGO_DATA, '') or '').strip()
    if not logo_data:
        logo_url = (Settings.get(Settings.BRAND_LOGO_URL, '') or '').strip()
        if logo_url:
            return redirect(logo_url)
        return '', 404
    logo_mime = Settings.get(Settings.BRAND_LOGO_MIME, 'image/png') or 'image/png'
    try:
        image_bytes = base64.b64decode(logo_data)
        response = make_response(image_bytes)
        response.headers['Content-Type'] = logo_mime
        response.headers['Cache-Control'] = 'public, max-age=3600'
        return response
    except Exception:
        return '', 404


# ── Pages ─────────────────────────────────────────────────────────────────────

@main_bp.route('/maintenance')
def maintenance():
    from app.models.settings import Settings
    if not Settings.get(Settings.MAINTENANCE_MODE, False):
        return redirect('/')
    return render_template('maintenance.html'), 503

@main_bp.route('/')
def index():
    from app.models.task import Task, TaskSubmission
    from app.models.settings import Settings
    from app.models.level import LearningLevel, level_tasks as _lv_tasks_tbl

    if Settings.get(Settings.AUTH_REQUIRED) and not current_user.is_authenticated:
        return redirect(url_for('auth.login', next='/'))

    tasks = Task.query.filter_by(is_active=True).order_by(Task.sort_order).all()

    # Show only standard-mode tasks on the index
    # (leveling-mode tasks appear in the level system, research-mode tasks in studies)
    tasks = [t for t in tasks if getattr(t, 'task_mode', 'standard') == 'standard']

    # Load ALL user submissions once; derive completed/in_progress/submitted sets in memory
    in_progress_task_ids: set = set()
    completed_task_ids: set = set()
    submitted_ids: set = set()
    if current_user.is_authenticated:
        all_subs = TaskSubmission.query.filter_by(user_id=current_user.id).all()
        for s in all_subs:
            submitted_ids.add(s.task_id)
            if s.completed_at:
                completed_task_ids.add(s.task_id)
            else:
                in_progress_task_ids.add(s.task_id)
        tasks = [t for t in tasks if not (t.hide_after_completion and t.id in completed_task_ids)]

    level_system_enabled = Settings.get(Settings.LEVEL_SYSTEM_ENABLED, False)
    levels = []
    level_data = []
    if level_system_enabled:
        levels = LearningLevel.query.filter_by(is_active=True).order_by(LearningLevel.level_number).all()
        if current_user.is_authenticated and levels:
            # Pre-fetch all tasks for all levels in one join query — avoids N+1
            level_ids = [lv.id for lv in levels]
            level_task_rows = (
                db.session.query(_lv_tasks_tbl.c.level_id, Task)
                .join(Task, Task.id == _lv_tasks_tbl.c.task_id)
                .filter(
                    _lv_tasks_tbl.c.level_id.in_(level_ids),
                    Task.is_active.is_(True),
                )
                .order_by(Task.sort_order)
                .all()
            )
            tasks_by_level: dict = {}
            for lvl_id, t in level_task_rows:
                tasks_by_level.setdefault(lvl_id, []).append(t)

            for lv in levels:
                lv_tasks = tasks_by_level.get(lv.id, [])
                done = sum(1 for t in lv_tasks if t.id in submitted_ids)
                total = len(lv_tasks)
                completed = done == total and total > 0
                unlocked = lv.is_unlocked_for(current_user)
                level_data.append({
                    'level': lv,
                    'tasks': lv_tasks,
                    'done': done,
                    'total': total,
                    'pct': int(done / total * 100) if total > 0 else 0,
                    'completed': completed,
                    'unlocked': unlocked,
                    'submitted_ids': submitted_ids,
                })

    return render_template('index.html', tasks=tasks, levels=levels, level_data=level_data,
                           level_system_enabled=level_system_enabled,
                           in_progress_task_ids=list(in_progress_task_ids),
                           completed_task_ids=list(completed_task_ids))


@main_bp.route('/feedback', methods=['POST'])
@csrf.exempt
@limiter.limit('10 per minute')
def submit_feedback():
    """Receive a student feedback/bug report and forward it via email."""
    data = request.get_json(silent=True) or {}
    category = (data.get('category') or '').strip()
    message = (data.get('message') or '').strip()
    page_context = (data.get('page') or '').strip()
    if not message or not category:
        return jsonify({'ok': False, 'error': 'Kategorie und Beschreibung sind erforderlich.'}), 400
    sender_name = (data.get('name') or '').strip()
    sender_email = (data.get('email') or '').strip()
    if not sender_name and current_user.is_authenticated:
        sender_name = getattr(current_user, 'display_name', None) or getattr(current_user, 'username', '')
    if not sender_email and current_user.is_authenticated:
        sender_email = getattr(current_user, 'email', '') or ''
    from datetime import datetime as _dt
    timestamp = _dt.now().strftime('%d.%m.%Y %H:%M:%S')
    try:
        from app.utils.email import send_feedback_email
        send_feedback_email(sender_name, sender_email, category, message, timestamp, page_context)
    except Exception as exc:
        logger.warning('[feedback] Email send error: %s', exc)
    return jsonify({'ok': True})


@main_bp.route('/task/<task_id>')
def task_page(task_id):
    from app.models.task import Task
    from app.models.settings import Settings
    from app.models.agent import AIAgent

    if Settings.get(Settings.AUTH_REQUIRED) and not current_user.is_authenticated:
        return redirect(url_for('auth.login', next=f'/task/{task_id}'))

    task = db.session.get(Task, task_id)
    if not task or not task.is_active:
        return render_template(
            'index.html',
            tasks=Task.query.filter_by(is_active=True).order_by(Task.sort_order).all(),
            error='Aufgabe nicht gefunden.',
        ), 404

    # Resolve agent for this task
    agent = None
    if task.agent_id:
        agent = db.session.get(AIAgent, task.agent_id)
    if not agent:
        agent = AIAgent.get_default()

    return render_template('task.html', task=task, is_custom=False, agent=agent)


@main_bp.route('/task/custom')
def custom_task_page():
    task = {'id': 'custom', 'title': 'Custom Task', 'description': ''}
    return render_template('task.html', task=task, is_custom=True)


# ── API endpoints ─────────────────────────────────────────────────────────────

@main_bp.route('/api/extract-file-content', methods=['POST'])
@csrf.exempt
@limiter.limit('20 per minute')
def extract_file_content():
    if 'file' not in request.files:
        return jsonify({'success': False, 'message': 'No file provided'}), 400

    file = request.files['file']
    filename = file.filename or ''
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''

    # Validate file size (max 10 MB)
    file.seek(0, 2)
    file_size = file.tell()
    file.seek(0)
    if file_size > 10 * 1024 * 1024:
        return jsonify({'success': False, 'message': 'File too large (max 10 MB)'}), 413

    try:
        if ext in ('txt', 'md', 'csv'):
            content = file.read().decode('utf-8', errors='replace')
        elif ext == 'pdf':
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(file.read()))
            content = '\n'.join(page.extract_text() or '' for page in reader.pages)
        elif ext == 'docx':
            from docx import Document
            doc = Document(io.BytesIO(file.read()))
            content = '\n'.join(para.text for para in doc.paragraphs)
        else:
            return jsonify({'success': False, 'message': f'Unsupported file type: .{ext}'}), 400

        return jsonify({'success': True, 'content': content})
    except Exception as exc:
        logger.error('[extract_file_content] Error: %s', exc)
        return jsonify({'success': False, 'message': str(exc)}), 500


@main_bp.route('/api/auto-save-bpmn', methods=['POST'])
@csrf.exempt
@limiter.limit('60 per minute')
def auto_save_bpmn():
    """Auto-save draft BPMN without completing the submission."""
    data = request.get_json()
    if not data:
        return jsonify({'success': False}), 400
    task_id = data.get('task_id', '')
    bpmn_xml = data.get('bpmn_xml', '')
    sid = data.get('sid', '')
    if not bpmn_xml or not task_id:
        return jsonify({'success': False}), 400
    try:
        from app.models.task import TaskSubmission, TaskBPMNSnapshot
        sub = None
        if sid:
            sub = (TaskSubmission.query
                   .filter_by(task_id=task_id, session_id=sid)
                   .filter(TaskSubmission.completed_at.is_(None))
                   .order_by(TaskSubmission.started_at.desc())
                   .first())
        if sub:
            sub.bpmn_draft = bpmn_xml
            snapshot = TaskBPMNSnapshot(submission_id=sub.id, bpmn_xml=bpmn_xml, source='auto')
            db.session.add(snapshot)
            db.session.commit()
    except Exception as e:
        logger.debug('[auto_save_bpmn] %s', e)
    return jsonify({'success': True})


@main_bp.route('/api/save-bpmn', methods=['POST'])
@csrf.exempt
def save_bpmn():
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'message': 'No data provided'}), 400

    task_id = data.get('task_id', '')
    bpmn_xml = data.get('bpmn_xml', '')
    sid = data.get('sid', '')
    study_id = data.get('study_id') or None

    if not bpmn_xml:
        return jsonify({'success': False, 'message': 'No BPMN XML provided'}), 400

    from app.sockets import chat_handler
    submission_id = chat_handler.complete_and_upload(task_id, bpmn_xml, sid=sid)

    # Fallback: if the socket session was already gone (e.g. socket disconnected before
    # the save request arrived), find the latest open submission for this user and
    # mark it complete directly from the database.
    if not submission_id and task_id and task_id != 'custom' and current_user.is_authenticated:
        try:
            from datetime import datetime as _dt, timezone as _tz
            from app.models.task import TaskSubmission as _TS
            sub = (_TS.query
                   .filter_by(task_id=task_id, user_id=current_user.id)
                   .filter(_TS.completed_at.is_(None))
                   .order_by(_TS.started_at.desc())
                   .first())
            if sub:
                sub.bpmn_xml = bpmn_xml or sub.bpmn_xml
                sub.completed_at = _dt.now(_tz.utc)
                db.session.commit()
                submission_id = sub.id
        except Exception:
            logger.exception('[save_bpmn] fallback persist error')

    # Tag the submission with the study_id if present
    if study_id and submission_id:
        try:
            from app.extensions import db
            from app.models.task import TaskSubmission
            sub = db.session.get(TaskSubmission, submission_id)
            if sub:
                sub.study_id = int(study_id)
                db.session.commit()
        except Exception:
            pass

    # If in a study, redirect to study step_done instead of survey/index
    if study_id:
        redirect_url = url_for('study.step_done', study_id=study_id)
        logger.info('[save_bpmn] study_id=%s → redirect to step_done: %s', study_id, redirect_url)
        return jsonify({'success': True, 'redirect': redirect_url})

    redirect_url = '/'
    grading_pending = False
    if task_id and task_id != 'custom':
        try:
            from app.extensions import db
            from app.models.task import Task as _Task
            from app.models.survey import Survey
            task_obj = db.session.get(_Task, task_id)
            # Determine grading state
            if task_obj and task_obj.grading_type and task_obj.grading_type != 'none':
                grading_pending = True
            # First try a survey linked to this specific task
            survey = Survey.query.filter_by(
                survey_type='post_task', task_id=task_id, is_active=True
            ).first()
            # Fall back to a generic post_task survey (no specific task linked)
            if not survey:
                survey = Survey.query.filter(
                    Survey.survey_type == 'post_task',
                    Survey.is_active == True,
                    db.or_(Survey.task_id.is_(None), Survey.task_id == '')
                ).first()
            # Also check for post_all surveys
            if not survey:
                survey = Survey.query.filter_by(
                    survey_type='post_all', is_active=True
                ).first()
            if survey:
                redirect_url = url_for(
                    'survey_bp.take',
                    survey_id=survey.id,
                    submission_id=submission_id or '',
                    next='/',
                )
        except Exception:
            logger.exception('[save_bpmn] survey redirect lookup failed')

    return jsonify({'success': True, 'redirect': redirect_url, 'grading_pending': grading_pending})


@main_bp.route('/api/models', methods=['POST'])
@csrf.exempt
@limiter.limit('30 per minute')
def get_models():
    """Proxy request to CampusKI to list available models."""
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'message': 'No data provided'}), 400

    api_key = data.get('api_key', '')
    if not api_key:
        return jsonify({'success': False, 'message': 'API key required'}), 400

    # Decrypt if the key was stored encrypted (enc: prefix)
    from app.utils.crypto import decrypt_api_key
    api_key = decrypt_api_key(api_key)
    if not api_key:
        return jsonify({'success': False, 'message': 'API key could not be decrypted'}), 400

    raw_base_url = data.get('base_url', '').strip().rstrip('/')
    if not raw_base_url:
        # Fall back to admin-configured endpoint, then config default
        try:
            from app.models.settings import Settings
            raw_base_url = (Settings.get(Settings.API_ENDPOINT) or '').strip().rstrip('/')
        except Exception:
            pass
    if raw_base_url:
        if not raw_base_url.startswith('https://'):
            return jsonify({'success': False, 'message': 'base_url must start with https://'}), 400
        models_base = raw_base_url
    else:
        models_base = config.CAMPUS_KI_BASE_URL.rstrip('/')

    try:
        resp = http_requests.get(
            f'{models_base}/v1/models',
            headers={'Authorization': f'Bearer {api_key}'},
            timeout=15,
        )
        resp.raise_for_status()
        models_data = resp.json()
        models = sorted(
            [{'id': m.get('id', ''), 'name': m.get('id', '')} for m in models_data.get('data', [])],
            key=lambda x: x['id'],
        )
        return jsonify({'success': True, 'models': models})
    except http_requests.exceptions.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else 500
        if status in (401, 403):
            return jsonify({'success': False, 'message': 'Invalid API key'}), 401
        return jsonify({'success': False, 'message': f'API error: {status}'}), 502
    except Exception as exc:
        logger.error('[get_models] Error: %s', exc)
        return jsonify({'success': False, 'message': str(exc)}), 500
