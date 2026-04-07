import argparse
import asyncio
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Sequence

from app.services.agent.tools import agent_runtime_context


SESSION_ROOT_DIR = ".apsara-cli"
SESSIONS_DIR = "sessions"


def resolve_workspace(path_str: str) -> Path:
    return Path(path_str).expanduser().resolve()


def sanitize_session_name(name: str) -> str:
    sanitized = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip(".-")
    if not sanitized:
        raise ValueError("Session name must contain letters, numbers, dots, dashes, or underscores.")
    return sanitized


def get_sessions_dir(workspace_root: Path) -> Path:
    return workspace_root / SESSION_ROOT_DIR / SESSIONS_DIR


def get_session_path(workspace_root: Path, session_name: str) -> Path:
    sanitized_name = sanitize_session_name(session_name)
    return get_sessions_dir(workspace_root) / f"{sanitized_name}.json"


def load_session_messages(workspace_root: Path, session_name: str) -> list[dict[str, Any]]:
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


def print_event(event: dict[str, Any]) -> None:
    event_type = event.get("type")

    if event_type == "status":
        print(f"[status] {event.get('message', '')}")
        return

    if event_type == "assistant_dispatch":
        content = (event.get("content") or "").strip()
        if content:
            print("\nassistant>")
            print(content)
        tool_calls = event.get("tool_calls", [])
        if tool_calls:
            print(f"[assistant] dispatched {len(tool_calls)} tool call(s)")
        return

    if event_type == "tool_call":
        name = event.get("name", "unknown_tool")
        arguments = json.dumps(event.get("arguments", {}), ensure_ascii=True)
        print(f"[tool] {name} {arguments}")
        return

    if event_type == "tool_result":
        result = truncate_text(str(event.get("result", "")))
        print("[tool-result]")
        print(result)
        return

    if event_type == "final_answer":
        print("\nassistant>")
        print(event.get("content", ""))
        return

    if event_type == "blocked":
        print(f"[blocked] {event.get('message', '')}")
        return

    if event_type == "error":
        print(f"[error] {event.get('message', '')}")
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


def parse_allowed_commands(raw_commands: Optional[str]) -> Optional[set[str]]:
    if raw_commands is None:
        return None
    commands = {part.strip() for part in raw_commands.split(",") if part.strip()}
    if not commands:
        raise ValueError("Allowed commands cannot be empty when provided.")
    return commands


async def execute_instruction(
    instruction: str,
    model: str,
    history: list[dict[str, Any]],
    workspace_root: Path,
    allow_bash: bool,
    allowed_commands: Optional[set[str]],
    max_file_size_bytes: Optional[int],
) -> tuple[list[dict[str, Any]], Optional[dict[str, Any]]]:
    from app.services.agent.executor import run_agent_stream

    next_history = list(history)
    next_history.append({"role": "user", "content": instruction})
    latest_usage = None

    with agent_runtime_context(
        workspace_root=workspace_root,
        enable_bash=allow_bash,
        allowed_commands=allowed_commands,
        max_file_size_bytes=max_file_size_bytes,
    ):
        async for chunk_str in run_agent_stream(next_history, model=model):
            event = json.loads(chunk_str)
            if event.get("type") == "usage":
                latest_usage = event.get("data")
            else:
                print_event(event)
                update_history_from_event(next_history, event)

    return next_history, latest_usage


async def run_once(args: argparse.Namespace) -> int:
    workspace_root = resolve_workspace(args.workspace)
    history: list[dict[str, Any]] = []

    if not args.stateless:
        history = load_session_messages(workspace_root, args.session)

    updated_history, latest_usage = await execute_instruction(
        instruction=args.instruction,
        model=args.model,
        history=history,
        workspace_root=workspace_root,
        allow_bash=args.allow_bash,
        allowed_commands=parse_allowed_commands(args.allowed_commands),
        max_file_size_bytes=args.max_file_size,
    )

    if not args.stateless:
        session_path = save_session_messages(
            workspace_root=workspace_root,
            session_name=args.session,
            model=args.model,
            messages=updated_history,
        )
        print(f"\n[session] saved to {session_path}")

    if latest_usage and latest_usage.get("total_tokens") is not None:
        print(
            "[usage] "
            f"prompt={latest_usage.get('prompt_tokens', '?')} "
            f"completion={latest_usage.get('completion_tokens', '?')} "
            f"total={latest_usage.get('total_tokens', '?')}"
        )

    return 0


