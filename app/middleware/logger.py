"""
UnifiedAICallLogger — one log record per model call.
Writes to stdout (for CloudWatch parity) and SQLite (for the demo inspector).
"""

import json
import logging
from typing import Optional

from ..db import conn

logger = logging.getLogger("summit.ai")


def log_call(
    *,
    call_id: str,
    tenant_id: str,
    user_id: str,
    session_id: str,
    product_id: str,
    prompt_id: str,
    prompt_version: int,
    model_id: str,
    input_tokens: int,
    output_tokens: int,
    cost_usd: float,
    latency_ms: int,
    tools_called: Optional[list[str]] = None,
    skill_ids: Optional[list[str]] = None,
    guardrail_triggered: bool = False,
    error: Optional[str] = None,
) -> None:
    """Write one row for every model call. Single schema, every product."""
    tools_called = tools_called or []
    skill_ids = skill_ids or []

    # 1. Structured stdout (what CloudWatch sees in prod)
    logger.info(
        "AI_CALL %s",
        json.dumps(
            {
                "call_id": call_id,
                "tenant_id": tenant_id,
                "user_id": user_id,
                "product_id": product_id,
                "prompt_id": prompt_id,
                "prompt_version": prompt_version,
                "model_id": model_id,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cost_usd": cost_usd,
                "latency_ms": latency_ms,
                "tools_called": tools_called,
                "skill_ids": skill_ids,
                "guardrail_triggered": guardrail_triggered,
                "error": error,
            }
        ),
    )

    # 2. SQLite (what the demo inspector reads)
    with conn() as c:
        c.execute(
            "INSERT INTO summit_unified_log "
            "(call_id, tenant_id, user_id, session_id, product_id, prompt_id, "
            "prompt_version, model_id, input_tokens, output_tokens, cost_usd, "
            "latency_ms, tools_called, skill_ids, guardrail_triggered, error) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                call_id, tenant_id, user_id, session_id, product_id, prompt_id,
                prompt_version, model_id, input_tokens, output_tokens, cost_usd,
                latency_ms, json.dumps(tools_called), json.dumps(skill_ids),
                1 if guardrail_triggered else 0, error,
            ),
        )
        c.commit()
