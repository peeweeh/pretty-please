"""
Signed caller identity for Fortress mode (L1 guardrail).
The caller_id comes from the server-side session — the LLM never sees it
as a parameter it can forge.
"""
import hashlib
import hmac
import os
import time


def _secret() -> bytes:
    key = os.environ.get("CALLER_HMAC_SECRET", "demo-only-secret-not-for-prod")
    return key.encode()


def sign_caller(caller_id: int, session_id: str) -> str:
    """Generate HMAC signature: '{caller_id}.{ts}.{sig}'."""
    ts = str(int(time.time()))
    msg = f"{caller_id}:{session_id}:{ts}".encode()
    sig = hmac.new(_secret(), msg, hashlib.sha256).hexdigest()
    return f"{caller_id}.{ts}.{sig}"


def verify_caller(token: str, session_id: str, max_age_seconds: int = 3600) -> int:
    """
    Verify the HMAC token and return the caller_id.
    Raises ValueError if invalid or expired.
    """
    try:
        caller_id_str, ts_str, sig = token.split(".")
        caller_id = int(caller_id_str)
        ts = int(ts_str)
    except (ValueError, AttributeError):
        raise ValueError("Malformed caller token")

    if abs(time.time() - ts) > max_age_seconds:
        raise ValueError("Caller token expired")

    msg = f"{caller_id}:{session_id}:{ts_str}".encode()
    expected = hmac.new(_secret(), msg, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig):
        raise ValueError("Caller token signature invalid")

    return caller_id
