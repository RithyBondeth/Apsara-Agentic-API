from typing import Any
import litellm
from apsara_cli.services.agent.tools import get_agent_tools

litellm.suppress_debug_info = True
DEFAULT_MAX_COMPLETION_TOKENS = 1200


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
    """
    Sends the conversation to OpenAI with our configured tools via LiteLLM router.
    Returns (Response Message Object, Usage Dictionary Object)
    """
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
