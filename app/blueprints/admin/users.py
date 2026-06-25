"""Admin — user management routes."""
from flask import render_template, redirect, url_for, flash, request, jsonify
from flask_login import current_user

from app.blueprints.admin import admin_bp
from app.extensions import db
from app.models.user import User
from app.models.task import Task
from app.models.settings import Notification, Settings
from app.utils.decorators import admin_required
from app.utils.audit import log_action
from app.utils.enums import UserRole
from app.utils.stats import user_stats, since_from_period, chart_data_timeline


# Users

@admin_bp.route('/users')
@admin_required
def users_list():
    q = request.args.get('q', '').strip()
    role_filter = request.args.get('role', '')
    page = request.args.get('page', 1, type=int)

    query = User.query
    if q:
        like = f'%{q}%'
        query = query.filter(
            db.or_(User.email.ilike(like), User.username.ilike(like),
                   User.first_name.ilike(like), User.last_name.ilike(like))
        )
    if role_filter:
        query = query.filter(User.role == role_filter)

    pagination = query.order_by(User.created_at.desc()).paginate(
        page=page, per_page=25, error_out=False)
    return render_template('cms/admin/users_list.html',
                           pagination=pagination, q=q, role_filter=role_filter)


@admin_bp.route('/users/create', methods=['GET', 'POST'])
@admin_required
def user_create():
    errors: dict = {}
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        role = request.form.get('role', 'student')
        first_name = request.form.get('first_name', '').strip()
        last_name = request.form.get('last_name', '').strip()
        verified = bool(request.form.get('is_verified'))

        if not email:
            errors['email'] = 'E-Mail erforderlich.'
        elif User.query.filter_by(email=email).first():
            errors['email'] = 'E-Mail bereits registriert.'
        if not username or len(username) < 3:
            errors['username'] = 'Benutzername (min. 3 Zeichen) erforderlich.'
        elif User.query.filter_by(username=username).first():
            errors['username'] = 'Benutzername bereits vergeben.'
        if not password or len(password) < 8:
            errors['password'] = 'Passwort (min. 8 Zeichen) erforderlich.'
        if role not in [r.value for r in UserRole]:
            errors['role'] = 'Ungültige Rolle.'

        if not errors:
            user = User(
                email=email, username=username, role=role,
                first_name=first_name or None, last_name=last_name or None,
                is_active=True, is_verified=verified, data_consent=True,
            )
            user.set_password(password)
            db.session.add(user)
            db.session.commit()

            if not verified and Settings.get(Settings.MAIL_ENABLED):
                from app.utils.tokens import generate_email_token
                from app.utils.email import send_verification_email
                token = generate_email_token(email)
                send_verification_email(user, token)
                flash(f'Benutzer {username} erstellt. Bestätigungs-E-Mail wurde gesendet.', 'success')
            else:
                flash(f'Benutzer {username} erstellt.', 'success')
            return redirect(url_for('admin.user_detail', user_id=user.id))

    return render_template('cms/admin/user_create.html', errors=errors)


@admin_bp.route('/users/<int:user_id>')
@admin_required
def user_detail(user_id: int):
    user = User.query.get_or_404(user_id)
    period = request.args.get('period', '30d')
    since = since_from_period(period)
    stats = user_stats(user.id, since)
    chart = chart_data_timeline(user.id, since, period)
    tasks = Task.query.order_by(Task.sort_order).all()
    return render_template('cms/admin/user_detail.html',
                           target_user=user, stats=stats, chart=chart,
                           period=period, tasks=tasks)


@admin_bp.route('/users/<int:user_id>/edit', methods=['POST'])
@admin_required
def user_edit(user_id: int):
    user = User.query.get_or_404(user_id)
    field = request.form.get('field')
    value = request.form.get('value')

    allowed_fields = {
        'role': [r.value for r in UserRole],
        'is_active': ('true', 'false'),
        'is_verified': ('true', 'false'),
        'is_locked': ('true', 'false'),
    }

    if field not in allowed_fields:
        return jsonify({'ok': False, 'error': 'Unknown field'}), 400
    if isinstance(allowed_fields[field], tuple) and value not in allowed_fields[field]:
        return jsonify({'ok': False, 'error': 'Invalid value'}), 400

    if field == 'role':
        if user.role == 'admin' and value != 'admin':
            if User.query.filter_by(role='admin').count() <= 1:
                return jsonify({'ok': False, 'error': 'Letzten Admin nicht degradieren'}), 400
        user.role = value
    elif field in ('is_active', 'is_verified', 'is_locked'):
        setattr(user, field, value == 'true')

    db.session.commit()
    return jsonify({'ok': True})


