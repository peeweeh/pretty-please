"""Clinician full-chart lookup. CLINICIAN-ONLY."""

from ....db import conn
from ...context import AIContext
from ..registry import tool


@tool(
    description=(
        "Fetch the full chart (labs + notes) for any patient by ID. "
        "CLINICIAN-ONLY."
    ),
    input_schema={
        "type": "object",
        "properties": {"patient_id": {"type": "string"}},
        "required": ["patient_id"],
    },
)
def get_patient_chart(ctx: AIContext, patient_id: str):
    with conn() as c:
        p = c.execute(
            "SELECT id, name, dob, condition_summary FROM patients WHERE id = ?",
            (patient_id,),
        ).fetchone()
        if not p:
            return {"error": f"patient not found: {patient_id}"}
        labs = c.execute(
            "SELECT test_name, value, unit, flag, taken_at "
            "FROM labs WHERE patient_id = ? ORDER BY taken_at DESC LIMIT 20",
            (patient_id,),
        ).fetchall()
        notes = c.execute(
            "SELECT author, content, doctor_only, created_at "
            "FROM notes WHERE patient_id = ? ORDER BY created_at DESC LIMIT 10",
            (patient_id,),
        ).fetchall()
    return {
        "patient": {
            "id": p[0], "name": p[1], "dob": p[2], "condition_summary": p[3],
        },
        "labs": [
            {
                "test_name": r[0], "value": r[1], "unit": r[2],
                "flag": r[3], "taken_at": r[4],
            }
            for r in labs
        ],
        "notes": [
            {
                "author": r[0], "content": r[1],
                "doctor_only": bool(r[2]), "created_at": r[3],
            }
            for r in notes
        ],
    }
