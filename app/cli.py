import argparse
import asyncio
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Sequence, Set

from app.cli_config import CliConfig, CliDefaults, DEFAULT_CONFIG_PATH, load_cli_config
from app.services.agent.tools import agent_runtime_context, get_agent_tools


SESSION_ROOT_DIR = ".apsara-cli"
SESSIONS_DIR = "sessions"


@dataclass
class ResolvedOptions:
    workspace_root: Path
    model: str
    session: str
    stateless: bool
    allow_bash: bool
    allowed_commands: Optional[Set[str]]
    max_file_size: Optional[int]
    auto_approve: bool
    use_color: bool


def resolve_workspace(path_str: str) -> Path:
    return Path(path_str).expanduser().resolve()


def sanitize_session_name(name: str) -> str:
    sanitized = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip(".-")
    if not sanitized:
        raise ValueError(
            "Session name must contain letters, numbers, dots, dashes, or underscores."
        )
    return sanitized


def get_sessions_dir(workspace_root: Path) -> Path:
    return workspace_root / SESSION_ROOT_DIR / SESSIONS_DIR


def get_session_path(workspace_root: Path, session_name: str) -> Path:
    sanitized_name = sanitize_session_name(session_name)
    return get_sessions_dir(workspace_root) / f"{sanitized_name}.json"


def load_session_messages(
    workspace_root: Path, session_name: str
) -> list[dict[str, Any]]:
    session_path = get_session_path(workspace_root, session_name)
    if not session_path.exists():
        return []

    payload = json.loads(session_path.read_text(encoding="utf-8"))
    messages = payload.get("messages", [])
    if not isinstance(messages, list):
        raise ValueError(f"Session file '{session_path}' is invalid.")
    return messages


def save_session_messages(
    workspace_root: Path,
    session_name: str,
    model: str,
    messages: list[dict[str, Any]],
) -> Path:
    session_path = get_session_path(workspace_root, session_name)
    session_path.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "session_name": sanitize_session_name(session_name),
        "workspace_root": str(workspace_root),
        "model": model,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "messages": messages,
    }
    session_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return session_path


def list_sessions(workspace_root: Path) -> list[Path]:
    sessions_dir = get_sessions_dir(workspace_root)
    if not sessions_dir.exists():
        return []
    return sorted(path for path in sessions_dir.glob("*.json") if path.is_file())


def truncate_text(text: str, max_lines: int = 16, max_chars: int = 1200) -> str:
    if len(text) > max_chars:
        text = text[:max_chars].rstrip() + "\n... [truncated]"

    lines = text.splitlines()
    if len(lines) > max_lines:
        lines = lines[:max_lines] + ["... [truncated]"]
    return "\n".join(lines)


def summarize_history(history: list[dict[str, Any]], limit: int = 10) -> list[str]:
    summaries = []
    for message in history[-limit:]:
        role = str(message.get("role", "unknown"))
        content = str(message.get("content") or "").strip().replace("\n", " ")
        if len(content) > 100:
            content = content[:97].rstrip() + "..."
        summaries.append(f"{role:>9}: {content or '[no content]'}")
    return summaries


def default_use_color() -> bool:
    return sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


def resolve_value(explicit: Any, config_value: Any, fallback: Any) -> Any:
    if explicit is not None:
        return explicit
    if config_value is not None:
        return config_value
    return fallback


def parse_allowed_commands(raw_commands: Any) -> Optional[Set[str]]:
    if raw_commands is None:
        return None
    if isinstance(raw_commands, str):
        commands = {part.strip() for part in raw_commands.split(",") if part.strip()}
    elif isinstance(raw_commands, list):
        commands = {str(item).strip() for item in raw_commands if str(item).strip()}
    else:
        raise ValueError("Allowed commands must be a comma-separated string or a list.")

    if not commands:
        raise ValueError("Allowed commands cannot be empty when provided.")
    return commands


