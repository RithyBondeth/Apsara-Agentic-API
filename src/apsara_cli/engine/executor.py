import json
from typing import List, Dict, Any, AsyncGenerator
from apsara_cli.engine.llm import call_llm_stream
from apsara_cli.engine.tools import execute_tool

SYSTEM_PROMPT = """You are an expert autonomous software engineer named Apsara Agent.
You are equipped with workspace-scoped tools to read files, write files, search the codebase, inspect project structure, and replace file lines. If a command tool is available, use only simple non-interactive commands that respect the workspace boundary.
Analyze problems deeply, execute files or tools as requested to accomplish the goal. Always aim to be succinct when communicating back to the user but highly detailed in tool calls."""

async def run_agent_stream(
    conversation_history: List[Dict[str, Any]],
    model: str = "gpt-4o"
) -> AsyncGenerator[str, None]:
    """
    Core execution streaming loop for the agent.
    Yields JSON string events tracking the agent's progress and token usage.
    """
    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + conversation_history

    max_steps = 15
    consecutive_errors = 0
    consecutive_repeats = 0
    last_tool_invocation = None

    for step in range(max_steps):

        yield json.dumps({"type": "status", "message": "Agent is thinking..."})

        # Stream the LLM response
        full_content = ""
        tool_calls = None
        usage: dict = {}
        streamed_text = False

        async for event in call_llm_stream(messages, model):
            etype = event["type"]

            if etype == "text_chunk":
                if not streamed_text:
                    yield json.dumps({"type": "response_start"})
                    streamed_text = True
                yield json.dumps({"type": "text_chunk", "content": event["content"]})

            elif etype == "stream_done":
                full_content = event["content"]
                tool_calls = event["tool_calls"]
                usage = event["usage"]

            elif etype == "stream_error":
                yield json.dumps({"type": "error", "message": f"LLM Connection Error: {event['error']}"})
                return

        if usage:
            yield json.dumps({"type": "usage", "data": usage})

        assistant_dict: Dict[str, Any] = {"role": "assistant", "content": full_content}

        if tool_calls:
            assistant_dict["tool_calls"] = tool_calls
            messages.append(assistant_dict)

            yield json.dumps({
                "type": "assistant_dispatch",
                "content": full_content,
                "tool_calls": tool_calls,
            })

            for tool_call in tool_calls:
                tool_name = tool_call["function"]["name"]
                arguments_raw = tool_call["function"]["arguments"]

                current_invocation = (tool_name, arguments_raw)
                if current_invocation == last_tool_invocation:
                    consecutive_repeats += 1
                else:
                    consecutive_repeats = 0
                last_tool_invocation = current_invocation

                try:
                    arguments = json.loads(arguments_raw)
                except json.JSONDecodeError:
                    arguments = {}

                yield json.dumps({
                    "type": "tool_call",
                    "name": tool_name,
                    "arguments": arguments,
                    "tool_call_id": tool_call["id"],
                })

                tool_result_str = execute_tool(tool_name, arguments)

                if "Error:" in tool_result_str:
                    consecutive_errors += 1
                else:
                    consecutive_errors = 0

                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call["id"],
                    "name": tool_name,
                    "content": tool_result_str,
                })

                yield json.dumps({
                    "type": "tool_result",
                    "name": tool_name,
                    "tool_call_id": tool_call["id"],
                    "result": tool_result_str,
                })

            if consecutive_errors >= 3 or consecutive_repeats >= 2:
                yield json.dumps({
                    "type": "blocked",
                    "message": "I am stuck in a loop. I keep hitting errors or repeating actions. Please review my outputs and provide new instructions."
                })
                break

        else:
            messages.append(assistant_dict)
            if streamed_text:
                yield json.dumps({"type": "response_end", "content": full_content})
            else:
                yield json.dumps({"type": "final_answer", "content": full_content})
            break
