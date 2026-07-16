"""Tests for the core agent execution loop (engine/executor.py).

These are fully offline: the LLM stream and tool execution are patched, so we
exercise the loop's control flow (tool dispatch, final-answer handling, error
abort, and loop/stuck detection) without any network or real tool side effects.
"""
import asyncio
import json
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from apsara_cli.engine import executor


def _scripted_llm(scripts):
    """Return a fake call_llm_stream that yields each script's events per call.

    `scripts` is a list of event-lists; call N replays scripts[N] (the last
    script repeats if the loop makes more calls than scripts provided).
    """
    state = {"calls": 0}

    async def _fake(messages, model):
        idx = min(state["calls"], len(scripts) - 1)
        state["calls"] += 1
        for event in scripts[idx]:
            yield event

    return _fake, state


def _run(conversation):
    """Drive run_agent_stream to completion, returning parsed event dicts."""
    async def _collect():
        return [json.loads(chunk) async for chunk in executor.run_agent_stream(conversation)]

    return asyncio.run(_collect())


def _tool_call_event(content="", name="read_file", arguments='{"path": "a.txt"}', call_id="c1", usage=None):
    return {
        "type": "stream_done",
        "content": content,
        "tool_calls": [{
            "id": call_id,
            "type": "function",
            "function": {"name": name, "arguments": arguments},
        }],
        "usage": usage or {},
    }


def _final_event(content="All done.", usage=None):
    return {"type": "stream_done", "content": content, "tool_calls": None, "usage": usage or {}}


def test_direct_final_answer():
    fake, _ = _scripted_llm([[_final_event("The answer is 42.")]])
    with patch.object(executor, "call_llm_stream", fake):
        events = _run([{"role": "user", "content": "hi"}])

    types = [e["type"] for e in events]
    assert "final_answer" in types
    final = next(e for e in events if e["type"] == "final_answer")
    assert final["content"] == "The answer is 42."


def test_streamed_text_emits_response_end_not_final_answer():
    script = [
        {"type": "text_chunk", "content": "Think"},
        {"type": "text_chunk", "content": "ing..."},
        _final_event("Thinking..."),
    ]
    fake, _ = _scripted_llm([script])
    with patch.object(executor, "call_llm_stream", fake):
        events = _run([{"role": "user", "content": "hi"}])

    types = [e["type"] for e in events]
    assert "response_start" in types
    assert types.count("text_chunk") == 2
    assert "response_end" in types
    assert "final_answer" not in types


def test_tool_call_then_final_answer():
    scripts = [[_tool_call_event(usage={"total_tokens": 10})], [_final_event("Read it.")]]
    fake, state = _scripted_llm(scripts)
    with patch.object(executor, "call_llm_stream", fake), \
         patch.object(executor, "execute_tool", return_value="file contents") as exec_mock:
        events = _run([{"role": "user", "content": "read a.txt"}])

    # Tool was dispatched with parsed arguments.
    exec_mock.assert_called_once_with("read_file", {"path": "a.txt"})

    tool_call = next(e for e in events if e["type"] == "tool_call")
    assert tool_call["arguments"] == {"path": "a.txt"}

    tool_result = next(e for e in events if e["type"] == "tool_result")
    assert tool_result["result"] == "file contents"

    # usage event surfaced from the first step
    assert any(e["type"] == "usage" and e["data"]["total_tokens"] == 10 for e in events)

    # Ended on a final answer after the tool round-trip (2 LLM calls total).
    assert events[-1]["type"] == "final_answer"
    assert state["calls"] == 2


def test_stream_error_aborts():
    fake, state = _scripted_llm([[{"type": "stream_error", "error": "boom"}]])
    with patch.object(executor, "call_llm_stream", fake):
        events = _run([{"role": "user", "content": "hi"}])

    assert events[-1]["type"] == "error"
    assert "boom" in events[-1]["message"]
    assert state["calls"] == 1  # aborted immediately, no further steps


def test_repeated_erroring_tool_calls_trigger_blocked():
    # Every LLM turn returns the identical failing tool call.
    fake, state = _scripted_llm([[_tool_call_event()]])
    with patch.object(executor, "call_llm_stream", fake), \
         patch.object(executor, "execute_tool", return_value="Error: nope"):
        events = _run([{"role": "user", "content": "loop"}])

    assert any(e["type"] == "blocked" for e in events)
    # The guardrail must break the loop well before the 15-step ceiling.
    assert state["calls"] < 15
