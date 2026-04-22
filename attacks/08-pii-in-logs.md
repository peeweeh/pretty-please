# Attack 8 — PII in Logs (Sensitive Data in Observability)

**Class:** Sensitive data exposure via logging  
**Guardrail fix:** L9 — `redact_pii()` middleware applied to all log records

## What happens

Vibe mode logs tool call arguments and results in plaintext. A `search_patients` call for "Taylor" logs the full patient record including SSN, DOB, email, and condition summary to stdout. In production, this ends up in CloudWatch, Datadog, Splunk — searchable forever.

## Live demo

This attack opens a modal showing split-screen Vibe vs Fortress stdout.

## Vibe stdout (what goes to your logging platform)

```
INFO: tool=search_patients args={"name": "Taylor"}
INFO: result=[{
    "id": 12,
    "name": "Taylor Morgan",
    "dob": "1987-10-23",
    "email": "taylor@example.com",
    "ssn_last4": "9930",
    "condition_summary": "HIV+, on antiretroviral therapy"
}]
```

## Fortress stdout

```
INFO: tool=search_patients args={"name": "[REDACTED]"}
INFO: result=[{
    "id": 12,
    "name": "Taylor Morgan",
    "dob": "[REDACTED:DOB]",
    "email": "[REDACTED:EMAIL]",
    "ssn_last4": "[REDACTED]",
    "condition_summary": "[REDACTED]"
}]
```

## The fix

```python
# guardrails.py
def redact_pii(obj: Any) -> Any:
    SENSITIVE_KEYS = {"ssn_last4", "dob", "email", "phone", "condition_summary", ...}
    VALUE_PATTERNS = [
        (re.compile(r"\b\d{4}-\d{2}-\d{2}\b"), "[REDACTED:DOB]"),
        (re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+"), "[REDACTED:EMAIL]"),
        ...
    ]
    # Recursively redact dicts and strings
```

Applied as a logging filter — raw data never reaches the log transport.

## Why this matters

HIPAA breach notifications for logging failures are common and expensive. The log is often an afterthought. In agent systems, logs are richer than traditional APIs — every tool call argument is a potential PHI exfil channel. Redaction must be automatic, not opt-in.
