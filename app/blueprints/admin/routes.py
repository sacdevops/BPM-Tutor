"""Admin blueprint — dashboard route and shared upload/translation helpers."""
from flask import render_template

from app.blueprints.admin import admin_bp
from app.models.task import TaskSubmission
from app.utils.decorators import tutor_or_admin_required
from app.utils.stats import global_stats
from app.blueprints.admin._helpers import (  # re-export for sub-modules that import from here
    ALLOWED_IMAGE_EXTENSIONS, _allowed_image, _save_upload, _save_extra_translations,
)

__all__ = [
    'ALLOWED_IMAGE_EXTENSIONS', '_allowed_image', '_save_upload', '_save_extra_translations',
]


@admin_bp.route('/')
@tutor_or_admin_required
def dashboard():
    stats = global_stats()
    recent_subs = TaskSubmission.query.order_by(
        TaskSubmission.started_at.desc()).limit(10).all()
    return render_template('cms/admin/dashboard.html',
                           stats=stats, recent_subs=recent_subs)
