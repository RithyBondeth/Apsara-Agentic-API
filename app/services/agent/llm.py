import os
from typing import Any
from openai import AsyncOpenAI
from app.services.agent.tools import AGENT_TOOLS

# Initialize AsyncOpenAI client (fail gracefully if missing on boot)
client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY", "dummy_key_for_boot"))

async def call_llm(messages: list[dict], model: str = "gpt-4o") -> tuple[Any, Any]:
    """
    Sends the conversation to OpenAI with our configured tools.
    Returns (Response Message Object, Usage Dictionary Object)
    """
    try:
        response = await client.chat.completions.create(
            model=model,
            messages=messages,
            tools=AGENT_TOOLS,
            tool_choice="auto",
        )
        return response.choices[0].message, response.usage.model_dump() if response.usage else {}
    except Exception as e:
        return {"error": str(e)}, {}