async def chat_loop(args: argparse.Namespace) -> int:
    workspace_root = resolve_workspace(args.workspace)
    history: list[dict[str, Any]] = []

    if not args.stateless:
        history = load_session_messages(workspace_root, args.session)

    print(f"Workspace: {workspace_root}")
    if not args.stateless:
        print(f"Session: {sanitize_session_name(args.session)}")
    print(f"Model: {args.model}")
    print("Type /exit to quit, /clear to reset the current session in memory.")

    while True:
        try:
            instruction = input("\nyou> ").strip()
        except EOFError:
            print()
            break

        if not instruction:
            continue
        if instruction in {"/exit", "/quit"}:
            break
        if instruction == "/clear":
            history = []
            print("[session] cleared in memory")
            continue

        history, latest_usage = await execute_instruction(
            instruction=instruction,
            model=args.model,
            history=history,
            workspace_root=workspace_root,
            allow_bash=args.allow_bash,
            allowed_commands=parse_allowed_commands(args.allowed_commands),
            max_file_size_bytes=args.max_file_size,
        )

        if not args.stateless:
            session_path = save_session_messages(
                workspace_root=workspace_root,
                session_name=args.session,
                model=args.model,
                messages=history,
            )
            print(f"[session] saved to {session_path}")

        if latest_usage and latest_usage.get("total_tokens") is not None:
            print(
                "[usage] "
                f"prompt={latest_usage.get('prompt_tokens', '?')} "
                f"completion={latest_usage.get('completion_tokens', '?')} "
                f"total={latest_usage.get('total_tokens', '?')}"
            )

    return 0


def print_sessions(args: argparse.Namespace) -> int:
    workspace_root = resolve_workspace(args.workspace)
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
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_shared_options(subparser: argparse.ArgumentParser) -> None:
        subparser.add_argument(
            "--workspace",
            default=".",
            help="Workspace root the agent is allowed to access. Defaults to the current directory.",
        )
        subparser.add_argument(
            "--model",
            default="gpt-4o",
            help="Model name to send through LiteLLM.",
        )
        subparser.add_argument(
            "--session",
            default="default",
            help="Session name for local conversation persistence.",
        )
        subparser.add_argument(
            "--stateless",
            action="store_true",
            help="Run without loading or saving local session history.",
        )
        subparser.add_argument(
            "--allow-bash",
            action="store_true",
            help="Enable the local bash tool for allowlisted non-interactive commands.",
        )
        subparser.add_argument(
            "--allowed-commands",
            help="Comma-separated command allowlist used with --allow-bash.",
        )
        subparser.add_argument(
            "--max-file-size",
            type=int,
            help="Override the maximum readable file size in bytes for this run.",
        )

    run_parser = subparsers.add_parser("run", help="Run one instruction against the local workspace.")
    run_parser.add_argument("instruction", help="Instruction to send to the agent.")
    add_shared_options(run_parser)

    chat_parser = subparsers.add_parser("chat", help="Open an interactive local chat session.")
    add_shared_options(chat_parser)

    sessions_parser = subparsers.add_parser("sessions", help="List saved local sessions for a workspace.")
    sessions_parser.add_argument(
        "--workspace",
        default=".",
        help="Workspace root whose saved sessions should be listed.",
    )

    return parser


async def dispatch_command(args: argparse.Namespace) -> int:
    if args.command == "run":
        return await run_once(args)
    if args.command == "chat":
        return await chat_loop(args)
    if args.command == "sessions":
        return print_sessions(args)
    raise ValueError(f"Unknown command: {args.command}")


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        return asyncio.run(dispatch_command(args))
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
