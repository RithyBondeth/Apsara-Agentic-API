"""Tests for context trimming and history event recording."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from apsara_cli.cli.history import (
    SAFE_INPUT_TOKEN_BUDGET,
    group_conversation_turns,
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
    result = trim_history_for_request(history, model="gpt-3.5-turbo")
    assert result.dropped_turns == 0
    assert result.dropped_messages == 0
    assert result.request_history == history


def test_trim_drops_oldest_turns():
    # Build a history large enough to exceed the budget
    # Each turn ~4000 chars → ~1000 tokens; 15 turns → ~15000 tokens > 9000 budget
    big_history = _make_history(15, chars_per_turn=4000)
    result = trim_history_for_request(big_history, model="gpt-3.5-turbo")
    assert result.dropped_turns > 0
    assert result.trimmed_tokens <= SAFE_INPUT_TOKEN_BUDGET
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
