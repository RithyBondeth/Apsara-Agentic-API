import argparse
import json
from pathlib import Path
from typing import Sequence

from apsara_cli.cli.options import resolve_value, resolve_workspace
from apsara_cli.cli.session import get_sessions_dir, list_sessions, sanitize_session_name
from apsara_cli.shared.ui import ConsoleUI, default_use_color

    from apsara_cli.cli.chat import chat_loop
    return await chat_loop(init_args, initialized_config)


def print_sessions(args: argparse.Namespace, config: object) -> int:
    workspace_value = resolve_value(args.workspace, config.defaults.workspace, ".")
    workspace_root = resolve_workspace(str(workspace_value))
    sessions = list_sessions(workspace_root)
    if not sessions:
        print(f"No sessions found in {get_sessions_dir(workspace_root)}")
        return 0

    for session_path in sessions:
        print(session_path.stem)
    return 0
