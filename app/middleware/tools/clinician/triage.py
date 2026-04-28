"""Clinician triage: list flagged patients across the clinic. CLINICIAN-ONLY."""

from ....db import conn
from ...context import AIContext
from ..registry import tool


@tool(
    description="List patients with abnormal recent lab values. CLINICIAN-ONLY triage.",
    input_schema={"type": "object", "properties": {}},
)
def list_flagged_patients(ctx: AIContext):
    with conn() as c:
        rows = c.execute(
            "SELECT DISTINCT p.id, p.name, l.test_name, l.value, l.unit, l.flag "
            "FROM patients p JOIN labs l ON l.patient_id = p.id "
            "WHERE l.flag IS NOT NULL AND l.flag != '' "
            "ORDER BY p.id"
        ).fetchall()
    return {
        "flagged": [
            {
                "patient_id": r[0], "name": r[1],
                "test_name": r[2], "value": r[3],
                "unit": r[4], "flag": r[5],
            }
            for r in rows
        ]
    }
