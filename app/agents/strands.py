"""
Strands Agents SDK translator (~40 lines).
Same behavior as plain.py — different SDK. Same architectural bugs/fixes.
Talking point: the vuln is in the tools, not the SDK.
"""
import os
from collections.abc import AsyncGenerator
from typing import Any, Callable

try:
    from strands import Agent
    from strands.models import BedrockModel
    STRANDS_AVAILABLE = True
except ImportError:
    STRANDS_AVAILABLE = False


async def run(
    messages: list[dict],
    system_prompt: str,
    tool_schemas: list[dict],
    dispatch_fn: Callable[[str, dict], Any],
    emit_audit: Callable[[str, dict, Any, bool, str, float], None],
) -> AsyncGenerator[dict, None]:
    if not STRANDS_AVAILABLE:
        yield {"type": "text", "delta": "[Strands SDK not installed — pip install strands-agents]"}
        yield {"type": "done"}
        return

    model_id = os.environ.get("BEDROCK_MODEL_ID", "us.anthropic.claude-haiku-4-5-20251001-v1:0")
    region = os.environ.get("AWS_REGION", "us-east-1")

    # Build Strands tools from dispatch_fn + schemas
    strands_tools = _build_strands_tools(tool_schemas, dispatch_fn, emit_audit)

    agent = Agent(
        model=BedrockModel(model_id=model_id, region_name=region),
        system_prompt=system_prompt,
        tools=strands_tools,
    )

    # Strands is synchronous — run in thread to avoid blocking event loop
    import asyncio
    last_user_msg = messages[-1]["content"] if messages else ""
    loop = asyncio.get_event_loop()

    try:
        result = await loop.run_in_executor(None, lambda: agent(last_user_msg))
        response_text = str(result)
        yield {"type": "text", "delta": response_text}
    except Exception as e:
        yield {"type": "text", "delta": f"[Strands error: {e}]"}

    yield {"type": "done"}


def _build_strands_tools(
    tool_schemas: list[dict],
    dispatch_fn: Callable,
    emit_audit: Callable,
) -> list:
    """
    Convert Bedrock-format schemas into Strands @tool decorated functions.
    We do this dynamically so the dispatch logic stays in one place.
    """
    import time

    try:
        from strands import tool as strands_tool
    except ImportError:
        return []

    built = []
    for schema_wrapper in tool_schemas:
        spec = schema_wrapper["toolSpec"]
        tool_name = spec["name"]
        description = spec.get("description", "")

        # Create a closure for each tool
        def make_fn(name):
            def fn(**kwargs):
                start = time.perf_counter()
                result = dispatch_fn(name, kwargs)
                duration_ms = (time.perf_counter() - start) * 1000
                emit_audit(name, kwargs, result, True, "ok (strands)", duration_ms)
                return str(result)
            fn.__name__ = name
            fn.__doc__ = description
            return fn

        tool_fn = strands_tool(make_fn(tool_name))
        built.append(tool_fn)

    return built
