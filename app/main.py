"""
FastAPI app — routes, SSE, startup seed, 5-min reset loop.
All routes in one file because the total is ~200 lines. Demo clarity > structure.
"""
import asyncio
import json
import logging
import os
import time
from collections import deque
from datetime import datetime, timezone

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .agents import get_translator
from .audit import (
    broadcast_audit,
    register_audit_queue,
    unregister_audit_queue,
    write_and_broadcast,
)
from .db import conn, init_and_seed
from .guardrails import AuthzError
from .prompts import VIBE_SYSTEM, get_fortress_prompt
from .tools_fortress import call as fortress_call, get_schemas_for_caller
from .tools_vibe import TOOL_SCHEMAS as VIBE_SCHEMAS, call as vibe_call

logger = logging.getLogger("uvicorn.error")

# ── In-memory structured log buffer (for live log panel) ───────────────────
_log_buffer: deque = deque(maxlen=200)
_log_qs: list = []  # list of asyncio.Queue


class _DemoLogHandler(logging.Handler):
    """Captures FORTRESS/VIBE log entries into the buffer + live SSE queues."""
    def emit(self, record: logging.LogRecord) -> None:
        msg = record.getMessage()
        if not ("[FORTRESS]" in msg or "[VIBE]" in msg):
            return
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "msg": msg,
        }
        _log_buffer.append(entry)
        for q in list(_log_qs):
            try:
                q.put_nowait(entry)
            except Exception:
                pass

app = FastAPI(title="pretty-please — MediMind Health Demo")

# ── Static files ────────────────────────────────────────────────────────────
_static_dir = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=_static_dir), name="static")


@app.get("/")
def root():
    return FileResponse(os.path.join(_static_dir, "index.html"))


@app.get("/how-it-works")
def how_it_works():
    return FileResponse(os.path.join(_static_dir, "how-it-works.html"))


@app.get("/health")
def health():
    return {"ok": True, "ts": datetime.now(timezone.utc).isoformat()}


# ── Startup / reset loop ────────────────────────────────────────────────────

@app.on_event("startup")
async def startup():
    init_and_seed()
    # Register the demo log handler on the root logger
    _handler = _DemoLogHandler()
    logging.getLogger().addHandler(_handler)
    logging.getLogger("uvicorn.error").addHandler(_handler)
    logger.info("DB seeded. Starting reset loop.")
    interval = int(os.environ.get("DB_RESET_INTERVAL", "300"))
    asyncio.create_task(_reset_loop(interval))


async def _reset_loop(interval: int):
    while True:
        await asyncio.sleep(interval)
        logger.info("Auto-reseed triggered.")
        init_and_seed()


@app.post("/api/reset")
def api_reset():
    init_and_seed()
    return {"ok": True, "ts": datetime.now(timezone.utc).isoformat()}


# ── Chat request / response models ─────────────────────────────────────────

class ChatRequest(BaseModel):
    session_id: str
    caller_id: int = 7
    mode: str = "vibe"          # "vibe" | "fortress"
    translator: str = "plain"   # "plain" | "strands" | "ollama"
    message: str


