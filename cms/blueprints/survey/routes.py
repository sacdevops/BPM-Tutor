"""Survey-taking blueprint â€” render and collect survey responses."""
import json
from flask import (Blueprint, render_template, redirect, url_for,
                   flash, request, session, jsonify)
from flask_login import current_user

from cms.extensions import db
from cms.models.survey import Survey, SurveyResponse
from cms.models.settings import Settings
from datetime import datetime

survey_bp = Blueprint('survey_bp', __name__, url_prefix='/survey')


def _get_or_create_response(survey_id: int, submission_id: int | None) -> SurveyResponse:
    user_id = current_user.id if current_user.is_authenticated else None
    resp = SurveyResponse(
        user_id=user_id,
        survey_id=survey_id,
        submission_id=submission_id,
    )
    db.session.add(resp)
    db.session.flush()
    return resp


@survey_bp.route('/<int:survey_id>', methods=['GET', 'POST'])
def take(survey_id: int):
    survey = Survey.query.get_or_404(survey_id)
    if not survey.is_active:
        flash('Diese Umfrage ist nicht verfÃ¼gbar.', 'warning')
        return redirect('/')

    submission_id = request.args.get('submission_id', type=int)
    page_num = request.args.get('page', 0, type=int)
    pages = survey.pages

    if not pages:
        flash('Diese Umfrage hat keine Fragen.', 'info')
        return redirect(request.args.get('next', '/'))

    current_page = pages[page_num] if page_num < len(pages) else pages[-1]
    is_last = page_num >= len(pages) - 1

    # Store partial answers in session
    session_key = f'survey_{survey_id}_answers'
    answers: dict = session.get(session_key, {})

    if request.method == 'POST':
        action = request.form.get('action', 'next')

        # Collect answers from this page
        errors: dict = {}
        for q in current_page.questions:
            val = request.form.get(f'q_{q.id}', '').strip()
            if q.required and not val:
                errors[f'q_{q.id}'] = 'Pflichtfeld.'
            answers[str(q.id)] = val

        if errors and action != 'skip':
            return render_template('cms/survey/take.html',
                                   survey=survey, page=current_page,
                                   page_num=page_num, total_pages=len(pages),
                                   is_last=is_last, answers=answers,
                                   errors=errors, submission_id=submission_id)

        session[session_key] = answers

        if action == 'prev' and page_num > 0:
            return redirect(url_for('survey_bp.take', survey_id=survey_id,
                                    page=page_num - 1, submission_id=submission_id,
                                    next=request.args.get('next', '')))

        if not is_last and action == 'next':
            return redirect(url_for('survey_bp.take', survey_id=survey_id,
                                    page=page_num + 1, submission_id=submission_id,
                                    next=request.args.get('next', '')))

        # Final submit
        resp = _get_or_create_response(survey_id, submission_id)
        resp.answers = answers
        resp.completed_at = datetime.utcnow()
        db.session.commit()

        # Clear session
        session.pop(session_key, None)

        next_url = request.args.get('next', '/')
        return redirect(next_url)

    return render_template('cms/survey/take.html',
                           survey=survey, page=current_page,
                           page_num=page_num, total_pages=len(pages),
                           is_last=is_last, answers=answers,
                           errors={}, submission_id=submission_id)

