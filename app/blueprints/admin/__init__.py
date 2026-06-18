"""Admin blueprint package."""
from flask import Blueprint, request, current_app

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')


@admin_bp.before_request
def _relax_limit_for_db_import() -> None:
    """Raise MAX_CONTENT_LENGTH to 512 MB for the DB-import endpoint only.

    The check is lazy (enforced when the request body is read), so setting
    the config key here — before the view accesses request.files — is enough.
    """
    if request.endpoint == 'admin.db_import':
        current_app.config['MAX_CONTENT_LENGTH'] = 512 * 1024 * 1024


# Register all sub-modules (must come after admin_bp is defined)
from . import routes, users, tasks, grading, surveys, admin_settings, cohorts, analytics, content, agents, studies, research  # noqa: E402,F401

__all__ = ['admin_bp']
