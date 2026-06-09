"""Admin — grading routes."""
import json
from datetime import datetime, timezone

from flask import render_template, redirect, url_for, flash, request, jsonify, current_app
from flask_login import current_user

from app.blueprints.admin import admin_bp
from app.blueprints.admin._helpers import _get_admin_api_key
from app.extensions import db
from app.models.task import Task, TaskSubmission
from app.models.settings import Notification
from app.utils.decorators import admin_required, tutor_or_admin_required
from app.utils.audit import log_action
from app.utils.email import send_grade_notification_email


# ── Grading list ──────────────────────────────────────────────────────────────

@admin_bp.route('/grading')
@tutor_or_admin_required
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
        # 'no grading' tasks are always considered done — exclude them from the pending queue
        query = (query
                 .join(Task, TaskSubmission.task_id == Task.id)
                 .filter(Task.grading_type != 'none')
                 .filter(
                     TaskSubmission.grade_value.is_(None),
                     TaskSubmission.grade_passed.is_(None)
                 ))

    pagination = query.order_by(TaskSubmission.completed_at.desc()).paginate(
        page=page, per_page=25, error_out=False)
    tasks = Task.query.order_by(Task.sort_order).all()
    return render_template('cms/admin/grading_list.html',
                           pagination=pagination, tasks=tasks,
                           task_filter=task_filter, graded_filter=graded_filter)


# ── Grading detail / save grade ───────────────────────────────────────────────

@admin_bp.route('/grading/<int:sub_id>', methods=['GET', 'POST'])
@tutor_or_admin_required
def grading_detail(sub_id: int):
    submission = TaskSubmission.query.get_or_404(sub_id)
    task = db.session.get(Task, submission.task_id)

    if request.method == 'POST':
        grading_type = request.form.get('grading_type', 'none')
        comment = request.form.get('comment', '').strip()
        send_notif = bool(request.form.get('send_notification'))

        if grading_type == 'points':
            grade_val = request.form.get('grade_value', '')
            try:
                grade_float = float(grade_val)
            except ValueError:
                flash('Ungültiger Punktwert.', 'danger')
                return redirect(request.url)
            if task and task.max_points is not None and grade_float > task.max_points:
                flash(f'Punktzahl darf {task.max_points} nicht überschreiten.', 'danger')
                return redirect(request.url)
            submission.grade_value = grade_float
            submission.grade_passed = None
        elif grading_type == 'pass_fail':
            submission.grade_passed = request.form.get('grade_passed') == 'true'
            submission.grade_value = None
        else:
            submission.grade_value = None
            submission.grade_passed = None

        submission.grade_comment = comment or None
        submission.graded_by_id = current_user.id
        submission.graded_at = datetime.now(timezone.utc)

        raw_annots = request.form.get('grade_annotations', '[]').strip()
        try:
            json.loads(raw_annots)
            submission.grade_annotations = raw_annots
        except Exception:
            pass

        db.session.commit()

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

            try:
                from main import socketio as _sio
                _sio.emit('notification', {
                    'id': notif.id,
                    'type': 'grade',
                    'title': notif.title,
                    'message': notif.message or '',
                    'link': notif.link,
                }, room=f'user_{submission.user_id}')
            except Exception:
                pass

            if submission.user and task:
                send_grade_notification_email(submission.user, task.title, grade_info)

        flash('Bewertung gespeichert.', 'success')
        return redirect(url_for('admin.grading_list'))

    from app.models.task import TaskBPMNSnapshot
    snapshots = (TaskBPMNSnapshot.query
                 .filter_by(submission_id=sub_id)
                 .order_by(TaskBPMNSnapshot.created_at.desc())
                 .limit(20).all())
    return render_template('cms/admin/grading_detail.html',
                           submission=submission, task=task, snapshots=snapshots)


@admin_bp.route('/grading/<int:sub_id>/delete', methods=['POST'])
@admin_required
def submission_delete(sub_id: int):
    submission = TaskSubmission.query.get_or_404(sub_id)
    db.session.delete(submission)
    db.session.commit()
    log_action('delete_submission', 'TaskSubmission', sub_id, {})
    flash('Einreichung gelöscht.', 'success')
    return redirect(url_for('admin.grading_list'))


# ── AI grading suggestion ─────────────────────────────────────────────────────

@admin_bp.route('/grading/<int:sub_id>/ai-suggest', methods=['POST'])
@tutor_or_admin_required
def grading_ai_suggest(sub_id: int):
    sub = TaskSubmission.query.get_or_404(sub_id)
    task = db.session.get(Task, sub.task_id)
    if not task:
        return jsonify({'error': 'Task not found'}), 404
    try:
        from app.services.ai_service import AIService
        api_key, model, base_url = _get_admin_api_key()
        ai = AIService(api_key=api_key, model=model, base_url=base_url)
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
        sub.ai_grade_generated_at = datetime.now(timezone.utc)
        db.session.commit()
        log_action('ai_grade_suggest', 'TaskSubmission', sub_id,
                   {'grade_value': result.get('grade_value'),
                    'grade_passed': result.get('grade_passed')})
        return jsonify({'ok': True, 'result': result})
    except Exception as exc:
        current_app.logger.exception('[admin] AI grading failed for sub %s', sub_id)
        return jsonify({'error': str(exc)}), 500
