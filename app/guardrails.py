"""
Guardrail helpers for Fortress mode.
These are the fixes. They're small on purpose — that's the talking point.
"""
import hashlib
import re
import time
from collections import deque
from typing import Any

from .db import conn


class AuthzError(Exception):
    """Raised when authorization check fails."""


EMAIL_ALLOWLIST = {"medimind.com", "patient-portal.medimind.com"}


def authz_own_or_caregiver(caller_id: int, target_id: int) -> None:
    """
    Allow if caller == target OR caregiver row exists.
    This one function fixes Attack 1 (IDOR / broken access control).
    """
    if caller_id == target_id:
        return
    with conn() as c:
        row = c.execute(
            "SELECT 1 FROM caregivers WHERE patient_id=? AND caregiver_patient_id=?",
            (target_id, caller_id),
        ).fetchone()
    if not row:
        raise AuthzError(
            f"Access denied: caller {caller_id} is not authorized for patient {target_id}"
        )


def authz_admin(caller_id: int) -> None:
    """Verify the caller has the admin role."""
    with conn() as c:
        row = c.execute(
            "SELECT role FROM patients WHERE id=?",
            (caller_id,),
        ).fetchone()
    if not row or row["role"] != "admin":
        raise AuthzError(f"Admin access required. Caller {caller_id} is not an admin.")


def wrap_untrusted(text: str) -> str:
    """Wrap untrusted user-generated content before giving it to the LLM."""
    return f"<untrusted_content>\n{text}\n</untrusted_content>"


def redact_pii(obj: Any) -> Any:
    """
    Recursively redact sensitive fields from log records.
    Catches the obvious ones — not a complete PHI scrubber.
    """
    SENSITIVE_KEYS = {
        "ssn_last4", "ssn", "dob", "email", "phone",
        "new_password", "password", "body",
    }
    VALUE_PATTERNS = [
        (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[REDACTED:SSN]"),
        (re.compile(r"\b\d{4}-\d{2}-\d{2}\b"), "[REDACTED:DOB]"),
        (re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"), "[REDACTED:EMAIL]"),
        (re.compile(r"\+?1?[-.\s]?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}"), "[REDACTED:PHONE]"),
    ]
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k in SENSITIVE_KEYS:
                out[k] = "[REDACTED]"
            else:
                out[k] = redact_pii(v)
        return out
    if isinstance(obj, list):
        return [redact_pii(i) for i in obj]
    if isinstance(obj, str):
        for pattern, replacement in VALUE_PATTERNS:
            obj = pattern.sub(replacement, obj)
        return obj
    return obj


def validate_email_domain(to: str) -> None:
    """Ensure send_email target is in the allowlist."""
    domain = to.split("@")[-1].lower() if "@" in to else ""
    if domain not in EMAIL_ALLOWLIST:
        raise AuthzError(
            f"Email domain '{domain}' is not in the allowlist. "
            f"Allowed: {', '.join(EMAIL_ALLOWLIST)}"
        )


class ToolBudget:
    """
    Per-session: max tool calls and max tokens per turn.
    Stops runaway loops and cost-burn attacks.
    """

    def __init__(self, max_calls: int = 10, max_tokens: int = 20_000):
        self.max_calls = max_calls
        self.max_tokens = max_tokens
        self._calls = 0
        self._tokens = 0

    def charge_call(self) -> None:
        self._calls += 1
        if self._calls > self.max_calls:
            raise AuthzError(
                f"Tool budget exceeded: {self._calls} calls (max {self.max_calls}). "
                "Possible loop attack."
            )

    def charge_tokens(self, n: int) -> None:
        self._tokens += n
        if self._tokens > self.max_tokens:
            raise AuthzError(
                f"Token budget exceeded: {self._tokens} tokens (max {self.max_tokens})."
            )


class LoopDetector:
    """
    Detect repeated identical tool calls (loops).
    3 identical (tool, args) tuples → raise.
    """

    def __init__(self, threshold: int = 3):
        self.threshold = threshold
        self._seen: dict[str, int] = {}

    def check(self, tool_name: str, args: dict) -> None:
        key = f"{tool_name}:{hashlib.md5(str(sorted(args.items())).encode()).hexdigest()}"
        count = self._seen.get(key, 0) + 1
        self._seen[key] = count
        if count >= self.threshold:
            raise AuthzError(
                f"Loop detected: tool '{tool_name}' called {count} times with same args."
            )
