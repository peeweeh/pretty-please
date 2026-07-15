"""
aiguard.py — Summit 2.0 Act 4 (SUMMIT-05): Trend Vision One AI Guard.

Content-level guardrails — a genuinely different threat class from the
L1-L9 architecture ladder in Act 2. L1-L9 answers "is this caller allowed
to touch this tool/row?" This answers "did the caller just ask something
harmful, or is the model about to leak PII in free text?" Two real HTTP
calls to a real Trend Vision One tenant. Not clean-room — correctly
attributed, same as the reference integration this is built from
(github.com/peeweeh/aiguard-strands).

Fails closed: any network error, timeout, or non-200 response blocks
rather than silently passing through — this is the reference repo's own
explicit production recommendation, not an invented default.
"""

import logging
import os

import requests

logger = logging.getLogger("uvicorn.error")

_TIMEOUT_SECONDS = 10


def _host(region: str) -> str:
    """The US region has no subdomain; every other region does."""
    region = (region or "us").lower()
    return "api.xdr.trendmicro.com" if region in ("us", "") else f"api.{region}.xdr.trendmicro.com"


def _guardrails_url() -> str:
    return f"https://{_host(os.environ.get('V1_REGION', 'us'))}/v3.0/aiSecurity/applyGuardrails"


def _headers(request_type: str) -> dict:
    api_key = os.environ.get("V1_API_KEY", "")
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "TMV1-Application-Name": os.environ.get("V1_APP_NAME", "pretty-please"),
        "TMV1-Request-Type": request_type,
        "Prefer": "return=minimal",
        "Accept": "application/json",
    }


def enabled() -> bool:
    return bool(os.environ.get("V1_API_KEY"))


def check_prompt(prompt: str) -> dict:
    """SimpleRequestGuardrails — the input guard, called before Bedrock."""
    if not enabled():
        return {"action": "Block", "reasons": ["V1_API_KEY not set — AI Guard disabled"]}
    try:
        resp = requests.post(
            _guardrails_url(),
            headers=_headers("SimpleRequestGuardrails"),
            json={"prompt": prompt},
            timeout=_TIMEOUT_SECONDS,
        )
        if resp.status_code != 200:
            logger.warning(f"[AIGUARD] input check HTTP {resp.status_code}: {resp.text[:200]}")
            return {"action": "Block", "reasons": [f"AI Guard HTTP {resp.status_code} — failing closed"]}
        return resp.json()
    except requests.RequestException as e:
        logger.warning(f"[AIGUARD] input check failed: {e}")
        return {"action": "Block", "reasons": ["AI Guard unreachable — failing closed"]}


def check_response(response_text: str, model_id: str) -> dict:
    """OpenAIChatCompletionResponseV1 — the output guard, called on the model's reply."""
    if not enabled():
        return {"action": "Block", "reasons": ["V1_API_KEY not set — AI Guard disabled"]}
    payload = {
        "id": "pretty-please-summit2",
        "object": "chat.completion",
        "model": model_id,
        "choices": [
            {
                "index": 0,
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": response_text},
            }
        ],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }
    try:
        resp = requests.post(
            _guardrails_url(),
            headers=_headers("OpenAIChatCompletionResponseV1"),
            json=payload,
            timeout=_TIMEOUT_SECONDS,
        )
        if resp.status_code != 200:
            logger.warning(f"[AIGUARD] output check HTTP {resp.status_code}: {resp.text[:200]}")
            return {"action": "Block", "reasons": [f"AI Guard HTTP {resp.status_code} — failing closed"]}
        return resp.json()
    except requests.RequestException as e:
        logger.warning(f"[AIGUARD] output check failed: {e}")
        return {"action": "Block", "reasons": ["AI Guard unreachable — failing closed"]}
