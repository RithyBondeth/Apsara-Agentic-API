"""Tests for the LLM layer (engine/llm.py).

Auth gating and streaming-chunk aggregation are covered offline by patching
`is_authenticated` and `litellm.acompletion`. No network calls are made.
"""
import asyncio
import os
import sys
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import litellm

from apsara_cli.engine import llm


def _run(coro):
    return asyncio.run(coro)


def _drain(async_gen):
    async def _collect():
        return [event async for event in async_gen]

    return asyncio.run(_collect())


def test_estimate_request_tokens_positive():
    messages = [{"role": "user", "content": "hello world"}]
    tokens = llm.estimate_request_tokens(messages, model="gpt-3.5-turbo")
    assert isinstance(tokens, int)
    assert tokens >= 1


def test_call_llm_requires_auth():
    with patch("apsara_cli.cli.auth.is_authenticated", return_value=False):
        message, usage = _run(llm.call_llm([{"role": "user", "content": "hi"}]))
    assert isinstance(message, dict)
    assert "error" in message
    assert "login" in message["error"].lower()
    assert usage == {}


def test_call_llm_stream_requires_auth():
    with patch("apsara_cli.cli.auth.is_authenticated", return_value=False):
        events = _drain(llm.call_llm_stream([{"role": "user", "content": "hi"}]))
    assert len(events) == 1
    assert events[0]["type"] == "stream_error"
    assert "login" in events[0]["error"].lower()


def _chunk(content=None, tool_calls=None, usage=None):
    delta = SimpleNamespace(content=content, tool_calls=tool_calls)
    choice = SimpleNamespace(delta=delta)
    chunk = SimpleNamespace(choices=[choice])
    if usage is not None:
        chunk.usage = SimpleNamespace(model_dump=lambda: usage)
    return chunk


def _tc(index, call_id=None, name=None, arguments=None):
    function = SimpleNamespace(name=name, arguments=arguments)
    return SimpleNamespace(index=index, id=call_id, function=function)


def test_call_llm_stream_aggregates_text_and_tool_calls():
    chunks = [
        _chunk(content="Hel"),
        _chunk(content="lo"),
        _chunk(tool_calls=[_tc(0, call_id="c1", name="read_file", arguments='{"path":')]),
        _chunk(tool_calls=[_tc(0, arguments='"a.txt"}')]),
        _chunk(usage={"total_tokens": 42}),
    ]

    async def fake_acompletion(**kwargs):
        async def gen():
            for c in chunks:
                yield c
        return gen()

    with patch("apsara_cli.cli.auth.is_authenticated", return_value=True), \
         patch.object(litellm, "acompletion", fake_acompletion):
        events = _drain(llm.call_llm_stream([{"role": "user", "content": "read a.txt"}]))

    text_chunks = [e for e in events if e["type"] == "text_chunk"]
    assert "".join(e["content"] for e in text_chunks) == "Hello"

    done = next(e for e in events if e["type"] == "stream_done")
    assert done["content"] == "Hello"
    assert done["usage"] == {"total_tokens": 42}
    assert done["tool_calls"] is not None
    assert len(done["tool_calls"]) == 1

    tool_call = done["tool_calls"][0]
    assert tool_call["id"] == "c1"
    assert tool_call["function"]["name"] == "read_file"
    # Arguments streamed across two deltas are concatenated.
    assert tool_call["function"]["arguments"] == '{"path":"a.txt"}'


def test_call_llm_stream_retries_on_rate_limit():
    attempts = {"n": 0}

    async def flaky_acompletion(**kwargs):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise litellm.RateLimitError("slow down", llm_provider="test", model="m")

        async def gen():
            yield _chunk(content="ok")
        return gen()

    # Patch sleep so the retry delay doesn't actually block the test.
    async def no_sleep(_seconds):
        return None

    with patch("apsara_cli.cli.auth.is_authenticated", return_value=True), \
         patch.object(litellm, "acompletion", flaky_acompletion), \
         patch("apsara_cli.engine.llm.asyncio.sleep", no_sleep):
        events = _drain(llm.call_llm_stream([{"role": "user", "content": "hi"}]))

    types = [e["type"] for e in events]
    assert "retry_notice" in types
    assert attempts["n"] == 2  # failed once, then succeeded
    done = next(e for e in events if e["type"] == "stream_done")
    assert done["content"] == "ok"
