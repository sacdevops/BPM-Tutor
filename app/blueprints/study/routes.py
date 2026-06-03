"""Study (Research Mode) student-facing blueprint."""
from datetime import datetime, timezone

from flask import (Blueprint, render_template, redirect, url_for,
                   flash, request, jsonify, abort)
from flask_login import current_user, login_required

from app.extensions import db, csrf

study_bp = Blueprint('study', __name__, url_prefix='/study')


def _get_participant(study_id: int):
    """Return the StudyParticipant for the current user, or None."""
    from app.models.study import StudyParticipant
    if not current_user.is_authenticated:
        return None
    return StudyParticipant.query.filter_by(
        study_id=study_id, user_id=current_user.id
    ).first()


def _record_step_start(participant, step):
    """Upsert a StudyStepCompletion with started_at for the given step."""
    from app.models.study import StudyStepCompletion
    comp = StudyStepCompletion.query.filter_by(
        participant_id=participant.id, step_id=step.id
    ).first()
    if comp is None:
        comp = StudyStepCompletion(
            participant_id=participant.id,
            step_id=step.id,
            started_at=datetime.now(timezone.utc),
        )
        db.session.add(comp)
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
    return comp


def _record_step_done(participant, step, study):
    """Mark a StudyStepCompletion as completed; compute time_spent and is_late."""
    from app.models.study import StudyStepCompletion
    now = datetime.now(timezone.utc)
    comp = StudyStepCompletion.query.filter_by(
        participant_id=participant.id, step_id=step.id
    ).first()
    if comp is None:
        comp = StudyStepCompletion(
            participant_id=participant.id,
            step_id=step.id,
            started_at=now,
        )
        db.session.add(comp)
    comp.completed_at = now
    comp.is_late = step.is_past_deadline(study)
    if comp.started_at:
        delta = now - (
            comp.started_at.replace(tzinfo=timezone.utc)
            if comp.started_at.tzinfo is None else comp.started_at
        )
        comp.time_spent_seconds = int(delta.total_seconds())
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
    return comp


@study_bp.route('/<int:study_id>')
@login_required
def study_index(study_id: int):
    """Show current step or redirect to the correct sub-route."""
    from app.models.study import Study
    study = Study.query.get_or_404(study_id)

    if not study.is_active or study.is_archived:
        flash('Diese Studie ist nicht verfuegbar.', 'warning')
        return redirect('/')

    participant = _get_participant(study_id)
    if not participant:
        return redirect(url_for('study.enroll', study_id=study_id))

    if participant.is_dropped_out:
        flash('Du hast dich aus dieser Studie abgemeldet.', 'info')
        return redirect(url_for('study.available_studies'))

    if participant.is_completed:
        return render_template('study_done.html', study=study, participant=participant)

    step = study.get_step_for_participant(participant)
    if step is None:
        participant.completed_at = datetime.now(timezone.utc)
        db.session.commit()
        try:
            from app.utils.email import send_study_completed
            send_study_completed(
                participant.user.email,
                participant.user.display_name or participant.user.username,
                study.title,
            )
        except Exception:
            pass
        return render_template('study_done.html', study=study, participant=participant)

    # Per-step availability check
    eff_from, eff_until = step.get_availability(study)
    now = datetime.utcnow()
    if eff_from and now < eff_from:
        return render_template('study_waiting.html', study=study, step=step,
                               available_from=eff_from, participant=participant)
    if eff_until and now > eff_until and not step.allow_late_submission:
        flash('Die Frist fuer diesen Schritt ist abgelaufen.', 'danger')
        # Move past a hard-deadline missed step to avoid getting stuck
        participant.current_step += 1
        db.session.commit()
        return redirect(url_for('study.study_index', study_id=study_id))

    if step.step_type == 'agent_choice':
        _record_step_start(participant, step)
        return redirect(url_for('study.agent_choice_step', study_id=study_id, step_id=step.id))
    elif step.step_type == 'survey':
        _record_step_start(participant, step)
        next_url = url_for('study.step_done', study_id=study_id)
        return redirect(url_for('survey_bp.take', survey_id=step.survey_id, step_id=step.id, next=next_url))
    else:
        return redirect(url_for('study.task_step', study_id=study_id, task_id=step.task_id))


