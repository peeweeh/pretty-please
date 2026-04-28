"""
PromptManager — SQLite-backed prompt lookup with short TTL cache.
Port of eonar-mono/backend/ai_middleware/prompts/manager.py (trimmed).
"""

import json
import os
import time
from typing import Optional

from ..db import conn

_CACHE: dict[str, tuple[dict, float]] = {}
_TTL = int(os.environ.get("PROMPT_CACHE_TTL", "30"))


def get_prompt(product_id: str) -> Optional[dict]:
    """Fetch prompt by product_id. Cached for PROMPT_CACHE_TTL seconds."""
    now = time.time()
    cached = _CACHE.get(product_id)
    if cached and (now - cached[1]) < _TTL:
        return cached[0]

    with conn() as c:
        row = c.execute(
            "SELECT product_id, version, system_prompt, tool_ids, skill_ids "
            "FROM summit_prompts WHERE product_id = ?",
            (product_id,),
        ).fetchone()

    if not row:
        return None

    prompt = {
        "product_id": row[0],
        "version": row[1],
        "system_prompt": row[2],
        "tool_ids": json.loads(row[3]),
        "skill_ids": json.loads(row[4]),
    }
    _CACHE[product_id] = (prompt, now)
    return prompt


def update_prompt(product_id: str, system_prompt: str) -> int:
    """Update system_prompt, bump version, invalidate cache. Returns new version."""
    with conn() as c:
        row = c.execute(
            "SELECT version FROM summit_prompts WHERE product_id = ?",
            (product_id,),
        ).fetchone()
        new_version = (row[0] if row else 0) + 1
        c.execute(
            "UPDATE summit_prompts SET system_prompt = ?, version = ?, "
            "updated_at = CURRENT_TIMESTAMP WHERE product_id = ?",
            (system_prompt, new_version, product_id),
        )
        c.commit()
    _CACHE.pop(product_id, None)
    return new_version


def cache_info() -> dict:
    return {"ttl_seconds": _TTL, "entries": list(_CACHE.keys())}
