from flask_socketio import emit, join_room
from flask import request
from flask_login import current_user
import os
from app.services.ai_service import AIService, AIServiceError
from app.services.session_store import store
from app.services import task_tracker
import config
import logging
import traceback
import uuid
import json
from datetime import datetime, timezone

logger = logging.getLogger('bpmtutor.chat')

_FALLBACK_GREETING = (
    "Hello! I'm your BPMN Mentor. "
    "Start modeling your process, and feel free to ask me for help anytime!"
)
_FALLBACK_GREETING_DE = (
    "Hallo! Ich bin dein BPMN-Mentor. "
    "Beginne mit der Modellierung deines Prozesses und frag mich jederzeit um Hilfe!"
)
_INITIAL_GREETING_SIGNAL = '[INITIAL_GREETING]'
_COMPLETION_REVIEW_SIGNAL = '[COMPLETION_REVIEW]'


def _resolve_agent(agent_id: str, task_id: str) -> tuple:
    """Return (agent_id, agent_name, modeling_mode, control_mode) for the session.
    Falls back to the task's assigned agent, then the platform default."""
    try:
        from app.models.agent import AIAgent
        # 1. Explicit agent_id from client (study condition or UI picker)
        if agent_id:
            a = AIAgent.query.get(agent_id)
            if a:
                return a.id, a.name, a.modeling_mode, a.control_mode
        # 2. Task-assigned agent
        if task_id and task_id != 'custom':
            from app.models.task import Task
            t = Task.query.get(task_id)
            if t and t.agent_id:
                a = AIAgent.query.get(t.agent_id)
                if a:
                    return a.id, a.name, a.modeling_mode, a.control_mode
        # 3. Platform default
        a = AIAgent.get_default()
        if a:
            return a.id, a.name, a.modeling_mode, a.control_mode
    except Exception as _e:
        logger.warning('[chat_handler] agent resolve error: %s', _e)
    return '', 'Mentor', 'none', 'human'


def _celery_available() -> bool:
    """Return True if a Redis broker is configured and Celery tasks can be dispatched."""
    return bool(os.getenv('REDIS_URL', ''))


def _get_task_description(task_id: str, session: dict, lang: str) -> str:
    """Resolve the task description for the given task_id, session, and language."""
    if task_id == 'custom':
        return session.get('custom_task_desc', '')
    try:
        from app.models.task import Task as TaskModel
        task_obj = TaskModel.query.get(task_id)
        if task_obj:
            return task_obj.description_de if lang == 'de' and task_obj.description_de else task_obj.description or ''
    except Exception:
        pass
    return ''

