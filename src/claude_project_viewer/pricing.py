"""Token pricing for Claude models ($ per million tokens)."""

from dataclasses import dataclass


@dataclass
class ModelPricing:
    input: float
    output: float
    cache_read: float
    cache_write: float


# Prices per million tokens. Prefix-matched against model strings.
# Order matters: longer prefixes checked first.
_PRICING_TABLE: list[tuple[str, ModelPricing]] = [
    ("claude-fable-5", ModelPricing(10.00, 50.00, 1.00, 12.50)),
    ("claude-opus-5", ModelPricing(5.00, 25.00, 0.50, 6.25)),
    ("claude-opus-4", ModelPricing(5.00, 25.00, 0.50, 6.25)),
    ("claude-sonnet-5", ModelPricing(3.00, 15.00, 0.30, 3.75)),
    ("claude-sonnet-4", ModelPricing(3.00, 15.00, 0.30, 3.75)),
    ("claude-haiku-4", ModelPricing(1.00, 5.00, 0.10, 1.25)),
    ("claude-haiku-3", ModelPricing(0.25, 1.25, 0.03, 0.30)),
    ("sonnet", ModelPricing(3.00, 15.00, 0.30, 3.75)),
    ("haiku", ModelPricing(1.00, 5.00, 0.10, 1.25)),
    ("opus", ModelPricing(5.00, 25.00, 0.50, 6.25)),
]


def get_pricing(model: str) -> ModelPricing | None:
    for prefix, pricing in _PRICING_TABLE:
        if model.startswith(prefix):
            return pricing
    return None


def estimate_cost(
    model: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_read_tokens: int = 0,
    cache_create_tokens: int = 0,
) -> float | None:
    """Estimate cost in dollars. Returns 0.0 if model pricing unknown."""
    pricing = get_pricing(model)
    if pricing is None:
        return 0.0
    return (
        input_tokens * pricing.input
        + output_tokens * pricing.output
        + cache_read_tokens * pricing.cache_read
        + cache_create_tokens * pricing.cache_write
    ) / 1_000_000
