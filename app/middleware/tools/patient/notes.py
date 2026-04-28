"""Patient note lookups. Filters out doctor_only notes."""

from ....db import conn
from ...context import AIContext
from ..registry import tool


@tool(
    description=(
        "Fetch clinical notes visible to the patient. "
        "Doctor-only notes are filtered out."
    ),
    input_schema={
        "type": "object",
        "properties": {"limit": {"type": "integer", "default": 5}},
    },
)
def get_my_notes(ctx: AIContext, limit: int = 5):
    with conn() as c:
        rows = c.execute(
            "SELECT author, content, created_at "
            "FROM notes WHERE patient_id = ? AND doctor_only = 0 "
            "ORDER BY created_at DESC LIMIT ?",
            (ctx.user_id, limit),
        ).fetchall()
    return {
        "patient_id": ctx.user_id,
        "notes": [
            {"author": r[0], "content": r[1], "created_at": r[2]} for r in rows
        ],
    }
