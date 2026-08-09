"""Refreshable model pricing backed by LiteLLM's public cost map."""

from __future__ import annotations

import json
import math
import os
import tempfile
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import httpx
import litellm


PRICING_URL = (
    "https://raw.githubusercontent.com/BerriAI/litellm/main/"
    "model_prices_and_context_window.json"
)
REFRESH_INTERVAL = timedelta(hours=24)
PROMOTION_VERIFICATION_MAX_AGE = timedelta(days=30)
_MEMORY_CACHE_KEY: tuple[str, int] | None = None
_MEMORY_CACHE_PAYLOAD: dict[str, Any] = {}


def pricing_cache_path() -> Path:
    override = os.environ.get("APSARA_PRICING_CACHE")
    return Path(override).expanduser() if override else Path.home() / ".apsara" / "pricing.json"


def _read_cache() -> dict[str, Any]:
    global _MEMORY_CACHE_KEY, _MEMORY_CACHE_PAYLOAD
    path = pricing_cache_path()
    try:
        cache_key = (str(path), path.stat().st_mtime_ns)
        if cache_key == _MEMORY_CACHE_KEY:
            return _MEMORY_CACHE_PAYLOAD
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return {}
        _MEMORY_CACHE_KEY = cache_key
        _MEMORY_CACHE_PAYLOAD = payload
        return payload
    except (OSError, ValueError, TypeError):
        return {}


def _cache_is_fresh(payload: dict[str, Any]) -> bool:
    try:
        fetched = datetime.fromisoformat(str(payload["fetched_at"]))
        if fetched.tzinfo is None:
            fetched = fetched.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) - fetched < REFRESH_INTERVAL
    except (KeyError, TypeError, ValueError):
        return False


def refresh_pricing(*, force: bool = False, timeout: float = 4.0) -> bool:
    """Refresh the public cost map. Fail closed and retain the prior cache."""
    global _MEMORY_CACHE_KEY
    current = _read_cache()
    if not force and _cache_is_fresh(current):
        return False
    headers = {"Accept": "application/json", "User-Agent": "apsara-agentic-cli"}
    etag = current.get("etag")
    if etag:
        headers["If-None-Match"] = str(etag)
    response = httpx.get(PRICING_URL, headers=headers, timeout=timeout, follow_redirects=True)
    if response.status_code == 304:
        current["fetched_at"] = datetime.now(timezone.utc).isoformat()
        models = current.get("models")
    else:
        response.raise_for_status()
        models = response.json()
        if not isinstance(models, dict) or len(models) < 100:
            raise ValueError("Pricing response did not contain a valid model map")
        current = {
            "schema_version": 1,
            "source": PRICING_URL,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "etag": response.headers.get("etag"),
            "models": models,
        }
    if not isinstance(models, dict):
        raise ValueError("Cached pricing model map is invalid")
    path = pricing_cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent,
        prefix="pricing-", suffix=".tmp", delete=False,
    ) as handle:
        json.dump(current, handle, separators=(",", ":"))
        temporary = Path(handle.name)
    temporary.replace(path)
    _MEMORY_CACHE_KEY = None
    return True


def refresh_pricing_if_stale() -> None:
    """Refresh stale metadata without delaying CLI startup."""
    if _cache_is_fresh(_read_cache()):
        return

    def _worker() -> None:
        try:
            refresh_pricing()
        except Exception:
            pass

    threading.Thread(target=_worker, name="apsara-pricing-refresh", daemon=True).start()


def _model_map() -> tuple[dict[str, Any], str]:
    cached = _read_cache().get("models")
    if isinstance(cached, dict):
        return cached, "refreshed LiteLLM pricing"
    return litellm.model_cost, "bundled LiteLLM pricing"


def _promotion_is_current(verified_on: Optional[str]) -> bool:
    try:
        verified = datetime.fromisoformat(str(verified_on)).date()
        age = datetime.now(timezone.utc).date() - verified
        return timedelta(0) <= age <= PROMOTION_VERIFICATION_MAX_AGE
    except (TypeError, ValueError):
        return False