@study_bp.route('/<int:study_id>/enroll', methods=['GET', 'POST'])
@login_required
def enroll(study_id: int):
    """Let a student self-enroll in a study (with optional consent gate)."""
    from app.models.study import Study, StudyParticipant
    study = Study.query.get_or_404(study_id)

    if not study.is_active or study.is_archived:
        flash('Diese Studie ist nicht verfuegbar.', 'warning')
        return redirect('/')

    participant = _get_participant(study_id)
    if participant:
        return redirect(url_for('study.study_index', study_id=study_id))

    if not study.enrollment_open:
        flash('Die Anmeldefrist fuer diese Studie ist abgelaufen oder noch nicht gestartet.', 'warning')
        return redirect(url_for('study.available_studies'))

    if study.max_participants:
        count = StudyParticipant.query.filter_by(study_id=study_id).count()
        if count >= study.max_participants:
            flash('Diese Studie hat die maximale Teilnehmerzahl erreicht.', 'warning')
            return redirect(url_for('study.available_studies'))

    if request.method == 'POST':
        # Informed consent validation
        if study.require_consent and not request.form.get('consent_checkbox'):
            flash('Bitte stimme den Datenschutzhinweisen zu, um fortzufahren.', 'danger')
            return render_template('study_enroll.html', study=study)

        p = StudyParticipant(study_id=study_id, user_id=current_user.id)
        if study.require_consent:
            p.consent_given_at = datetime.now(timezone.utc)
        db.session.add(p)
        try:
            db.session.flush()
            # Between-subjects: assign condition
            study.assign_condition(p)
            db.session.commit()
        except Exception:
            db.session.rollback()
            flash('Du bist bereits angemeldet.', 'warning')
            return redirect(url_for('study.study_index', study_id=study_id))
        flash('Erfolgreich angemeldet!', 'success')
        return redirect(url_for('study.study_index', study_id=study_id))

    return render_template('study_enroll.html', study=study)


@study_bp.route('/<int:study_id>/task/<task_id>')
@login_required
def task_step(study_id: int, task_id: str):
    """Show a task that is part of the study flow."""
    from app.models.study import Study
    from app.models.task import Task
    study = Study.query.get_or_404(study_id)
    task = Task.query.get_or_404(task_id)

    participant = _get_participant(study_id)
    if not participant:
        return redirect(url_for('study.enroll', study_id=study_id))
    if participant.is_dropped_out:
        return redirect(url_for('study.available_studies'))

    # Find the matching step to record start time
    step = study.get_step_for_participant(participant)
    if step and step.task_id == task_id:
        _record_step_start(participant, step)
        # Availability check
        eff_from, eff_until = step.get_availability(study)
        now = datetime.utcnow()
        if eff_from and now < eff_from:
            return render_template('study_waiting.html', study=study, step=step,
                                   available_from=eff_from, participant=participant)
        if eff_until and now > eff_until and not step.allow_late_submission:
            flash('Die Frist fuer diesen Schritt ist abgelaufen.', 'danger')
            participant.current_step += 1
            db.session.commit()
            return redirect(url_for('study.study_index', study_id=study_id))

    # Determine agent: priority 1 = participant's active_agent (set by agent_choice step)
    #                   priority 2 = between-subjects condition agent
    #                   priority 3 = task-level agent override
    agent = None
    no_ai = False
    if participant.active_agent_id:
        from app.models.agent import AIAgent
        agent = db.session.get(AIAgent, participant.active_agent_id)
    elif study.study_design == 'between' and participant.condition_id:
        from app.models.study import StudyCondition
        condition = db.session.get(StudyCondition, participant.condition_id)
        if condition and condition.agent_id:
            from app.models.agent import AIAgent
            agent = db.session.get(AIAgent, condition.agent_id)
        elif condition and not condition.agent_id:
            no_ai = True
    elif task.agent_id:
        from app.models.agent import AIAgent
        agent = db.session.get(AIAgent, task.agent_id)

    # Resolve canonical agent info (falls back to task-default then platform default)
    from app.utils.agent_utils import resolve_agent as _ra
    _agent_id_raw = (agent.id if agent else None) or task.agent_id or ''
    resolved_agent_id, _, _, _, _ = _ra(_agent_id_raw, task.id)

    import json as _json
    _tracking_cfg = {}
    if study.tracking_config:
        try:
            _tracking_cfg = _json.loads(study.tracking_config)
        except Exception:
            _tracking_cfg = {}

    return render_template('task.html', task=task, agent=agent, is_custom=False,
                           study_id=study_id, in_study=True,
                           tracking_config=_tracking_cfg,
                           agent_display_name=study.agent_display_name or None,
                           no_ai=no_ai)