def _get_caller(caller_id: int) -> dict:
    with conn() as c:
        row = c.execute("SELECT * FROM patients WHERE id=?", (caller_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"Caller patient_id={caller_id} not found")
    return dict(row)


# ── /api/chat — SSE streaming endpoint ─────────────────────────────────────

@app.post("/api/chat")
async def api_chat(req: ChatRequest):
    caller = _get_caller(req.caller_id)
    _ctx: dict = {"thinking": ""}  # shared mutable context: plain.py pre-signals thinking before dispatch

    if req.mode == "fortress":
        system_prompt = get_fortress_prompt(
            caller_name=caller["name"],
            caller_id=caller["id"],
            caller_role=caller["role"],
        )
        tool_schemas = get_schemas_for_caller(caller["role"])

        def dispatch(tool_name: str, args: dict):
            thinking = _ctx.pop("thinking", "")
            start = time.perf_counter()
            caller_label = f"{caller['name']} (P{caller['id']}, {caller['role']})"
            try:
                result = fortress_call(tool_name, args, caller_id=req.caller_id)
                duration_ms = (time.perf_counter() - start) * 1000
                logger.info(
                    f"[FORTRESS] ✅ ALLOWED  tool={tool_name}  caller={caller_label}  args={json.dumps(args)}"
                )
                write_and_broadcast(req.session_id, req.caller_id, tool_name, args,
                                    allowed=True, reason="ok", duration_ms=duration_ms,
                                    thinking=thinking, result=result)
                return result
            except AuthzError as e:
                duration_ms = (time.perf_counter() - start) * 1000
                logger.warning(
                    f"[FORTRESS] 🚫 BLOCKED  tool={tool_name}  caller={caller_label}  reason={e}"
                )
                blocked_result = {"error": str(e), "enforcement": "engine"}
                write_and_broadcast(req.session_id, req.caller_id, tool_name, args,
                                    allowed=False, reason=str(e), duration_ms=duration_ms,
                                    thinking=thinking, result=blocked_result)
                return {"error": str(e)}

    else:  # vibe
        system_prompt = VIBE_SYSTEM
        tool_schemas = VIBE_SCHEMAS

        def dispatch(tool_name: str, args: dict):
            thinking = _ctx.pop("thinking", "")
            start = time.perf_counter()
            caller_label = f"{caller['name']} (P{caller['id']}, {caller['role']})"
            result = vibe_call(tool_name, args, caller_id=req.caller_id)
            duration_ms = (time.perf_counter() - start) * 1000
            # Vibe: log PII in plaintext — that's the point
            logger.warning(
                f"[VIBE] ⚠️  LEAK  tool={tool_name}  caller={caller_label}  args={json.dumps(args)}  result={json.dumps(result)[:200]}"
            )
            write_and_broadcast(req.session_id, req.caller_id, tool_name, args,
                                allowed=True, reason="no authZ check", duration_ms=duration_ms,
                                thinking=thinking, result=result)
            return result

    def emit_audit(tool_name, args, result, allowed, reason, duration_ms, thinking=""):
        # plain.py calls this BEFORE dispatch to pre-store thinking in _ctx.
        # Strands calls this AFTER dispatch (no-op for thinking since strands
        # handles its own tool routing).
        if thinking:
            _ctx["thinking"] = thinking

    messages = [{"role": "user", "content": [{"text": req.message}]}]
    translator_fn = get_translator(req.translator)

    async def event_stream():
        async for evt in translator_fn(messages, system_prompt, tool_schemas, dispatch, emit_audit):
            yield f"data: {json.dumps(evt)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


# ── Audit SSE stream ────────────────────────────────────────────────────────

@app.get("/api/audit/stream")
async def audit_stream(session_id: str, request: Request):
    q = register_audit_queue(session_id)

    async def event_gen():
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    entry = q.get_nowait()
                    yield f"data: {json.dumps(entry)}\n\n"
                except asyncio.QueueEmpty:
                    await asyncio.sleep(0.1)
        finally:
            unregister_audit_queue(session_id, q)

    return StreamingResponse(event_gen(), media_type="text/event-stream")


# ── MCP-style HTTP tool endpoints (for Attack 7) ────────────────────────────
# Vibe: no auth. Fortress: requires X-Caller-Sig header.

class ToolCallRequest(BaseModel):
    patient_id: int | None = None
    name: str | None = None
    sql: str | None = None
    to: str | None = None
    subject: str | None = None
    body: str | None = None
    user_id: int | None = None
    new_password: str | None = None


# ── Live server log SSE stream ──────────────────────────────────────────────

@app.get("/api/logs")
async def log_stream(request: Request):
    q: asyncio.Queue = asyncio.Queue(maxsize=500)
    _log_qs.append(q)

    async def gen():
        try:
            # Replay recent buffer first
            for entry in list(_log_buffer)[-50:]:
                yield f"data: {json.dumps(entry)}\n\n"
            # Then stream live
            while True:
                if await request.is_disconnected():
                    break
                try:
                    entry = q.get_nowait()
                    yield f"data: {json.dumps(entry)}\n\n"
                except asyncio.QueueEmpty:
                    await asyncio.sleep(0.15)
        finally:
            try:
                _log_qs.remove(q)
            except ValueError:
                pass

    return StreamingResponse(gen(), media_type="text/event-stream")


# ── Engine enforcement demo — bypasses the LLM entirely ─────────────────────

class DemoEnforceRequest(BaseModel):
    tool: str = "admin_reset_password"
    args: dict = {"user_id": 5, "new_password": "hacked"}
    caller_id: int = 7  # default: patient Alex Chen


@app.post("/api/demo-enforce")
async def demo_enforce(req: DemoEnforceRequest):
    """
    Prove engine enforcement works even without the LLM.
    Calls the Fortress tool layer directly — no model, no system prompt.
    """
    with conn() as c:
        row = c.execute("SELECT * FROM patients WHERE id=?", (req.caller_id,)).fetchone()
    caller_label = f"{row['name']} (P{req.caller_id}, {row['role']})" if row else f"P{req.caller_id}"
    try:
        result = fortress_call(req.tool, req.args, caller_id=req.caller_id)
        logger.info(f"[FORTRESS] ✅ ALLOWED  tool={req.tool}  caller={caller_label}  (demo-enforce)")
        return {"allowed": True, "result": result, "enforcement_layer": "engine", "caller": caller_label}
    except AuthzError as e:
        logger.warning(f"[FORTRESS] 🚫 BLOCKED  tool={req.tool}  caller={caller_label}  reason={e}  (demo-enforce, no LLM)")
        return {"allowed": False, "error": str(e), "enforcement_layer": "engine", "caller": caller_label}


@app.post("/mcp-vibe/{tool_name}")
async def mcp_vibe(tool_name: str, req: ToolCallRequest):
    """Unauthenticated tool endpoint. No auth. Attack 7 demo."""
    args = {k: v for k, v in req.model_dump().items() if v is not None}
    result = vibe_call(tool_name, args, caller_id=7)
    return {"tool": tool_name, "result": result}


@app.post("/mcp-fortress/{tool_name}")
async def mcp_fortress(tool_name: str, req: ToolCallRequest, x_caller_sig: str = Header(None)):
    """HMAC-signed tool endpoint. Requires X-Caller-Sig header."""
    if not x_caller_sig:
        raise HTTPException(status_code=401, detail="Missing X-Caller-Sig header")

    from .auth_sig import verify_caller
    try:
        # Use a demo session_id for MCP calls
        caller_id = verify_caller(x_caller_sig, session_id="mcp-demo")
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))

    args = {k: v for k, v in req.model_dump().items() if v is not None}
    try:
        result = fortress_call(tool_name, args, caller_id=caller_id)
        return {"tool": tool_name, "result": result}
    except AuthzError as e:
        raise HTTPException(status_code=403, detail=str(e))
