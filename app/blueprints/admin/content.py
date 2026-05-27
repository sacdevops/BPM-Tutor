"""Admin — i18n / language strings and learning level management."""
import json

from flask import render_template, redirect, url_for, flash, request
from flask_login import current_user

from app.blueprints.admin import admin_bp
from app.extensions import db
from app.models.task import Task
from app.models.i18n import Language, LanguageString
from app.models.level import LearningLevel
from app.models.settings import Settings
from app.utils.decorators import admin_required
from app.utils.audit import log_action
from app.utils.i18n_helper import invalidate_cache


# ── Language / i18n admin ─────────────────────────────────────────────────────

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
        _actions = request.form.getlist('action')
        action = _actions[-1] if _actions else None
        if action == 'update_meta':
            lang.name = request.form.get('name', lang.name)
            lang.flag = request.form.get('flag', lang.flag)
            if lang_code == 'en':
                lang.is_active = True
                lang.is_default = True
            else:
                lang.is_active = bool(request.form.get('is_active'))
                if request.form.get('is_default'):
                    Language.query.filter_by(is_default=True).update({'is_default': False})
                    lang.is_default = True
            lang.sort_order = int(request.form.get('sort_order', lang.sort_order))
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
            LanguageString.query.filter_by(language_code=lang_code, key=key).delete()
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
            if lang_code == 'en':
                flash('Englisch ist die Systemstandard-Sprache und kann nicht gelöscht werden.', 'warning')
                return redirect(url_for('admin.language_strings', lang_code=lang_code))
            db.session.delete(lang)
            db.session.commit()
            invalidate_cache()
            log_action('delete_language', 'Language', None, {'code': lang_code})
            flash('Sprache gelöscht.', 'success')
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


# ── Level system admin ────────────────────────────────────────────────────────

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
            selected_ids = set(request.form.getlist('task_ids'))
            for t in level.tasks.all():
                if t.id not in selected_ids:
                    level.tasks.remove(t)
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
            remaining = LearningLevel.query.order_by(LearningLevel.level_number).all()
            for i, lv in enumerate(remaining, start=1):
                lv.level_number = i
            db.session.commit()
            log_action('delete_level', 'LearningLevel', level_id, {})
            flash('Level gelöscht und Nummerierung aktualisiert.', 'success')
            return redirect(url_for('admin.levels_list'))
        return redirect(url_for('admin.level_edit', level_id=level_id))

    levels = LearningLevel.query.order_by(LearningLevel.level_number).all()
    return render_template('cms/admin/level_edit.html',
                           level=level, tasks_all=tasks_all,
                           level_task_ids=level_task_ids,
                           levels=levels)
