import asyncio
from typing import Any, AsyncGenerator
import litellm
from apsara_cli.engine.tools import get_agent_tools

litellm.suppress_debug_info = True
DEFAULT_MAX_COMPLETION_TOKENS = 1200

_RETRY_DELAYS = [5, 15, 30]


def estimate_request_tokens(messages: list[dict], model: str = "gpt-4o") -> int:
    try:
        return litellm.token_counter(
            model=model,
            messages=messages,
            tools=get_agent_tools(),
            tool_choice="auto",
        )
    except Exception:
        return max(
            1,
            sum(len(str(message.get("content", ""))) for message in messages) // 4,
        )


async def call_llm(messages: list[dict], model: str = "gpt-4o") -> tuple[Any, Any]:
    try:
        response = await litellm.acompletion(
            model=model,
            messages=messages,
            tools=get_agent_tools(),
            tool_choice="auto",
            max_tokens=DEFAULT_MAX_COMPLETION_TOKENS,
        )
        return response.choices[0].message, response.usage.model_dump() if response.usage else {}
    except Exception as e:
        return {"error": str(e)}, {}


async def call_llm_stream(
    messages: list[dict], model: str = "gpt-4o"
) -> AsyncGenerator[dict, None]:
    """
    Streaming LLM call with automatic retry on rate-limit errors.
    Yields dicts:
      {"type": "retry_notice", "delay": int, "attempt": int}
      {"type": "text_chunk", "content": str}
      {"type": "stream_done", "content": str, "tool_calls": list|None, "usage": dict}
      {"type": "stream_error", "error": str}
    """
    for attempt in range(len(_RETRY_DELAYS) + 1):
        try:
            response = await litellm.acompletion(
                model=model,
                messages=messages,
                tools=get_agent_tools(),
                tool_choice="auto",
                max_tokens=DEFAULT_MAX_COMPLETION_TOKENS,
                stream=True,
            )

            content_parts: list[str] = []
            tool_calls_acc: dict[int, dict] = {}
            usage: dict = {}

            async for chunk in response:
                choice = chunk.choices[0] if chunk.choices else None
                if not choice:
                    continue
                delta = choice.delta

                if delta.content:
                    content_parts.append(delta.content)
                    yield {"type": "text_chunk", "content": delta.content}

                if delta.tool_calls:
                    for tc in delta.tool_calls:
                        idx = tc.index
                        if idx not in tool_calls_acc:
                            tool_calls_acc[idx] = {
                                "id": "",
                                "type": "function",
                                "function": {"name": "", "arguments": ""},
                            }
                        if tc.id:
                            tool_calls_acc[idx]["id"] = tc.id
                        if tc.function:
                            if tc.function.name:
                                tool_calls_acc[idx]["function"]["name"] += tc.function.name
                            if tc.function.arguments:
                                tool_calls_acc[idx]["function"]["arguments"] += tc.function.arguments

                if hasattr(chunk, "usage") and chunk.usage:
                    try:
                        usage = chunk.usage.model_dump()
                    except Exception:
                        pass

            yield {
                "type": "stream_done",
                "content": "".join(content_parts),
                "tool_calls": list(tool_calls_acc.values()) if tool_calls_acc else None,
                "usage": usage,
            }
            return

        except litellm.RateLimitError as e:
            if attempt < len(_RETRY_DELAYS):
                delay = _RETRY_DELAYS[attempt]
                yield {"type": "retry_notice", "delay": delay, "attempt": attempt + 1}
                await asyncio.sleep(delay)
            else:
                yield {"type": "stream_error", "error": str(e)}
                return

        except Exception as e:
            yield {"type": "stream_error", "error": str(e)}
            return
