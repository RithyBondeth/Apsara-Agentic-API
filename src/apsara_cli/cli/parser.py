import argparse
from typing import Optional, Sequence

from apsara_cli.config.settings import DEFAULT_CONFIG_PATH


def _add_shared_options(subparser: argparse.ArgumentParser) -> None:
    subparser.add_argument("--workspace", default=None, help="Workspace root the agent is allowed to access.")
    subparser.add_argument("--model", default=None, help="Model name to send through LiteLLM.")
    subparser.add_argument("--session", default=None, help="Session name for local conversation persistence.")
    subparser.add_argument("--stateless", dest="stateless", action="store_true", default=None,
                           help="Run without loading or saving local session history.")
    subparser.add_argument("--stateful", dest="stateless", action="store_false",
                           help="Force session history on even if the config enables stateless mode.")
    subparser.add_argument("--allow-bash", dest="allow_bash", action="store_true", default=None,
                           help="Enable the local bash tool for allowlisted non-interactive commands.")
    subparser.add_argument("--no-bash", dest="allow_bash", action="store_false",
                           help="Disable the local bash tool for this run.")
    subparser.add_argument("--allowed-commands", default=None,
                           help="Comma-separated command allowlist used with bash tool access.")
    subparser.add_argument("--max-file-size", type=int, default=None,
                           help="Override the maximum readable file size in bytes for this run.")
    subparser.add_argument("--auto-approve", dest="auto_approve", action="store_true", default=None,
                           help="Skip interactive confirmations for writes and local commands.")
    subparser.add_argument("--confirm", dest="auto_approve", action="store_false",
                           help="Require confirmations even if the config auto-approves actions.")
    subparser.add_argument("--color", dest="color", action="store_true", default=None,
                           help="Force colored terminal output.")
    subparser.add_argument("--no-color", dest="color", action="store_false",
                           help="Disable colored terminal output.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="apsara", description="Local CLI for Apsara.")
    parser.add_argument("--config", default=None,
                        help=f"Path to a TOML config file. Defaults to {DEFAULT_CONFIG_PATH}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Run one instruction against the local workspace.")
    run_parser.add_argument("instruction", help="Instruction to send to the agent.")
    _add_shared_options(run_parser)

    chat_parser = subparsers.add_parser("chat", help="Open an interactive local chat session.")
    _add_shared_options(chat_parser)

    init_parser = subparsers.add_parser("init", help="Initialize Apsara in the current project and open chat.")
    _add_shared_options(init_parser)
    init_parser.add_argument("--force", action="store_true",
                             help="Rewrite the local .apsara/config.toml file even if it already exists.")
    init_parser.add_argument("--no-chat", action="store_true",
                             help="Initialize the project without opening chat immediately.")

    sessions_parser = subparsers.add_parser("sessions", help="List saved local sessions for a workspace.")
    sessions_parser.add_argument("--workspace", default=None,
                                 help="Workspace root whose saved sessions should be listed.")

    doctor_parser = subparsers.add_parser(
        "doctor", help="Validate config, workspace access, tool readiness, and likely model credentials."
    )
    _add_shared_options(doctor_parser)
    doctor_parser.add_argument("--live", action="store_true",
                               help="Attempt a short live model probe after offline checks pass.")

    return parser


async def dispatch_command(args: argparse.Namespace, config: object) -> int:
    if args.command == "run":
        from apsara_cli.cli.chat import run_once
        return await run_once(args, config)
    if args.command == "chat":
        from apsara_cli.cli.chat import chat_loop
        return await chat_loop(args, config)
    if args.command == "init":
        from apsara_cli.cli.workspace import init_workspace
        return await init_workspace(args, config)
    if args.command == "sessions":
        from apsara_cli.cli.workspace import print_sessions
        return print_sessions(args, config)
    if args.command == "doctor":
        from apsara_cli.cli.doctor import doctor
        return await doctor(args, config)
    raise ValueError(f"Unknown command: {args.command}")


def main(argv: Optional[Sequence[str]] = None) -> int:
    import asyncio
    import sys

    from apsara_cli.config.settings import load_cli_config
    from apsara_cli.cli.options import load_cli_environment

    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        config = load_cli_config(args.config, getattr(args, "workspace", None))
        load_cli_environment(args, config)
        return asyncio.run(dispatch_command(args, config))
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
