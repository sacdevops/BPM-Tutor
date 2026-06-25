"""Authentication blueprint â€” login, register, email verify, password reset."""

from flask import (Blueprint, render_template, redirect, url_for,
                   flash, request, current_app)
from flask_login import login_user, logout_user, login_required, current_user
from urllib.parse import urlsplit

from app.extensions import db
from app.models.user import User
from app.models.settings import Settings, RegistrationField
from app.utils.tokens import (generate_email_token, verify_email_token,
                               generate_reset_token, verify_reset_token)
from app.utils.email import send_verification_email, send_password_reset_email
from app.utils.validators import is_valid_email
from app.utils.i18n_helper import _t

import re
from datetime import datetime, timezone

auth_bp = Blueprint('auth', __name__, url_prefix='/auth')


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect('/')
    error = None
    if request.method == 'POST':
        identifier = request.form.get('identifier', '').strip()
        password = request.form.get('password', '')
        remember = bool(request.form.get('remember'))
        user = (User.query.filter_by(email=identifier).first()
                or User.query.filter_by(username=identifier).first())
        if user is None or not user.check_password(password):
            error = 'Ungültige Anmeldedaten.'
        elif user.is_locked:
            error = 'Dein Konto wurde gesperrt. Wende dich an einen Administrator.'
        elif not user.is_active:
            error = 'Dieses Konto ist deaktiviert.'
        elif not user.is_verified and Settings.get(Settings.REQUIRE_EMAIL_VERIFICATION):
            error = 'Bitte bestätige zuerst deine E-Mail-Adresse.'
        else:
            login_user(user, remember=remember)
            user.last_login = datetime.now(timezone.utc)
            db.session.commit()
            if Settings.get(Settings.MAINTENANCE_MODE, False) and user.role != 'admin':
                logout_user()
                return render_template('cms/auth/login.html',
                                       error=_t('auth.error_maintenance', 'The system is currently in maintenance mode. Only admins can log in.'))
            next_page = request.args.get('next', '')

            if next_page:
                parsed = urlsplit(next_page)
                if not parsed.scheme and not parsed.netloc and not next_page.startswith('//'):
                    return redirect(next_page)
            return redirect('/')
    return render_template('cms/auth/login.html', error=error)


@auth_bp.route('/logout')
@login_required
def logout():

    logout_user()
    flash(_t('auth.logout_success', 'You have been logged out successfully.'), 'success')
    if Settings.get(Settings.AUTH_REQUIRED):
        return redirect(url_for('auth.login'))
    return redirect('/')


