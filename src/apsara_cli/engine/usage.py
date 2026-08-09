"""Provider-neutral token usage normalization and aggregation."""

from __future__ import annotations

from typing import Any


TOKEN_FIELDS = (
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
    "cached_tokens",
    "cache_creation_tokens",
    "reasoning_tokens",
)

USAGE_COUNTER_FIELDS = TOKEN_FIELDS + (
    "estimated_input_tokens",
    "provider_reported_calls",
    "unreported_calls",
    "interrupted_calls",
    "auxiliary_calls",
)


def _integer(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def normalize_usage(data: dict[str, Any]) -> dict[str, Any]:
    """Normalize common OpenAI, Anthropic, and LiteLLM usage shapes."""
    prompt_details = data.get("prompt_tokens_details") or {}
    completion_details = data.get("completion_tokens_details") or {}
    if not isinstance(prompt_details, dict):
        prompt_details = {}
    if not isinstance(completion_details, dict):
        completion_details = {}

    prompt = _integer(data.get("prompt_tokens") or data.get("input_tokens"))
    completion = _integer(data.get("completion_tokens") or data.get("output_tokens"))
    normalized: dict[str, Any] = {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": _integer(data.get("total_tokens")) or prompt + completion,
        "cached_tokens": _integer(
            data.get("cache_read_input_tokens")
            or data.get("cached_tokens")
            or prompt_details.get("cached_tokens")
        ),
        "cache_creation_tokens": _integer(
            data.get("cache_creation_input_tokens")
            or data.get("cache_creation_tokens")
        ),
        "reasoning_tokens": _integer(
            data.get("reasoning_tokens")
            or completion_details.get("reasoning_tokens")
        ),
        # Estimated input is deliberately separate from provider-reported
        # totals: mixing them would make local telemetry look like billing.
        "estimated_input_tokens": _integer(
            data.get("estimated_input_tokens") or data.get("estimated_tokens")
        ),
        "provider_reported_calls": _integer(data.get("provider_reported_calls")),
        "unreported_calls": _integer(data.get("unreported_calls")),
        "interrupted_calls": _integer(data.get("interrupted_calls")),
        "auxiliary_calls": _integer(data.get("auxiliary_calls")),
    }
    if data.get("apsara_model"):
        normalized["apsara_model"] = str(data["apsara_model"])
    if isinstance(data.get("rate_limits"), dict):
        normalized["rate_limits"] = dict(data["rate_limits"])
    return normalized


def add_usage(target: dict[str, Any], source: dict[str, Any]) -> None:
    """Add normalized token counters into *target* in place."""
    normalized = normalize_usage(source)
    for field in USAGE_COUNTER_FIELDS:
        target[field] = _integer(target.get(field)) + _integer(normalized.get(field))
    if normalized.get("rate_limits"):
        target["rate_limits"] = normalized["rate_limits"]
