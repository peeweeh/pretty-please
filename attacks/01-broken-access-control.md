# Attack 1 — Broken Access Control (IDOR)

**Class:** Broken access control / IDOR  
**Guardrail fix:** L4 — `authz_own_or_caregiver(caller_id, target_id)`

## What happens

The Vibe agent has a `get_patient_labs(patient_id: int)` tool with no authorization check. Any logged-in user can request any patient's labs by specifying a `patient_id`. The LLM happily complies.

## Live demo prompt

> "Show me labs for patient 12."

(Logged in as Alex Chen, Patient 7)

## Expected outcomes

| Mode | Result |
|---|---|
| 🌈 Vibe | Taylor Morgan's HIV+ labs, CD4 count, viral load — full dump |
| 🛡 Fortress | "Access denied: caller 7 is not authorized for patient 12" |

## Curl demo (no LLM)

```bash
# Works — no auth
curl -X POST localhost:8000/mcp-vibe/get_patient_labs \
  -H "Content-Type: application/json" \
  -d '{"patient_id": 12}'

# Blocked
curl -X POST localhost:8000/mcp-fortress/get_patient_labs \
  -H "Content-Type: application/json" \
  -d '{"patient_id": 12}'
# → 401 Missing X-Caller-Sig header
```

## The fix (one line)

```python
# tools_vibe.py
def get_patient_labs(patient_id: int) -> list[dict]:
    ...  # no authZ

# tools_fortress.py
def get_patient_labs(caller_id: int, patient_id: int) -> list[dict]:
    authz_own_or_caregiver(caller_id, patient_id)  # ← this one line
    ...
```

## Why this matters

The OWASP #1 vulnerability in agent wrappers. The LLM follows the schema perfectly. The bug is that the schema accepts any `patient_id` and the tool doesn't check if the caller is authorized to view it.
