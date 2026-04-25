import json
from pathlib import Path
from typing import Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from apsara_cli.shared.types import ResolvedOptions
    from apsara_cli.shared.ui import ConsoleUI

from apsara_cli.shared.events import print_event
from apsara_cli.cli.history import SAFE_INPUT_TOKEN_BUDGET, trim_history_for_request, update_history_from_event
from apsara_cli.cli.input import get_input_async
from apsara_cli.cli.options import resolve_runtime_options
from apsara_cli.cli.session import (
    get_session_path,
    list_sessions,
    load_session_messages,
    sanitize_session_name,
    save_session_messages,
)
from apsara_cli.shared.text import summarize_history  # noqa: F401 (kept for potential external use)
from apsara_cli.shared.ui import ConsoleUI
from apsara_cli.engine.tools import agent_runtime_context, get_agent_tools


def print_chat_help(ui: "ConsoleUI") -> None:
    ui.info("Slash commands:")
    ui.print_line("/help      Show available chat commands")
    ui.print_line("/details   Show hidden internal activity from the latest turn")
    ui.print_line("/history   Show recent conversation turns")
    ui.print_line("/tools     Show enabled tools with descriptions")
    ui.print_line("/status    Show token usage, turns, and context health")
    ui.print_line("/model     Show the current model")
    ui.print_line("/model X   Switch to a different model for later turns")
    ui.print_line("/session   Show session and workspace details")
    ui.print_line("/save              Save the current session now")
    ui.print_line("/sessions          List all saved sessions")
    ui.print_line("/sessions clear    Delete all saved sessions")
    ui.print_line("/sessions clear X  Delete session named X")
    ui.print_line("/clear             Clear in-memory conversation history")
    ui.print_line("/exit              Quit the chat session")
    ui.print_line("")
    ui.print_line("Tips: Esc+Enter inserts a newline · ↑/↓ navigates input history · Tab completes /commands")