def resolve_runtime_options(
    args: argparse.Namespace,
    config_defaults: CliDefaults,
) -> ResolvedOptions:
    workspace = resolve_value(args.workspace, config_defaults.workspace, ".")
    model = resolve_value(args.model, config_defaults.model, "gpt-4o")
    session = resolve_value(args.session, config_defaults.session, "default")
    stateless = bool(resolve_value(args.stateless, config_defaults.stateless, False))
    allow_bash = bool(resolve_value(args.allow_bash, config_defaults.allow_bash, False))
    allowed_commands = parse_allowed_commands(
        resolve_value(args.allowed_commands, config_defaults.allowed_commands, None)
    )
    max_file_size = resolve_value(
        args.max_file_size, config_defaults.max_file_size, None
    )
    auto_approve = bool(
        resolve_value(args.auto_approve, config_defaults.auto_approve, False)
    )
    use_color = bool(resolve_value(args.color, config_defaults.color, default_use_color()))

    return ResolvedOptions(
        workspace_root=resolve_workspace(str(workspace)),
        model=str(model),
        session=str(session),
        stateless=stateless,
        allow_bash=allow_bash,
        allowed_commands=allowed_commands,
        max_file_size=max_file_size,
        auto_approve=auto_approve,
        use_color=use_color,
    )


class ConsoleUI:
    def __init__(self, use_color: bool, auto_approve: bool = False):
        self.use_color = use_color
        self.auto_approve = auto_approve
        self.approve_all = auto_approve

    def style(self, text: str, *codes: str) -> str:
        if not self.use_color:
            return text
        joined_codes = ";".join(codes)
        return f"\033[{joined_codes}m{text}\033[0m"

    def print_line(self, text: str = "") -> None:
        print(text)

    def status(self, text: str) -> None:
        self.print_line(self.style(f"[status] {text}", "33"))

    def info(self, text: str) -> None:
        self.print_line(self.style(text, "36"))

    def success(self, text: str) -> None:
        self.print_line(self.style(text, "32"))

    def warning(self, text: str) -> None:
        self.print_line(self.style(text, "33"))

    def error(self, text: str) -> None:
        self.print_line(self.style(text, "31"))

    def assistant(self, text: str) -> None:
        self.print_line()
        self.print_line(self.style("assistant>", "1", "35"))
        self.print_line(text)

    def tool_call(self, name: str, arguments: dict[str, Any]) -> None:
        arguments_text = json.dumps(arguments, ensure_ascii=True)
        self.print_line(self.style(f"[tool] {name} {arguments_text}", "34"))

    def tool_result(self, result: str) -> None:
        self.print_line(self.style("[tool-result]", "34"))
        self.print_line(result)

    def blocked(self, text: str) -> None:
        self.warning(f"[blocked] {text}")

    def usage(self, usage_data: dict[str, Any]) -> None:
        self.success(
            "[usage] "
            f"prompt={usage_data.get('prompt_tokens', '?')} "
            f"completion={usage_data.get('completion_tokens', '?')} "
            f"total={usage_data.get('total_tokens', '?')}"
        )

    def session_saved(self, session_path: Path) -> None:
        self.info(f"[session] saved to {session_path}")

    def confirm_action(self, action: str, payload: dict[str, Any]) -> bool:
        if self.approve_all:
            return True

        if not sys.stdin.isatty():
            self.error(
                f"Approval required for {action}, but stdin is not interactive. "
                "Re-run with --auto-approve if you trust this action."
            )
            return False

        title, preview = describe_action(action, payload)
        self.warning(f"[confirm] {title}")
        if preview:
            self.print_line(truncate_text(preview, max_lines=12, max_chars=900))
        response = input(self.style("Approve? [y]es/[n]o/[a]ll: ", "1", "33")).strip().lower()

        if response == "a":
            self.approve_all = True
            return True
        return response in {"y", "yes"}


def describe_action(action: str, payload: dict[str, Any]) -> tuple[str, Optional[str]]:
    if action == "write_to_file":
        path = payload.get("path", "<unknown>")
        preview = payload.get("content_preview")
        return (f"Write file {path}", preview if isinstance(preview, str) else None)

    if action == "replace_file_lines":
        path = payload.get("path", "<unknown>")
        start_line = payload.get("start_line", "?")
        end_line = payload.get("end_line", "?")
        preview = payload.get("replacement_preview")
        return (
            f"Replace lines {start_line}-{end_line} in {path}",
            preview if isinstance(preview, str) else None,
        )

    if action == "run_bash_command":
        command = payload.get("command", "")
        cwd = payload.get("cwd", "")
        return (f"Run command in {cwd}: {command}", None)

    return (f"Approve action: {action}", None)