@admin_bp.route('/users/<int:user_id>/reset-password', methods=['POST'])
@admin_required
def user_reset_password(user_id: int):
    user = User.query.get_or_404(user_id)
    new_pw = request.form.get('new_password', '').strip()
    if len(new_pw) < 8:
        flash('Passwort muss mindestens 8 Zeichen haben.', 'danger')
        return redirect(url_for('admin.user_detail', user_id=user_id))
    user.set_password(new_pw)
    db.session.commit()
    flash('Passwort wurde zurückgesetzt.', 'success')
    return redirect(url_for('admin.user_detail', user_id=user_id))


@admin_bp.route('/users/<int:user_id>/delete', methods=['POST'])
@admin_required
def user_delete(user_id: int):
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        flash('Du kannst deinen eigenen Account nicht löschen.', 'danger')
        return redirect(url_for('admin.users_list'))
    if user.role == 'admin' and User.query.filter_by(role='admin').count() <= 1:
        flash('Letzten Admin nicht löschen.', 'danger')
        return redirect(url_for('admin.users_list'))
    db.session.delete(user)
    db.session.commit()
    flash(f'Benutzer {user.username} gelöscht.', 'success')
    return redirect(url_for('admin.users_list'))


@admin_bp.route('/users/<int:user_id>/notify', methods=['POST'])
@admin_required
def user_notify(user_id: int):
    user = User.query.get_or_404(user_id)
    title = request.form.get('title', '').strip()
    message = request.form.get('message', '').strip()
    if not title:
        flash('Titel erforderlich.', 'danger')
        return redirect(url_for('admin.user_detail', user_id=user_id))
    notif = Notification(user_id=user_id, title=title, message=message, notif_type='message')
    db.session.add(notif)
    db.session.commit()
    flash('Benachrichtigung gesendet.', 'success')
    return redirect(url_for('admin.user_detail', user_id=user_id))


# Bulk user actions

@admin_bp.route('/users/bulk', methods=['POST'])
@admin_required
def users_bulk():
    user_ids = [int(i) for i in request.form.getlist('user_ids') if i.isdigit()]
    action = request.form.get('bulk_action', '')
    if not user_ids:
        flash('Keine Nutzer ausgewählt.', 'warning')
        return redirect(url_for('admin.users_list'))
    users = User.query.filter(User.id.in_(user_ids)).all()
    if action == 'activate':
        for u in users:
            u.is_active = True
        db.session.commit()
        log_action('bulk_activate_users', 'User', None, {'ids': user_ids})
        flash(f'{len(users)} Nutzer aktiviert.', 'success')
    elif action == 'deactivate':
        if any(u.id == current_user.id or u.role == 'admin' for u in users):
            flash('Eigener Account oder Admin kann nicht deaktiviert werden.', 'danger')
            return redirect(url_for('admin.users_list'))
        for u in users:
            u.is_active = False
        db.session.commit()
        log_action('bulk_deactivate_users', 'User', None, {'ids': user_ids})
        flash(f'{len(users)} Nutzer deaktiviert.', 'success')
    elif action == 'delete':
        if any(u.id == current_user.id or u.role == 'admin' for u in users):
            flash('Eigener Account oder Admin kann nicht gelöscht werden.', 'danger')
            return redirect(url_for('admin.users_list'))
        for u in users:
            db.session.delete(u)
        db.session.commit()
        log_action('bulk_delete_users', 'User', None, {'ids': user_ids})
        flash(f'{len(users)} Nutzer gelöscht.', 'success')
    else:
        flash('Unbekannte Aktion.', 'warning')
    return redirect(url_for('admin.users_list'))
