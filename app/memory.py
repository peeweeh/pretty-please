"""
Session memory.

Vibe:     global dict[session_id] → deque  (no TTL, no isolation — the bug)
Fortress: dict[(session_id, caller_id)] → deque  (scoped + TTL)
"""

import time
from collections import deque
from typing import Any

# ── Vibe memory — intentionally broken ────────────────────────────────────
# Session-only key. Two different callers on the same session share memory.
_vibe_store: dict[str, deque] = {}


def vibe_get(session_id: str) -> list:
    return list(_vibe_store.get(session_id, []))


def vibe_append(session_id: str, item: Any) -> None:
    store = _vibe_store.setdefault(session_id, deque(maxlen=50))
    store.append(item)


# ── Fortress memory — scoped by (session_id, caller_id) with TTL ──────────
_TTL_SECONDS = 900  # 15 min

_fortress_store: dict[tuple[str, int], tuple[float, deque]] = {}


def fortress_get(session_id: str, caller_id: int) -> list:
    key = (session_id, caller_id)
    if key not in _fortress_store:
        return []
    created_at, store = _fortress_store[key]
    if time.time() - created_at > _TTL_SECONDS:
        del _fortress_store[key]
        return []
    return list(store)


def fortress_append(session_id: str, caller_id: int, item: Any) -> None:
    key = (session_id, caller_id)
    if key not in _fortress_store or time.time() - _fortress_store[key][0] > _TTL_SECONDS:
        _fortress_store[key] = (time.time(), deque(maxlen=50))
    _fortress_store[key][1].append(item)


def fortress_clear_expired() -> None:
    now = time.time()
    expired = [k for k, (ts, _) in _fortress_store.items() if now - ts > _TTL_SECONDS]
    for k in expired:
        del _fortress_store[k]