@study_bp.route('/<int:study_id>/step-done', methods=['GET', 'POST'])
@login_required
def step_done(study_id: int):
    """Called after a step is completed; records completion and advances step."""
    from app.models.study import Study
    study = Study.query.get_or_404(study_id)
    participant = _get_participant(study_id)
    if not participant:
        return redirect(url_for('study.enroll', study_id=study_id))
    if participant.is_completed:
        return render_template('study_done.html', study=study, participant=participant)

    step = study.get_step_for_participant(participant)
    if step:
        _record_step_done(participant, step, study)

    participant.current_step += 1
    total_steps = study.get_step_count_for_participant(participant)
    if participant.current_step >= total_steps:
        participant.completed_at = datetime.now(timezone.utc)
        db.session.commit()
        try:
            from app.utils.email import send_study_completed
            send_study_completed(
                participant.user.email,
                participant.user.display_name or participant.user.username,
                study.title,
            )
        except Exception:
            pass
        return render_template('study_done.html', study=study, participant=participant)

    db.session.commit()
    return redirect(url_for('study.study_index', study_id=study_id))


@study_bp.route('/<int:study_id>/dropout', methods=['POST'])
@login_required
def dropout(study_id: int):
    """Allow a student to withdraw from a study."""
    from app.models.study import Study
    Study.query.get_or_404(study_id)
    participant = _get_participant(study_id)
    if not participant:
        abort(404)
    if not participant.is_dropped_out:
        participant.dropped_out_at = datetime.now(timezone.utc)
        participant.dropout_reason = request.form.get('reason', '')[:500]
        db.session.commit()
    flash('Du wurdest erfolgreich aus der Studie abgemeldet.', 'info')
    return redirect(url_for('study.available_studies'))


@study_bp.route('/<int:study_id>/agent-choice/<int:step_id>', methods=['GET', 'POST'])
@login_required
def agent_choice_step(study_id: int, step_id: int):
    """Let a participant choose their AI agent for the upcoming tasks."""
    import json as _json
    from app.models.study import Study, StudyStep, AgentSwitchHistory
    from app.models.agent import AIAgent

    study = Study.query.get_or_404(study_id)
    step = StudyStep.query.filter_by(id=step_id, study_id=study_id).first_or_404()
    participant = _get_participant(study_id)
    if not participant:
        return redirect(url_for('study.enroll', study_id=study_id))
    if participant.is_dropped_out:
        return redirect(url_for('study.available_studies'))

    # Load available agents defined for this step
    agent_ids = []
    if step.available_agents:
        try:
            agent_ids = _json.loads(step.available_agents)
        except Exception:
            agent_ids = []
    if agent_ids:
        agents = AIAgent.query.filter(AIAgent.id.in_(agent_ids)).order_by(AIAgent.sort_order).all()
    else:
        agents = AIAgent.query.filter_by(is_active=True, use_research=True).order_by(AIAgent.sort_order).all()

    if request.method == 'POST':
        chosen_id = request.form.get('agent_id', '').strip()
        valid_ids = [a.id for a in agents]
        if not chosen_id or chosen_id not in valid_ids:
            flash('Bitte wähle einen Agenten aus.', 'danger')
            return render_template('study_agent_choice.html', study=study, step=step,
                                   agents=agents, participant=participant)

        prev_id = participant.active_agent_id
        switch = AgentSwitchHistory(
            participant_id=participant.id,
            agent_id=chosen_id,
            previous_agent_id=prev_id,
            step_id=step.id,
            wave_number=step.wave_number,
            chosen_at=datetime.now(timezone.utc),
        )
        db.session.add(switch)
        participant.active_agent_id = chosen_id
        _record_step_done(participant, step, study)
        participant.current_step += 1
        total_steps = study.get_step_count_for_participant(participant)
        if participant.current_step >= total_steps:
            participant.completed_at = datetime.now(timezone.utc)
            db.session.commit()
            return render_template('study_done.html', study=study, participant=participant)
        db.session.commit()
        return redirect(url_for('study.study_index', study_id=study_id))

    return render_template('study_agent_choice.html', study=study, step=step,
                           agents=agents, participant=participant)


