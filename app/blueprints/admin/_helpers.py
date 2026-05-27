"""Shared helper utilities for admin sub-modules."""
import json
import os
import uuid
from datetime import datetime

from flask import current_app, request
from werkzeug.utils import secure_filename

ALLOWED_IMAGE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp', 'svg'}


def _allowed_image(filename: str) -> bool:
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_IMAGE_EXTENSIONS


def _save_upload(file, subfolder: str = 'uploads') -> str | None:
    """Save an uploaded file; return path relative to the data-uploads mount."""
    if not file or not file.filename:
        return None
    if not _allowed_image(file.filename):
        return None
    filename = secure_filename(f'{uuid.uuid4().hex}_{file.filename}')
    upload_dir = os.path.join(current_app.root_path, '..', 'data', subfolder)
    os.makedirs(upload_dir, exist_ok=True)
    file.save(os.path.join(upload_dir, filename))
    return f'/data-uploads/{subfolder}/{filename}'


def _save_extra_translations(task, form) -> None:
    """Persist extra language fields (title_XX, description_XX) into task.extra_translations."""
    from app.models.i18n import Language
    extra = task.extra_translations_dict
    for lang in Language.query.filter(Language.is_active == True, Language.code.notin_(['en', 'de'])).all():
        t_val = form.get(f'title_{lang.code}', '').strip()
        d_val = form.get(f'description_{lang.code}', '').strip()
        if t_val or d_val:
            extra[lang.code] = {k: v for k, v in {'title': t_val, 'description': d_val}.items() if v}
        else:
            extra.pop(lang.code, None)
    task.extra_translations_dict = extra


def _get_admin_api_key() -> tuple[str, str, str]:
    """Return (api_key, model, base_url) from Settings + current user fallback."""
    from app.models.settings import Settings
    from app.utils.crypto import decrypt_api_key
    from flask_login import current_user

    api_key = ''
    if Settings.get('API_KEY_MODE', 'global') == 'global':
        raw = Settings.get('GLOBAL_API_KEY', '') or ''
        if raw:
            api_key = decrypt_api_key(raw)
    if not api_key and current_user.is_authenticated:
        personal = getattr(current_user, 'personal_api_key', None)
        if personal:
            api_key = decrypt_api_key(personal)
    model = getattr(current_user, 'preferred_model', None) or Settings.get('DEFAULT_MODEL', '')
    base_url = (Settings.get(Settings.API_ENDPOINT) or '').strip()
    return api_key, model, base_url


def _apply_task_form(task, form) -> dict:
    """Apply common task form fields to a Task object; return validation errors."""
    errors: dict = {}

    task.title = form.get('title', '').strip()
    task.title_de = form.get('title_de', '').strip() or None
    task.description = form.get('description', '').strip()
    task.description_de = form.get('description_de', '').strip() or None
    task.bpmn_xml = form.get('bpmn_xml', '').strip() or None
    task.grading_type = form.get('grading_type', 'none')
    task.sort_order = form.get('sort_order', 0, type=int)
    task.is_active = bool(form.get('is_active'))
    task.hide_after_completion = bool(form.get('hide_after_completion'))
    task.agent_id = form.get('agent_id', '').strip() or None

    mp = form.get('max_points', '').strip()
    task.max_points = float(mp) if mp else None

    tl = form.get('time_limit_minutes', '').strip()
    task.time_limit_minutes = int(tl) if tl and tl.isdigit() else None

    for attr in ('available_from', 'available_until'):
        val = form.get(attr, '').strip()
        try:
            setattr(task, attr, datetime.fromisoformat(val) if val else None)
        except ValueError:
            errors[attr] = 'Ungültiges Datum.'

    prereq_raw = form.get('prerequisites_json', '[]').strip()
    try:
        task.prerequisites = json.dumps(json.loads(prereq_raw)) if prereq_raw else None
    except (ValueError, TypeError):
        task.prerequisites = None

    if not task.title:
        errors['title'] = 'Titel erforderlich.'
    if not task.description:
        errors['description'] = 'Beschreibung erforderlich.'
    return errors
