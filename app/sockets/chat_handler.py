from flask_socketio import emit, join_room
from flask import request
from flask_login import current_user
from app.ai_service import AIService, AIServiceError
from app.session_store import store
from app import task_tracker
import config
import traceback
import uuid
import json
from datetime import datetime, timezone

_FALLBACK_GREETING = (
    "Hello! I'm your BPMN Mentor. "
    "Start modeling your process, and feel free to ask me for help anytime!"
)
_FALLBACK_GREETING_DE = (
    "Hallo! Ich bin dein BPMN-Mentor. "
    "Beginne mit der Modellierung deines Prozesses und frag mich jederzeit um Hilfe!"
)
_INITIAL_GREETING_SIGNAL = '[INITIAL_GREETING]'

def register_handlers(socketio):

    @socketio.on('connect')
    def handle_connect():
        emit('connected', {'status': 'connected'})

    @socketio.on('disconnect')
    def handle_disconnect():
        sid = request.sid
        session = store.remove(sid)
        if session:
            task_tracker.cleanup_task(sid)
            print(f'[Backend] Cleaned up session {sid} for task {session["task_id"]}')

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

        session_uuid = str(uuid.uuid4())[:8]

        # --- Resolve API key from DB settings if available ---
        api_key = data.get('api_key', '')
        try:
            from cms.models.settings import Settings
            api_key_mode = Settings.get('API_KEY_MODE', 'global')
            if api_key_mode == 'global':
                api_key = Settings.get('GLOBAL_API_KEY', api_key) or api_key
            elif api_key_mode == 'per_user' and current_user.is_authenticated:
                api_key = current_user.personal_api_key or api_key
        except Exception:
            pass

        settings = {
            'api_key': api_key,
            'model': data.get('model', ''),
            'lang': data.get('lang', 'en'),
        }

        store.create(sid, task_id, session_uuid, settings)
        task_tracker.start_task(sid, task_id, session_uuid)

        # --- Create TaskSubmission in DB ---
        try:
            from cms.extensions import db
            from cms.models.task import TaskSubmission, Task
            task_obj = Task.query.get(task_id)
            if task_obj:
                user_id = current_user.id if current_user.is_authenticated else None
                sub = TaskSubmission(
                    task_id=task_id,
                    user_id=user_id,
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
            print(f'[chat_handler] TaskSubmission create error: {e}')

        # --- Load mentor memory from most recent open submission ---
        try:
            from cms.models.task import TaskSubmission, Task as _Task
            user_id = current_user.id if current_user.is_authenticated else None
            if user_id:
                prev = (TaskSubmission.query
                        .filter_by(task_id=task_id, user_id=user_id)
                        .filter(TaskSubmission.completed_at.is_(None))
                        .order_by(TaskSubmission.started_at.desc())
                        .first())
                if prev and prev.mentor_memory_list:
                    store.get(sid)['mentor_state']['memory'] = prev.mentor_memory_list
        except Exception as _me:
            print(f'[chat_handler] mentor memory load error: {_me}')

        emit('task_joined', {'task_id': task_id})

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
        api_key = data.get('api_key') or settings.get('api_key', '')
        model = data.get('model') or settings.get('model', '')
        lang = data.get('lang') or settings.get('lang', 'en')

        if task_id == 'custom':
            task_description = session.get('custom_task_desc', '')
        else:
            # Try DB first, fall back to config
            try:
                from cms.models.task import Task as TaskModel
                task_obj = TaskModel.query.get(task_id)
                if task_obj:
                    task_description = task_obj.description_de if lang == 'de' and task_obj.description_de else task_obj.description or ''
                else:
                    raise LookupError
            except Exception:
                task_description = ''

        state = session['mentor_state']
        chat_history = session['chat_history']

        mentor = AIService(task_id, session_id=session['session_uuid'],
                           api_key=api_key, model=model, lang=lang,
                           tracker_key=sid)

        is_initial_greeting = message == _INITIAL_GREETING_SIGNAL

        # -- Initial greeting --
        if is_initial_greeting:
            if chat_history and chat_history[-1]['message'] == _INITIAL_GREETING_SIGNAL:
                chat_history.pop()

            try:
                result = mentor.generate_greeting(task_description)
                greeting = result.get('message', _FALLBACK_GREETING_DE if lang == 'de' else _FALLBACK_GREETING)
            except AIServiceError as e:
                print(f"[Mentor] Greeting API error ({e.error_type}): {e}")
                emit('ai_typing', {'typing': False})
                emit('error', {
                    'message': str(e),
                    'error_type': e.error_type,
                })
                return
            except Exception as e:
                print(f"[Mentor] Greeting error: {e}")
                greeting = _FALLBACK_GREETING_DE if lang == 'de' else _FALLBACK_GREETING

            chat_history.append({'sender': 'ai', 'message': greeting})
            state['memory'].append({'role': 'assistant', 'content': greeting})

            emit('ai_response', {
                'sender': 'ai',
                'message': greeting,
                'complete': False,
                'phase': 'GREETING',
                'issues': [],
            })
            emit('ai_typing', {'typing': False})
            return

        # -- Regular user message --
        chat_history.append({'sender': 'user', 'message': message})
        state['memory'].append({'role': 'user', 'content': message})

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

        try:
            response = mentor.get_mentor_response(
                task_description, instruction, state['memory'],
                current_bpmn, user_message=message,
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

            # Track phase counts
            phase_counts = state.setdefault('phase_counts', {})
            phase_counts[resp_phase] = phase_counts.get(resp_phase, 0) + 1

            # Persist mentor memory + phase counts to DB
            try:
                from cms.extensions import db as _db
                from cms.models.task import TaskSubmission as _Sub
                _sub_id = session.get('submission_id')
                if _sub_id:
                    _sub = _Sub.query.get(_sub_id)
                    if _sub:
                        import json as _j
                        _sub.mentor_memory = _j.dumps(state['memory'])
                        _sub.phase_counts = _j.dumps(phase_counts)
                        _db.session.commit()
            except Exception as _pe:
                print(f'[chat_handler] memory persist error: {_pe}')

            emit('ai_response', {
                'sender': 'ai',
                'message': resp_message,
                'complete': is_complete,
                'phase': resp_phase,
                'issues': [],
            })

            if issues:
                emit('mentor_issues', {'issues': issues})

            emit('ai_typing', {'typing': False})

        except AIServiceError as e:
            print(f"[Mentor] API error ({e.error_type}): {e}")
            emit('ai_typing', {'typing': False})
            emit('error', {
                'message': str(e),
                'error_type': e.error_type,
            })
        except Exception as e:
            print(f"[Mentor] send_message error: {e}")
            traceback.print_exc()
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
        api_key = data.get('api_key') or settings.get('api_key', '')
        model = data.get('model') or settings.get('model', '')
        lang = data.get('lang') or settings.get('lang', 'en')

        if task_id == 'custom':
            task_description = session.get('custom_task_desc', '')
        else:
            try:
                from cms.models.task import Task as TaskModel
                task_obj = TaskModel.query.get(task_id)
                if task_obj:
                    task_description = task_obj.description_de if lang == 'de' and task_obj.description_de else task_obj.description or ''
                else:
                    task_description = ''
            except Exception:
                task_description = ''

        state = session['mentor_state']

        mentor = AIService(task_id, session_id=session['session_uuid'],
                           api_key=api_key, model=model, lang=lang,
                           tracker_key=sid)

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
            print(f"[Mentor] Analysis API error ({e.error_type}): {e}")
            emit('error', {
                'message': str(e),
                'error_type': e.error_type,
            })
        except Exception as e:
            print(f"[Mentor] Analysis error: {e}")
            traceback.print_exc()
            emit('error', {'message': 'An unexpected error occurred during analysis.'})
        finally:
            emit('ai_typing', {'typing': False})

    @socketio.on('request_completion')
    def handle_request_completion(data):
        task_id = data.get('task_id')

        is_valid = isinstance(task_id, str) and task_id
        if not is_valid:
            return

        session = store.get(request.sid)
        if not session:
            return

        last_issues = session['mentor_state'].get('last_issues', [])
        blocking = [i for i in last_issues if i.get('severity') == 'syntax']

        if not blocking:
            emit('completion_review_result', {
                'task_id': task_id,
                'has_issues': False,
                'issues': last_issues,
                'message': 'Your model is ready for submission.'
            })
        else:
            blocking_summary = '; '.join(i.get('shortDesc', '') for i in blocking[:3])
            emit('completion_review_result', {
                'task_id': task_id,
                'has_issues': True,
                'issues': last_issues,
                'message': f'There are {len(blocking)} syntax issue(s): {blocking_summary}. You can still submit, but consider fixing them first.'
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
                print(f"[Mentor] Issue dismissed: {removed.get('shortDesc', '?')}")


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
        from cms.extensions import db
        from cms.models.task import TaskSubmission
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
            from app import task_tracker as tt
            stats = tt.get_task_stats(sid) or {}
            sub.tokens_in = stats.get('tokens_in', 0)
            sub.tokens_out = stats.get('tokens_out', 0)
        except Exception:
            pass
        db.session.commit()
        return sub_id
    except Exception as e:
        print(f'[chat_handler] TaskSubmission persist error: {e}')
        return None
