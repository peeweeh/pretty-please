"""
Audit log writer and SSE stream helper.
Every tool call in both modes goes through write_audit().
"""
import asyncio
import json
import sqlite3
import time
from datetime import datetime, timezone

from .db import conn


def write_audit(
    session_id: str,
    caller_id: int,
    tool: str,
    args: dict,
    allowed: bool,
    reason: str,
    duration_ms: float = 0.0,
) -> None:
    """Write one row to audit_log. Fire-and-forget."""
    ts = datetime.now(timezone.utc).isoformat()
    args_json = json.dumps(args)
    try:
        with conn() as c:
            c.execute(
                """
                INSERT INTO audit_log
                    (session_id, caller_id, tool, args_json, allowed, reason, duration_ms, ts)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (session_id, caller_id, tool, args_json, int(allowed), reason, duration_ms, ts),
            )
            c.commit()
    except sqlite3.Error:
        pass  # never crash demo over an audit failure


# In-memory queues per session_id for SSE delivery
_queues: dict[str, list[asyncio.Queue]] = {}


def register_audit_queue(session_id: str) -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue()
    _queues.setdefault(session_id, []).append(q)
    return q


def unregister_audit_queue(session_id: str, q: asyncio.Queue) -> None:
    if session_id in _queues:
        _queues[session_id].discard(q) if hasattr(_queues[session_id], "discard") else None
        try:
            _queues[session_id].remove(q)
        except ValueError:
            pass


def broadcast_audit(session_id: str, entry: dict) -> None:
    """Push audit entry to all SSE listeners for this session."""
    for q in list(_queues.get(session_id, [])):
        try:
            q.put_nowait(entry)
        except asyncio.QueueFull:
            pass


def write_and_broadcast(
    session_id: str,
    caller_id: int,
    tool: str,
    args: dict,
    allowed: bool,
    reason: str,
    duration_ms: float = 0.0,
    thinking: str = "",
) -> None:
    write_audit(session_id, caller_id, tool, args, allowed, reason, duration_ms)
    entry = {
        "session_id": session_id,
        "caller_id": caller_id,
        "tool": tool,
        "args": args,
        "allowed": allowed,
        "reason": reason,
        "duration_ms": round(duration_ms, 1),
        "ts": datetime.now(timezone.utc).isoformat(),
        "thinking": thinking,
    }
    broadcast_audit(session_id, entry)