def handle_chat_command(
    command_text: str,
    history: list[dict[str, Any]],
    current_model: str,
    options: "ResolvedOptions",
    config: object,
    ui: "ConsoleUI",
) -> tuple[bool, str]:
    if command_text in {"/exit", "/quit"}:
        turns = sum(1 for m in history if m.get("role") == "user")
        if turns > 0 and options.stateless:
            ui.warning(f"Stateless session — {turns} turn(s) will not be saved.")
            ui.print_line(
                f"  {ui.badge('↵  exit', '17', '48;2;80;170;140')}  "
                f"{ui.badge('n  stay', '17', '48;2;200;100;80')}"
            )
            key = ui.read_single_key()
            if key not in {"y", "Y", "\r", "\n", ""}:
                ui.info("Staying in session.")
                return True, current_model
        return False, current_model

    if command_text == "/help":
        print_chat_help(ui)
        return True, current_model

    if command_text == "/details":
        ui.show_hidden_events()
        return True, current_model

    if command_text == "/clear":
        history.clear()
        ui.latest_hidden_events = []
        ui.warning("Session cleared in memory")
        return True, current_model

    if command_text == "/history":
        if not history:
            ui.info("No conversation history yet.")
            return True, current_model

        total_msgs = len(history)
        user_turns = sum(1 for m in history if m.get("role") == "user")
        turn_plural = "s" if user_turns != 1 else ""
        ui.print_line()
        ui.print_line(
            f"  {ui.badge('history', '15', '48;2;70;85;115')}  "
            f"{ui.style(f'{user_turns} turn{turn_plural}  ·  {total_msgs} messages', '38;2;200;210;230')}"
        )
        ui.print_line()

        turn_num = 0
        i = 0
        while i < len(history):
            msg = history[i]
            role = msg.get("role", "")

            if role == "user":
                turn_num += 1
                content = str(msg.get("content") or "").strip().replace("\n", " ")
                if len(content) > 74:
                    content = content[:71] + "…"
                ui.print_line(
                    f"  {ui.style(f'#{turn_num}', '1', '38;2;180;210;255')}"
                    f"  {ui.style('you', '2', '38;2;130;140;160')}"
                    f"  {ui.style(content, '38;2;230;228;224')}"
                )
                i += 1

                # Collect assistant messages and tool calls for this turn
                tool_call_count = 0
                while i < len(history) and history[i].get("role") != "user":
                    inner = history[i]
                    inner_role = inner.get("role", "")
                    if inner_role == "assistant":
                        tool_calls = inner.get("tool_calls") or []
                        tool_call_count += len(tool_calls)
                        reply = str(inner.get("content") or "").strip().replace("\n", " ")
                        if reply:
                            if len(reply) > 74:
                                reply = reply[:71] + "…"
                            ui.print_line(
                                f"    {ui.style('apsara', '2', '38;2;130;140;160')}"
                                f"  {ui.style(reply, '38;2;210;208;204')}"
                            )
                    i += 1

                if tool_call_count:
                    plural = "s" if tool_call_count != 1 else ""
                    ui.print_line(
                        f"    {ui.dim(f'↳ {tool_call_count} tool call{plural}')}"
                    )
            else:
                i += 1

        ui.print_line()
        return True, current_model

    if command_text == "/tools":
        with agent_runtime_context(
            workspace_root=options.workspace_root,
            enable_bash=options.allow_bash,
            allowed_commands=options.allowed_commands,
            max_file_size_bytes=options.max_file_size,
        ):
            tools = get_agent_tools()
        ui.print_line()
        ui.print_line(
            f"  {ui.badge('tools', '15', '48;2;70;85;115')}  "
            f"{ui.style(f'{len(tools)} enabled', '1', '38;2;200;210;230')}"
        )
        ui.print_line()
        for tool in tools:
            fn = tool.get("function", {})
            name = fn.get("name", "unknown")
            desc = fn.get("description", "")
            ui.print_line(
                f"  {ui.style('◆', '38;2;100;150;220')} "
                f"{ui.style(name, '1', '38;2;180;210;255')}"
            )
            if desc:
                short_desc = desc[:86] + "…" if len(desc) > 86 else desc
                ui.print_line(f"    {ui.dim(short_desc)}")
        ui.print_line()
        return True, current_model

    if command_text == "/model":
        ui.info(f"Current model: {current_model}")
        return True, current_model

    if command_text.startswith("/model "):
        next_model = command_text[len("/model "):].strip()
        if not next_model:
            ui.error("Usage: /model <model-name>")
            return True, current_model
        ui.info(f"Model changed to {next_model}")
        return True, next_model

    if command_text == "/session":
        ui.info(f"Workspace: {options.workspace_root}")
        if options.stateless:
            ui.info("Session mode: stateless")
        else:
            ui.info(f"Session: {sanitize_session_name(options.session)}")
        config_path = getattr(config, "path", None)
        config_exists = getattr(config, "exists", False)
        ui.info(f"Config: {config_path} ({'loaded' if config_exists else 'default values'})")
        return True, current_model

    if command_text == "/save":
        save_if_needed(history, current_model, options, ui)
        return True, current_model

    if command_text == "/sessions" or command_text.startswith("/sessions "):
        sub = command_text[len("/sessions"):].strip()  # "", "clear", or "clear <name>"

        if not sub:
            # ── List all sessions ──────────────────────────────────────────
            sessions = list_sessions(options.workspace_root)
            if not sessions:
                ui.info("No saved sessions found.")
                return True, current_model

            current_name = (
                sanitize_session_name(options.session) if not options.stateless else None
            )
            ui.print_line()
            ui.print_line(
                f"  {ui.badge('sessions', '15', '48;2;70;85;115')}  "
                f"{ui.style(f'{len(sessions)} saved', '38;2;200;210;230')}"
            )
            ui.print_line()
            for path in sessions:
                name = path.stem
                is_current = name == current_name
                try:
                    payload = json.loads(path.read_text(encoding="utf-8"))
                    msg_count = len(payload.get("messages", []))
                    updated_at = payload.get("updated_at", "")[:19].replace("T", " ")
                    model_name = payload.get("model", "?")
                except Exception:
                    msg_count, updated_at, model_name = 0, "?", "?"
                size_kb = path.stat().st_size / 1024
                current_marker = ui.style("  ← active", "38;2;120;200;150") if is_current else ""
                ui.print_line(
                    f"  {ui.style('◆', '38;2;100;150;220')} "
                    f"{ui.style(name, '1', '38;2;180;210;255')}"
                    f"{current_marker}"
                )
                ui.print_line(
                    f"    {ui.dim(f'{msg_count} messages  ·  {updated_at}  ·  {size_kb:.1f} kb  ·  {model_name}')}"
                )
            ui.print_line()
            ui.print_line(f"  {ui.dim('  /sessions clear         delete all sessions')}")
            ui.print_line(f"  {ui.dim('  /sessions clear <name>  delete a specific session')}")
            ui.print_line()
            return True, current_model

        if sub == "clear":
            # ── Delete all sessions ────────────────────────────────────────
            sessions = list_sessions(options.workspace_root)
            if not sessions:
                ui.info("No saved sessions to clear.")
                return True, current_model

            ui.warning(f"This will permanently delete {len(sessions)} session file(s).")
            ui.print_line(
                f"  {ui.badge('↵  confirm', '17', '48;2;80;170;140')}  "
                f"{ui.badge('n  cancel', '17', '48;2;200;100;80')}"
            )
            key = ui.read_single_key()
            if key not in {"y", "Y", "\r", "\n", ""}:
                ui.info("Cancelled.")
                return True, current_model

            deleted = 0
            for path in sessions:
                try:
                    path.unlink()
                    deleted += 1
                except Exception as exc:
                    ui.error(f"Could not delete {path.name}: {exc}")
            ui.success(f"Deleted {deleted} session file(s).")
            return True, current_model

        if sub.startswith("clear "):
            # ── Delete one session by name ─────────────────────────────────
            target_name = sub[len("clear "):].strip()
            if not target_name:
                ui.error("Usage: /sessions clear <name>")
                return True, current_model

            target_path = get_session_path(options.workspace_root, target_name)
            if not target_path.exists():
                ui.error(f"Session '{target_name}' not found.")
                return True, current_model

            ui.warning(f"Delete session '{target_name}'?")
            ui.print_line(
                f"  {ui.badge('↵  confirm', '17', '48;2;80;170;140')}  "
                f"{ui.badge('n  cancel', '17', '48;2;200;100;80')}"
            )
            key = ui.read_single_key()
            if key not in {"y", "Y", "\r", "\n", ""}:
                ui.info("Cancelled.")
                return True, current_model

            try:
                target_path.unlink()
                ui.success(f"Session '{target_name}' deleted.")
            except Exception as exc:
                ui.error(f"Could not delete session: {exc}")
            return True, current_model

        ui.error("Usage: /sessions  |  /sessions clear  |  /sessions clear <name>")
        return True, current_model

    if command_text == "/status":
        from apsara_cli.engine.executor import SYSTEM_PROMPT
        from apsara_cli.engine.llm import estimate_request_tokens

        base = [{"role": "system", "content": SYSTEM_PROMPT}]
        tokens = estimate_request_tokens(base + history, model=current_model)
        pct = int(tokens / SAFE_INPUT_TOKEN_BUDGET * 100)
        turns = sum(1 for m in history if m.get("role") == "user")
        msgs = len(history)
        session_label = (
            sanitize_session_name(options.session) if not options.stateless else "stateless"
        )

        if pct < 70:
            health_color = "38;2;120;200;150"
            health_label = "good"
        elif pct < 90:
            health_color = "38;2;247;223;181"
            health_label = "warn"
        else:
            health_color = "38;2;255;168;168"
            health_label = "critical"

        ui.print_line()
        ui.print_line(
            f"  {ui.badge('status', '15', '48;2;70;85;115')}  "
            f"{ui.style('Session Context', '1', '38;2;200;210;230')}"
        )
        ui.print_line()
        ui.print_line(f"  {ui.dim('  model    ')} {ui.style(current_model, '38;2;188;218;255')}")
        ui.print_line(f"  {ui.dim('  session  ')} {ui.style(session_label, '38;2;220;216;210')}")
        ui.print_line(f"  {ui.dim('  turns    ')} {ui.style(str(turns), '38;2;220;216;210')}")
        ui.print_line(f"  {ui.dim('  messages ')} {ui.style(str(msgs), '38;2;220;216;210')}")
        ui.print_line(
            f"  {ui.dim('  tokens   ')} "
            f"{ui.style(f'{tokens:,}', health_color)} "
            f"{ui.dim(f'/ {SAFE_INPUT_TOKEN_BUDGET:,} budget  ({pct}%  {health_label})')}"
        )
        ui.print_line()
        return True, current_model

    ui.error("Unknown slash command. Type /help for a list of commands.")
    return True, current_model


