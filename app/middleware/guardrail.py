"""
Guardrail — Bedrock Guardrails config applied to every converse() call.

In prod this calls Bedrock with a real guardrailIdentifier. In the demo
we return the config dict so the orchestrator can merge it in — and the
inspector panel can show the rail is active without needing a real ID.
"""

import os
from typing import Optional


def apply_config() -> Optional[dict]:
    """Return the guardrail config to merge into a converse() call, or None."""
    gid = os.environ.get("BEDROCK_GUARDRAIL_ID")
    if not gid:
        return None
    return {
        "guardrailIdentifier": gid,
        "guardrailVersion": os.environ.get("BEDROCK_GUARDRAIL_VERSION", "DRAFT"),
        "trace": "enabled",
    }


def is_configured() -> bool:
    return bool(os.environ.get("BEDROCK_GUARDRAIL_ID"))
