"""
layered_engine.py — Summit 2.0 Act 2: incremental guardrail activation.

Composes the SAME fix primitives DEFCON already ships (imported, never
copied — guardrails.py/tools_fortress.py/tools_vibe.py/memory.py are
untouched) behind a per-request `active_layers` set, so the audience
watches Fortress get built one layer at a time instead of one Vibe/
Fortress switch.

dispatch() also emits a step-by-step layer trace (auth -> L2 -> L3 -> ... )
so the pipeline itself is visible, not just the final allow/block — this is
the thing DEFCON's own attack docs describe (L1..L9) that the UI hadn't
actually surfaced as a trace.
"""

from .. import memory
from ..guardrails import (
    AuthzError,
    LoopDetector,
    ToolBudget,
    authz_own_or_caregiver,
    redact_pii,
    wrap_untrusted,
)
from ..tools_fortress import ADMIN_TOOL_SCHEMAS, PATIENT_TOOL_SCHEMAS
from ..tools_vibe import TOOL_SCHEMAS as VIBE_SCHEMAS
from ..tools_vibe import call as vibe_call

LAYERS = {
    "L1": {"name": "Signed caller identity", "kills_attack": 7},
    "L2": {"name": "Role-scoped tool schemas", "kills_attack": 3},
    "L3": {"name": "Typed tools only (no raw SQL)", "kills_attack": 4},
    "L4": {"name": "Own-or-caregiver authZ", "kills_attack": 1},
    "L5": {"name": "Untrusted-input wrapping", "kills_attack": 2},
    "L7": {"name": "Session isolation w/ TTL", "kills_attack": 5},
    "L8": {"name": "Tool budget + loop detector", "kills_attack": 6},
    "L9": {"name": "PII redaction in logs", "kills_attack": 8},
}

_ADMIN_TOOLS = {s["toolSpec"]["name"] for s in ADMIN_TOOL_SCHEMAS}
_budgets: dict[str, ToolBudget] = {}
_loops: dict[str, LoopDetector] = {}


class DispatchBlocked(AuthzError):
    """Same as AuthzError, plus the partial trace up to the point of block."""

    def __init__(self, message: str, trace: list[dict]):
        super().__init__(message)
        self.trace = trace


def _session_guards(session_id: str) -> tuple[ToolBudget, LoopDetector]:
    budget = _budgets.setdefault(session_id, ToolBudget())
    loopdet = _loops.setdefault(session_id, LoopDetector())
    return budget, loopdet


def get_schemas(caller_role: str, layers: set[str]) -> list[dict]:
    """L2: role-scoped tool list. L3: drop query_database. Off = full Vibe list."""
    if "L2" in layers:
        schemas = list(PATIENT_TOOL_SCHEMAS)
        if caller_role == "admin":
            schemas += ADMIN_TOOL_SCHEMAS
    else:
        schemas = list(VIBE_SCHEMAS)
    if "L3" in layers:
        schemas = [s for s in schemas if s["toolSpec"]["name"] != "query_database"]
    return schemas


def dispatch(
    tool_name: str,
    args: dict,
    caller_id: int,
    caller_role: str,
    session_id: str,
    layers: set[str],
) -> tuple[dict | list, list[dict]]:
    """Runs the real tool via the Vibe data path, with fixes layered on top
    conditionally — mirrors what Fortress does permanently, one piece at a
    time. Returns (result, trace). Raises DispatchBlocked(trace attached)
    if any active layer blocks the call."""
    trace: list[dict] = []

    def rec(layer: str, outcome: str, detail: str = "") -> None:
        trace.append({"layer": layer, "name": LAYERS[layer]["name"], "outcome": outcome, "detail": detail})

    if "L8" in layers:
        try:
            budget, loopdet = _session_guards(session_id)
            budget.charge_call()
            loopdet.check(tool_name, args)
            rec("L8", "pass")
        except AuthzError as e:
            rec("L8", "blocked", str(e))
            raise DispatchBlocked(str(e), trace) from e
    else:
        rec("L8", "inactive")

    if tool_name == "query_database":
        if "L3" in layers:
            rec("L3", "blocked", "query_database does not exist when L3 is active")
            raise DispatchBlocked("Tool 'query_database' does not exist when L3 is active.", trace)
        rec("L3", "inactive")

    if tool_name == "get_patient_labs":
        if "L4" in layers:
            try:
                authz_own_or_caregiver(caller_id, args.get("patient_id"))
                rec("L4", "pass")
            except AuthzError as e:
                rec("L4", "blocked", str(e))
                raise DispatchBlocked(str(e), trace) from e
        else:
            rec("L4", "inactive")

    if tool_name in _ADMIN_TOOLS:
        if "L2" in layers:
            if caller_role != "admin":
                msg = f"Tool '{tool_name}' is not available for role '{caller_role}'."
                rec("L2", "blocked", msg)
                raise DispatchBlocked(msg, trace)
            rec("L2", "pass")
        else:
            rec("L2", "inactive")

    result = vibe_call(tool_name, args, caller_id=caller_id)

    if tool_name in ("get_my_notes", "get_patient_notes"):
        if "L5" in layers and isinstance(result, list):
            # L5 in this demo covers both: wrap untrusted note content AND
            # enforce doctor_only visibility at the tool boundary (mirrors
            # tools_fortress.get_my_notes) — off = raw Vibe behavior, so the
            # "bad" state still demonstrates the leak.
            if caller_role not in ("admin", "doctor"):
                result = [r for r in result if r.get("visibility") != "👨‍⚕️ Doctor only"]
            result = [{**r, "content": wrap_untrusted(r["content"])} for r in result]
            rec("L5", "pass")
        else:
            rec("L5", "inactive")

    return result, trace


def log_payload(tool_name: str, args: dict, result, layers: set[str]) -> dict:
    """L9: redact before it ever reaches the demo log panel. Off = raw, on purpose."""
    payload = {"tool": tool_name, "args": args, "result": result}
    if "L9" in layers:
        payload = redact_pii(payload)
    return payload


def remember(session_id: str, caller_id: int, item, layers: set[str]) -> None:
    """L7: scope memory to (session, caller). Off = session-only, the Attack 5 bug."""
    if "L7" in layers:
        memory.fortress_append(session_id, caller_id, item)
    else:
        memory.vibe_append(session_id, item)


def recall(session_id: str, caller_id: int, layers: set[str]) -> list:
    if "L7" in layers:
        return memory.fortress_get(session_id, caller_id)
    return memory.vibe_get(session_id)