async def execute_instruction(
    instruction: str,
    model: str,
    history: list[dict[str, Any]],
    options: "ResolvedOptions",
    ui: "ConsoleUI",
) -> tuple[list[dict[str, Any]], Optional[dict[str, Any]]]:
    from apsara_cli.engine.executor import run_agent_stream
    from apsara_cli.engine.llm import DEFAULT_MAX_COMPLETION_TOKENS

    next_history = list(history)
    next_history.append({"role": "user", "content": instruction})
    latest_usage = None
    ui.begin_turn()

    with agent_runtime_context(
        workspace_root=options.workspace_root,
        enable_bash=options.allow_bash,
        allowed_commands=options.allowed_commands,
        max_file_size_bytes=options.max_file_size,
        confirmation_callback=None if options.auto_approve else ui.confirm_action,
    ):
        trim_result = trim_history_for_request(next_history, model=model)
        if trim_result.dropped_turns:
            ui.warning(
                f"Trimmed {trim_result.dropped_turns} earlier turn(s) "
                f"({trim_result.dropped_messages} messages) to stay within the request budget."
            )
            ui.info(
                f"Estimated input tokens: {trim_result.original_tokens} -> {trim_result.trimmed_tokens}. "
                f"Response budget capped at about {DEFAULT_MAX_COMPLETION_TOKENS} tokens."
            )
        if trim_result.trimmed_tokens > SAFE_INPUT_TOKEN_BUDGET:
            ui.warning("This prompt is still very large. If rate-limit errors continue, try /clear or --stateless.")

        async for chunk_str in run_agent_stream(trim_result.request_history, model=model):
            event = json.loads(chunk_str)
            if event.get("type") == "usage":
                latest_usage = event.get("data")
            else:
                print_event(event, ui)
                update_history_from_event(next_history, event)

    ui.finish_turn()
    return next_history, latest_usage


