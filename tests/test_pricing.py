import json
from datetime import datetime, timezone

from apsara_cli.engine import pricing


def test_big_pickle_and_local_models_are_zero_cost(monkeypatch):
    monkeypatch.setattr(pricing, "_promotion_is_current", lambda _verified: True)
    for model in ("opencode/big-pickle", "ollama/llama3.2"):
        prices, _source = pricing.pricing_for_model(model)
        assert prices == {
            "input": 0.0, "output": 0.0, "cache_read": 0.0, "cache_write": 0.0,
        }


def test_big_pickle_zero_cost_is_explicitly_temporary(monkeypatch):
    monkeypatch.setattr(pricing, "_promotion_is_current", lambda _verified: True)
    _prices, source = pricing.pricing_for_model("opencode/big-pickle")
    assert source.startswith("temporary provider promotion")


def test_stale_promotion_does_not_claim_zero_forever(monkeypatch, tmp_path):
    monkeypatch.setattr(pricing, "_promotion_is_current", lambda _verified: False)
    monkeypatch.setenv("APSARA_PRICING_CACHE", str(tmp_path / "missing.json"))

    prices, source = pricing.pricing_for_model("opencode/big-pickle")

    assert prices is None
    assert source == "temporary promotion requires re-verification"


def test_stale_promotion_ignores_bundled_zero_price(monkeypatch):
    monkeypatch.setattr(pricing, "_promotion_is_current", lambda _verified: False)
    monkeypatch.setattr(pricing, "_model_map", lambda: ({
        "opencode/big-pickle": {
            "input_cost_per_token": 0,
            "output_cost_per_token": 0,
        }
    }, "bundled LiteLLM pricing"))

    prices, source = pricing.pricing_for_model("opencode/big-pickle")

    assert prices is None
    assert source == "temporary promotion requires re-verification"


def test_invalid_cached_prices_fail_closed(monkeypatch, tmp_path):
    path = tmp_path / "pricing.json"
    monkeypatch.setenv("APSARA_PRICING_CACHE", str(path))
    path.write_text(json.dumps({
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "models": {
            "gpt-4o": {
                "input_cost_per_token": -1,
                "output_cost_per_token": "nan",
            }
        },
    }), encoding="utf-8")

    prices, source = pricing.pricing_for_model("gpt-4o")

    assert prices is None
    assert source == "pricing incomplete"


def test_registry_snapshot_covers_deprecated_paid_models(monkeypatch, tmp_path):
    monkeypatch.setenv("APSARA_PRICING_CACHE", str(tmp_path / "missing.json"))
    prices, source = pricing.pricing_for_model(
        "anthropic/claude-3-5-sonnet-20241022"
    )
    assert prices["input"] == 3.0 / 1_000_000
    assert prices["output"] == 15.0 / 1_000_000
    assert prices["cache_read"] == 0.30 / 1_000_000
    assert prices["cache_write"] == 3.75 / 1_000_000
    assert source == "Apsara registry pricing snapshot"


def test_cached_pricing_handles_cache_read_and_write(monkeypatch, tmp_path):
    path = tmp_path / "pricing.json"
    monkeypatch.setenv("APSARA_PRICING_CACHE", str(path))
    path.write_text(json.dumps({
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "models": {
            "gpt-4o": {
                "input_cost_per_token": 1.0,
                "output_cost_per_token": 10.0,
                "cache_read_input_token_cost": 0.5,
                "cache_creation_input_token_cost": 2.0,
            }
        },
    }), encoding="utf-8")

    cost = pricing.usage_cost("gpt-4o", {
        "prompt_tokens": 100,
        "completion_tokens": 10,
        "cached_tokens": 20,
        "cache_creation_tokens": 30,
    })
    assert cost == 20 * 0.5 + 30 * 2.0 + 50 * 1.0 + 10 * 10.0


def test_refresh_writes_validated_cache(monkeypatch, tmp_path):
    path = tmp_path / "pricing.json"
    monkeypatch.setenv("APSARA_PRICING_CACHE", str(path))
    models = {
        f"provider/model-{index}": {
            "input_cost_per_token": 1e-6,
            "output_cost_per_token": 2e-6,
        }
        for index in range(101)
    }

    class Response:
        status_code = 200
        headers = {"etag": "abc"}
        def raise_for_status(self): pass
        def json(self): return models

    monkeypatch.setattr(pricing.httpx, "get", lambda *args, **kwargs: Response())
    assert pricing.refresh_pricing(force=True) is True
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["models"] == models
    assert payload["source"] == pricing.PRICING_URL
