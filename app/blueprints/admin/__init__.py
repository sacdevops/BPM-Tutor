"""Admin blueprint package."""
from flask import Blueprint

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')

from . import routes, users, tasks, grading, surveys, admin_settings, cohorts, analytics, content, agents, studies, research

__all__ = ['admin_bp']
