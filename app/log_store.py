"""
Shared in-memory log buffer — populated by main.py, readable by tools.
Avoids circular imports: main → tools_vibe → log_store ← main.
"""

from collections import deque

_recent: deque = deque(maxlen=30)


def append(msg: str) -> None:
    _recent.append(msg)


def get_all() -> list[str]:
    return list(_recent)
