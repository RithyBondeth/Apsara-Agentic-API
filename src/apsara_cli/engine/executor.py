import json
import os
import asyncio
from typing import List, Dict, Any, AsyncGenerator
from apsara_cli.engine.llm import call_llm_stream, estimate_request_tokens
from apsara_cli.engine.models import DEFAULT_MODEL, lookup_model, model_availability
from apsara_cli.engine.runtime import RunJournal
from apsara_cli.engine.tools import classify_tool_risk, execute_tool_async, get_mcp_manager
from apsara_cli.shared.types import AgentRun, AgentRunState, ToolResult

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


def _fallback_allowed(primary: str, candidate: str) -> bool:
    primary_entry = lookup_model(primary)
    candidate_entry = lookup_model(candidate)
    if candidate_entry is not None and not model_availability(candidate_entry)[0]:
        return False
    if primary_entry is None or primary_entry.tier not in {"free", "local"}:
        return True
    return candidate_entry is not None and candidate_entry.tier in {"free", "local"}


def _configured_fallbacks() -> list[str]:
    return [
        item.strip()
        for item in os.environ.get("APSARA_FALLBACK_MODELS", "").split(",")
        if item.strip()
    ]


def _model_candidates(primary: str) -> list[str]:
    """Return fallbacks that cannot silently turn a free run into a bill.

    Free/local primaries may only auto-fallback to another known free/local
    model. Paid and unknown candidates still work when selected explicitly.
    """
    candidates = [primary]
    for candidate in _configured_fallbacks():
        if candidate not in candidates and _fallback_allowed(primary, candidate):
            candidates.append(candidate)
    return candidates


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
    from apsara_cli.engine.tools import _bash_enabled, _workspace_root
    objective = next(
        (
            str(message.get("content") or "")
            for message in reversed(conversation_history)
            if message.get("role") == "user"
        ),
        "Complete the requested coding task",
    )
    run = AgentRun(
        objective=objective,
        model=model,
        workspace=str(_workspace_root()),
    )
    journal = RunJournal(_workspace_root(), run)
    from apsara_cli.engine.turn_checkpoints import activate_turn_checkpoint
    activate_turn_checkpoint(run.run_id)
    plan_steps = [
        ("inspect", "Understand the request and repository context"),
        ("implement", "Make the smallest complete set of changes"),
        ("verify", "Run relevant checks and review the final diff"),
    ]
    for kind, title in plan_steps:
        journal.add_step(kind, title)
    journal.transition(AgentRunState.PLANNING)
    yield json.dumps({
        "type": "run_state",
        "run_id": run.run_id,
        "state": run.state.value,
        "objective": objective,
    })
    yield json.dumps({
        "type": "plan",
        "run_id": run.run_id,
        "steps": [{"kind": kind, "title": title, "status": "pending"} for kind, title in plan_steps],
    })
    journal.update_step(0, "in_progress")
    journal.transition(AgentRunState.EXECUTING)

    full_system_prompt = SYSTEM_PROMPT
    
    # Load workspace-specific instructions
    try:
        inst_path = _workspace_root() / ".apsara" / "instructions.md"
        if inst_path.exists():
            custom_instructions = inst_path.read_text(encoding="utf-8")
            full_system_prompt += f"\n\nFOLLOW THESE ADDITIONAL WORKSPACE-SPECIFIC RULES:\n{custom_instructions}"
    except Exception:
        pass

    try:
        from apsara_cli.engine.memory import read_memory
        project_memory = read_memory(_workspace_root())
        if project_memory:
            full_system_prompt += f"\n\nPROJECT MEMORY (user-maintained context):\n{project_memory}"
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
    changed_workspace = False
    verification_seen = False
    verification_nudged = False
    verification_capable = _bash_enabled()
    model_candidates = _model_candidates(model)
    primary_entry = lookup_model(model)
    if primary_entry is not None:
        primary_allowed, primary_health = model_availability(primary_entry)
        if not primary_allowed:
            journal.transition(AgentRunState.FAILED, primary_health)
            yield json.dumps({"type": "error", "message": primary_health})
            return
        if primary_health:
            yield json.dumps({"type": "warning", "message": primary_health})
    blocked_fallbacks = [
        candidate
        for candidate in _configured_fallbacks()
        if candidate != model and not _fallback_allowed(model, candidate)
    ]
    if blocked_fallbacks:
        yield json.dumps({
            "type": "warning",
            "message": (
                "Skipped paid or unknown automatic fallback(s) from this free model: "
                f"{', '.join(dict.fromkeys(blocked_fallbacks))}. "
                "Select one explicitly with /model if you accept provider billing."
            ),
        })
    active_model_index = 0
    mutation_tools = {
        "write_to_file", "edit_file", "replace_file_lines", "replace_symbol", "delete_file",
        "move_file", "create_directory",
    }

    for step in range(max_steps):

        yield json.dumps({"type": "status", "message": "Agent is thinking..."})

        # Stream the LLM response
        full_content = ""
        tool_calls = None
        usage: dict = {}
        streamed_text = False

        while True:
            stream_error = None
            active_model = model_candidates[active_model_index]
            try:
                async for event in call_llm_stream(messages, active_model):
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
                        if event.get("rate_limits"):
                            usage = dict(usage or {})
                            usage["rate_limits"] = event["rate_limits"]

                    elif etype == "retry_notice":
                        yield json.dumps({"type": "status", "message": f"Provider busy — retrying in {event['delay']}s."})

                    elif etype == "stream_error":
                        stream_error = str(event["error"])
            except asyncio.CancelledError:
                journal.transition(AgentRunState.CANCELLED, "Cancelled by user")
                raise

            if stream_error is None:
                break
            if not streamed_text and active_model_index + 1 < len(model_candidates):
                previous = active_model
                active_model_index += 1
                run.model = model_candidates[active_model_index]
                journal.record("model_fallback", previous=previous, model=run.model, error=stream_error)
                yield json.dumps({"type": "status", "message": f"{previous} unavailable — falling back to {run.model}."})
                continue
            journal.transition(AgentRunState.FAILED, stream_error)
            yield json.dumps({"type": "error", "message": f"LLM Connection Error: {stream_error}"})
            return

        if usage:
            usage = dict(usage)
            usage["provider_reported_calls"] = 1
        else:
            # Some OpenAI-compatible providers omit the final usage-only
            # streaming chunk. Keep a separate local estimate without
            # pretending it is provider billing data.
            usage = {
                "estimated_input_tokens": estimate_request_tokens(messages, model=active_model),
                "unreported_calls": 1,
            }
        usage["apsara_model"] = active_model
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

                try:
                    tool_result_str = await execute_tool_async(tool_name, arguments)
                except asyncio.CancelledError:
                    journal.transition(AgentRunState.CANCELLED, "Cancelled by user")
                    raise
                typed_result = ToolResult.from_text(tool_result_str)
                journal.tool_result(tool_name, typed_result, arguments, classify_tool_risk(tool_name).value)

                if not typed_result.ok:
                    consecutive_errors += 1
                else:
                    consecutive_errors = 0

                if typed_result.ok and tool_name in mutation_tools:
                    changed_workspace = True
                    candidate = arguments.get("path") or arguments.get("dest") or arguments.get("src")
                    if candidate and str(candidate) not in run.changed_files:
                        run.changed_files.append(str(candidate))
                    journal.update_step(0, "completed")
                    journal.update_step(1, "in_progress")
                if typed_result.ok and tool_name == "run_bash_command":
                    verification_seen = True
                    command = str(arguments.get("command") or "")
                    if command and command not in run.verification:
                        run.verification.append(command)
                    journal.update_step(1, "completed")
                    journal.update_step(2, "in_progress")

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
                journal.transition(AgentRunState.BLOCKED, "Repeated tool failures or actions")
                completed = True
                break

        else:
            if (
                changed_workspace
                and verification_capable
                and not verification_seen
                and not verification_nudged
            ):
                verification_nudged = True
                messages.append({
                    "role": "system",
                    "content": (
                        "Before you finish, verify the changes. Run the most relevant available "
                        "tests, formatter, linter, type checker, or build command. If command "
                        "execution is unavailable, inspect git_diff and explicitly report that "
                        "automated verification could not run."
                    ),
                })
                yield json.dumps({
                    "type": "run_state",
                    "run_id": run.run_id,
                    "state": AgentRunState.VERIFYING.value,
                    "objective": objective,
                })
                journal.transition(AgentRunState.VERIFYING)
                continue
            messages.append(assistant_dict)
            journal.update_step(0, "completed")
            journal.update_step(1, "completed")
            journal.update_step(2, "completed" if verification_seen else "blocked", "No command verification was run" if not verification_seen else "")
            journal.transition(AgentRunState.COMPLETED)
            yield json.dumps({
                "type": "run_state",
                "run_id": run.run_id,
                "state": AgentRunState.COMPLETED.value,
                "objective": objective,
            })
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
        journal.transition(AgentRunState.BLOCKED, "Step budget exhausted")
