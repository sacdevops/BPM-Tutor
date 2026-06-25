"""Survey-taking blueprint -- render and collect survey responses."""

import json
import os
import uuid

from flask import (Blueprint, render_template, redirect, url_for,
                   flash, request, session, jsonify, current_app)
from flask_login import current_user
from werkzeug.utils import secure_filename

from app.extensions import db
from app.models.survey import Survey, SurveyResponse, SurveyQuestion
from app.models.settings import Settings
from datetime import datetime, timezone

survey_bp = Blueprint('survey_bp', __name__, url_prefix='/survey')

ALLOWED_IMAGE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp', 'svg'}
ALLOWED_VIDEO_EXTENSIONS = {'mp4', 'webm', 'ogg', 'mov'}


def _allowed_image(filename: str) -> bool:
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_IMAGE_EXTENSIONS


def _allowed_video(filename: str) -> bool:
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_VIDEO_EXTENSIONS


def _get_or_create_response(survey_id: int, submission_id, step_id=None) -> SurveyResponse:
    user_id = current_user.id if current_user.is_authenticated else None
    resp = SurveyResponse(
        user_id=user_id,
        survey_id=survey_id,
        submission_id=submission_id,
        step_id=step_id,
    )
    db.session.add(resp)
    db.session.flush()
    return resp


@survey_bp.route('/<int:survey_id>', methods=['GET', 'POST'])
def take(survey_id: int):
    survey = Survey.query.get_or_404(survey_id)
    if not survey.is_active:
        flash('Diese Umfrage ist nicht verfuegbar.', 'warning')
        return redirect('/')

    submission_id = request.args.get('submission_id', type=int)
    step_id = request.args.get('step_id', type=int)
    page_num = request.args.get('page', 0, type=int)
    pages = survey.pages

    if not pages:
        flash('Diese Umfrage hat keine Fragen.', 'info')
        return redirect(request.args.get('next', '/'))

    current_page = pages[page_num] if page_num < len(pages) else pages[-1]
    is_last = page_num >= len(pages) - 1

    session_key = f'survey_{survey_id}_step_{step_id}_answers' if step_id else f'survey_{survey_id}_answers'
    answers = session.get(session_key, {})

    if request.method == 'POST':
        action = request.form.get('action', 'next')

        errors = {}
        for q in current_page.questions:
            val = request.form.get(f'q_{q.id}', '').strip()
            if q.required and not val and q.question_type not in ('info', 'image'):
                errors[f'q_{q.id}'] = 'Pflichtfeld.'
            answers[str(q.id)] = val

        if errors and action != 'skip':
            return render_template('survey_take.html',
                                   survey=survey, page=current_page,
                                   page_num=page_num, total_pages=len(pages),
                                   is_last=is_last, answers=answers,
                                   errors=errors, submission_id=submission_id)

        session[session_key] = answers

        if action == 'prev' and page_num > 0:
            return redirect(url_for('survey_bp.take', survey_id=survey_id,
                                    page=page_num - 1, submission_id=submission_id,
                                    step_id=step_id, next=request.args.get('next', '')))

        if not is_last and action == 'next':
            return redirect(url_for('survey_bp.take', survey_id=survey_id,
                                    page=page_num + 1, submission_id=submission_id,
                                    step_id=step_id, next=request.args.get('next', '')))

        resp = _get_or_create_response(survey_id, submission_id, step_id=step_id)
        resp.answers = answers
        resp.completed_at = datetime.now(timezone.utc)

        try:
            snapshot = {}
            for _pg in survey.pages:
                for _q in _pg.questions:
                    if _q.question_type != 'info':
                        snapshot[str(_q.id)] = {
                            'label': _q.label,
                            'type': _q.question_type,
                            'options': _q.options,
                            'page': _pg.title or '',
                        }
            resp.questions_snapshot = json.dumps(snapshot, ensure_ascii=False)
        except Exception:
            pass
        db.session.commit()

        session.pop(session_key, None)

        next_url = request.args.get('next', '/')
        return redirect(next_url)

    return render_template('survey_take.html',
                           survey=survey, page=current_page,
                           page_num=page_num, total_pages=len(pages),
                           is_last=is_last, answers=answers,
                           errors={}, submission_id=submission_id)


@survey_bp.route('/upload-image', methods=['POST'])
def upload_image():
    """Upload an image for a survey question (admin only)."""
    from app.utils.decorators import admin_required
    from flask_login import current_user
    if not current_user.is_authenticated or not current_user.has_role('admin'):
        return jsonify({'error': 'Forbidden'}), 403

    file = request.files.get('file')
    question_id = request.form.get('question_id', type=int)
    if not file or not file.filename:
        return jsonify({'error': 'No file provided'}), 400
    if not _allowed_image(file.filename):
        return jsonify({'error': 'Invalid file type'}), 400

    filename = secure_filename(f'{uuid.uuid4().hex}_{file.filename}')
    upload_dir = os.path.join(current_app.root_path, '..', 'data', 'survey_images')
    os.makedirs(upload_dir, exist_ok=True)
    filepath = os.path.join(upload_dir, filename)
    file.save(filepath)
    image_url = f'/data-uploads/survey_images/{filename}'

    if question_id:
        q = db.session.get(SurveyQuestion, question_id)
        if q:
            q.image_path = image_url
            db.session.commit()

    return jsonify({'url': image_url})


@survey_bp.route('/upload-video', methods=['POST'])
def upload_video():
    """Upload a video for a survey question (admin only)."""
    from flask_login import current_user
    if not current_user.is_authenticated or not current_user.has_role('admin'):
        return jsonify({'error': 'Forbidden'}), 403

    file = request.files.get('file')
    if not file or not file.filename:
        return jsonify({'error': 'No file provided'}), 400
    if not _allowed_video(file.filename):
        return jsonify({'error': 'Invalid file type. Allowed: mp4, webm, ogg, mov'}), 400

    filename = secure_filename(f'{uuid.uuid4().hex}_{file.filename}')
    upload_dir = os.path.join(current_app.root_path, '..', 'data', 'survey_videos')
    os.makedirs(upload_dir, exist_ok=True)
    filepath = os.path.join(upload_dir, filename)
    file.save(filepath)
    video_url = f'/data-uploads/survey_videos/{filename}'

    return jsonify({'url': video_url})