def print_event(event: dict[str, Any], ui: ConsoleUI) -> None:
    event_type = event.get("type")

    if event_type == "status":
        ui.status(str(event.get("message", "")))
        return

    if event_type == "assistant_dispatch":
        content = str(event.get("content") or "").strip()
        if content:
            ui.assistant(content)
        tool_calls = event.get("tool_calls", [])
        if tool_calls:
            ui.info(f"[assistant] dispatched {len(tool_calls)} tool call(s)")
        return

    if event_type == "tool_call":
        ui.tool_call(str(event.get("name", "unknown_tool")), event.get("arguments", {}))
        return

    if event_type == "tool_result":
        ui.tool_result(truncate_text(str(event.get("result", ""))))
        return

    if event_type == "final_answer":
        ui.assistant(str(event.get("content", "")))
        return

    if event_type == "blocked":
        ui.blocked(str(event.get("message", "")))
        return

    if event_type == "error":
        ui.error(f"[error] {event.get('message', '')}")
        return


def update_history_from_event(
    history: list[dict[str, Any]],
    event: dict[str, Any],
) -> None:
    event_type = event.get("type")

    if event_type == "assistant_dispatch":
        history.append(
            {
                "role": "assistant",
                "content": event.get("content"),
                "tool_calls": event.get("tool_calls", []),
            }
        )
    elif event_type == "tool_result":
        history.append(
            {
                "role": "tool",
                "content": event.get("result"),
                "tool_call_id": event.get("tool_call_id"),
                "name": event.get("name", ""),
            }
        )
    elif event_type == "final_answer":
        history.append(
            {
                "role": "assistant",
                "content": event.get("content"),
            }
        )


async def execute_instruction(
    instruction: str,
    model: str,
    history: list[dict[str, Any]],
    options: ResolvedOptions,
    ui: ConsoleUI,
) -> tuple[list[dict[str, Any]], Optional[dict[str, Any]]]:
    from app.services.agent.executor import run_agent_stream

    next_history = list(history)
    next_history.append({"role": "user", "content": instruction})
    latest_usage = None

    with agent_runtime_context(
        workspace_root=options.workspace_root,
        enable_bash=options.allow_bash,
        allowed_commands=options.allowed_commands,
        max_file_size_bytes=options.max_file_size,
        confirmation_callback=None if options.auto_approve else ui.confirm_action,
    ):
        async for chunk_str in run_agent_stream(next_history, model=model):
            event = json.loads(chunk_str)
            if event.get("type") == "usage":
                latest_usage = event.get("data")
            else:
                print_event(event, ui)
                update_history_from_event(next_history, event)

    return next_history, latest_usage


def save_if_needed(
    history: list[dict[str, Any]],
    model: str,
    options: ResolvedOptions,
    ui: ConsoleUI,
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


def print_chat_help(ui: ConsoleUI) -> None:
    ui.info("Slash commands:")
    ui.print_line("/help      Show available chat commands")
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
    options: ResolvedOptions,
    config: CliConfig,
    ui: ConsoleUI,
) -> tuple[bool, str]:
    if command_text in {"/exit", "/quit"}:
        return False, current_model

    if command_text == "/help":
        print_chat_help(ui)
        return True, current_model

    if command_text == "/clear":
        history.clear()
        ui.warning("[session] cleared in memory")
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
        next_model = command_text[len("/model ") :].strip()
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
        ui.info(f"Config: {config.path} ({'loaded' if config.exists else 'default values'})")
        return True, current_model

    if command_text == "/save":
        save_if_needed(history, current_model, options, ui)
        return True, current_model

    ui.error("Unknown slash command. Type /help for a list of commands.")
    return True, current_model


async def run_once(
    args: argparse.Namespace,
    config: CliConfig,
) -> int:
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


