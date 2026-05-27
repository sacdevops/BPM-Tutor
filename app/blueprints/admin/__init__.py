"""Admin blueprint package."""
from flask import Blueprint

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')

# Register all sub-modules (must come after admin_bp is defined)
from . import routes, users, tasks, grading, surveys, admin_settings, cohorts, analytics, content, agents, studies  # noqa: E402,F401

__all__ = ['admin_bp']
