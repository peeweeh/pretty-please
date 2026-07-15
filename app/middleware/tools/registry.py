"""
ToolRegistry — @tool decorator + discovery.

The "two-step gotcha" worth remembering lives here:
registering a function via @tool is NOT enough — the prompt's tool_ids
list in DynamoDB/SQLite controls which tools actually get offered to
the model at runtime. That's a feature, not a bug — it lets the same
registry serve many products with different tool surfaces.
"""

import inspect
from dataclasses import dataclass
from typing import Any, Callable, Optional

from ..context import AIContext


@dataclass
class ToolSpec:
    name: str
    description: str
    input_schema: dict
    fn: Callable
    source: str = ""  # file path where the @tool decorator fired


_REGISTRY: dict[str, ToolSpec] = {}


def tool(description: str, input_schema: Optional[dict] = None):
    """Decorator that registers a function as a callable tool."""

    def decorator(fn: Callable):
        spec = ToolSpec(
            name=fn.__name__,
            description=description,
            input_schema=input_schema or {"type": "object", "properties": {}},
            fn=fn,
            source=getattr(fn, "__module__", ""),
        )
        _REGISTRY[fn.__name__] = spec
        return fn

    return decorator


def list_all() -> list[str]:
    return sorted(_REGISTRY.keys())


def get(name: str) -> Optional[ToolSpec]:
    return _REGISTRY.get(name)


def resolve_for_prompt(tool_ids: list[str]) -> list[ToolSpec]:
    """Return only the tools the prompt was configured to use."""
    return [_REGISTRY[tid] for tid in tool_ids if tid in _REGISTRY]


def to_bedrock_schemas(specs: list[ToolSpec]) -> list[dict]:
    """Convert ToolSpecs to Bedrock Converse toolConfig format."""
    return [
        {
            "toolSpec": {
                "name": s.name,
                "description": s.description,
                "inputSchema": {"json": s.input_schema},
            }
        }
        for s in specs
    ]


def invoke(name: str, tool_input: dict, ctx: AIContext) -> Any:
    """Call a registered tool with the AIContext in scope."""
    spec = _REGISTRY.get(name)
    if not spec:
        return {"error": f"unknown tool: {name}"}
    sig = inspect.signature(spec.fn)
    kwargs = dict(tool_input)
    if "ctx" in sig.parameters:
        kwargs["ctx"] = ctx
    try:
        return spec.fn(**kwargs)
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}
