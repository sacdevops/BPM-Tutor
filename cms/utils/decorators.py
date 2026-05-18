"""Role-based access decorators."""
from functools import wraps
from flask import abort, redirect, url_for, flash
from flask_login import current_user, login_required as _login_required


def roles_required(*roles):
    """Decorator — requires the current user to have one of the given roles."""
    def decorator(f):
        @wraps(f)
        @_login_required
        def decorated_function(*args, **kwargs):
            if not current_user.has_role(*roles):
                abort(403)
            return f(*args, **kwargs)
        return decorated_function
    return decorator


def admin_required(f):
    return roles_required('admin')(f)


def instructor_or_admin_required(f):
    return roles_required('admin', 'instructor')(f)


def active_required(f):
    """Deny access if the user account is locked."""
    @wraps(f)
    @_login_required
    def decorated_function(*args, **kwargs):
        if current_user.is_locked:
            flash('Dein Konto wurde gesperrt. Wende dich an einen Administrator.', 'danger')
            from flask_login import logout_user
            logout_user()
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated_function


def auth_guard(f):
    """Redirect to login when auth_required setting is True and user is not logged in."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        from cms.models.settings import Settings
        if Settings.get(Settings.AUTH_REQUIRED):
            return _login_required(f)(*args, **kwargs)
        return f(*args, **kwargs)
    return decorated_function
