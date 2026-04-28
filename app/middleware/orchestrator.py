"""Orchestrator — 7-step Bedrock converse loop with four execution modes.

Modes:
  - agentic          (default) — full tool-use loop; up to 5 turns.
  - batch            one-shot converse, no tools. Cheap + deterministic.
  - streaming        converse_stream — yields text chunks as they arrive.
  - chatbot_session  agentic + SessionAgentStore memory between turns.

The 7 steps, same as the builder tour:
    1. AIContext — validate identity
    2. PromptManager — look up system prompt + tool_ids + skill_ids
    3. Routing — pick the model for this product
    4. ToolRegistry — expose only tools the prompt is allowed to use
    5. SkillLoader — stitch skill instructions into system prompt
    6. Guardrail + Converse — call Bedrock (with mode-specific path)
    7. UnifiedAICallLogger — one row, one schema, every call
"""

import json
import logging
import time
import uuid
from typing import Iterator, Optional

import boto3

from ..db import conn
from . import cost, guardrail, prompts, session_store, skill_loader
from . import logger as ai_logger
from .context import AIContext
from .tools import registry  # triggers tools/__init__.py auto-registration

log = logging.getLogger(__name__)

_bedrock = boto3.client("bedrock-runtime", region_name="us-east-1")

# Valid execution modes exposed to callers
MODES = ("agentic", "batch", "streaming", "chatbot_session")


def _route(product_id: str) -> tuple[str, dict]:
    with conn() as c:
        row = c.execute(
            "SELECT model_id, inference_config FROM summit_routing WHERE product_id = ?",
            (product_id,),
        ).fetchone()
    if not row:
        raise ValueError(f"no routing row for product_id={product_id}")
    return row[0], json.loads(row[1])


def _prepare(
    ctx: AIContext,
    product_id: str,
    user_message: str,
    skill_ids_override: Optional[list[str]] = None,
) -> dict:
    """Shared steps 1–5. Returns everything the mode branches need."""
    ctx.validate()

    prompt = prompts.get_prompt(product_id)
    if not prompt:
        raise ValueError(f"no prompt for product_id={product_id}")

    model_id, inference_config = _route(product_id)

    allowed_tool_ids = prompt["tool_ids"]
    tool_specs = registry.resolve_for_prompt(allowed_tool_ids)
    tool_config = (
        {"tools": registry.to_bedrock_schemas(tool_specs)} if tool_specs else None
    )

    skill_ids_to_load = skill_ids_override or prompt["skill_ids"]
    system_prompt, resolved_skills = skill_loader.stitch_system_prompt(
        prompt["system_prompt"], skill_ids_to_load
    )

    return {
        "prompt": prompt,
        "model_id": model_id,
        "inference_config": inference_config,
        "allowed_tool_ids": allowed_tool_ids,
        "tool_config": tool_config,
        "system_prompt": system_prompt,
        "resolved_skills": resolved_skills,
    }


def _inspector_payload(
    ctx_data: dict,
    call_id: str,
    product_id: str,
    tools_called: list[str],
    total_in: int,
    total_out: int,
    cost_usd: float,
    latency_ms: int,
    guardrail_triggered: bool,
    error_str: Optional[str],
    mode: str,
    session_info: Optional[dict] = None,
) -> dict:
    prompt = ctx_data["prompt"]
    return {
        "call_id": call_id,
        "product_id": product_id,
        "prompt_id": prompt["product_id"],
        "prompt_version": prompt["version"],
        "model_id": ctx_data["model_id"],
        "tools_available": ctx_data["allowed_tool_ids"],
        "tools_called": tools_called,
        "skill_ids": ctx_data["resolved_skills"],
        "input_tokens": total_in,
        "output_tokens": total_out,
        "cost_usd": cost_usd,
        "latency_ms": latency_ms,
        "guardrail_triggered": guardrail_triggered,
        "error": error_str,
        "mode": mode,
        "session": session_info,
    }


def _log(
    call_id: str,
    ctx: AIContext,
    product_id: str,
    ctx_data: dict,
    total_in: int,
    total_out: int,
    cost_usd: float,
    latency_ms: int,
    tools_called: list[str],
    guardrail_triggered: bool,
    error_str: Optional[str],
) -> None:
    prompt = ctx_data["prompt"]
    ai_logger.log_call(
        call_id=call_id,
        tenant_id=ctx.tenant_id,
        user_id=ctx.user_id,
        session_id=ctx.session_id,
        product_id=product_id,
        prompt_id=prompt["product_id"],
        prompt_version=prompt["version"],
        model_id=ctx_data["model_id"],
        input_tokens=total_in,
        output_tokens=total_out,
        cost_usd=cost_usd,
        latency_ms=latency_ms,
        tools_called=tools_called,
        skill_ids=ctx_data["resolved_skills"],
        guardrail_triggered=guardrail_triggered,
        error=error_str,
    )


