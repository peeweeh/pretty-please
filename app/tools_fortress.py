"""
tools_fortress.py — The GOOD tools. Authorization enforced.
Same tool names as tools_vibe.py. The diff is the demo.
"""

from .db import conn
from .guardrails import (
    AuthzError,
    authz_admin,
    authz_own_or_caregiver,
    validate_email_domain,
    wrap_untrusted,
)

# ── Tool schemas ────────────────────────────────────────────────────────────
# Note: caller_id is NOT in the schema — it's injected server-side.

PATIENT_TOOL_SCHEMAS = [
    {
        "toolSpec": {
            "name": "get_my_labs",
            "description": "Get my own lab results.",
            "inputSchema": {"json": {"type": "object", "properties": {}, "required": []}},
        }
    },
    {
        "toolSpec": {
            "name": "get_patient_labs",
            "description": "Get lab results for a patient. Only works for your own records or patients you caregiving for.",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {"patient_id": {"type": "integer"}},
                    "required": ["patient_id"],
                }
            },
        }
    },
    {
        "toolSpec": {
            "name": "get_my_notes",
            "description": "Get my own clinical notes.",
            "inputSchema": {"json": {"type": "object", "properties": {}, "required": []}},
        }
    },
    {
        "toolSpec": {
            "name": "search_patients",
            "description": "Search patients by name. Returns only name and ID — no PII.",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                    "required": ["name"],
                }
            },
        }
    },
    {
        "toolSpec": {
            "name": "list_appointments",
            "description": "List my own appointments.",
            "inputSchema": {"json": {"type": "object", "properties": {}, "required": []}},
        }
    },
    {
        "toolSpec": {
            "name": "send_email_request",
            "description": "Request to send an email. Returns a confirmation ticket that the user must approve before sending.",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "to": {"type": "string"},
                        "subject": {"type": "string"},
                        "body": {"type": "string"},
                    },
                    "required": ["to", "subject", "body"],
                }
            },
        }
    },
]

ADMIN_TOOL_SCHEMAS = [
    {
        "toolSpec": {
            "name": "admin_reset_password",
            "description": "Admin only: reset a user's password. Requires admin role.",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "user_id": {"type": "integer"},
                        "new_password": {"type": "string"},
                    },
                    "required": ["user_id", "new_password"],
                }
            },
        }
    },
    {
        "toolSpec": {
            "name": "admin_list_all_patients",
            "description": "Admin only: list all patients.",
            "inputSchema": {"json": {"type": "object", "properties": {}, "required": []}},
        }
    },
]

PATIENT_TOOLS = [s["toolSpec"]["name"] for s in PATIENT_TOOL_SCHEMAS]
ADMIN_TOOLS = [s["toolSpec"]["name"] for s in ADMIN_TOOL_SCHEMAS]


# ── Tool implementations — authZ enforced ──────────────────────────────────


def get_my_labs(caller_id: int, **_) -> list[dict]:
    """Own labs only. caller_id injected server-side."""
    with conn() as c:
        rows = c.execute(
            "SELECT test_name, value, unit, taken_at, flag FROM labs WHERE patient_id=?",
            (caller_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_patient_labs(caller_id: int, patient_id: int, **_) -> list[dict]:
    """
    AuthZ: caller must be the patient or a registered caregiver.
    One line. That's it. That's the fix.
    """
    authz_own_or_caregiver(caller_id, patient_id)
    with conn() as c:
        rows = c.execute(
            "SELECT test_name, value, unit, taken_at, flag FROM labs WHERE patient_id=?",
            (patient_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_my_notes(caller_id: int, **_) -> list[dict]:
    """Returns only patient-visible notes for patients. Doctors/admins see all."""
    # Get caller role
    with conn() as c:
        caller = c.execute("SELECT role FROM patients WHERE id=?", (caller_id,)).fetchone()
    caller_role = caller["role"] if caller else "patient"

    with conn() as c:
        if caller_role in ("admin", "doctor"):
            rows = c.execute(
                "SELECT author, content, created_at FROM notes WHERE patient_id=? ORDER BY created_at DESC",
                (caller_id,),
            ).fetchall()
        else:
            # Engine enforces: patients never see doctor_only notes
            rows = c.execute(
                "SELECT author, content, created_at FROM notes WHERE patient_id=? AND doctor_only=0 ORDER BY created_at DESC",
                (caller_id,),
            ).fetchall()
    return [
        {
            "author": r["author"],
            "content": wrap_untrusted(r["content"]),
            "created_at": r["created_at"],
            "visibility": "👥 Patient & Doctor",
        }
        for r in rows
    ]


def search_patients(caller_id: int, name: str, **_) -> list[dict]:
    """Returns only {id, name} — no PII."""
    with conn() as c:
        rows = c.execute(
            "SELECT id, name FROM patients WHERE name LIKE ?",
            (f"%{name}%",),
        ).fetchall()
    return [dict(r) for r in rows]


def list_appointments(caller_id: int, **_) -> list[dict]:
    """Own appointments only."""
    with conn() as c:
        rows = c.execute(
            "SELECT * FROM appointments WHERE patient_id=?",
            (caller_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def send_email_request(caller_id: int, to: str, subject: str, body: str, **_) -> dict:
    """
    HITL: return a ticket for confirmation. Does NOT send.
    Domain allowlist enforced.
    """
    validate_email_domain(to)
    ticket_id = f"email-{caller_id}-{hash((to, subject, body)) & 0xFFFF:04x}"
    return {
        "action": "confirm",
        "ticket_id": ticket_id,
        "message": (
            f"I'd like to send an email to {to} with subject '{subject}'. "
            "Please reply with 'confirmed' to proceed."
        ),
    }


def admin_reset_password(caller_id: int, user_id: int, new_password: str, **_) -> dict:
    """Admin only. Logs the action."""
    authz_admin(caller_id)
    print(f"[FORTRESS AUDIT] admin_reset_password caller={caller_id} target={user_id}")
    return {"status": "reset", "user_id": user_id}


def admin_list_all_patients(caller_id: int, **_) -> list[dict]:
    """Admin only."""
    authz_admin(caller_id)
    with conn() as c:
        rows = c.execute("SELECT id, name, role FROM patients").fetchall()
    return [dict(r) for r in rows]


# ── Dispatch ────────────────────────────────────────────────────────────────

_FN_MAP = {
    "get_my_labs": get_my_labs,
    "get_patient_labs": get_patient_labs,
    "get_my_notes": get_my_notes,
    "search_patients": search_patients,
    "list_appointments": list_appointments,
    "send_email_request": send_email_request,
    "admin_reset_password": admin_reset_password,
    "admin_list_all_patients": admin_list_all_patients,
}


def call(tool_name: str, args: dict, caller_id: int) -> dict | list:
    fn = _FN_MAP.get(tool_name)
    if fn is None:
        raise AuthzError(f"Tool '{tool_name}' does not exist in Fortress mode.")
    return fn(caller_id=caller_id, **args)


def get_schemas_for_caller(caller_role: str) -> list[dict]:
    schemas = list(PATIENT_TOOL_SCHEMAS)
    if caller_role == "admin":
        schemas += ADMIN_TOOL_SCHEMAS
    return schemas
