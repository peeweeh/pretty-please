"""
Summit demo routes — /summit page + /v1/infer endpoint.

Additive only. Does not touch DEFCON routes in main.py.
"""

import json
import logging
import os
from typing import Optional

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from .db import conn
from .middleware import orchestrator, session_store, skill_loader, swarm
from .middleware.context import AIContext
from .middleware.tools import registry as tool_registry

logger = logging.getLogger(__name__)

router = APIRouter()

_STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")


@router.get("/summit")
def summit_page():
    return FileResponse(os.path.join(_STATIC_DIR, "summit.html"))


# ─────────────────────────────────────────────────────────────────────────────
# Read-only introspection endpoints for the inspector pane
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/summit/api/prompts")
def api_prompts():
    with conn() as c:
        rows = c.execute(
            "SELECT product_id, version, system_prompt, tool_ids, skill_ids "
            "FROM summit_prompts ORDER BY product_id"
        ).fetchall()
    return [
        {
            "product_id": r[0],
            "version": r[1],
            "system_prompt": r[2],
            "tool_ids": json.loads(r[3]),
            "skill_ids": json.loads(r[4]),
        }
        for r in rows
    ]


@router.get("/summit/api/skills")
def api_skills():
    with conn() as c:
        rows = c.execute(
            "SELECT skill_id, name, description, instructions, tags, dependencies, "
            "inject_full, status, version "
            "FROM summit_skills ORDER BY skill_id"
        ).fetchall()
    return [
        {
            "skill_id": r[0],
            "name": r[1],
            "description": r[2],
            "instructions": r[3],
            "tags": json.loads(r[4] or "[]"),
            "dependencies": json.loads(r[5] or "[]"),
            "inject_full": bool(r[6]),
            "status": r[7],
            "version": r[8],
        }
        for r in rows
    ]


@router.get("/summit/api/routing")
def api_routing():
    with conn() as c:
        rows = c.execute(
            "SELECT product_id, model_id, inference_config FROM summit_routing ORDER BY product_id"
        ).fetchall()
    return [
        {
            "product_id": r[0],
            "model_id": r[1],
            "inference_config": json.loads(r[2]),
        }
        for r in rows
    ]


@router.get("/summit/api/log")
def api_log(limit: int = 20):
    with conn() as c:
        rows = c.execute(
            "SELECT call_id, product_id, prompt_id, prompt_version, model_id, "
            "input_tokens, output_tokens, cost_usd, latency_ms, tools_called, "
            "skill_ids, guardrail_triggered, created_at "
            "FROM summit_unified_log ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [
        {
            "call_id": r[0],
            "product_id": r[1],
            "prompt_id": r[2],
            "prompt_version": r[3],
            "model_id": r[4],
            "input_tokens": r[5],
            "output_tokens": r[6],
            "cost_usd": r[7],
            "latency_ms": r[8],
            "tools_called": json.loads(r[9] or "[]"),
            "skill_ids": json.loads(r[10] or "[]"),
            "guardrail_triggered": bool(r[11]),
            "created_at": r[12],
        }
        for r in rows
    ]


@router.get("/summit/api/guardrail")
def api_guardrail():
    return {
        "id_set": bool(os.environ.get("BEDROCK_GUARDRAIL_ID")),
        "version": os.environ.get("BEDROCK_GUARDRAIL_VERSION", "DRAFT"),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Edit endpoints — show live hot-reload in the demo
# ─────────────────────────────────────────────────────────────────────────────


class PromptUpdate(BaseModel):
    system_prompt: Optional[str] = None
    tool_ids: Optional[list[str]] = None
    skill_ids: Optional[list[str]] = None


@router.put("/summit/api/prompts/{product_id}")
def update_prompt(product_id: str, body: PromptUpdate):
    """Edit a prompt — bumps version, invalidates PromptManager cache."""
    from .middleware.prompts import _CACHE

    with conn() as c:
        row = c.execute(
            "SELECT version, system_prompt, tool_ids, skill_ids "
            "FROM summit_prompts WHERE product_id = ?",
            (product_id,),
        ).fetchone()
        if not row:
            raise HTTPException(404, f"unknown product_id={product_id}")
        new_version = row[0] + 1
        new_sys = body.system_prompt if body.system_prompt is not None else row[1]
        new_tools = json.dumps(body.tool_ids) if body.tool_ids is not None else row[2]
        new_skills = json.dumps(body.skill_ids) if body.skill_ids is not None else row[3]
        c.execute(
            "UPDATE summit_prompts SET version=?, system_prompt=?, tool_ids=?, "
            "skill_ids=?, updated_at=CURRENT_TIMESTAMP WHERE product_id=?",
            (new_version, new_sys, new_tools, new_skills, product_id),
        )
        c.commit()
    _CACHE.pop(product_id, None)
    return {"ok": True, "product_id": product_id, "version": new_version}


class RoutingUpdate(BaseModel):
    model_id: str
    inference_config: Optional[dict] = None


@router.put("/summit/api/routing/{product_id}")
def update_routing(product_id: str, body: RoutingUpdate):
    with conn() as c:
        row = c.execute(
            "SELECT inference_config FROM summit_routing WHERE product_id = ?",
            (product_id,),
        ).fetchone()
        if not row:
            raise HTTPException(404, f"unknown product_id={product_id}")
        new_cfg = (
            json.dumps(body.inference_config)
            if body.inference_config is not None
            else row[0]
        )
        c.execute(
            "UPDATE summit_routing SET model_id=?, inference_config=?, "
            "updated_at=CURRENT_TIMESTAMP WHERE product_id=?",
            (body.model_id, new_cfg, product_id),
        )
        c.commit()
    return {"ok": True, "product_id": product_id, "model_id": body.model_id}


class SkillUpdate(BaseModel):
    instructions: Optional[str] = None
    status: Optional[str] = None


@router.put("/summit/api/skills/{skill_id}")
def update_skill(skill_id: str, body: SkillUpdate):
    with conn() as c:
        row = c.execute(
            "SELECT version, instructions, status FROM summit_skills WHERE skill_id=?",
            (skill_id,),
        ).fetchone()
        if not row:
            raise HTTPException(404, f"unknown skill_id={skill_id}")
        new_version = row[0] + 1
        new_instr = body.instructions if body.instructions is not None else row[1]
        new_status = body.status if body.status is not None else row[2]
        c.execute(
            "UPDATE summit_skills SET version=?, instructions=?, status=?, "
            "updated_at=CURRENT_TIMESTAMP WHERE skill_id=?",
            (new_version, new_instr, new_status, skill_id),
        )
        c.commit()
    return {"ok": True, "skill_id": skill_id, "version": new_version}


# ─────────────────────────────────────────────────────────────────────────────
# Single entry point for all Summit products
# ─────────────────────────────────────────────────────────────────────────────


class InferRequest(BaseModel):
    product_id: str
    user_message: str
    skill_ids: Optional[list[str]] = None
    mode: Optional[str] = "agentic"


@router.post("/v1/infer")
async def infer_endpoint(
    body: InferRequest,
    x_tenant_id: str = Header(default="lab-default"),
    x_user_id: str = Header(default=""),
    x_session_id: str = Header(default=""),
):
    """Single entry point — every Summit product calls this."""
    try:
        ctx = AIContext(
            tenant_id=x_tenant_id,
            user_id=x_user_id,
            session_id=x_session_id,
            metadata={"product_id": body.product_id},
        )
        ctx.validate()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"invalid AIContext: {e}") from e

    logger.info(
        "AIContext validated: tenant=%s user=%s session=%s product=%s mode=%s",
        ctx.tenant_id, ctx.user_id, ctx.session_id[:8], body.product_id, body.mode,
    )

    result = orchestrator.execute(
        ctx=ctx,
        product_id=body.product_id,
        user_message=body.user_message,
        skill_ids_override=body.skill_ids,
        mode=body.mode or "agentic",
    )
    return result


