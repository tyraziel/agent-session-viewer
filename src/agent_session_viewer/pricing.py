"""Public token pricing for supported models ($ per million tokens)."""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ModelRates:
    """Rates per million tokens for one context-length tier."""

    input: float
    output: float
    cache_read: float
    cache_write: float


@dataclass(frozen=True)
class ModelPricing(ModelRates):
    """Standard rates, with optional long-context and cache-write tiers."""

    cache_write_1h: float | None = None
    long_context: ModelRates | None = None
    long_context_threshold: int = 272_000

    def rates_for(self, input_tokens: int) -> ModelRates:
        """Choose the applicable rates for a request's full input context."""
        if self.long_context is not None and input_tokens > self.long_context_threshold:
            return self.long_context
        return self


def _claude(
    input: float,
    output: float,
    cache_read: float,
    cache_write: float,
    cache_write_1h: float,
) -> ModelPricing:
    return ModelPricing(input, output, cache_read, cache_write, cache_write_1h)


# Standard API prices per million tokens, from Anthropic's model pricing page.
# Cache writes are 5-minute TTL rates; the separate 1-hour rates are used when
# the transcript includes Anthropic's ephemeral_1h_input_tokens usage field.
_PRICING_TABLE: list[tuple[str, ModelPricing]] = [
    ("claude-fable-5-1", _claude(10.00, 50.00, 0.25, 12.50, 20.00)),
    ("claude-mythos-5-1", _claude(10.00, 50.00, 0.25, 12.50, 20.00)),
    ("claude-fable-5", _claude(10.00, 50.00, 1.00, 12.50, 20.00)),
    ("claude-mythos-5", _claude(10.00, 50.00, 1.00, 12.50, 20.00)),
    ("claude-opus-5-5", _claude(4.00, 20.00, 0.20, 5.00, 8.00)),
    ("claude-opus-5", _claude(5.00, 25.00, 0.50, 6.25, 10.00)),
    ("claude-opus-4-8", _claude(5.00, 25.00, 0.50, 6.25, 10.00)),
    ("claude-opus-4-7", _claude(5.00, 25.00, 0.50, 6.25, 10.00)),
    ("claude-opus-4-6", _claude(5.00, 25.00, 0.50, 6.25, 10.00)),
    ("claude-opus-4-5", _claude(5.00, 25.00, 0.50, 6.25, 10.00)),
    ("claude-opus-4-1", _claude(15.00, 75.00, 1.50, 18.75, 30.00)),
    ("claude-opus-4", _claude(15.00, 75.00, 1.50, 18.75, 30.00)),
    ("claude-sonnet-5", _claude(2.00, 10.00, 0.20, 2.50, 4.00)),
    ("claude-sonnet-4-6", _claude(3.00, 15.00, 0.30, 3.75, 6.00)),
    ("claude-sonnet-4-5", _claude(3.00, 15.00, 0.30, 3.75, 6.00)),
    ("claude-sonnet-4", _claude(3.00, 15.00, 0.30, 3.75, 6.00)),
    ("claude-haiku-4-5", _claude(1.00, 5.00, 0.10, 1.25, 2.00)),
    ("claude-haiku-3-5", _claude(0.80, 4.00, 0.08, 1.00, 1.60)),
    # Legacy/alternate Anthropic model ID ordering.
    ("claude-3-5-haiku", _claude(0.80, 4.00, 0.08, 1.00, 1.60)),
    # Bare shorthand model names reported by some providers use latest pricing.
    ("sonnet", _claude(2.00, 10.00, 0.20, 2.50, 4.00)),
    ("haiku", _claude(1.00, 5.00, 0.10, 1.25, 2.00)),
    ("opus", _claude(4.00, 20.00, 0.20, 5.00, 8.00)),
]


def get_pricing(model: str) -> ModelPricing | None:
    """Return Claude pricing for a model ID or shorthand alias."""
    for prefix, pricing in sorted(
        _PRICING_TABLE, key=lambda item: len(item[0]), reverse=True,
    ):
        if model.startswith(prefix):
            return pricing
    return None


def cost_by_type(pricing: ModelPricing, usage: dict[str, Any]) -> dict[str, float]:
    """Calculate a usage record's cost using its context and cache details."""
    input_tokens = _usage_int(usage.get("input_tokens", 0))
    cache_read_tokens = _usage_int(usage.get("cache_read_input_tokens", 0))
    cache_create_tokens = _usage_int(usage.get("cache_creation_input_tokens", 0))
    rates = pricing.rates_for(
        input_tokens + cache_read_tokens + cache_create_tokens,
    )

    cache_creation = usage.get("cache_creation")
    if isinstance(cache_creation, dict) and (
        "ephemeral_5m_input_tokens" in cache_creation
        or "ephemeral_1h_input_tokens" in cache_creation
    ):
        cache_5m = _usage_int(cache_creation.get("ephemeral_5m_input_tokens", 0))
        cache_1h = _usage_int(cache_creation.get("ephemeral_1h_input_tokens", 0))
        unclassified = max(0, cache_create_tokens - cache_5m - cache_1h)
        cache_write_cost = (
            cache_5m * rates.cache_write
            + cache_1h * (
                pricing.cache_write_1h
                if pricing.cache_write_1h is not None
                else rates.cache_write
            )
            + unclassified * rates.cache_write
        ) / 1_000_000
    else:
        cache_write_cost = cache_create_tokens * rates.cache_write / 1_000_000

    return {
        "input": input_tokens * rates.input / 1_000_000,
        "output": (
            _usage_int(usage.get("output_tokens", 0)) * rates.output / 1_000_000
        ),
        "reasoning": (
            _usage_int(usage.get("reasoning_tokens", 0))
            * rates.output / 1_000_000
        ),
        "cache_read": cache_read_tokens * rates.cache_read / 1_000_000,
        "cache_create": cache_write_cost,
    }


def estimate_usage_cost(model: str, usage: dict[str, Any]) -> dict[str, float]:
    """Estimate usage cost for Claude; unknown models contribute zero."""
    pricing = get_pricing(model)
    if pricing is None:
        return {
            "input": 0.0,
            "output": 0.0,
            "reasoning": 0.0,
            "cache_read": 0.0,
            "cache_create": 0.0,
        }
    return cost_by_type(pricing, usage)


def estimate_cost(
    model: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_read_tokens: int = 0,
    cache_create_tokens: int = 0,
) -> float:
    """Estimate one token category in dollars; unknown model pricing is $0."""
    pricing = get_pricing(model)
    if pricing is None:
        return 0.0
    rates = pricing.rates_for(input_tokens + cache_read_tokens + cache_create_tokens)
    return (
        input_tokens * rates.input
        + output_tokens * rates.output
        + cache_read_tokens * rates.cache_read
        + cache_create_tokens * rates.cache_write
    ) / 1_000_000


def _usage_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0
