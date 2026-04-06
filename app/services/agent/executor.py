import json
from typing import List, Dict, Any
from app.services.agent.llm import call_llm
from app.services.agent.tools import execute_tool

# Fallback Prompt. Eventually this comes from the DB config.
SYSTEM_PROMPT = """You are an expert autonomous software engineer named Apsara Agent.
You are equipped with tools to read files, write files, and execute bash commands.
Analyze problems deeply, execute files or tools as requested to accomplish the goal. Always aim to be succinct when communicating back to the user but highly detailed in tool calls."""

async def run_agent(task_instruction: str, model: str = "gpt-4o") -> List[Dict[str, Any]]:
    """
    Core execution loop for the agent.
    Returns the final message history array containing the execution trace.
    """
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": task_instruction}
    ]

    max_steps = 15
    for step in range(max_steps):
        
        # 1. Ask LLM
        response_msg = await call_llm(messages, model)
        
        # Guard clause for API errors
        if isinstance(response_msg, dict) and "error" in response_msg:
            messages.append({"role": "assistant", "content": f"LLM Connection Error: {response_msg['error']}"})
            break

        # Formatting standard Python dict of the LLM response object
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

            # 3. Handle tools execution concurrently or synchronously
            for tool_call in response_msg.tool_calls:
                tool_name = tool_call.function.name
                try:
                    arguments = json.loads(tool_call.function.arguments)
                except json.JSONDecodeError:
                    arguments = {}

                # Execute internally mapped backend function
                tool_result_str = execute_tool(tool_name, arguments)
                
                # Write result to conversational memory
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "name": tool_name,
                    "content": tool_result_str
                })
                
            # The loop continues back to call the LLM with the latest tool outputs!
        else:
            # End of chain logic; LLM is answering directly to user.
            messages.append(assistant_dict)
            break
            
    return messages
