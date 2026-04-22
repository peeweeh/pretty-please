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
    # Extract plain text from message content (may be list [{text:...}] or str)
    raw = messages[-1]["content"] if messages else ""
    if isinstance(raw, list):
        last_user_msg = " ".join(block.get("text", "") for block in raw if isinstance(block, dict))
    else:
        last_user_msg = str(raw)
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
    Uses exec() to generate functions with the exact parameter names+types
    that @strands.tool (and the underlying LLM) need to introspect correctly.
    Without proper signatures, Strands produces incomplete schemas and Haiku
    never calls the tools.
    """
    import time as _time

    try:
        from strands import tool as strands_tool
    except ImportError:
        return []

    built = []
    for schema_wrapper in tool_schemas:
        spec = schema_wrapper["toolSpec"]
        tool_name = spec["name"]
        description = spec.get("description", "no description")
        properties = spec.get("inputSchema", {}).get("json", {}).get("properties", {})
        param_names = list(properties.keys())

        # Build a properly-annotated function so strands can generate a correct schema.
        # All params typed as str — Bedrock/Haiku will coerce numerics anyway.
        param_sig  = ", ".join(f"{p}: str = ''" for p in param_names)
        kwargs_dict = "{" + ", ".join(f'"{p}": {p}' for p in param_names) + "}"

        src = f"""
def {tool_name}({param_sig}):
    '''{description}'''
    start = _time.perf_counter()
    # Coerce numeric-looking strings to int for tool dispatch
    kwargs = {{}}
    for k, v in {kwargs_dict}.items():
        try:
            kwargs[k] = int(v) if str(v).lstrip('-').isdigit() else v
        except (ValueError, TypeError):
            kwargs[k] = v
    result = _dispatch("{tool_name}", kwargs)
    duration_ms = (_time.perf_counter() - start) * 1000
    _emit("{tool_name}", kwargs, result, True, "ok (strands)", duration_ms)
    return str(result)
"""
        globs = {"_time": _time, "_dispatch": dispatch_fn, "_emit": emit_audit}
        exec(src, globs)  # noqa: S102 — demo-only dynamic tool generation
        fn = globs[tool_name]
        built.append(strands_tool(fn))

    return built