def register_handlers(socketio):

    @socketio.on('connect')
    def handle_connect():
        emit('connected', {'status': 'connected'})
        # Join user-specific notification room if authenticated
        try:
            if current_user.is_authenticated:
                join_room(f'user_{current_user.id}')
        except Exception:
            pass

    @socketio.on('disconnect')
    def handle_disconnect():
        sid = request.sid
        session = store.remove(sid)
        if session:
            task_tracker.cleanup_task(sid)
            logger.info('[Backend] Cleaned up session %s for task %s', sid, session['task_id'])

    @socketio.on('stop_ai')
    def handle_stop_ai(data):
        session = store.get(request.sid)
        if session:
            session['stopped'] = True

    @socketio.on('join_task')
    def handle_join_task(data):
        task_id = data.get('task_id')
        # Accept DB tasks (any string) or 'custom'; validate below
        if not isinstance(task_id, str) or not task_id:
            return

        sid = request.sid
        join_room(task_id)

        session_uuid = str(uuid.uuid4())

        # --- Resolve which agent to use for this session ---
        requested_agent_id = data.get('agent_id', '')
        agent_id, agent_name, modeling_mode, control_mode = _resolve_agent(requested_agent_id, task_id)

        # --- Resolve API key from DB settings if available ---
        api_key = data.get('api_key', '')
        base_url = data.get('base_url', '')
        try:
            from app.models.settings import Settings
            from app.utils.crypto import decrypt_api_key
            api_key_mode = Settings.get('API_KEY_MODE', 'global')
            if api_key_mode == 'global':
                raw = Settings.get('GLOBAL_API_KEY', api_key) or api_key
                api_key = decrypt_api_key(raw)
            elif api_key_mode == 'per_user' and current_user.is_authenticated:
                raw = current_user.personal_api_key or api_key
                api_key = decrypt_api_key(raw)
            # Fallback: if key is still empty but user has a personal key, use it
            if not api_key and current_user.is_authenticated:
                personal = getattr(current_user, 'personal_api_key', None)
                if personal:
                    api_key = decrypt_api_key(personal)
            # Use admin-configured endpoint as base_url fallback
            if not base_url:
                base_url = (Settings.get(Settings.API_ENDPOINT) or '').strip()
        except Exception:
            pass

        settings = {
            'api_key': api_key,
            'model': data.get('model', ''),
            'lang': data.get('lang', 'en'),
            'base_url': base_url,
        }

        # Fall back to user's saved preferred model if the client didn't send one
        if not settings['model'] and current_user.is_authenticated and getattr(current_user, 'preferred_model', None):
            settings['model'] = current_user.preferred_model

        store.create(sid, task_id, session_uuid, settings, agent_id=agent_id)
        task_tracker.start_task(sid, task_id, session_uuid)

        # --- Resume or create TaskSubmission in DB ---
        bpmn_draft = None
        elapsed_seconds = 0
        try:
            from app.extensions import db
            from app.models.task import TaskSubmission, Task
            task_obj = Task.query.get(task_id)
            if task_obj:
                user_id = current_user.id if current_user.is_authenticated else None
                # Look for an existing in-progress submission first
                existing = None
                if user_id:
                    existing = (TaskSubmission.query
                                .filter_by(task_id=task_id, user_id=user_id)
                                .filter(TaskSubmission.completed_at.is_(None))
                                .order_by(TaskSubmission.started_at.desc())
                                .first())
                if existing:
                    sub = existing
                    # Update session_id so autosave queries can find this submission
                    sub.session_id = request.sid
                    db.session.commit()
                    bpmn_draft = existing.bpmn_draft or None
                    # Calculate elapsed time so client can set remaining time
                    if existing.started_at:
                        started = existing.started_at
                        if started.tzinfo is None:
                            from datetime import timezone as _tz
                            started = started.replace(tzinfo=_tz.utc)
                        elapsed_seconds = int((datetime.now(timezone.utc) - started).total_seconds())
                    # Restore mentor memory from this submission
                    if existing.mentor_memory_list:
                        store.get(sid)['mentor_state']['memory'] = existing.mentor_memory_list
                    # Restore chat history from this submission
                    if existing.chat_history:
                        store.get(sid)['chat_history'] = list(existing.chat_history)
                else:
                    sub = TaskSubmission(
                        task_id=task_id,
                        user_id=user_id,
                        session_id=request.sid,
                        started_at=datetime.now(timezone.utc),
                        interactions=0,
                        tokens_in=0,
                        tokens_out=0,
                    )
                    db.session.add(sub)
                    db.session.commit()
                # Store submission ID in session for later update
                store.get(sid)['submission_id'] = sub.id
        except Exception as e:
            logger.warning('[chat_handler] TaskSubmission create error: %s', e)

        # --- Load mentor memory from most recent open submission (fallback if not already set) ---
        try:
            from app.models.task import TaskSubmission, Task as _Task
            user_id = current_user.id if current_user.is_authenticated else None
            if user_id and not store.get(sid)['mentor_state']['memory']:
                prev = (TaskSubmission.query
                        .filter_by(task_id=task_id, user_id=user_id)
                        .filter(TaskSubmission.completed_at.is_(None))
                        .order_by(TaskSubmission.started_at.desc())
                        .first())
                if prev and prev.mentor_memory_list:
                    store.get(sid)['mentor_state']['memory'] = prev.mentor_memory_list
        except Exception as _me:
            logger.warning('[chat_handler] mentor memory load error: %s', _me)

        emit('task_joined', {
            'task_id': task_id,
            'bpmn_draft': bpmn_draft,
            'elapsed_seconds': elapsed_seconds,
            'chat_log': store.get(sid)['chat_history'] if store.get(sid) else [],
        })
        emit('agent_info', {
            'agent_id': agent_id,
            'agent_name': agent_name,
            'modeling_mode': modeling_mode,
            'control_mode': control_mode,
        })

    @socketio.on('update_settings')
    def handle_update_settings(data):
        session = store.get(request.sid)
        if not session:
            return
        settings = session['settings']
        if data.get('api_key'):
            settings['api_key'] = data['api_key']
        if data.get('model'):
            settings['model'] = data['model']
        if data.get('lang'):
            settings['lang'] = data['lang']
        if data.get('base_url') is not None:
            settings['base_url'] = data['base_url']

    @socketio.on('set_custom_task')
    def handle_set_custom_task(data):
        description = data.get('description', '')
        session = store.get(request.sid)
        if session and session['task_id'] == 'custom' and isinstance(description, str):
            session['custom_task_desc'] = description

    @socketio.on('send_message')
    def handle_send_message(data):
        task_id = data.get('task_id')
        message = data.get('message')
        current_bpmn = data.get('bpmn_xml', '')

        if not isinstance(task_id, str) or not task_id:
            return
        if not isinstance(message, str) or not message:
            return

        sid = request.sid
        session = store.get(sid)
        if not session:
            return

        if session['stopped']:
            session['stopped'] = False

        emit('ai_typing', {'typing': True})

        settings = session['settings']
        # Prefer server-side api_key (from DB) over client-supplied localStorage key
        api_key = settings.get('api_key', '') or data.get('api_key', '')
        model = data.get('model') or settings.get('model', '')
        lang = data.get('lang') or settings.get('lang', 'en')
        base_url = data.get('base_url') or settings.get('base_url', '')

        task_description = _get_task_description(task_id, session, lang)

        chat_history = session['chat_history']
        state = session['mentor_state']

        mentor = AIService(task_id, session_id=session['session_uuid'],
                           api_key=api_key, model=model, lang=lang,
                           tracker_key=sid, base_url=base_url,
                           agent_id=session.get('agent_id', ''))

        is_initial_greeting = message == _INITIAL_GREETING_SIGNAL

        # -- Initial greeting --
        if is_initial_greeting:
            if chat_history and chat_history[-1]['message'] == _INITIAL_GREETING_SIGNAL:
                chat_history.pop()

            _fallback = _FALLBACK_GREETING_DE if lang == 'de' else _FALLBACK_GREETING

            if _celery_available():
                from app.tasks.llm_tasks import process_mentor_greeting
                try:
                    ar = process_mentor_greeting.delay(
                        sid=sid,
                        task_id=task_id,
                        session_uuid=session['session_uuid'],
                        task_description=task_description,
                        api_key=api_key,
                        model=model,
                        lang=lang,
                        tracker_key=sid,
                        fallback_greeting=_fallback,
                        agent_id=session.get('agent_id', ''),
                    )
                    greeting = ar.get(timeout=300)
                except Exception as _ce:
                    logger.error('[Mentor] Celery greeting error: %s', _ce)
                    greeting = _fallback
            else:
                try:
                    result = mentor.generate_greeting(task_description)
                    greeting = result.get('message', _fallback)
                except AIServiceError as e:
                    logger.error('[Mentor] Greeting API error (%s): %s', e.error_type, e)
                    emit('ai_typing', {'typing': False})
                    emit('error', {'message': str(e), 'error_type': e.error_type})
                    return
                except Exception as e:
                    logger.error('[Mentor] Greeting error: %s', e)
                    greeting = _fallback

                emit('ai_response', {
                    'sender': 'ai',
                    'message': greeting,
                    'complete': False,
                    'phase': 'GREETING',
                    'issues': [],
                })
                emit('ai_typing', {'typing': False})

            chat_history.append({'sender': 'ai', 'message': greeting})
            state['memory'].append({'role': 'assistant', 'content': greeting})
            return


        # -- Regular user message --
        is_completion_review = message == _COMPLETION_REVIEW_SIGNAL
        if not is_completion_review:
            chat_history.append({'sender': 'user', 'message': message})
            state['memory'].append({'role': 'user', 'content': message})

        # Resolve agent type for instruction routing
        _agent_type = 'mentor'
        _agent_id = session.get('agent_id', '')
        if _agent_id:
            try:
                from app.models.agent import AIAgent
                _agent = AIAgent.query.get(_agent_id)
                if _agent:
                    _agent_type = _agent.agent_type or 'mentor'
            except Exception:
                pass

        if is_completion_review:
            # Special completion review instruction — override normal instruction
            if _agent_type == 'colleague':
                if lang == 'de':
                    instruction = (
                        'Der Studierende möchte die Aufgabe abschließen. Überprüfe das aktuelle Modell gemeinsam. '
                        'Wenn es vollständig und korrekt ist: setze complete: true in deiner Antwort. '
                        'Wenn noch Probleme vorhanden sind: erkläre sie klar und setze complete: false. '
                        'Verwende ANALYSIS-Phase. Antworte auf Deutsch.'
                    )
                else:
                    instruction = (
                        'The student wants to complete the task. Review the current model together. '
                        'If it is complete and correct: set complete: true in your response. '
                        'If there are still issues: explain them clearly and set complete: false. '
                        'Use ANALYSIS phase.'
                    )
            else:  # supervisor
                if lang == 'de':
                    instruction = (
                        'Der Studierende beantragt den Abschluss der Aufgabe. Überprüfe das Modell autoritativ und gründlich (ANALYSIS-Phase). '
                        'Genehmige (complete: true) nur, wenn das Modell alle Anforderungen erfüllt und keine syntax- oder semantic-Fehler hat. '
                        'Andernfalls: erkläre genau, was noch fehlt oder falsch ist (complete: false). '
                        'Antworte auf Deutsch.'
                    )
                else:
                    instruction = (
                        'The student is requesting task completion. Review the model authoritatively and thoroughly (ANALYSIS phase). '
                        'Approve (complete: true) only if the model meets all requirements with no syntax or semantic errors. '
                        'Otherwise: explain exactly what is missing or wrong (complete: false).'
                    )
        elif _agent_type == 'colleague':
            if lang == 'de':
                instruction = (
                    'Der Studierende hat eine Nachricht gesendet. Reagiere als gleichberechtigter Kollege. '
                    'Wenn der Studierende der Aufgabenteilung zustimmt oder ihr bereits modelliert: '
                    'Generiere SOFORT bpmn_ops für alle deine Elemente in deinem Pool. '
                    'Wenn er eine Frage stellt: beantworte sie direkt und sachlich (ANSWER-Phase). '
                    'Wenn er das Modell überprüfen lassen möchte: verwende ANALYSIS-Phase mit gemeinsamer Perspektive. '
                    'Antworte auf Deutsch.'
                )
            else:
                instruction = (
                    'The student has sent a message. React as an equal Colleague. '
                    'If the student agrees to the task split or you are already modeling: '
                    'Generate bpmn_ops IMMEDIATELY for all your elements in your pool. '
                    'If they ask a question: answer directly (ANSWER phase). '
                    'If they request a model review: use ANALYSIS phase with collaborative perspective.'
                )
        elif _agent_type == 'supervisor':
            if lang == 'de':
                instruction = (
                    'Der Studierende hat eine Nachricht gesendet. Reagiere als Supervisor. '
                    'Wenn er Feedback oder eine Überprüfung wünscht: gib direktes, autoritatives Feedback (ANALYSIS-Phase). '
                    'Wenn er eine Frage stellt: beantworte sie direkt (ANSWER-Phase). '
                    'Wenn er allgemeine Nachrichten sendet: reagiere kurz (FEEDBACK-Phase). '
                    'Genehmige den Abschluss nur, wenn alle syntax- und semantic-Probleme behoben sind. '
                    'Antworte auf Deutsch.'
                )
            else:
                instruction = (
                    'The student has sent a message. React as a Supervisor. '
                    'If they request feedback or a review: give direct, authoritative evaluation (ANALYSIS phase). '
                    'If they ask a question: answer directly (ANSWER phase). '
                    'For general messages: respond briefly (FEEDBACK phase). '
                    'Only approve completion when all syntax and semantic issues are resolved.'
                )
        elif _agent_type == 'assistant':
            if lang == 'de':
                instruction = (
                    'Der Studierende hat eine Nachricht gesendet. Reagiere als hilfreicher Assistent. '
                    'Wenn er eine Frage stellt: beantworte sie direkt und sachlich (ANSWER-Phase). '
                    'Wenn er das Modell überprüfen lassen möchte: führe ANALYSIS-Phase durch. '
                    'Wenn er allgemeine Kommentare macht: reagiere ermutigend (FEEDBACK-Phase). '
                    'Antworte auf Deutsch.'
                )
            else:
                instruction = (
                    'The student has sent a message. React as a helpful Assistant. '
                    'If they ask a question: answer directly and factually (ANSWER phase). '
                    'If they request model review: use ANALYSIS phase. '
                    'For general comments: respond encouragingly (FEEDBACK phase).'
                )
        else:  # mentor, delegant, or custom
            if lang == 'de':
                instruction = (
                    'Der Studierende hat eine Nachricht gesendet. Reagiere darauf: '
                    'Wenn er dich bittet, sein Modell zu überprüfen, verwende die ANALYSIS-Phase. '
                    'Wenn er eine Frage zu BPMN stellt, verwende die ANSWER-Phase mit sokratischen Fragen. '
                    'Wenn er einen allgemeinen Kommentar macht, verwende die FEEDBACK-Phase mit Ermutigung. '
                    'Antworte auf Deutsch.'
                )
            else:
                instruction = (
                    'The student has sent a message. React to it: '
                    'If they are asking you to check, review, or analyze their model, use ANALYSIS phase. '
                    'If they are asking a question about BPMN, the task, or modeling techniques, use ANSWER phase with Socratic questioning. '
                    'If they are making a general comment or showing progress, use FEEDBACK phase with encouragement.'
                )

        # Use a natural-language equivalent when the signal is a special internal signal
        _effective_message = message
        if is_completion_review:
            _effective_message = ('Bitte überprüfe das Modell und entscheide, ob die Aufgabe abgeschlossen werden kann.'
                                  if lang == 'de' else
                                  'Please review the model and decide if the task can be completed.')

        if _celery_available():
            from app.tasks.llm_tasks import process_mentor_message
            ar = process_mentor_message.delay(
                sid=sid,
                task_id=task_id,
                session_uuid=session['session_uuid'],
                task_description=task_description,
                instruction=instruction,
                memory=list(state['memory']),
                current_bpmn=current_bpmn,
                user_message=_effective_message,
                previous_issues=state.get('last_issues', []),
                api_key=api_key,
                model=model,
                lang=lang,
                tracker_key=sid,
                submission_id=session.get('submission_id'),
            )
            try:
                response = ar.get(timeout=300)
            except Exception as _ce:
                logger.error('[Mentor] Celery message error: %s', _ce)
                return  # Celery task already emitted error to the client
            # Update in-memory state (Celery task handled DB persist and SocketIO emit)
            resp_message = response.get('message', '')
            if resp_message:
                state['memory'].append({'role': 'assistant', 'content': resp_message})
                chat_history.append({'sender': 'ai', 'message': resp_message})
            issues = response.get('issues', [])
            if issues:
                state['last_issues'] = issues
            resp_phase = response.get('phase', 'FEEDBACK')
            phase_counts = state.setdefault('phase_counts', {})
            phase_counts[resp_phase] = phase_counts.get(resp_phase, 0) + 1
            # Persist chat_log to DB so it survives page reloads
            try:
                from app.extensions import db as _db
                from app.models.task import TaskSubmission as _Sub
                import json as _j
                _sub_id = session.get('submission_id')
                if _sub_id:
                    _sub = _Sub.query.get(_sub_id)
                    if _sub:
                        _sub.chat_log = _j.dumps(chat_history, ensure_ascii=False)
                        _db.session.commit()
            except Exception as _cpe:
                logger.warning('[chat_handler] chat_log persist error (celery): %s', _cpe)
        else:
            try:
                response = mentor.get_mentor_response(
                    task_description, instruction, state['memory'],
                    current_bpmn, user_message=_effective_message,
                    previous_issues=state.get('last_issues', []),
                )
                resp_phase = response.get('phase', 'FEEDBACK')
                resp_message = response.get('message', '')
                issues = response.get('issues', [])
                is_complete = response.get('complete', False)

                if resp_message:
                    state['memory'].append({'role': 'assistant', 'content': resp_message})
                    chat_history.append({'sender': 'ai', 'message': resp_message})

                if issues:
                    state['last_issues'] = issues

                phase_counts = state.setdefault('phase_counts', {})
                phase_counts[resp_phase] = phase_counts.get(resp_phase, 0) + 1

                try:
                    from app.extensions import db as _db
                    from app.models.task import TaskSubmission as _Sub
                    _sub_id = session.get('submission_id')
                    if _sub_id:
                        _sub = _Sub.query.get(_sub_id)
                        if _sub:
                            import json as _j
                            _sub.mentor_memory = _j.dumps(state['memory'])
                            _sub.phase_counts = _j.dumps(phase_counts)
                            _sub.chat_log = _j.dumps(chat_history, ensure_ascii=False)
                            _db.session.commit()
                except Exception as _pe:
                    logger.warning('[chat_handler] memory persist error: %s', _pe)

                emit('ai_response', {
                    'sender': 'ai',
                    'message': resp_message,
                    'complete': is_complete,
                    'phase': resp_phase,
                    'issues': [],
                    'bpmn_ops': response.get('bpmn_ops', []),
                })

                if issues:
                    emit('mentor_issues', {'issues': issues})

                if response.get('bpmn_ops'):
                    emit('bpmn_ops', {'ops': response['bpmn_ops']})

                emit('ai_typing', {'typing': False})

            except AIServiceError as e:
                logger.error('[Mentor] API error (%s): %s', e.error_type, e)
                emit('ai_typing', {'typing': False})
                emit('error', {
                    'message': str(e),
                    'error_type': e.error_type,
                })
            except Exception as e:
                logger.error('[Mentor] send_message error: %s', e, exc_info=True)
                emit('ai_typing', {'typing': False})
                emit('error', {'message': 'An unexpected error occurred. Please try again.'})

    @socketio.on('request_analysis')
    def handle_request_analysis(data):
        """Student explicitly requests mentor analysis of their model."""
        task_id = data.get('task_id')
        current_bpmn = data.get('bpmn_xml', '')

        is_valid = isinstance(task_id, str) and task_id
        if not is_valid:
            return

        sid = request.sid
        session = store.get(sid)
        if not session:
            return

        emit('ai_typing', {'typing': True})

        settings = session['settings']
        # Prefer server-side api_key (from DB) over client-supplied localStorage key
        api_key = settings.get('api_key', '') or data.get('api_key', '')
        model = data.get('model') or settings.get('model', '')
        lang = data.get('lang') or settings.get('lang', 'en')

        task_description = _get_task_description(task_id, session, lang)

        state = session['mentor_state']

        mentor = AIService(task_id, session_id=session['session_uuid'],
                           api_key=api_key, model=model, lang=lang,
                           tracker_key=sid,
                           agent_id=session.get('agent_id', ''))

        if lang == 'de':
            instruction = (
                'Der Studierende hat eine vollständige Überprüfung seines BPMN-Modells angefordert. '
                'Analysiere das Modell gründlich anhand der Aufgabenbeschreibung und BPMN-Standards. '
                'Verwende die ANALYSIS-Phase. Melde alle Probleme mit sokratischen Hinweisen. Antworte auf Deutsch.'
            )
            user_msg = 'Bitte überprüfe mein Modell.'
        else:
            instruction = (
                'The student has requested a full review of their BPMN model. '
                'Analyze the model thoroughly against the task description and BPMN standards. '
                'Use ANALYSIS phase. Report all issues with Socratic hints.'
            )
            user_msg = 'Please review my model.'

        try:
            response = mentor.get_mentor_response(
                task_description, instruction, state['memory'],
                current_bpmn, user_message=user_msg,
                phase_hint='ANALYSIS',
                previous_issues=state.get('last_issues', []),
            )
            message = response.get('message', '')
            issues = response.get('issues', [])

            if message:
                state['memory'].append({'role': 'assistant', 'content': message})
                session['chat_history'].append({'sender': 'ai', 'message': message})

            state['last_issues'] = issues

            emit('ai_response', {
                'sender': 'ai',
                'message': message,
                'complete': False,
                'phase': 'ANALYSIS',
                'issues': [],
            })

            if issues:
                emit('mentor_issues', {'issues': issues})

            task_tracker.snapshot_task(sid, current_bpmn)

        except AIServiceError as e:
            logger.error('[Mentor] Analysis API error (%s): %s', e.error_type, e)
            emit('error', {
                'message': str(e),
                'error_type': e.error_type,
            })
        except Exception as e:
            logger.error('[Mentor] Analysis error: %s', e, exc_info=True)
            emit('error', {'message': 'An unexpected error occurred during analysis.'})
        finally:
            emit('ai_typing', {'typing': False})

    @socketio.on('request_completion')
    def handle_request_completion(data):
        task_id = data.get('task_id')
        bpmn_xml = data.get('bpmn_xml', '')

        is_valid = isinstance(task_id, str) and task_id
        if not is_valid:
            return

        session = store.get(request.sid)
        if not session:
            return

        # Mark that the next AI response should trigger completion_result logic
        session['mentor_state']['completion_review_pending'] = True

        # Delegate to the normal message handler with a special completion review signal
        handle_send_message({
            'task_id': task_id,
            'message': _COMPLETION_REVIEW_SIGNAL,
            'bpmn_xml': bpmn_xml,
        })

    @socketio.on('clear_chat')
    def handle_clear_chat(data):
        session = store.get(request.sid)
        if session:
            session['chat_history'] = []
            session['mentor_state'] = {'memory': [], 'last_issues': []}
            emit('chat_cleared', {'task_id': session['task_id']})

    @socketio.on('dismiss_issue')
    def handle_dismiss_issue(data):
        """Remove a single issue from mentor state."""
        issue_index = data.get('issue_index')
        if issue_index is None:
            return
        session = store.get(request.sid)
        if session and isinstance(issue_index, int):
            last_issues = session['mentor_state'].get('last_issues', [])
            if 0 <= issue_index < len(last_issues):
                removed = last_issues.pop(issue_index)
                logger.debug('[Mentor] Issue dismissed: %s', removed.get('shortDesc', '?'))