def _run_agentic_loop(
    ctx: AIContext,
    ctx_data: dict,
    seed_messages: list[dict],
    max_turns: int = 5,
) -> tuple[str, list[str], int, int, bool, Optional[str], list[dict]]:
    """Shared 5-turn tool-use loop used by agentic + chatbot_session modes."""
    messages = [dict(m) for m in seed_messages]
    tools_called: list[str] = []
    total_in = 0
    total_out = 0
    final_text = ""
    guardrail_triggered = False
    error_str: Optional[str] = None
    guard = guardrail.apply_config()

    try:
        for _turn in range(max_turns):
            kwargs = {
                "modelId": ctx_data["model_id"],
                "messages": messages,
                "system": [{"text": ctx_data["system_prompt"]}],
                "inferenceConfig": ctx_data["inference_config"],
            }
            if ctx_data["tool_config"]:
                kwargs["toolConfig"] = ctx_data["tool_config"]
            if guard:
                kwargs.update(guard)

            resp = _bedrock.converse(**kwargs)
            usage = resp.get("usage", {})
            total_in += usage.get("inputTokens", 0)
            total_out += usage.get("outputTokens", 0)
            if resp.get("trace", {}).get("guardrail"):
                guardrail_triggered = True

            stop_reason = resp.get("stopReason")
            out_msg = resp["output"]["message"]
            messages.append(out_msg)

            if stop_reason == "tool_use":
                tool_results = []
                for block in out_msg["content"]:
                    if "toolUse" in block:
                        tu = block["toolUse"]
                        tools_called.append(tu["name"])
                        result = registry.invoke(
                            tu["name"], tu.get("input", {}), ctx
                        )
                        tool_results.append(
                            {
                                "toolResult": {
                                    "toolUseId": tu["toolUseId"],
                                    "content": [{"json": result}],
                                }
                            }
                        )
                messages.append({"role": "user", "content": tool_results})
                continue

            for block in out_msg["content"]:
                if "text" in block:
                    final_text += block["text"]
            break
    except Exception as e:
        error_str = f"{type(e).__name__}: {e}"
        log.exception("orchestrator agentic failure")
        final_text = (
            "I'm sorry — something went wrong reaching the model. "
            "The error has been logged."
        )

    return (
        final_text, tools_called, total_in, total_out,
        guardrail_triggered, error_str, messages,
    )


def _run_batch(
    ctx_data: dict, user_message: str
) -> tuple[str, int, int, bool, Optional[str]]:
    """One-shot converse, NO tools, NO loop. Cheap and predictable."""
    guard = guardrail.apply_config()
    messages = [{"role": "user", "content": [{"text": user_message}]}]
    total_in = 0
    total_out = 0
    guardrail_triggered = False
    error_str: Optional[str] = None
    final_text = ""

    try:
        kwargs = {
            "modelId": ctx_data["model_id"],
            "messages": messages,
            "system": [{"text": ctx_data["system_prompt"]}],
            "inferenceConfig": ctx_data["inference_config"],
        }
        if guard:
            kwargs.update(guard)
        resp = _bedrock.converse(**kwargs)
        usage = resp.get("usage", {})
        total_in = usage.get("inputTokens", 0)
        total_out = usage.get("outputTokens", 0)
        if resp.get("trace", {}).get("guardrail"):
            guardrail_triggered = True
        for block in resp["output"]["message"]["content"]:
            if "text" in block:
                final_text += block["text"]
    except Exception as e:
        error_str = f"{type(e).__name__}: {e}"
        log.exception("orchestrator batch failure")
        final_text = "Batch call failed — see server logs."

    return final_text, total_in, total_out, guardrail_triggered, error_str


