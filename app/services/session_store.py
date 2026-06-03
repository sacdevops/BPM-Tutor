"""Thread-safe session store for concurrent users.

All state is keyed by SocketIO session ID (request.sid), so
concurrent users on the same task get fully isolated state.

Backend selection
-----------------
When the ``REDIS_URL`` environment variable is set, sessions are stored in
Redis (one Hash per SID) so they survive across multiple Gunicorn workers.
When Redis is unavailable or the variable is absent the store falls back to
an in-process dict, which is safe for single-worker deployments.
"""

import json
import logging
import os
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger('bpmtutor.session_store')

# ── serialisation helpers (datetime ↔ ISO string) ───────────────────────────

def _default(obj: Any) -> Any:
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f'Not serialisable: {type(obj)}')


def _revive(dct: dict) -> dict:
    """Convert ISO-string timestamps back to datetime on JSON load."""
    for key in ('last_activity',):
        if key in dct and isinstance(dct[key], str):
            try:
                dct[key] = datetime.fromisoformat(dct[key])
            except ValueError:
                pass
    return dct


# ── TTL for leaked sessions (4 hours) ───────────────────────────────────────
_STALE_SECONDS = 4 * 3600
_REDIS_TTL = _STALE_SECONDS + 3600  # give Redis 1 extra hour margin


# ── Redis-backed store ───────────────────────────────────────────────────────

class _RedisSessionStore:
    """Session store backed by Redis hashes.  One key per SID."""

    _NAMESPACE = 'bpmtutor:session:'

    def __init__(self, redis_client: Any) -> None:
        self._r = redis_client

    def _key(self, sid: str) -> str:
        return self._NAMESPACE + sid

    def create(self, sid: str, task_id: str, session_uuid: str, settings: dict,
               agent_id: str = '') -> dict:
        data: dict = {
            'task_id': task_id,
            'session_uuid': session_uuid,
            'settings': settings,
            'chat_history': [],
            'mentor_state': {'memory': [], 'last_issues': []},
            'stopped': False,
            'custom_task_desc': '',
            'last_activity': datetime.now(timezone.utc),
            'agent_id': agent_id,
        }
        payload = json.dumps(data, default=_default, ensure_ascii=False)
        self._r.setex(self._key(sid), _REDIS_TTL, payload)
        return data

    def get(self, sid: str) -> Optional[dict]:
        raw = self._r.get(self._key(sid))
        if raw is None:
            return None
        try:
            data = json.loads(raw, object_hook=_revive)
        except (ValueError, TypeError):
            return None
        # Refresh TTL and last_activity
        data['last_activity'] = datetime.now(timezone.utc)
        payload = json.dumps(data, default=_default, ensure_ascii=False)
        self._r.setex(self._key(sid), _REDIS_TTL, payload)
        return data

    def remove(self, sid: str) -> Optional[dict]:
        key = self._key(sid)
        raw = self._r.get(key)
        self._r.delete(key)
        if raw is None:
            return None
        try:
            return json.loads(raw, object_hook=_revive)
        except (ValueError, TypeError):
            return None

    def exists(self, sid: str) -> bool:
        return bool(self._r.exists(self._key(sid)))

    def all_sids(self) -> List[str]:
        prefix = self._NAMESPACE
        keys = self._r.keys(prefix + '*')
        return [k.decode() if isinstance(k, bytes) else k
                for k in keys]

    def stale_sids(self, max_age_seconds: int) -> List[str]:
        """Return SIDs whose last_activity is older than *max_age_seconds*."""
        stale = []
        for raw_key in self._r.keys(self._NAMESPACE + '*'):
            raw = self._r.get(raw_key)
            if raw is None:
                continue
            try:
                data = json.loads(raw, object_hook=_revive)
            except (ValueError, TypeError):
                continue
            la = data.get('last_activity')
            if la is None:
                continue
            if not la.tzinfo:
                la = la.replace(tzinfo=timezone.utc)
            age = (datetime.now(timezone.utc) - la).total_seconds()
            if age > max_age_seconds:
                key = raw_key.decode() if isinstance(raw_key, bytes) else raw_key
                stale.append(key.removeprefix(self._NAMESPACE))
        return stale

    def find_by_task(self, task_id: str) -> List[str]:
        result = []
        for raw_key in self._r.keys(self._NAMESPACE + '*'):
            raw = self._r.get(raw_key)
            if raw is None:
                continue
            try:
                data = json.loads(raw)
            except (ValueError, TypeError):
                continue
            if data.get('task_id') == task_id:
                key = raw_key.decode() if isinstance(raw_key, bytes) else raw_key
                result.append(key.removeprefix(self._NAMESPACE))
        return result


