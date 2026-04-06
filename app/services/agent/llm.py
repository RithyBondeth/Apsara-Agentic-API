import os
from typing import Any
import litellm
from app.services.agent.tools import AGENT_TOOLS

litellm.suppress_debug_info = True

async def call_llm(messages: list[dict], model: str = "gpt-4o") -> tuple[Any, Any]:
    """
    Sends the conversation to OpenAI with our configured tools via LiteLLM router.
    Returns (Response Message Object, Usage Dictionary Object)
    """
    try:
        response = await litellm.acompletion(
            model=model,
            messages=messages,
            tools=AGENT_TOOLS,
            tool_choice="auto",
        )
        return response.choices[0].message, response.usage.model_dump() if response.usage else {}
    except Exception as e:
        return {"error": str(e)}, {}
