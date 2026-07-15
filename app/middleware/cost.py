"""
CostCalculator — Bedrock per-token pricing.
Prices per 1K tokens in USD. Last checked: Nov 2025.
"""

# (input_per_1k, output_per_1k) USD
BEDROCK_PRICING: dict[str, tuple[float, float]] = {
    # Anthropic Claude
    "claude-haiku-4-5": (0.001, 0.005),
    "claude-sonnet-4-5": (0.003, 0.015),
    "claude-3-5-haiku": (0.0008, 0.004),
    "claude-3-5-sonnet": (0.003, 0.015),
    # Amazon Nova
    "nova-lite": (0.00006, 0.00024),
    "nova-pro": (0.0008, 0.0032),
    "nova-micro": (0.000035, 0.00014),
    # Meta Llama
    "llama-3-3-70b": (0.00072, 0.00072),
}


def _model_key(model_id: str) -> str:
    """Normalise a Bedrock model ID to a pricing key."""
    m = model_id.lower()
    if "claude-haiku-4-5" in m:
        return "claude-haiku-4-5"
    if "claude-sonnet-4-5" in m:
        return "claude-sonnet-4-5"
    if "claude-3-5-haiku" in m:
        return "claude-3-5-haiku"
    if "claude-3-5-sonnet" in m:
        return "claude-3-5-sonnet"
    if "nova-lite" in m:
        return "nova-lite"
    if "nova-pro" in m:
        return "nova-pro"
    if "nova-micro" in m:
        return "nova-micro"
    if "llama-3-3-70b" in m:
        return "llama-3-3-70b"
    return "claude-haiku-4-5"  # safe default


def calculate(model_id: str, input_tokens: int, output_tokens: int) -> float:
    key = _model_key(model_id)
    in_rate, out_rate = BEDROCK_PRICING.get(key, BEDROCK_PRICING["claude-haiku-4-5"])
    return round(
        (input_tokens / 1000.0) * in_rate + (output_tokens / 1000.0) * out_rate,
        8,
    )
