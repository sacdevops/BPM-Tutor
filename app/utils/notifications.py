"""Notification helpers — create DB notifications and optionally push via Socket.IO."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger('bpmtutor.notifications')


def send_notification(
    user_id: int,
    notif_type: str,
    title: str,
    message: str = '',
    link: Optional[str] = None,
) -> None:
    """Persist a notification to the DB and push a Socket.IO event to the user.

    The Socket.IO push is best-effort: if the user has no active connection it
    is silently skipped (they will still see the notification on next page load).
    """
    try:
        from app.extensions import db
        from app.models.settings import Notification

        notif = Notification(
            user_id=user_id,
            notif_type=notif_type,
            title=title,
            message=message,
            link=link,
        )
        db.session.add(notif)
        db.session.commit()
    except Exception as exc:
        logger.warning('[notifications] DB save failed: %s', exc)
        return

    # Push real-time notification via Socket.IO (best-effort)
    try:
        from main import socketio  # lazy import avoids circular dependency at startup
        payload = {
            'id': notif.id,
            'type': notif_type,
            'title': title,
            'message': message,
            'link': link,
            'created_at': datetime.now(timezone.utc).isoformat(),
        }
        socketio.emit('notification', payload, room=f'user_{user_id}')
    except Exception as exc:
        logger.debug('[notifications] Socket.IO emit failed for user %s: %s', user_id, exc)
