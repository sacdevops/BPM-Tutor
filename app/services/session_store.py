"""Thread-safe session store for concurrent users.

All state is keyed by SocketIO session ID (request.sid), so
concurrent users on the same task get fully isolated state.
"""

import threading
from datetime import datetime
from typing import Any, Dict, List, Optional


class SessionStore:
    def __init__(self):
        self._lock = threading.Lock()
        self._sessions: Dict[str, Dict[str, Any]] = {}

    def create(self, sid: str, task_id: str, session_uuid: str, settings: dict,
               agent_id: str = '') -> dict:
        with self._lock:
            self._sessions[sid] = {
                'task_id': task_id,
                'session_uuid': session_uuid,
                'settings': dict(settings),
                'chat_history': [],
                'mentor_state': {'memory': [], 'last_issues': []},
                'stopped': False,
                'custom_task_desc': '',
                'last_activity': datetime.now(),
                'agent_id': agent_id,
            }
            return self._sessions[sid]

    def get(self, sid: str) -> Optional[dict]:
        with self._lock:
            s = self._sessions.get(sid)
            if s:
                s['last_activity'] = datetime.now()
            return s

    def remove(self, sid: str) -> Optional[dict]:
        with self._lock:
            return self._sessions.pop(sid, None)

    def exists(self, sid: str) -> bool:
        with self._lock:
            return sid in self._sessions

    def all_sids(self) -> List[str]:
        with self._lock:
            return list(self._sessions.keys())

    def stale_sids(self, max_age_seconds: int) -> List[str]:
        with self._lock:
            now = datetime.now()
            return [
                sid for sid, s in self._sessions.items()
                if (now - s['last_activity']).total_seconds() > max_age_seconds
            ]

    def find_by_task(self, task_id: str) -> List[str]:
        with self._lock:
            return [
                sid for sid, s in self._sessions.items()
                if s.get('task_id') == task_id
            ]


store = SessionStore()