def _valid_price(value: Any) -> Optional[float]:
    try:
        price = float(value)
    except (TypeError, ValueError):
        return None
    return price if math.isfinite(price) and price >= 0 else None


def pricing_for_model(model: str) -> tuple[Optional[dict[str, float]], str]:
    """Return per-token prices plus their source, or (None, reason)."""
    from apsara_cli.engine.models import lookup_model, resolve_model_id

    entry = lookup_model(model)
    if entry and entry.tier == "local":
        return {
            "input": 0.0, "output": 0.0, "cache_read": 0.0, "cache_write": 0.0,
        }, "local model"
    promotion_current = bool(
        entry
        and entry.promotional_pricing
        and entry.input_cost_per_million == 0
        and entry.output_cost_per_million == 0
        and _promotion_is_current(entry.pricing_verified_on)
    )
    if promotion_current:
        return {
            "input": 0.0, "output": 0.0, "cache_read": 0.0, "cache_write": 0.0,
        }, f"temporary provider promotion (verified {entry.pricing_verified_on})"
    if (
        entry
        and not entry.promotional_pricing
        and entry.input_cost_per_million == 0
        and entry.output_cost_per_million == 0
    ):
        return {
            "input": 0.0, "output": 0.0, "cache_read": 0.0, "cache_write": 0.0,
        }, "Apsara model registry"

    model_map, source = _model_map()
    if (
        entry
        and entry.promotional_pricing
        and not promotion_current
        and (source != "refreshed LiteLLM pricing" or not _cache_is_fresh(_read_cache()))
    ):
        # A bundled or stale cost map must not extend a temporary zero-price
        # claim beyond the separately verified promotion window.
        return None, "temporary promotion requires re-verification"
    canonical = resolve_model_id(model)
    candidates = [canonical, model]
    if canonical.startswith("anthropic/"):
        candidates.append(canonical.removeprefix("anthropic/"))
    info = next((model_map.get(name) for name in candidates if isinstance(model_map.get(name), dict)), None)
    if not info:
        if entry and entry.promotional_pricing:
            return None, "temporary promotion requires re-verification"
        if entry and entry.input_cost_per_million is not None and entry.output_cost_per_million is not None:
            return {
                "input": entry.input_cost_per_million / 1_000_000,
                "output": entry.output_cost_per_million / 1_000_000,
                "cache_read": (
                    entry.cache_read_cost_per_million
                    if entry.cache_read_cost_per_million is not None
                    else entry.input_cost_per_million
                ) / 1_000_000,
                "cache_write": (
                    entry.cache_write_cost_per_million
                    if entry.cache_write_cost_per_million is not None
                    else entry.input_cost_per_million
                ) / 1_000_000,
            }, "Apsara registry pricing snapshot"
        return None, "pricing unavailable"
    input_cost = _valid_price(info.get("input_cost_per_token"))
    output_cost = _valid_price(info.get("output_cost_per_token"))
    if input_cost is None or output_cost is None:
        return None, "pricing incomplete"
    cache_read = _valid_price(info.get("cache_read_input_token_cost", input_cost))
    cache_write = _valid_price(info.get("cache_creation_input_token_cost", input_cost))
    if cache_read is None or cache_write is None:
        return None, "pricing incomplete"
    return {
        "input": input_cost,
        "output": output_cost,
        "cache_read": cache_read,
        "cache_write": cache_write,
    }, source


def usage_cost(model: str, usage: dict[str, Any]) -> Optional[float]:
    from apsara_cli.engine.usage import normalize_usage

    prices, _source = pricing_for_model(model)
    if prices is None:
        return None
    data = normalize_usage(usage)
    cached = min(data["cached_tokens"], data["prompt_tokens"])
    cache_creation = min(
        data["cache_creation_tokens"], max(0, data["prompt_tokens"] - cached)
    )
    uncached = max(0, data["prompt_tokens"] - cached - cache_creation)
    return (
        uncached * prices["input"]
        + cached * prices["cache_read"]
        + cache_creation * prices["cache_write"]
        + data["completion_tokens"] * prices["output"]
    )
