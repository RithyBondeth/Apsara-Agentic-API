import json
from pathlib import Path
from typing import Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from apsara_cli.shared.types import ResolvedOptions
    from apsara_cli.shared.ui import ConsoleUI

from apsara_cli.shared.events import print_event
from apsara_cli.cli.history import SAFE_INPUT_TOKEN_BUDGET, trim_history_for_request, update_history_from_event
from apsara_cli.cli.options import resolve_runtime_options
from apsara_cli.cli.session import load_session_messages, sanitize_session_name, save_session_messages
from apsara_cli.shared.text import summarize_history
from apsara_cli.shared.ui import ConsoleUI
from apsara_cli.engine.tools import agent_runtime_context, get_agent_tools


def print_chat_help(ui: "ConsoleUI") -> None:
    ui.info("Slash commands:")
    ui.print_line("/help      Show available chat commands")
    ui.print_line("/details   Show hidden internal activity from the latest turn")
    ui.print_line("/history   Show recent conversation turns")
    ui.print_line("/tools     Show enabled tools for this session")
    ui.print_line("/model     Show the current model")
    ui.print_line("/model X   Switch to a different model for later turns")
    ui.print_line("/session   Show session and workspace details")
    ui.print_line("/save      Save the current session now")
    ui.print_line("/clear     Clear in-memory conversation history")
    ui.print_line("/exit      Quit the chat session")


def handle_chat_command(
    command_text: str,
    history: list[dict[str, Any]],
    current_model: str,
    options: "ResolvedOptions",
    config: object,
    ui: "ConsoleUI",
) -> tuple[bool, str]:
    if command_text in {"/exit", "/quit"}:
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
        summaries = summarize_history(history)
        if not summaries:
            ui.info("No conversation history yet.")
        else:
            for line in summaries:
                ui.print_line(line)
        return True, current_model

    if command_text == "/tools":
        with agent_runtime_context(
            workspace_root=options.workspace_root,
            enable_bash=options.allow_bash,
            allowed_commands=options.allowed_commands,
            max_file_size_bytes=options.max_file_size,
        ):
            tools = [tool["function"]["name"] for tool in get_agent_tools()]
        ui.info("Enabled tools:")
        for tool_name in tools:
            ui.print_line(f"- {tool_name}")
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
        f"  {ui.dim('  /help for commands  ·  /exit to quit')}"
    )

    while True:
        try:
            instruction = input(ui.prompt("you")).strip()
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
