import os
from openai import AsyncOpenAI
from app.services.agent.tools import AGENT_TOOLS

# Initialize AsyncOpenAI client (fail gracefully if missing on boot)
client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY", "dummy_key_for_boot"))

async def call_llm(messages: list[dict], model: str = "gpt-4o") -> dict:
    """
    Sends the conversation to OpenAI with our configured tools.
    """
    try:
        response = await client.chat.completions.create(
            model=model,
            messages=messages,
            tools=AGENT_TOOLS,
            tool_choice="auto",
        )
        return response.choices[0].message
    except Exception as e:
        return {"error": str(e)}
