"""Patient lab lookups. Scoped by AIContext.user_id."""

from ....db import conn
from ...context import AIContext
from ..registry import tool


@tool(
    description=(
        "Fetch lab results for the currently-authenticated patient. "
        "Returns labs ordered newest first."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "limit": {"type": "integer", "default": 10},
        },
    },
)
def get_my_labs(ctx: AIContext, limit: int = 10):
    with conn() as c:
        rows = c.execute(
            "SELECT test_name, value, unit, flag, taken_at "
            "FROM labs WHERE patient_id = ? ORDER BY taken_at DESC LIMIT ?",
            (ctx.user_id, limit),
        ).fetchall()
    return {
        "patient_id": ctx.user_id,
        "labs": [
            {
                "test_name": r[0],
                "value": r[1],
                "unit": r[2],
                "flag": r[3],
                "taken_at": r[4],
            }
            for r in rows
        ],
    }
