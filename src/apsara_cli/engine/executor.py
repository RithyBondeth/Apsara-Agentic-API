import json
from typing import List, Dict, Any, AsyncGenerator
from apsara_cli.engine.llm import call_llm
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
                "content": response_msg.content,
                "tool_calls": assistant_dict["tool_calls"]
            })

            # 3. Handle tools execution
            for tool_call in response_msg.tool_calls:
                tool_name = tool_call.function.name
                arguments_raw = tool_call.function.arguments
                
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
                    "tool_call_id": tool_call.id
                })

                # Execute natively
                tool_result_str = execute_tool(tool_name, arguments)
                
                if "Error:" in tool_result_str:
                    consecutive_errors += 1
                else:
                    consecutive_errors = 0
                
                # Write result to conversational memory
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "name": tool_name,
                    "content": tool_result_str
                })
                
                yield json.dumps({
                    "type": "tool_result",
                    "name": tool_name,
                    "tool_call_id": tool_call.id,
                    "result": tool_result_str
                })
                
            # 4. Check HITL fallback conditions
            if consecutive_errors >= 3 or consecutive_repeats >= 2:
                yield json.dumps({
                    "type": "blocked",
                    "message": "I am stuck in a loop. I keep hitting errors or repeating actions. Please review my outputs and provide new instructions."
                })
                break
        else:
            # End of chain logic; LLM is answering directly to user.
            messages.append(assistant_dict)
            yield json.dumps({"type": "final_answer", "content": response_msg.content})
            break
