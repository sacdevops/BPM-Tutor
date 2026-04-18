""" BPM-Tutor — BPMN Modeling Learning Environment """
import io
import signal
import sys

from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO
import requests as http_requests
import config

app = Flask(__name__,
            template_folder='app/templates',
            static_folder='app/static')
app.config['SECRET_KEY'] = config.SECRET_KEY

socketio = SocketIO(
    app, 
    cors_allowed_origins="*",
    ping_timeout=300,
    ping_interval=25,
    async_mode='eventlet'
)

from app.sockets import chat_handler
from app.session_store import store
from app import task_tracker
chat_handler.register_handlers(socketio)

# -- Session cleanup background thread --
SESSION_TIMEOUT_SECONDS = 30 * 60  # 30 minutes
CLEANUP_INTERVAL_SECONDS = 5 * 60  # check every 5 minutes


def _session_cleanup_loop():
    """Periodically remove stale sessions."""
    import eventlet
    while True:
        eventlet.sleep(CLEANUP_INTERVAL_SECONDS)
        try:
            stale = store.stale_sids(SESSION_TIMEOUT_SECONDS)
            for sid in stale:
                session = store.remove(sid)
                if session:
                    task_tracker.cleanup_task(sid)
                    print(f'[Cleanup] Removed stale session {sid} '
                          f'(task {session["task_id"]})')
        except Exception as e:
            print(f'[Cleanup] Error: {e}')


socketio.start_background_task(_session_cleanup_loop)

@app.route('/')
def index():
    return render_template('index.html', tasks=config.TASKS)

@app.route('/task/<task_id>')
def task_page(task_id):
    task = config.TASKS_BY_ID.get(task_id)
    if not task:
        return "Task not found", 404
    return render_template('task.html', task=task, is_custom=False)

@app.route('/task/custom')
def custom_task_page():
    task = {'id': 'custom', 'title': 'Custom Task', 'description': ''}
    return render_template('task.html', task=task, is_custom=True)


@app.route('/api/extract-file-content', methods=['POST'])
def extract_file_content():
    if 'file' not in request.files:
        return jsonify({'success': False, 'message': 'No file provided'}), 400

    file = request.files['file']
    filename = file.filename or ''
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''

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
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/save-bpmn', methods=['POST'])
def save_bpmn():
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'message': 'No data provided'}), 400

    task_id = data.get('task_id', '')
    bpmn_xml = data.get('bpmn_xml', '')
    sid = data.get('sid', '')

    if not bpmn_xml:
        return jsonify({'success': False, 'message': 'No BPMN XML provided'}), 400

    chat_handler.complete_and_upload(task_id, bpmn_xml, sid=sid)
    return jsonify({'success': True})


@app.route('/api/models', methods=['POST'])
def get_models():
    """Proxy request to CampusKI to list available models."""
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'message': 'No data provided'}), 400

    api_key = data.get('api_key', '')
    if not api_key:
        return jsonify({'success': False, 'message': 'API key required'}), 400

    try:
        resp = http_requests.get(
            f"{config.CAMPUS_KI_BASE_URL}/v1/models",
            headers={'Authorization': f'Bearer {api_key}'},
            timeout=15,
        )
        resp.raise_for_status()
        models_data = resp.json()
        models = []
        for m in models_data.get('data', []):
            models.append({
                'id': m.get('id', ''),
                'name': m.get('id', ''),
            })
        models.sort(key=lambda x: x['id'])
        return jsonify({'success': True, 'models': models})
    except http_requests.exceptions.HTTPError as e:
        status = e.response.status_code if e.response is not None else 500
        if status in (401, 403):
            return jsonify({'success': False, 'message': 'Invalid API key'}), 401
        return jsonify({'success': False, 'message': f'API error: {status}'}), 502
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


def _graceful_shutdown(signum, frame):
    """Graceful shutdown handler."""
    print(f'\n[Backend] Received signal {signum}, shutting down...')
    print('[Backend] Shutdown complete.')
    sys.exit(0)


signal.signal(signal.SIGINT, _graceful_shutdown)
signal.signal(signal.SIGTERM, _graceful_shutdown)

if __name__ == '__main__':
    socketio.run(
        app,
        debug=config.FLASK_DEBUG,
        host='0.0.0.0',
        port=8080
    )
