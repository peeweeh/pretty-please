"""SessionAgentStore — keeps a rolling conversation history per session_id.

The demo uses raw Bedrock Converse (not an Agent object), so what we cache
IS the message history. The orchestrator:
  - fetches prior messages on turn 2+
  - prepends them to the current user_message
  - stores the updated transcript on the way out

Thread-safety: CPython GIL makes the dict ops here atomic enough for demo
scale (single-container, one worker). Production at scale would swap this
for Redis or a shared cache.
"""

import threading
import time
from typing import Optional


class SessionAgentStore:
    """In-memory per-session message cache with wall-clock TTL."""

    def __init__(self, ttl_seconds: int = 1800):
        self._messages: dict[str, list[dict]] = {}
        self._touched: dict[str, float] = {}
        self._turns: dict[str, int] = {}
        self._lock = threading.Lock()
        self.ttl_seconds = ttl_seconds

    def _expired(self, session_id: str) -> bool:
        ts = self._touched.get(session_id)
        return ts is None or (time.time() - ts) > self.ttl_seconds

    def get(self, session_id: str) -> Optional[list[dict]]:
        """Return cached messages or None if cold/expired."""
        with self._lock:
            if session_id in self._messages and not self._expired(session_id):
                return list(self._messages[session_id])  # defensive copy
            if session_id in self._messages:  # expired
                self._evict(session_id)
            return None

    def put(self, session_id: str, messages: list[dict]) -> None:
        """Overwrite the session transcript with the latest messages."""
        with self._lock:
            self._messages[session_id] = list(messages)
            self._touched[session_id] = time.time()
            self._turns[session_id] = self._turns.get(session_id, 0) + 1

    def evict(self, session_id: str) -> None:
        with self._lock:
            self._evict(session_id)

    def _evict(self, session_id: str) -> None:
        self._messages.pop(session_id, None)
        self._touched.pop(session_id, None)
        self._turns.pop(session_id, None)

    def info(self, session_id: str) -> dict:
        """Inspector payload — turn count, age in seconds, hit vs cold."""
        with self._lock:
            msgs = self._messages.get(session_id)
            ts = self._touched.get(session_id)
            turns = self._turns.get(session_id, 0)
        if msgs is None or ts is None:
            return {"state": "cold", "turns": 0, "age_sec": 0}
        return {
            "state": "warm",
            "turns": turns,
            "age_sec": round(time.time() - ts, 1),
            "message_count": len(msgs),
        }

    def sweep(self) -> int:
        """Drop all expired sessions. Returns count evicted."""
        dropped = 0
        with self._lock:
            now = time.time()
            expired = [
                sid for sid, ts in list(self._touched.items())
                if (now - ts) > self.ttl_seconds
            ]
            for sid in expired:
                self._evict(sid)
                dropped += 1
        return dropped


# Singleton used by orchestrator
_STORE = SessionAgentStore()


def store() -> SessionAgentStore:
    return _STORE