@auth_bp.route('/register', methods=['GET', 'POST'])
def register():

    if not Settings.get(Settings.ALLOW_REGISTRATION):
        flash(_t('auth.registration_disabled', 'Registration is currently disabled.'), 'warning')
        return redirect(url_for('auth.login'))
    if current_user.is_authenticated:
        return redirect('/')
    extra_fields = RegistrationField.query.filter_by(is_active=True).order_by(
        RegistrationField.sort_order).all()
    errors: dict = {}
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        password2 = request.form.get('password2', '')
        consent = bool(request.form.get('data_consent'))
        first_name = request.form.get('first_name', '').strip()
        last_name = request.form.get('last_name', '').strip()
        if not is_valid_email(email):
            errors['email'] = 'Ungültige E-Mail-Adresse.'
        elif User.query.filter_by(email=email).first():
            errors['email'] = 'Diese E-Mail-Adresse ist bereits registriert.'
        if len(username) < 3:
            errors['username'] = 'Benutzername muss mindestens 3 Zeichen haben.'
        elif not re.match(r'^[a-zA-Z0-9_.-]+$', username):
            errors['username'] = 'Nur Buchstaben, Ziffern, _, . und - erlaubt.'
        elif User.query.filter_by(username=username).first():
            errors['username'] = 'Dieser Benutzername ist bereits vergeben.'
        if len(password) < 8:
            errors['password'] = 'Passwort muss mindestens 8 Zeichen haben.'
        elif password != password2:
            errors['password2'] = 'Passwörter stimmen nicht überein.'
        if not consent:
            errors['data_consent'] = 'Du musst der Datenspeicherung zustimmen.'

        extra_values: dict = {}
        for field in extra_fields:
            val = request.form.get(f'extra_{field.name}', '').strip()
            if field.required and not val:
                errors[f'extra_{field.name}'] = f'{field.label} ist erforderlich.'
            extra_values[field.name] = val
        if not errors:
            requires_verify = Settings.get(Settings.REQUIRE_EMAIL_VERIFICATION)
            user = User(
                email=email,
                username=username,
                role='student',
                is_active=True,
                is_verified=not requires_verify,
                data_consent=True,
                first_name=first_name or None,
                last_name=last_name or None,
            )
            user.set_password(password)
            if extra_values:
                user.profile = extra_values
            db.session.add(user)
            db.session.commit()
            if requires_verify:
                token = generate_email_token(email)
                mail_sent = send_verification_email(user, token)
                if mail_sent:
                    flash(_t('auth.register_success_verify', 'Registration successful! Please confirm your email address.'), 'success')
                else:
                    flash(_t('auth.register_success_no_mail', 'Registration successful! (No email sending configured — an admin can manually activate your account.)'), 'warning')
                return redirect(url_for('auth.login'))
            else:
                login_user(user)
                flash(_t('auth.register_success', 'Welcome! Registration successful.'), 'success')
                return redirect('/')
    return render_template('cms/auth/register.html',
                           extra_fields=extra_fields, errors=errors,
                           privacy_policy=Settings.get(Settings.PRIVACY_POLICY, ''))


@auth_bp.route('/verify/<token>')
def verify_email(token: str):

    email = verify_email_token(token)
    if email is None:
        flash(_t('auth.verify_invalid_link', 'The confirmation link is invalid or has expired.'), 'danger')
        return redirect(url_for('auth.login'))
    user = User.query.filter_by(email=email).first()
    if user is None:
        flash(_t('auth.verify_no_account', 'No account found with this email address.'), 'danger')
        return redirect(url_for('auth.login'))
    if user.is_verified:
        flash(_t('auth.verify_already_done', 'Your email address has already been confirmed.'), 'info')
    else:
        user.is_verified = True
        db.session.commit()
        flash(_t('auth.verify_success', 'Email address confirmed successfully! You can now sign in.'), 'success')
    return redirect(url_for('auth.login'))


@auth_bp.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():

    if current_user.is_authenticated:
        return redirect('/')
    sent = False
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        user = User.query.filter_by(email=email).first()
        if user and user.is_active:
            token = generate_reset_token(user.id)
            send_password_reset_email(user, token)

        sent = True
    return render_template('cms/auth/forgot_password.html', sent=sent)


@auth_bp.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token: str):

    user_id = verify_reset_token(token)
    if user_id is None:
        flash(_t('auth.reset_invalid_link', 'The reset link is invalid or has expired.'), 'danger')
        return redirect(url_for('auth.forgot_password'))
    user = db.session.get(User, user_id)
    if user is None:
        flash(_t('auth.user_not_found', 'User not found.'), 'danger')
        return redirect(url_for('auth.login'))
    error = None
    if request.method == 'POST':
        password = request.form.get('password', '')
        password2 = request.form.get('password2', '')
        if len(password) < 8:
            error = _t('auth.error_password_too_short', 'Password must be at least 8 characters.')
        elif password != password2:
            error = _t('auth.error_passwords_mismatch', 'Passwords do not match.')
        else:
            user.set_password(password)
            db.session.commit()
            flash(_t('auth.password_reset_success', 'Password changed successfully. You can now sign in.'), 'success')
            return redirect(url_for('auth.login'))
    return render_template('cms/auth/reset_password.html', error=error, token=token)
