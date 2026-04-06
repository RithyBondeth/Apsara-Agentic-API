import json
from typing import List, Dict, Any, AsyncGenerator
from app.services.agent.llm import call_llm
from app.services.agent.tools import execute_tool

SYSTEM_PROMPT = """You are an expert autonomous software engineer named Apsara Agent.
You are equipped with tools to read files, write files, search codebase, and execute bash commands.
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
    for step in range(max_steps):
        
        # 1. Ask LLM
        yield json.dumps({"type": "status", "message": "Agent is thinking..."})
        
        response_msg, usage = await call_llm(messages, model)
        
        if usage:
            yield json.dumps({"type": "usage", "data": usage})
            
        # Guard clause
        if isinstance(response_msg, dict) and "error" in response_msg:
            yield json.dumps({"type": "error", "message": f"LLM Connection Error: {response_msg['error']}"})
            break

        assistant_dict = {"role": "assistant", "content": response_msg.content}
        
        # 2. Check for tool decisions
        if response_msg.tool_calls:
            assistant_dict["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments
                    }
                }
                for tc in response_msg.tool_calls
            ]
            messages.append(assistant_dict)

            yield json.dumps({
                "type": "assistant_dispatch",
                "tool_calls": assistant_dict["tool_calls"]
            })

            # 3. Handle tools execution
            for tool_call in response_msg.tool_calls:
                tool_name = tool_call.function.name
                arguments_raw = tool_call.function.arguments
                
                try:
                    arguments = json.loads(arguments_raw)
                except json.JSONDecodeError:
                    arguments = {}

                yield json.dumps({
                    "type": "tool_call", 
                    "name": tool_name, 
                    "arguments": arguments,
                    "tool_call_id": tool_call.id
                })

                # Execute natively
                tool_result_str = execute_tool(tool_name, arguments)
                
                # Write result to conversational memory
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "name": tool_name,
                    "content": tool_result_str
                })
                
                yield json.dumps({
                    "type": "tool_result",
                    "tool_call_id": tool_call.id,
                    "result": tool_result_str
                })
        else:
            # End of chain logic; LLM is answering directly to user.
            messages.append(assistant_dict)
            yield json.dumps({"type": "final_answer", "content": response_msg.content})
            break