async def chat_loop(
    args: argparse.Namespace,
    config: CliConfig,
) -> int:
    options = resolve_runtime_options(args, config.defaults)
    ui = ConsoleUI(use_color=options.use_color, auto_approve=options.auto_approve)
    history: list[dict[str, Any]] = []
    current_model = options.model

    if not options.stateless:
        history = load_session_messages(options.workspace_root, options.session)

    ui.info(f"Workspace: {options.workspace_root}")
    if options.stateless:
        ui.info("Session mode: stateless")
    else:
        ui.info(f"Session: {sanitize_session_name(options.session)}")
    ui.info(f"Model: {current_model}")
    ui.info("Type /help for chat commands.")

    while True:
        try:
            instruction = input(ui.style("\nyou> ", "1", "36")).strip()
        except EOFError:
            ui.print_line()
            break

        if not instruction:
            continue
        if instruction.startswith("/"):
            should_continue, current_model = handle_chat_command(
                instruction,
                history,
                current_model,
                options,
                config,
                ui,
            )
            if not should_continue:
                break
            continue

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


def print_sessions(args: argparse.Namespace, config: CliConfig) -> int:
    workspace_value = resolve_value(args.workspace, config.defaults.workspace, ".")
    workspace_root = resolve_workspace(str(workspace_value))
    sessions = list_sessions(workspace_root)
    if not sessions:
        print(f"No sessions found in {get_sessions_dir(workspace_root)}")
        return 0

    for session_path in sessions:
        print(session_path.stem)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="apsara",
        description="Local CLI for the Apsara coding assistant.",
    )
    parser.add_argument(
        "--config",
        default=None,
        help=(
            "Path to a TOML config file. Defaults to "
            f"{DEFAULT_CONFIG_PATH}"
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_shared_options(subparser: argparse.ArgumentParser) -> None:
        subparser.add_argument(
            "--workspace",
            default=None,
            help="Workspace root the agent is allowed to access.",
        )
        subparser.add_argument(
            "--model",
            default=None,
            help="Model name to send through LiteLLM.",
        )
        subparser.add_argument(
            "--session",
            default=None,
            help="Session name for local conversation persistence.",
        )
        subparser.add_argument(
            "--stateless",
            dest="stateless",
            action="store_true",
            default=None,
            help="Run without loading or saving local session history.",
        )
        subparser.add_argument(
            "--stateful",
            dest="stateless",
            action="store_false",
            help="Force session history on even if the config enables stateless mode.",
        )
        subparser.add_argument(
            "--allow-bash",
            dest="allow_bash",
            action="store_true",
            default=None,
            help="Enable the local bash tool for allowlisted non-interactive commands.",
        )
        subparser.add_argument(
            "--no-bash",
            dest="allow_bash",
            action="store_false",
            help="Disable the local bash tool for this run.",
        )
        subparser.add_argument(
            "--allowed-commands",
            default=None,
            help="Comma-separated command allowlist used with bash tool access.",
        )
        subparser.add_argument(
            "--max-file-size",
            type=int,
            default=None,
            help="Override the maximum readable file size in bytes for this run.",
        )
        subparser.add_argument(
            "--auto-approve",
            dest="auto_approve",
            action="store_true",
            default=None,
            help="Skip interactive confirmations for writes and local commands.",
        )
        subparser.add_argument(
            "--confirm",
            dest="auto_approve",
            action="store_false",
            help="Require confirmations even if the config auto-approves actions.",
        )
        subparser.add_argument(
            "--color",
            dest="color",
            action="store_true",
            default=None,
            help="Force colored terminal output.",
        )
        subparser.add_argument(
            "--no-color",
            dest="color",
            action="store_false",
            help="Disable colored terminal output.",
        )

    run_parser = subparsers.add_parser(
        "run", help="Run one instruction against the local workspace."
    )
    run_parser.add_argument("instruction", help="Instruction to send to the agent.")
    add_shared_options(run_parser)

    chat_parser = subparsers.add_parser(
        "chat", help="Open an interactive local chat session."
    )
    add_shared_options(chat_parser)

    sessions_parser = subparsers.add_parser(
        "sessions", help="List saved local sessions for a workspace."
    )
    sessions_parser.add_argument(
        "--workspace",
        default=None,
        help="Workspace root whose saved sessions should be listed.",
    )

    return parser


async def dispatch_command(args: argparse.Namespace, config: CliConfig) -> int:
    if args.command == "run":
        return await run_once(args, config)
    if args.command == "chat":
        return await chat_loop(args, config)
    if args.command == "sessions":
        return print_sessions(args, config)
    raise ValueError(f"Unknown command: {args.command}")


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        config = load_cli_config(args.config)
        return asyncio.run(dispatch_command(args, config))
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
