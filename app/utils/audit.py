"""Audit logging helper — record admin/user actions to AuditLog."""
from __future__ import annotations

import logging

_audit_logger = logging.getLogger('bpmtutor.audit')


def log_action(
    action: str,
    entity_type: str | None = None,
    entity_id: str | None = None,
    details: dict | None = None,
    user_id: int | None = None,
) -> None:
    """Write one AuditLog row.

    On DB failure the event is still recorded at ERROR level in the
    application log so that compliance-relevant actions are never lost
    silently.  The DB rollback is executed to leave the session clean.
    """
    actor_id = user_id
    ip: str | None = None
    try:
        from flask_login import current_user
        if actor_id is None:
            try:
                actor_id = current_user.id if current_user.is_authenticated else None
            except Exception:
                pass
        from flask import request as flask_request
        try:
            ip = flask_request.remote_addr
        except Exception:
            pass
    except Exception:
        pass

    try:
        from app.extensions import db
        from app.models.audit import AuditLog

        entry = AuditLog(
            user_id=actor_id,
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id) if entity_id is not None else None,
            ip_address=ip,
        )
        if details:
            entry.details = details
        db.session.add(entry)
        db.session.commit()
        _audit_logger.debug('[AuditLog] %s | entity=%s/%s | user=%s | ip=%s',
                            action, entity_type, entity_id, actor_id, ip)
    except Exception as exc:
        # Roll back so the caller's session is not poisoned
        try:
            from app.extensions import db
            db.session.rollback()
        except Exception:
            pass
        # Log at ERROR so the event is visible in log aggregators / SIEM
        _audit_logger.error(
            '[AuditLog] FAILED to persist — action=%s entity=%s/%s user=%s ip=%s err=%s',
            action, entity_type, entity_id, actor_id, ip, exc,
            exc_info=True,
        )