def complete_and_upload(task_id: str, bpmn_xml: str = '', sid: str = '') -> int | None:
    """Clean up session state when a task is completed and persist to DB.
    Returns the TaskSubmission id if available."""
    sub_id = None
    if sid:
        session = store.remove(sid)
        if session:
            task_tracker.save_task_report(sid, bpmn_xml)
            sub_id = _persist_submission(sid, session, bpmn_xml)
    else:
        # Fallback: find all sessions for this task
        sids = store.find_by_task(task_id)
        for s in sids:
            session = store.remove(s)
            task_tracker.save_task_report(s, bpmn_xml)
            if session:
                sub_id = _persist_submission(s, session, bpmn_xml)
    return sub_id


def _persist_submission(sid: str, session: dict, bpmn_xml: str) -> int | None:
    """Update TaskSubmission record in DB with final data. Returns the submission id."""
    sub_id = session.get('submission_id')
    if not sub_id:
        return None
    try:
        from app.extensions import db
        from app.models.task import TaskSubmission
        sub = TaskSubmission.query.get(sub_id)
        if not sub:
            return None
        chat_history = session.get('chat_history', [])
        sub.bpmn_xml = bpmn_xml
        sub.chat_log = json.dumps(chat_history, ensure_ascii=False)
        sub.completed_at = datetime.now(timezone.utc)
        sub.interactions = len([m for m in chat_history if m.get('sender') == 'user'])
        # persist mentor memory and phase counts
        mentor_mem = session.get('mentor_state', {}).get('memory', [])
        phase_counts = session.get('mentor_state', {}).get('phase_counts', {})
        sub.mentor_memory = json.dumps(mentor_mem)
        sub.phase_counts = json.dumps(phase_counts)
        # tokens tracked externally by task_tracker — read if available
        try:
            from app.services import task_tracker as tt
            stats = tt.get_task_stats(sid) or {}
            sub.tokens_in = stats.get('tokens_in', 0)
            sub.tokens_out = stats.get('tokens_out', 0)
        except Exception:
            pass
        db.session.commit()
        return sub_id
    except Exception as e:
        logger.error('[chat_handler] TaskSubmission persist error: %s', e)
        return None