# ── In-memory fallback ───────────────────────────────────────────────────────

class _InMemorySessionStore:
    def __init__(self) -> None:
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
                'last_activity': datetime.now(timezone.utc),
                'agent_id': agent_id,
            }
            return self._sessions[sid]

    def get(self, sid: str) -> Optional[dict]:
        with self._lock:
            s = self._sessions.get(sid)
            if s:
                s['last_activity'] = datetime.now(timezone.utc)
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
            now = datetime.now(timezone.utc)
            return [
                sid for sid, s in self._sessions.items()
                if (now - s['last_activity'].replace(tzinfo=timezone.utc)
                    if not s['last_activity'].tzinfo else now - s['last_activity']
                    ).total_seconds() > max_age_seconds
            ]

    def find_by_task(self, task_id: str) -> List[str]:
        with self._lock:
            return [sid for sid, s in self._sessions.items()
                    if s.get('task_id') == task_id]

    def evict_stale(self, max_age_seconds: int = _STALE_SECONDS) -> int:
        """Remove sessions that have been idle longer than *max_age_seconds*.

        Returns the number of evicted entries.  Called periodically to prevent
        memory leaks when disconnect handlers are not invoked (e.g. abrupt
        client drops, worker crashes).
        """
        stale = self.stale_sids(max_age_seconds)
        for sid in stale:
            with self._lock:
                self._sessions.pop(sid, None)
        if stale:
            logger.info('[session_store] Evicted %d stale in-memory sessions', len(stale))
        return len(stale)


# ── Unified public interface (SessionStore) ──────────────────────────────────

class SessionStore:
    """Facade that selects the appropriate backend at construction time."""

    def __init__(self) -> None:
        self._backend: Any = None
        redis_url = os.environ.get('REDIS_URL', '')
        if redis_url:
            try:
                import redis as _redis
                client = _redis.from_url(redis_url, socket_connect_timeout=2,
                                          socket_timeout=2, decode_responses=False)
                client.ping()
                self._backend = _RedisSessionStore(client)
                logger.info('[session_store] Using Redis backend (%s)', redis_url)
            except Exception as exc:
                logger.warning('[session_store] Redis unavailable (%s) — falling back to in-memory', exc)

        if self._backend is None:
            self._backend = _InMemorySessionStore()
            logger.debug('[session_store] Using in-memory backend')

    # Delegate all public methods to the chosen backend

    def create(self, sid: str, task_id: str, session_uuid: str, settings: dict,
               agent_id: str = '') -> dict:
        return self._backend.create(sid, task_id, session_uuid, settings, agent_id)

    def get(self, sid: str) -> Optional[dict]:
        return self._backend.get(sid)

    def remove(self, sid: str) -> Optional[dict]:
        return self._backend.remove(sid)

    def exists(self, sid: str) -> bool:
        return self._backend.exists(sid)

    def all_sids(self) -> List[str]:
        return self._backend.all_sids()

    def stale_sids(self, max_age_seconds: int = _STALE_SECONDS) -> List[str]:
        return self._backend.stale_sids(max_age_seconds)

    def find_by_task(self, task_id: str) -> List[str]:
        return self._backend.find_by_task(task_id)

    def evict_stale(self, max_age_seconds: int = _STALE_SECONDS) -> int:
        if hasattr(self._backend, 'evict_stale'):
            return self._backend.evict_stale(max_age_seconds)
        # Redis backend expires via TTL; manual eviction not needed
        return 0


store = SessionStore()