@study_bp.route('/available')
@login_required
def available_studies():
    """List all studies a student can enroll in or is already enrolled in."""
    from app.models.study import Study, StudyParticipant
    studies = Study.query.filter_by(is_active=True, is_archived=False).all()
    my_studies = {
        p.study_id: p for p in
        StudyParticipant.query.filter_by(user_id=current_user.id).all()
    }
    return render_template('study_list.html', studies=studies, my_studies=my_studies)


@study_bp.route('/<int:study_id>/leaderboard')
@login_required
def study_leaderboard(study_id: int):
    """Return leaderboard data for a study (JSON or HTML depending on Accept header)."""
    from app.models.study import Study, StudyParticipant
    from app.models.task import TaskSubmission
    from app.models.user import User
    from sqlalchemy import func

    study = Study.query.get_or_404(study_id)

    # Must be enrolled to view leaderboard
    participant = _get_participant(study_id)
    if not participant:
        if request.accept_mimetypes.best == 'application/json':
            return jsonify({'error': 'Not enrolled'}), 403
        return redirect(url_for('study.enroll', study_id=study_id))

    if not study.leaderboard_enabled:
        if request.accept_mimetypes.best == 'application/json':
            return jsonify({'enabled': False, 'entries': []})
        abort(404)

    task_ids = study.task_ids

    entries = []
    if task_ids:
        # Single aggregating JOIN — avoids N+1 per participant
        rows = (
            db.session.query(
                StudyParticipant,
                User,
                func.avg(TaskSubmission.score).label('avg_score'),
                func.count(TaskSubmission.id).label('tasks_done'),
            )
            .join(User, User.id == StudyParticipant.user_id)
            .outerjoin(
                TaskSubmission,
                (TaskSubmission.user_id == StudyParticipant.user_id)
                & TaskSubmission.task_id.in_(task_ids)
                & TaskSubmission.score.isnot(None),
            )
            .filter(
                StudyParticipant.study_id == study_id,
                StudyParticipant.dropped_out_at.is_(None),
            )
            .group_by(StudyParticipant.id, User.id)
            .having(func.count(TaskSubmission.id) > 0)
            .all()
        )
        for p, user, avg_score, tasks_done in rows:
            display = 'Anonymous' if user.leaderboard_anonymous else user.username
            entries.append({
                'display': display,
                'avg_score': round(float(avg_score), 1),
                'tasks_done': int(tasks_done),
                'is_me': (p.user_id == current_user.id),
            })

        entries.sort(key=lambda e: e['avg_score'], reverse=True)
        for i, e in enumerate(entries):
            e['rank'] = i + 1

    if request.accept_mimetypes.best == 'application/json':
        return jsonify({'enabled': True, 'entries': entries})

    return render_template('study_leaderboard.html', study=study,
                           entries=entries, participant=participant)


@study_bp.route('/<int:study_id>/track', methods=['POST'])
@csrf.exempt
@login_required
def task_track(study_id: int):
    """Receive a batch of interaction tracking events from the client."""
    import json as _json
    from app.models.study import Study
    from app.models.tracking import TaskSessionTracking

    study = Study.query.get_or_404(study_id)

    # Verify participant is enrolled
    participant = _get_participant(study_id)
    if not participant:
        return jsonify({'ok': False, 'error': 'Not enrolled'}), 403

    # Check tracking is enabled
    tracking_cfg = {}
    if study.tracking_config:
        try:
            tracking_cfg = _json.loads(study.tracking_config)
        except Exception:
            tracking_cfg = {}

    if not tracking_cfg.get('enabled', False):
        return jsonify({'ok': False, 'error': 'Tracking disabled'}), 403

    data = request.get_json(silent=True) or {}
    task_id = data.get('task_id', '')
    session_start = data.get('session_start', '')
    batch_seq = int(data.get('batch_seq', 0))
    events = data.get('events', [])
    submission_id = data.get('submission_id')

    if not task_id or not events:
        return jsonify({'ok': False, 'error': 'Missing data'}), 400

    # Filter events by allowed types
    allowed = set(tracking_cfg.get('events', []))
    if allowed:
        events = [e for e in events if e.get('type', '') in allowed]

    if not events:
        return jsonify({'ok': True, 'saved': 0})

    record = TaskSessionTracking(
        user_id=current_user.id,
        study_id=study_id,
        task_id=task_id,
        submission_id=submission_id,
        session_start=session_start,
        batch_seq=batch_seq,
        events_data=_json.dumps(events),
    )
    db.session.add(record)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        return jsonify({'ok': False, 'error': 'DB error'}), 500

    return jsonify({'ok': True, 'saved': len(events)})