@router.post("/v1/infer/stream")
async def infer_stream_endpoint(
    body: InferRequest,
    x_tenant_id: str = Header(default="lab-default"),
    x_user_id: str = Header(default=""),
    x_session_id: str = Header(default=""),
):
    """Streaming SSE: one event per chunk, final event includes inspector."""
    try:
        ctx = AIContext(
            tenant_id=x_tenant_id, user_id=x_user_id, session_id=x_session_id,
            metadata={"product_id": body.product_id},
        )
        ctx.validate()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"invalid AIContext: {e}") from e

    def _gen():
        for event in orchestrator.execute_stream(
            ctx=ctx,
            product_id=body.product_id,
            user_message=body.user_message,
            skill_ids_override=body.skill_ids,
        ):
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(_gen(), media_type="text/event-stream")


class SwarmRequest(BaseModel):
    product_id: str
    user_message: str
    skill_ids: list[str]


@router.post("/v1/swarm")
async def swarm_endpoint(
    body: SwarmRequest,
    x_tenant_id: str = Header(default="lab-default"),
    x_user_id: str = Header(default=""),
    x_session_id: str = Header(default=""),
):
    """Run multiple skills in parallel waves against the same message."""
    try:
        ctx = AIContext(
            tenant_id=x_tenant_id, user_id=x_user_id, session_id=x_session_id,
            metadata={"product_id": body.product_id},
        )
        ctx.validate()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"invalid AIContext: {e}") from e

    # Build dep graph from summit_skills
    all_skills = skill_loader._fetch_all()
    deps = {sid: s["dependencies"] for sid, s in all_skills.items()}

    def _runner(skill_id: str, _upstream: dict) -> dict:
        return orchestrator.execute_single_skill(
            ctx=ctx,
            product_id=body.product_id,
            user_message=body.user_message,
            skill_id=skill_id,
        )

    report = swarm.run_swarm(
        skill_ids=body.skill_ids,
        deps=deps,
        runner=_runner,
        upstream={"user_message": body.user_message},
    )
    # Roll up totals for the inspector
    totals = {
        "input_tokens": 0, "output_tokens": 0,
        "cost_usd": 0.0, "calls": 0,
    }
    for r in report["results"].values():
        totals["input_tokens"] += r.get("input_tokens", 0)
        totals["output_tokens"] += r.get("output_tokens", 0)
        totals["cost_usd"] += r.get("cost_usd", 0.0)
        totals["calls"] += 1
    report["totals"] = totals
    return report


@router.post("/v1/session/reset")
async def session_reset(
    x_session_id: str = Header(default=""),
):
    """Forget the cached transcript for this session."""
    if not x_session_id.strip():
        raise HTTPException(status_code=400, detail="X-Session-Id required")
    session_store.store().evict(x_session_id)
    return {"evicted": x_session_id[:8]}


@router.get("/summit/api/session")
def api_session(
    x_session_id: str = Header(default=""),
):
    """Inspector payload for the Session Memory panel."""
    return session_store.store().info(x_session_id)


@router.get("/summit/api/tools")
def api_tools():
    """List registered @tool functions and the source file they came from."""
    return [
        {
            "name": spec.name,
            "description": spec.description,
            "source": spec.source,
        }
        for spec in tool_registry._REGISTRY.values()
    ]