def save_if_needed(
    history: list[dict[str, Any]],
    model: str,
    options: "ResolvedOptions",
    ui: "ConsoleUI",
) -> None:
    if options.stateless:
        return
    session_path = save_session_messages(
        workspace_root=options.workspace_root,
        session_name=options.session,
        model=model,
        messages=history,
    )
    ui.session_saved(session_path)


async def run_once(args: object, config: object) -> int:
    options = resolve_runtime_options(args, config.defaults)
    ui = ConsoleUI(use_color=options.use_color, auto_approve=options.auto_approve)
    history: list[dict[str, Any]] = []

    if not options.stateless:
        history = load_session_messages(options.workspace_root, options.session)

    updated_history, latest_usage = await execute_instruction(
        instruction=args.instruction,
        model=options.model,
        history=history,
        options=options,
        ui=ui,
    )

    save_if_needed(updated_history, options.model, options, ui)
    if latest_usage and latest_usage.get("total_tokens") is not None:
        ui.usage(latest_usage)

    return 0


async def chat_loop(args: object, config: object) -> int:
    from apsara_cli.cli.banner import print_welcome_banner

    options = resolve_runtime_options(args, config.defaults)
    ui = ConsoleUI(use_color=options.use_color, auto_approve=options.auto_approve)
    history: list[dict[str, Any]] = []
    current_model = options.model
    turn_count = 0

    if not options.stateless:
        history = load_session_messages(options.workspace_root, options.session)

    print_welcome_banner(ui, config)

    # Session status line
    session_label = sanitize_session_name(options.session) if not options.stateless else "stateless"
    ui.print_line(
        f"  {ui.dim(f'  workspace  {options.workspace_root}')}"
    )
    ui.print_line(
        f"  {ui.dim(f'  session    {session_label}  ·  model  {current_model}')}"
    )
    if history:
        prior_turns = sum(1 for m in history if m.get("role") == "user")
        plural = "s" if prior_turns != 1 else ""
        ui.print_line(
            f"  {ui.dim(f'  resumed    {prior_turns} prior turn{plural}')}"
        )
        turn_count = prior_turns
    ui.print_line(
        f"  {ui.dim('  /help for commands  ·  /exit to quit  ·  Esc+Enter for newline')}"
    )

    while True:
        try:
            instruction = (await get_input_async(ui.prompt("you"), options.workspace_root)).strip()
        except KeyboardInterrupt:
            ui.print_line()
            ui.info("Ctrl+C pressed. Type /exit to quit.")
            continue
        except EOFError:
            ui.print_line()
            break

        if not instruction:
            continue
        if instruction.startswith("/"):
            should_continue, current_model = handle_chat_command(
                instruction, history, current_model, options, config, ui
            )
            if not should_continue:
                break
            continue

        turn_count += 1

        # Proactive token budget warning before executing
        try:
            from apsara_cli.engine.executor import SYSTEM_PROMPT
            from apsara_cli.engine.llm import estimate_request_tokens
            _base = [{"role": "system", "content": SYSTEM_PROMPT}]
            _curr_tokens = estimate_request_tokens(_base + history, model=current_model)
            _warn_threshold = int(SAFE_INPUT_TOKEN_BUDGET * 0.75)
            if _curr_tokens >= _warn_threshold:
                _pct = int(_curr_tokens / SAFE_INPUT_TOKEN_BUDGET * 100)
                ui.warning(
                    f"Context at {_pct}% capacity ({_curr_tokens:,} / {SAFE_INPUT_TOKEN_BUDGET:,} tokens). "
                    "Oldest turns may be trimmed — use /clear to reset."
                )
        except Exception:
            pass

        ui.print_turn_separator(turn_count)

        history, latest_usage = await execute_instruction(
            instruction=instruction,
            model=current_model,
            history=history,
            options=options,
            ui=ui,
        )

        save_if_needed(history, current_model, options, ui)
        if latest_usage and latest_usage.get("total_tokens") is not None:
            ui.usage(latest_usage)

    return 0
