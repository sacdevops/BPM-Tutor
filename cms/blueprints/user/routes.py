"""User-facing CMS blueprint — profile, stats, notifications, own submissions."""
import re
from datetime import datetime

from flask import (Blueprint, render_template, redirect, url_for,
                   flash, request, jsonify)
from flask_login import login_required, current_user

from cms.extensions import db
from cms.models.user import User
from cms.models.task import Task, TaskSubmission
from cms.models.settings import Notification, Settings
from cms.models.level import LearningLevel
from cms.utils.stats import user_stats, since_from_period, chart_data_timeline
from cms.utils.crypto import encrypt_api_key

user_bp = Blueprint('user_bp', __name__, url_prefix='/me')

_EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')


@user_bp.route('/')
@login_required
def profile():
    return render_template('cms/user/profile.html')


@user_bp.route('/edit', methods=['POST'])
@login_required
def profile_edit():
    first_name = request.form.get('first_name', '').strip()
    last_name = request.form.get('last_name', '').strip()
    new_email = request.form.get('email', '').strip().lower()
    api_key = request.form.get('personal_api_key', '').strip()

    if new_email and not _EMAIL_RE.match(new_email):
        flash('Ungültige E-Mail-Adresse.', 'danger')
        return redirect(url_for('user_bp.profile'))

    if new_email and new_email != current_user.email:
        if User.query.filter_by(email=new_email).first():
            flash('Diese E-Mail-Adresse wird bereits verwendet.', 'danger')
            return redirect(url_for('user_bp.profile'))
        current_user.email = new_email
        # Require re-verification if setting is on
        if Settings.get(Settings.REQUIRE_EMAIL_VERIFICATION):
            current_user.is_verified = False
            flash('E-Mail geändert — bitte bestätige deine neue E-Mail-Adresse.', 'warning')

    current_user.first_name = first_name or None
    current_user.last_name = last_name or None

    if api_key:
        current_user.personal_api_key = encrypt_api_key(api_key)
    elif 'clear_api_key' in request.form:
        current_user.personal_api_key = None

    # Language preference
    new_lang = request.form.get('language', '').strip()
    if new_lang:
        from cms.models.i18n import Language
        if Language.query.get(new_lang):
            current_user.language = new_lang

    db.session.commit()
    flash('Profil gespeichert.', 'success')
    return redirect(url_for('user_bp.profile'))


@user_bp.route('/change-password', methods=['POST'])
@login_required
def change_password():
    current_pw = request.form.get('current_password', '')
    new_pw = request.form.get('new_password', '')
    new_pw2 = request.form.get('new_password2', '')

    if not current_user.check_password(current_pw):
        flash('Aktuelles Passwort falsch.', 'danger')
        return redirect(url_for('user_bp.profile'))
    if len(new_pw) < 8:
        flash('Neues Passwort muss mindestens 8 Zeichen haben.', 'danger')
        return redirect(url_for('user_bp.profile'))
    if new_pw != new_pw2:
        flash('Neue Passwörter stimmen nicht überein.', 'danger')
        return redirect(url_for('user_bp.profile'))

    current_user.set_password(new_pw)
    db.session.commit()
    flash('Passwort erfolgreich geändert.', 'success')
    return redirect(url_for('user_bp.profile'))


@user_bp.route('/stats')
@login_required
def my_stats():
    period = request.args.get('period', '30d')
    since = since_from_period(period)
    stats = user_stats(current_user.id, since)
    chart = chart_data_timeline(current_user.id, since, period)
    tasks = {t.id: t for t in Task.query.all()}
    # Level system
    level_enabled = Settings.get(Settings.LEVEL_SYSTEM_ENABLED, False)
    levels = []
    if level_enabled:
        levels = LearningLevel.query.filter_by(is_active=True).order_by(LearningLevel.level_number).all()
    return render_template('cms/user/stats.html',
                           stats=stats, chart=chart, period=period, tasks=tasks,
                           levels=levels, level_enabled=level_enabled)


@user_bp.route('/stats/api')
@login_required
def my_stats_api():
    period = request.args.get('period', '30d')
    since = since_from_period(period)
    stats = user_stats(current_user.id, since)
    chart = chart_data_timeline(current_user.id, since, period)
    return jsonify({'stats': stats, 'chart': chart})


@user_bp.route('/submissions')
@login_required
def my_submissions():
    page = request.args.get('page', 1, type=int)
    pagination = (TaskSubmission.query
                  .filter_by(user_id=current_user.id)
                  .order_by(TaskSubmission.started_at.desc())
                  .paginate(page=page, per_page=20, error_out=False))
    tasks = {t.id: t for t in Task.query.all()}
    return render_template('cms/user/submissions.html',
                           pagination=pagination, tasks=tasks)


@user_bp.route('/notifications')
@login_required
def notifications():
    page = request.args.get('page', 1, type=int)
    pagination = (Notification.query
                  .filter_by(user_id=current_user.id)
                  .order_by(Notification.created_at.desc())
                  .paginate(page=page, per_page=20, error_out=False))
    return render_template('cms/user/notifications.html', pagination=pagination)


@user_bp.route('/notifications/<int:notif_id>/read', methods=['POST'])
@login_required
def notification_read(notif_id: int):
    notif = Notification.query.filter_by(
        id=notif_id, user_id=current_user.id).first_or_404()
    notif.is_read = True
    db.session.commit()
    return jsonify({'ok': True})


@user_bp.route('/notifications/read-all', methods=['POST'])
@login_required
def notifications_read_all():
    Notification.query.filter_by(user_id=current_user.id, is_read=False).update(
        {'is_read': True})
    db.session.commit()
    return jsonify({'ok': True})


@user_bp.route('/notifications/count')
@login_required
def notification_count():
    count = Notification.query.filter_by(
        user_id=current_user.id, is_read=False).count()
    return jsonify({'count': count})
