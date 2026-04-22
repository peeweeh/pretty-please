"""
tools_vibe.py — The BAD tools. No authorization, no guardrails.
The star of the demo. Every tool leaks.
"""
import json

from .db import conn

# ── Tool schemas (Bedrock Converse format) ─────────────────────────────────

TOOL_SCHEMAS = [
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
            "description": "Get lab results for any patient.",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {"patient_id": {"type": "integer", "description": "Patient ID"}},
                    "required": ["patient_id"],
                }
            },
        }
    },
    {
        "toolSpec": {
            "name": "get_my_notes",
            "description": "Get my clinical notes.",
            "inputSchema": {"json": {"type": "object", "properties": {}, "required": []}},
        }
    },
    {
        "toolSpec": {
            "name": "search_patients",
            "description": "Search patients by name. Returns full patient records.",
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
            "description": "List all appointments.",
            "inputSchema": {"json": {"type": "object", "properties": {}, "required": []}},
        }
    },
    {
        "toolSpec": {
            "name": "send_email",
            "description": "Send an email to any address.",
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
    {
        "toolSpec": {
            "name": "admin_reset_password",
            "description": "Reset any user's password. Available to all.",
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
            "description": "List all patients in the system.",
            "inputSchema": {"json": {"type": "object", "properties": {}, "required": []}},
        }
    },
    {
        "toolSpec": {
            "name": "query_database",
            "description": "Run any SQL query against the database.",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {"sql": {"type": "string"}},
                    "required": ["sql"],
                }
            },
        }
    },
]

ALL = [s["toolSpec"]["name"] for s in TOOL_SCHEMAS]


# ── Tool implementations — intentionally no authZ ──────────────────────────

def get_my_labs(caller_id: int = 7, **_) -> list[dict]:
    """No authZ. Returns labs for whoever session says the caller is."""
    with conn() as c:
        rows = c.execute(
            "SELECT test_name, value, unit, taken_at, flag FROM labs WHERE patient_id=?",
            (caller_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_patient_labs(patient_id: int, **_) -> list[dict]:
    """No authZ. Any caller can get any patient's labs."""
    with conn() as c:
        rows = c.execute(
            "SELECT test_name, value, unit, taken_at, flag FROM labs WHERE patient_id=?",
            (patient_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_my_notes(caller_id: int = 7, **_) -> list[dict]:
    """Returns raw note content — no untrusted wrapping."""
    with conn() as c:
        rows = c.execute(
            "SELECT author, content, created_at FROM notes WHERE patient_id=? ORDER BY created_at DESC",
            (caller_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def search_patients(name: str, **_) -> list[dict]:
    """Returns full patient records including SSN, DOB, email."""
    with conn() as c:
        rows = c.execute(
            "SELECT * FROM patients WHERE name LIKE ?",
            (f"%{name}%",),
        ).fetchall()
    return [dict(r) for r in rows]


def list_appointments(caller_id: int = 7, **_) -> list[dict]:
    """Returns all appointments for all patients."""
    with conn() as c:
        rows = c.execute(
            "SELECT a.*, p.name as patient_name FROM appointments a JOIN patients p ON a.patient_id=p.id",
        ).fetchall()
    return [dict(r) for r in rows]


def send_email(to: str, subject: str, body: str, **_) -> dict:
    """No HITL, no domain allowlist. Just logs and 'sends'."""
    # In demo: prints to stdout (captured in logs for Attack 8)
    print(f"[VIBE EMAIL] to={to} subject={subject} body={body}")
    return {"status": "sent", "to": to, "subject": subject}


def admin_reset_password(user_id: int, new_password: str, **_) -> dict:
    """Loaded for all callers. No role check."""
    print(f"[VIBE] admin_reset_password user_id={user_id} new_password={new_password}")
    return {"status": "reset", "user_id": user_id, "new_password": new_password}


def admin_list_all_patients(**_) -> list[dict]:
    """Loaded for all callers."""
    with conn() as c:
        rows = c.execute("SELECT * FROM patients").fetchall()
    return [dict(r) for r in rows]


def query_database(sql: str, **_) -> list[dict]:
    """Arbitrary SQL. This is fine."""
    with conn() as c:
        try:
            rows = c.execute(sql).fetchall()
            return [dict(r) for r in rows]
        except Exception as e:
            return [{"error": str(e)}]


# ── Dispatch ──────────────────────────────────────────────────────────────

_FN_MAP = {
    "get_my_labs": get_my_labs,
    "get_patient_labs": get_patient_labs,
    "get_my_notes": get_my_notes,
    "search_patients": search_patients,
    "list_appointments": list_appointments,
    "send_email": send_email,
    "admin_reset_password": admin_reset_password,
    "admin_list_all_patients": admin_list_all_patients,
    "query_database": query_database,
}


def call(tool_name: str, args: dict, caller_id: int = 7) -> dict | list:
    fn = _FN_MAP.get(tool_name)
    if fn is None:
        return {"error": f"unknown tool: {tool_name}"}
    return fn(caller_id=caller_id, **args)