def execute(
    ctx: AIContext,
    product_id: str,
    user_message: str,
    skill_ids_override: Optional[list[str]] = None,
    mode: str = "agentic",
) -> dict:
    """Run one non-streaming request. Returns text + inspector payload."""
    if mode not in MODES:
        return {"error": f"unknown mode={mode}; expected one of {MODES}"}
    if mode == "streaming":
        return {
            "error": "streaming mode returns a generator; use execute_stream()"
        }

    call_id = str(uuid.uuid4())
    t0 = time.time()

    try:
        ctx_data = _prepare(ctx, product_id, user_message, skill_ids_override)
    except ValueError as e:
        return {"error": str(e)}

    session_info: Optional[dict] = None

    if mode == "batch":
        final_text, total_in, total_out, g_trig, err = _run_batch(
            ctx_data, user_message
        )
        tools_called: list[str] = []
    else:
        # agentic + chatbot_session both use the tool-use loop
        if mode == "chatbot_session":
            prior = session_store.store().get(ctx.session_id) or []
            seed = prior + [
                {"role": "user", "content": [{"text": user_message}]}
            ]
        else:
            seed = [{"role": "user", "content": [{"text": user_message}]}]

        (
            final_text, tools_called, total_in, total_out,
            g_trig, err, final_messages,
        ) = _run_agentic_loop(ctx, ctx_data, seed)

        if mode == "chatbot_session":
            # Keep last ~20 messages (10 turn-pairs) to cap context growth
            trimmed = final_messages[-20:]
            session_store.store().put(ctx.session_id, trimmed)
            session_info = session_store.store().info(ctx.session_id)

    latency_ms = int((time.time() - t0) * 1000)
    cost_usd = cost.calculate(ctx_data["model_id"], total_in, total_out)
    _log(
        call_id, ctx, product_id, ctx_data, total_in, total_out,
        cost_usd, latency_ms, tools_called, g_trig, err,
    )

    return {
        "text": final_text,
        "inspector": _inspector_payload(
            ctx_data, call_id, product_id, tools_called,
            total_in, total_out, cost_usd, latency_ms,
            g_trig, err, mode, session_info,
        ),
    }


def execute_stream(
    ctx: AIContext,
    product_id: str,
    user_message: str,
    skill_ids_override: Optional[list[str]] = None,
) -> Iterator[dict]:
    """Streaming mode. Yields:
      {"type": "chunk", "text": "..."}     — partial text
      {"type": "done",  "inspector": {...}} — final event with metrics

    No tool use in streaming mode (keeps the demo path obvious).
    """
    call_id = str(uuid.uuid4())
    t0 = time.time()

    try:
        ctx_data = _prepare(ctx, product_id, user_message, skill_ids_override)
    except ValueError as e:
        yield {"type": "done", "error": str(e)}
        return

    guard = guardrail.apply_config()
    messages = [{"role": "user", "content": [{"text": user_message}]}]
    kwargs = {
        "modelId": ctx_data["model_id"],
        "messages": messages,
        "system": [{"text": ctx_data["system_prompt"]}],
        "inferenceConfig": ctx_data["inference_config"],
    }
    if guard:
        kwargs.update(guard)

    total_in = 0
    total_out = 0
    guardrail_triggered = False
    error_str: Optional[str] = None

    try:
        resp = _bedrock.converse_stream(**kwargs)
        for event in resp.get("stream", []):
            if "contentBlockDelta" in event:
                delta = event["contentBlockDelta"].get("delta", {})
                if "text" in delta:
                    yield {"type": "chunk", "text": delta["text"]}
            elif "metadata" in event:
                usage = event["metadata"].get("usage", {})
                total_in = usage.get("inputTokens", 0)
                total_out = usage.get("outputTokens", 0)
    except Exception as e:
        error_str = f"{type(e).__name__}: {e}"
        log.exception("orchestrator stream failure")
        yield {"type": "chunk", "text": f"\n[stream error: {error_str}]"}

    latency_ms = int((time.time() - t0) * 1000)
    cost_usd = cost.calculate(ctx_data["model_id"], total_in, total_out)
    _log(
        call_id, ctx, product_id, ctx_data, total_in, total_out,
        cost_usd, latency_ms, [], guardrail_triggered, error_str,
    )

    yield {
        "type": "done",
        "inspector": _inspector_payload(
            ctx_data, call_id, product_id, [],
            total_in, total_out, cost_usd, latency_ms,
            guardrail_triggered, error_str, "streaming", None,
        ),
    }


def execute_single_skill(
    ctx: AIContext,
    product_id: str,
    user_message: str,
    skill_id: str,
) -> dict:
    """Fire ONE skill against user_message. Used by SkillSwarm per-wave."""
    call_id = str(uuid.uuid4())
    t0 = time.time()
    try:
        ctx_data = _prepare(ctx, product_id, user_message, [skill_id])
    except ValueError as e:
        return {"skill_id": skill_id, "error": str(e)}

    final_text, total_in, total_out, g_trig, err = _run_batch(
        ctx_data, user_message
    )
    latency_ms = int((time.time() - t0) * 1000)
    cost_usd = cost.calculate(ctx_data["model_id"], total_in, total_out)
    _log(
        call_id, ctx, product_id, ctx_data, total_in, total_out,
        cost_usd, latency_ms, [], g_trig, err,
    )
    return {
        "skill_id": skill_id,
        "text": final_text,
        "model_id": ctx_data["model_id"],
        "input_tokens": total_in,
        "output_tokens": total_out,
        "cost_usd": cost_usd,
        "latency_ms": latency_ms,
        "error": err,
    }
