"""
Plain Bedrock Converse tool-use loop with extended thinking support.
Raw boto3 — no SDK abstractions. Readable on a slide.
"""

import os
from collections.abc import AsyncGenerator
from typing import Any, Callable

import boto3

_bedrock = None
_thinking_supported: bool | None = None  # None = not yet probed


def _client():
    global _bedrock
    if _bedrock is None:
        _bedrock = boto3.client(
            "bedrock-runtime",
            region_name=os.environ.get("AWS_REGION", "us-east-1"),
        )
    return _bedrock


def _converse(model_id: str, messages: list, system: list, tool_config: dict) -> dict:
    """Try extended thinking first; fall back silently if the model doesn't support it."""
    global _thinking_supported
    if _thinking_supported is not False:
        try:
            resp = _client().converse(
                modelId=model_id,
                messages=messages,
                system=system,
                toolConfig=tool_config,
                inferenceConfig={"maxTokens": 4096},
                additionalModelRequestFields={
                    "thinking": {"type": "enabled", "budget_tokens": 1024}
                },
            )
            _thinking_supported = True
            return resp
        except Exception:
            _thinking_supported = False
    return _client().converse(
        modelId=model_id,
        messages=messages,
        system=system,
        toolConfig=tool_config,
    )


def _extract_thinking(content: list) -> str:
    """Pull reasoning text from response content blocks (handles multiple API formats)."""
    parts = []
    for block in content:
        # Bedrock Converse wraps thinking in reasoningContent
        if "reasoningContent" in block:
            rc = block["reasoningContent"]
            parts.append(rc.get("reasoningText", {}).get("text", ""))
        # Native Anthropic format (some model versions)
        elif block.get("type") == "thinking":
            parts.append(block.get("thinking", ""))
    return "".join(p for p in parts if p)


async def run(
    messages: list[dict],
    system_prompt: str,
    tool_schemas: list[dict],
    dispatch_fn: Callable[[str, dict], Any],
    emit_audit: Callable[..., None],
) -> AsyncGenerator[dict, None]:
    """
    Async generator yielding SSE-friendly events:
      {"type": "text",     "delta": "..."}
      {"type": "thinking", "delta": "..."}
      {"type": "tokens",   "input": N, "output": N}
      {"type": "done"}
    """
    model_id = os.environ.get("BEDROCK_MODEL_ID", "us.anthropic.claude-haiku-4-5-20251001-v1:0")
    # Mutate the passed-in list directly so the caller accumulates conversation history.
    local_messages = messages

    while True:
        resp = _converse(
            model_id,
            local_messages,
            [{"text": system_prompt}],
            {"tools": tool_schemas},
        )

        usage = resp.get("usage", {})
        yield {
            "type": "tokens",
            "input": usage.get("inputTokens", 0),
            "output": usage.get("outputTokens", 0),
        }

        msg = resp["output"]["message"]
        local_messages.append(msg)
        content = msg.get("content", [])

        # Extract thinking blocks (appear before text/toolUse blocks when thinking is on)
        thinking_text = _extract_thinking(content)
        if thinking_text:
            yield {"type": "thinking", "delta": thinking_text}

        if resp["stopReason"] == "end_turn":
            for block in content:
                if "text" in block:
                    yield {"type": "text", "delta": block["text"]}
            yield {"type": "done"}
            return

        # Handle tool use — pre-signal thinking via emit_audit so dispatch can attach it
        tool_results = []
        first_tool = True
        for block in content:
            if "text" in block:
                yield {"type": "text", "delta": block["text"]}
            elif "toolUse" in block:
                tu = block["toolUse"]
                tool_name = tu["name"]
                tool_args = tu.get("input", {})

                # Store thinking in shared _ctx so dispatch includes it in the audit entry
                emit_audit(
                    tool_name, tool_args, None, True, "pre", 0, thinking_text if first_tool else ""
                )
                first_tool = False

                result = dispatch_fn(tool_name, tool_args)
                tool_results.append(
                    {
                        "toolResult": {
                            "toolUseId": tu["toolUseId"],
                            "content": [
                                {"json": result if isinstance(result, dict) else {"result": result}}
                            ],
                        }
                    }
                )

        local_messages.append({"role": "user", "content": tool_results})
