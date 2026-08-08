import json
import os
from typing import List, Dict, Any, AsyncGenerator
from apsara_cli.engine.llm import call_llm_stream
from apsara_cli.engine.models import DEFAULT_MODEL
from apsara_cli.engine.tools import execute_tool_async, get_mcp_manager
from apsara_cli.shared.text import is_tool_error

DEFAULT_MAX_STEPS = 25
# A repeat only counts as cycling when the *result* repeats too. Re-running the
# test suite after an edit is the verification loop working as intended — the
# same command returning a different result is progress. The same command
# returning the identical output this many times is a stuck agent.
MAX_IDENTICAL_INVOCATIONS = 3


def _max_steps() -> int:
    """Tool-call budget for a single turn, overridable via APSARA_MAX_STEPS."""
    raw = os.environ.get("APSARA_MAX_STEPS")
    if not raw:
        return DEFAULT_MAX_STEPS
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_MAX_STEPS
    return max(1, min(value, 100))


SYSTEM_PROMPT = """You are an expert autonomous software engineer named Apsara Agent.
You are equipped with workspace-scoped tools to read files, write files, search the codebase, inspect project structure, and replace file lines. If a command tool is available, use only simple non-interactive commands that respect the workspace boundary.
Analyze problems deeply, execute files or tools as requested to accomplish the goal. Always aim to be succinct when communicating back to the user but highly detailed in tool calls."""

async def run_agent_stream(
    conversation_history: List[Dict[str, Any]],
    model: str = DEFAULT_MODEL
) -> AsyncGenerator[str, None]:
    """
    Core execution streaming loop for the agent.
    Yields JSON string events tracking the agent's progress and token usage.
    """
    from apsara_cli.engine.tools import _workspace_root
    from pathlib import Path
    
    full_system_prompt = SYSTEM_PROMPT
    
    # Load workspace-specific instructions
    try:
        inst_path = _workspace_root() / ".apsara" / "instructions.md"
        if inst_path.exists():
            custom_instructions = inst_path.read_text(encoding="utf-8")
            full_system_prompt += f"\n\nFOLLOW THESE ADDITIONAL WORKSPACE-SPECIFIC RULES:\n{custom_instructions}"
    except Exception:
        pass

    # Tools from MCP servers are namespaced mcp__<server>__<tool>; tell the model
    # what it has so it doesn't fall back to guessing with the built-ins.
    manager = get_mcp_manager()
    if manager is not None and manager.tool_names():
        servers = manager.connected_servers()
        full_system_prompt += (
            "\n\nYou also have tools from connected MCP servers "
            f"({', '.join(servers)}). They are named mcp__<server>__<tool> and "
            "may reach outside the workspace — prefer them when the task needs "
            "data or actions the built-in workspace tools cannot provide."
        )

    messages = [{"role": "system", "content": full_system_prompt}] + conversation_history

    max_steps = _max_steps()
    consecutive_errors = 0
    consecutive_repeats = 0
    last_tool_invocation = None
    # Counts (tool, args, result) across the whole turn, not just consecutive
    # calls: an agent alternating A,B,A,B is as stuck as one repeating A,A,A.
    invocation_counts: Dict[tuple, int] = {}
    completed = False
    # One corrective intervention per turn before we give up on it.
    nudged = False

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
            # Close any streamed thinking text before processing tool calls
            if streamed_text:
                yield json.dumps({"type": "response_end", "content": full_content})

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

                tool_result_str = await execute_tool_async(tool_name, arguments)

                if is_tool_error(tool_result_str):
                    consecutive_errors += 1
                else:
                    consecutive_errors = 0

                # Include the result: identical call + identical output is a
                # loop; identical call + changed output is the agent making
                # progress (e.g. re-running tests after a fix).
                outcome = (tool_name, arguments_raw, tool_result_str)
                invocation_counts[outcome] = invocation_counts.get(outcome, 0) + 1

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

            cycling = any(
                count >= MAX_IDENTICAL_INVOCATIONS for count in invocation_counts.values()
            )
            if consecutive_errors >= 3 or consecutive_repeats >= 2 or cycling:
                if not nudged:
                    # Don't give up on the first sign of trouble. Models often
                    # just need telling that they're repeating themselves —
                    # name the specific problem, clear the counters, and let it
                    # try once more before we stop the turn.
                    nudged = True
                    if consecutive_errors >= 3:
                        problem = (
                            f"Your last {consecutive_errors} tool calls all failed. "
                            f"The most recent error was: {tool_result_str[:300]}"
                        )
                    else:
                        problem = (
                            f"You have already called {last_tool_invocation[0]} with "
                            "exactly these arguments and got exactly this result. "
                            "Repeating it will not produce anything new."
                        )
                    messages.append({
                        "role": "system",
                        "content": (
                            f"STOP AND RECONSIDER. {problem}\n\n"
                            "Do not repeat that action. Either take a materially "
                            "different approach — re-read the file to get its current "
                            "exact contents, or use a different tool — or, if you "
                            "genuinely cannot proceed, stop calling tools and explain "
                            "what is blocking you."
                        ),
                    })
                    yield json.dumps({
                        "type": "status",
                        "message": "Detected a repeated action — redirecting.",
                    })
                    consecutive_errors = 0
                    consecutive_repeats = 0
                    invocation_counts.clear()
                    continue

                yield json.dumps({
                    "type": "blocked",
                    "message": (
                        "I am stuck in a loop. I kept hitting the same errors or "
                        "repeating the same actions even after changing course, so I "
                        "stopped rather than burn more tokens. Review the output above "
                        "and give me a more specific instruction."
                    ),
                })
                completed = True
                break

        else:
            messages.append(assistant_dict)
            if streamed_text:
                yield json.dumps({"type": "response_end", "content": full_content})
            else:
                yield json.dumps({"type": "final_answer", "content": full_content})
            completed = True
            break

    if not completed:
        # The step budget ran out mid-task. Say so — otherwise the turn just
        # stops and an unfinished job is indistinguishable from a finished one.
        yield json.dumps({
            "type": "blocked",
            "message": (
                f"I used all {max_steps} steps for this turn without finishing. "
                "The work so far is above. Tell me to continue, narrow the task, "
                "or raise the budget with APSARA_MAX_STEPS."
            ),
        })
