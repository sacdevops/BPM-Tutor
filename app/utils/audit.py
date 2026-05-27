"""Audit logging helper — record admin/user actions to AuditLog."""
from __future__ import annotations

import json


def log_action(
    action: str,
    entity_type: str | None = None,
    entity_id: str | None = None,
    details: dict | None = None,
    user_id: int | None = None,
) -> None:
    """Write one AuditLog row.  Silently swallows DB errors so it never
    interrupts the main request flow.
    """
    try:
        from flask import request as flask_request
        from flask_login import current_user
        from app.extensions import db
        from app.models.audit import AuditLog

        actor_id = user_id
        if actor_id is None:
            try:
                actor_id = current_user.id if current_user.is_authenticated else None
            except Exception:
                actor_id = None

        ip = None
        try:
            ip = flask_request.remote_addr
        except Exception:
            pass

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
    except Exception as exc:  # noqa: BLE001
        try:
            from flask import current_app
            current_app.logger.warning('[AuditLog] Failed to write entry: %s', exc)
        except Exception:
            pass
