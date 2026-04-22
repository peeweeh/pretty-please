"""
Ollama tool-use loop (~80 lines). Offline fallback.
Uses qwen2.5:7b by default. Falls back to llama3.1:8b if tool use is flaky.
"""

import json
import os
import time
from collections.abc import AsyncGenerator
from typing import Any, Callable

try:
    import ollama as ollama_client

    OLLAMA_AVAILABLE = True
except ImportError:
    OLLAMA_AVAILABLE = False


async def run(
    messages: list[dict],
    system_prompt: str,
    tool_schemas: list[dict],
    dispatch_fn: Callable[[str, dict], Any],
    emit_audit: Callable[[str, dict, Any, bool, str, float], None],
) -> AsyncGenerator[dict, None]:
    if not OLLAMA_AVAILABLE:
        yield {"type": "text", "delta": "[Ollama not installed — pip install ollama]"}
        yield {"type": "done"}
        return

    model = os.environ.get("OLLAMA_MODEL", "qwen2.5:7b")
    host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
    client = ollama_client.Client(host=host)

    # Convert Bedrock schemas → Ollama tool format
    ollama_tools = _to_ollama_tools(tool_schemas)

    local_messages = [
        {"role": "system", "content": system_prompt},
        *messages,
    ]

    max_turns = 10
    for _ in range(max_turns):
        try:
            resp = client.chat(
                model=model,
                messages=local_messages,
                tools=ollama_tools,
            )
        except Exception as e:
            yield {"type": "text", "delta": f"[Ollama error: {e}]"}
            break

        msg = resp["message"]
        local_messages.append(msg)

        tool_calls = msg.get("tool_calls") or []
        if not tool_calls:
            # Final response
            content = msg.get("content", "")
            if content:
                yield {"type": "text", "delta": content}
            break

        # Execute tool calls
        for call in tool_calls:
            fn = call.get("function", {})
            tool_name = fn.get("name", "")
            tool_args = fn.get("arguments", {})
            if isinstance(tool_args, str):
                try:
                    tool_args = json.loads(tool_args)
                except json.JSONDecodeError:
                    tool_args = {}

            start = time.perf_counter()
            result = dispatch_fn(tool_name, tool_args)
            duration_ms = (time.perf_counter() - start) * 1000
            emit_audit(tool_name, tool_args, result, True, "ok (ollama)", duration_ms)

            local_messages.append(
                {
                    "role": "tool",
                    "name": tool_name,
                    "content": json.dumps(result),
                }
            )

    yield {"type": "done"}


def _to_ollama_tools(tool_schemas: list[dict]) -> list[dict]:
    """Convert Bedrock toolSpec format to Ollama's function format."""
    tools = []
    for wrapper in tool_schemas:
        spec = wrapper["toolSpec"]
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": spec["name"],
                    "description": spec.get("description", ""),
                    "parameters": spec.get("inputSchema", {}).get("json", {}),
                },
            }
        )
    return tools
