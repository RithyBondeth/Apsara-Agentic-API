"""Tests for context trimming and history event recording."""
import asyncio
import sys
import os
from unittest.mock import patch
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from apsara_cli.cli.history import (
    FALLBACK_INPUT_TOKEN_BUDGET,
    MAX_INPUT_TOKEN_BUDGET,
    MIN_INPUT_TOKEN_BUDGET,
    group_conversation_turns,
    input_token_budget,
    model_context_window,
    trim_history_for_request,
    update_history_from_event,
)


def _make_history(n_turns: int, chars_per_turn: int = 20) -> list[dict]:
    history = []
    for i in range(n_turns):
        history.append({"role": "user", "content": "x" * chars_per_turn})
        history.append({"role": "assistant", "content": "y" * chars_per_turn})
    return history


def test_group_turns_empty():
    assert group_conversation_turns([]) == []


def test_group_turns_single():
    history = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]
    turns = group_conversation_turns(history)
    assert len(turns) == 1
    assert turns[0] == history


def test_group_turns_multiple():
    history = _make_history(3)
    turns = group_conversation_turns(history)
    assert len(turns) == 3
    for turn in turns:
        assert turn[0]["role"] == "user"
        assert turn[1]["role"] == "assistant"


def test_trim_short_history_unchanged():
    history = _make_history(2)
    result = asyncio.run(trim_history_for_request(history, model="gpt-3.5-turbo"))
    assert result.dropped_turns == 0
    assert result.dropped_messages == 0
    assert result.request_history == history


async def _fake_summarize(messages, model="gpt-3.5-turbo"):
    return "earlier conversation summary"


def test_trim_drops_oldest_turns():
    # Build a history large enough to exceed the budget
    # Each turn ~4000 chars → ~1000 tokens; 15 turns → ~15000 tokens > 9000 budget
    big_history = _make_history(15, chars_per_turn=4000)
    # Patch the summarizer so trimming stays offline (no LLM/network call).
    with patch("apsara_cli.engine.llm.summarize_messages", _fake_summarize):
        result = asyncio.run(trim_history_for_request(big_history, model="gpt-3.5-turbo"))
    assert result.dropped_turns > 0
    assert result.trimmed_tokens <= input_token_budget("gpt-3.5-turbo")
    # The kept history should end with the most recent turn
    assert result.request_history[-1]["role"] == "assistant"
    assert result.request_history[-2]["role"] == "user"


def test_update_history_final_answer():
    history = []
    update_history_from_event(history, {"type": "final_answer", "content": "done"})
    assert len(history) == 1
    assert history[0] == {"role": "assistant", "content": "done"}


def test_update_history_response_end():
    history = []
    update_history_from_event(history, {"type": "response_end", "content": "streamed"})
    assert len(history) == 1
    assert history[0]["role"] == "assistant"
    assert history[0]["content"] == "streamed"


def test_update_history_tool_result():
    history = []
    update_history_from_event(history, {
        "type": "tool_result",
        "name": "read_file",
        "tool_call_id": "call_1",
        "result": "file contents",
    })
    assert history[0]["role"] == "tool"
    assert history[0]["content"] == "file contents"
    assert history[0]["tool_call_id"] == "call_1"


def test_update_history_ignores_unknown():
    history = []
    update_history_from_event(history, {"type": "status", "message": "thinking"})
    assert history == []


# ── context budget sizing ─────────────────────────────────────────────────────

def test_registry_models_get_a_window_scaled_budget():
    """A 200k-window model must not be driven at the 9k fallback."""
    budget = input_token_budget("anthropic/claude-3-5-sonnet-20241022")
    assert budget > FALLBACK_INPUT_TOKEN_BUDGET * 5
    assert budget <= MAX_INPUT_TOKEN_BUDGET


def test_budget_never_exceeds_the_window():
    from apsara_cli.engine.models import MODELS

    for entry in MODELS:
        budget = input_token_budget(entry.model_id)
        assert budget < entry.context_window, (
            f"{entry.model_id}: budget {budget} >= window {entry.context_window}"
        )


def test_smaller_windows_get_smaller_budgets():
    small = input_token_budget("ollama/qwen2.5-coder:7b")   # 32k window
    large = input_token_budget("anthropic/claude-3-5-sonnet-20241022")  # 200k window
    assert small < large


def test_huge_windows_are_capped():
    """A 2M-token request would be slow and expensive on the user's own key."""
    assert input_token_budget("gemini/gemini-1.5-pro") == MAX_INPUT_TOKEN_BUDGET


def test_unknown_model_falls_back_conservatively():
    assert input_token_budget("nonexistent/model-xyz") == FALLBACK_INPUT_TOKEN_BUDGET


def test_litellm_known_models_are_recognised():
    """Models routable through LiteLLM but absent from our registry."""
    assert model_context_window("gpt-4o-mini")
    assert input_token_budget("gpt-4o-mini") > FALLBACK_INPUT_TOKEN_BUDGET


def test_env_override_wins(monkeypatch):
    monkeypatch.setenv("APSARA_INPUT_TOKEN_BUDGET", "25000")
    assert input_token_budget("anthropic/claude-3-5-sonnet-20241022") == 25_000
    assert input_token_budget("nonexistent/model-xyz") == 25_000


def test_env_override_is_floored(monkeypatch):
    monkeypatch.setenv("APSARA_INPUT_TOKEN_BUDGET", "10")
    assert input_token_budget("gpt-4o") == MIN_INPUT_TOKEN_BUDGET


def test_garbage_env_override_is_ignored(monkeypatch):
    monkeypatch.setenv("APSARA_INPUT_TOKEN_BUDGET", "lots")
    assert input_token_budget("gpt-4o") == input_token_budget("gpt-4o")
    assert input_token_budget("nonexistent/model-xyz") == FALLBACK_INPUT_TOKEN_BUDGET


def test_window_lookup_prefers_the_registry():
    from apsara_cli.engine.models import lookup_model

    entry = lookup_model("gpt-4o")
    assert entry is not None
    assert model_context_window("gpt-4o") == entry.context_window


def test_large_context_model_keeps_history_that_used_to_be_trimmed():
    """The regression this fixes: a mid-size conversation surviving intact."""
    # ~15 turns x 4000 chars ~= 15k tokens: over the old 9k budget, well under
    # what a 200k-window model can hold.
    history = _make_history(15, chars_per_turn=4000)
    with patch("apsara_cli.engine.llm.summarize_messages", _fake_summarize):
        result = asyncio.run(
            trim_history_for_request(history, model="anthropic/claude-3-5-sonnet-20241022")
        )
    assert result.dropped_turns == 0, "should no longer need to drop turns"
    assert result.request_history == history
