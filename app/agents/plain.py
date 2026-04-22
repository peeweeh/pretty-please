"""
Plain Bedrock Converse tool-use loop (~100 lines).
Raw boto3 — no SDK abstractions. Readable on a slide.
"""
import json
import os
import time
from collections.abc import AsyncGenerator
from typing import Any, Callable

import boto3

_bedrock = None


def _client():
    global _bedrock
    if _bedrock is None:
        _bedrock = boto3.client(
            "bedrock-runtime",
            region_name=os.environ.get("AWS_REGION", "us-east-1"),
        )
    return _bedrock


async def run(
    messages: list[dict],
    system_prompt: str,
    tool_schemas: list[dict],
    dispatch_fn: Callable[[str, dict], Any],
    emit_audit: Callable[[str, dict, Any, bool, str, float], None],
) -> AsyncGenerator[dict, None]:
    """
    Async generator yielding SSE-friendly events:
      {"type": "text", "delta": "..."}
      {"type": "tokens", "input": N, "output": N}
      {"type": "done"}
    """
    model_id = os.environ.get("BEDROCK_MODEL_ID", "us.anthropic.claude-haiku-4-5-20251001-v1:0")
    local_messages = list(messages)

    while True:
        resp = _client().converse(
            modelId=model_id,
            messages=local_messages,
            system=[{"text": system_prompt}],
            toolConfig={"tools": tool_schemas},
        )

        usage = resp.get("usage", {})
        yield {
            "type": "tokens",
            "input": usage.get("inputTokens", 0),
            "output": usage.get("outputTokens", 0),
        }

        msg = resp["output"]["message"]
        local_messages.append(msg)

        if resp["stopReason"] == "end_turn":
            # Emit final text
            for block in msg.get("content", []):
                if "text" in block:
                    yield {"type": "text", "delta": block["text"]}
            yield {"type": "done"}
            return

        # Handle tool use
        text_so_far = ""
        tool_results = []
        for block in msg.get("content", []):
            if "text" in block:
                text_so_far += block["text"]
                yield {"type": "text", "delta": block["text"]}
            elif "toolUse" in block:
                tu = block["toolUse"]
                tool_name = tu["name"]
                tool_args = tu.get("input", {})

                start = time.perf_counter()
                result = dispatch_fn(tool_name, tool_args)
                duration_ms = (time.perf_counter() - start) * 1000

                emit_audit(tool_name, tool_args, result, True, "ok", duration_ms)

                tool_results.append({
                    "toolResult": {
                        "toolUseId": tu["toolUseId"],
                        "content": [{"json": result}],
                    }
                })

        local_messages.append({"role": "user", "content": tool_results})
