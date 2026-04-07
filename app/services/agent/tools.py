import os
import shlex
import subprocess
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, Optional, Set

from app.core.config import settings


class ToolSecurityError(Exception):
    """Raised when a tool request breaks sandbox rules."""


ConfirmationCallback = Callable[[str, Dict[str, Any]], bool]

_workspace_root_override: ContextVar[Optional[Path]] = ContextVar(
    "workspace_root_override", default=None
)
_enable_bash_override: ContextVar[Optional[bool]] = ContextVar(
    "enable_bash_override", default=None
)
_allowed_commands_override: ContextVar[Optional[Set[str]]] = ContextVar(
    "allowed_commands_override", default=None
)
_max_file_size_override: ContextVar[Optional[int]] = ContextVar(
    "max_file_size_override", default=None
)
_confirmation_callback_override: ContextVar[Optional[ConfirmationCallback]] = ContextVar(
    "confirmation_callback_override", default=None
)


@contextmanager
def agent_runtime_context(
    workspace_root: Optional[Path] = None,
    enable_bash: Optional[bool] = None,
    allowed_commands: Optional[Set[str]] = None,
    max_file_size_bytes: Optional[int] = None,
    confirmation_callback: Optional[ConfirmationCallback] = None,
) -> Iterator[None]:
    workspace_token = None
    bash_token = None
    commands_token = None
    file_size_token = None
    confirmation_token = None

    try:
        if workspace_root is not None:
            workspace_token = _workspace_root_override.set(workspace_root.resolve())
        if enable_bash is not None:
            bash_token = _enable_bash_override.set(enable_bash)
        if allowed_commands is not None:
            commands_token = _allowed_commands_override.set(set(allowed_commands))
        if max_file_size_bytes is not None:
            file_size_token = _max_file_size_override.set(max_file_size_bytes)
        if confirmation_callback is not None:
            confirmation_token = _confirmation_callback_override.set(
                confirmation_callback
            )
        yield
    finally:
        if confirmation_token is not None:
            _confirmation_callback_override.reset(confirmation_token)
        if file_size_token is not None:
            _max_file_size_override.reset(file_size_token)
        if commands_token is not None:
            _allowed_commands_override.reset(commands_token)
        if bash_token is not None:
            _enable_bash_override.reset(bash_token)
        if workspace_token is not None:
            _workspace_root_override.reset(workspace_token)


def _workspace_root() -> Path:
    overridden_root = _workspace_root_override.get()
    if overridden_root is not None:
        return overridden_root
    return settings.agent_workspace_root_path


def _bash_enabled() -> bool:
    overridden_value = _enable_bash_override.get()
    if overridden_value is not None:
        return overridden_value
    return settings.AGENT_ENABLE_BASH_TOOL


def _allowed_commands() -> Set[str]:
    overridden_commands = _allowed_commands_override.get()
    if overridden_commands is not None:
        return overridden_commands
    return settings.agent_allowed_commands


def _max_file_size_bytes() -> int:
    overridden_max = _max_file_size_override.get()
    if overridden_max is not None:
        return overridden_max
    return settings.AGENT_MAX_FILE_SIZE_BYTES


def _resolve_path(path: str, *, must_exist: bool = False) -> Path:
    requested_path = Path(path).expanduser()
    candidate = requested_path
    if not requested_path.is_absolute():
        candidate = _workspace_root() / requested_path

    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(_workspace_root())
    except ValueError as exc:
        raise ToolSecurityError(
            f"Path '{path}' is outside the configured workspace root."
        ) from exc

    if must_exist and not resolved.exists():
        raise FileNotFoundError(f"Path '{path}' does not exist.")

    return resolved


def _format_exception(prefix: str, exc: Exception) -> str:
    return f"{prefix}: {str(exc)}"


def _confirm_action(action: str, payload: Dict[str, Any]) -> bool:
    callback = _confirmation_callback_override.get()
    if callback is None:
        return True
    return callback(action, payload)


def read_file(path: str) -> str:
    try:
        resolved_path = _resolve_path(path, must_exist=True)
        if not resolved_path.is_file():
            return f"Error reading file: '{path}' is not a file."

        file_size = resolved_path.stat().st_size
        if file_size > _max_file_size_bytes():
            return (
                "Error reading file: "
                f"'{path}' exceeds {_max_file_size_bytes()} bytes."
            )

        with resolved_path.open("r", encoding="utf-8") as file_handle:
            return file_handle.read()
    except Exception as exc:
        return _format_exception("Error reading file", exc)


def write_to_file(path: str, content: str) -> str:
    try:
        resolved_path = _resolve_path(path)
        if not _confirm_action(
            "write_to_file",
            {
                "path": str(resolved_path),
                "content_preview": content[:800],
            },
        ):
            return f"Error writing file: write to '{resolved_path}' was not approved."
        resolved_path.parent.mkdir(parents=True, exist_ok=True)
        with resolved_path.open("w", encoding="utf-8") as file_handle:
            file_handle.write(content)
        return f"Successfully wrote to {resolved_path}"
    except Exception as exc:
        return _format_exception("Error writing file", exc)


def run_bash_command(command: str) -> str:
    if not _bash_enabled():
        return "Error: The bash tool is disabled by configuration."

    try:
        if not command.strip():
            return "Error: Command cannot be empty."

        blocked_tokens = ["|", "&", ";", "`", "$(", ">", "<", "\n"]
        if any(token in command for token in blocked_tokens):
            return "Error: Shell control operators are not allowed."

        args = shlex.split(command)
        if not args:
            return "Error: Command cannot be empty."

        command_name = args[0]
        if command_name not in _allowed_commands():
            allowed = ", ".join(sorted(_allowed_commands()))
            return (
                f"Error: Command '{command_name}' is not allowed. "
                f"Allowed commands: {allowed}"
            )

        if not _confirm_action(
            "run_bash_command",
            {
                "command": command,
                "command_name": command_name,
                "cwd": str(_workspace_root()),
            },
        ):
            return f"Error executing command: command '{command}' was not approved."

        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(_workspace_root()),
        )
        return (
            f"STDOUT:\n{result.stdout}\n"
            f"STDERR:\n{result.stderr}\n"
            f"EXIT CODE: {result.returncode}"
        )
    except subprocess.TimeoutExpired:
        return "Error: Command timed out after 30 seconds."
    except Exception as exc:
        return _format_exception("Error executing command", exc)


def search_files(pattern: str, root_dir: str = ".") -> str:
    try:
        resolved_root = _resolve_path(root_dir, must_exist=True)
        if not resolved_root.is_dir():
            return f"Error searching files: '{root_dir}' is not a directory."

        try:
            result = subprocess.run(
                [
                    "rg",
                    "--line-number",
                    "--no-heading",
                    "--text",
                    "--max-count",
                    "100",
                    "--",
                    pattern,
                    str(resolved_root),
                ],
                capture_output=True,
                text=True,
                timeout=30,
                cwd=str(_workspace_root()),
            )
        except FileNotFoundError:
            result = subprocess.run(
                ["grep", "-rnI", "--", pattern, str(resolved_root)],
                capture_output=True,
                text=True,
                timeout=30,
                cwd=str(_workspace_root()),
            )

        if result.returncode not in (0, 1):
            return _format_exception("Error searching files", Exception(result.stderr))
        return result.stdout if result.stdout else "No matches found."
    except Exception as exc:
        return _format_exception("Error searching files", exc)


def list_project_structure(root_dir: str = ".") -> str:
    try:
        resolved_root = _resolve_path(root_dir, must_exist=True)
        if not resolved_root.is_dir():
            return f"Error listing structure: '{root_dir}' is not a directory."

        entries = []
        max_depth = 3
        max_entries = 100
        root_depth = len(resolved_root.parts)

        for current_root, dir_names, file_names in os.walk(resolved_root):
            current_path = Path(current_root)
            depth = len(current_path.parts) - root_depth
            dir_names[:] = sorted(
                [
                    directory
                    for directory in dir_names
                    if not directory.startswith(".") and depth < max_depth
                ]
            )

            if depth > max_depth:
                continue

            if current_path != resolved_root:
                entries.append(str(current_path))
                if len(entries) >= max_entries:
                    break

            for file_name in sorted(
                file_name for file_name in file_names if not file_name.startswith(".")
            ):
                file_path = current_path / file_name
                entries.append(str(file_path))
                if len(entries) >= max_entries:
                    break

            if len(entries) >= max_entries:
                break

        return "\n".join(entries) if entries else "Empty or could not read."
    except Exception as exc:
        return _format_exception("Error listing structure", exc)


def replace_file_lines(
    path: str,
    start_line: int,
    end_line: int,
    replacement_content: str,
) -> str:
    try:
        resolved_path = _resolve_path(path, must_exist=True)
        if not resolved_path.is_file():
            return f"Error replacing lines: '{path}' is not a file."

        with resolved_path.open("r", encoding="utf-8") as file_handle:
            lines = file_handle.readlines()

        if start_line < 1 or start_line > len(lines):
            return f"Error: start_line {start_line} is out of bounds."
        if end_line < start_line:
            return "Error: end_line cannot be before start_line."

        if not _confirm_action(
            "replace_file_lines",
            {
                "path": str(resolved_path),
                "start_line": start_line,
                "end_line": end_line,
                "replacement_preview": replacement_content[:800],
            },
        ):
            return (
                "Error replacing lines: "
                f"update to '{resolved_path}' was not approved."
            )

        prefix = lines[: start_line - 1]
        suffix = lines[end_line:] if end_line <= len(lines) else []

        with resolved_path.open("w", encoding="utf-8") as file_handle:
            file_handle.writelines(prefix)
            if replacement_content:
                file_handle.write(replacement_content)
                if not replacement_content.endswith("\n"):
                    file_handle.write("\n")
            file_handle.writelines(suffix)

        return (
            "Successfully replaced lines "
            f"{start_line} to {end_line} in {resolved_path}."
        )
    except Exception as exc:
        return _format_exception("Error replacing lines", exc)


def _tool_definition(
    name: str,
    description: str,
    properties: Dict[str, Any],
    required: Optional[list[str]] = None,
) -> Dict[str, Any]:
    definition = {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
            },
        },
    }
    if required:
        definition["function"]["parameters"]["required"] = required
    return definition


def get_agent_tools() -> list[Dict[str, Any]]:
    tools = [
        _tool_definition(
            "read_file",
            "Read the text contents of a file at a specific path inside the configured workspace.",
            {
                "path": {
                    "type": "string",
                    "description": "The file path to read. Relative paths resolve from the workspace root.",
                }
            },
            ["path"],
        ),
        _tool_definition(
            "write_to_file",
            "Create or overwrite a file with exact string contents inside the configured workspace.",
            {
                "path": {
                    "type": "string",
                    "description": "The file path to write. Relative paths resolve from the workspace root.",
                },
                "content": {
                    "type": "string",
                    "description": "The complete text content to write.",
                },
            },
            ["path", "content"],
        ),
        _tool_definition(
            "search_files",
            "Search for a string or regex inside files under the configured workspace.",
            {
                "pattern": {
                    "type": "string",
                    "description": "The search term or regex.",
                },
                "root_dir": {
                    "type": "string",
                    "description": "The directory to search. Defaults to the workspace root.",
                },
            },
            ["pattern"],
        ),
        _tool_definition(
            "list_project_structure",
            "List files and folders up to three levels deep under the configured workspace.",
            {
                "root_dir": {
                    "type": "string",
                    "description": "The directory to inspect. Defaults to the workspace root.",
                }
            },
        ),
        _tool_definition(
            "replace_file_lines",
            "Replace specific lines of code inside a file within the configured workspace.",
            {
                "path": {
                    "type": "string",
                    "description": "The file path to update.",
                },
                "start_line": {
                    "type": "integer",
                    "description": "1-indexed starting line number of the block to replace.",
                },
                "end_line": {
                    "type": "integer",
                    "description": "1-indexed ending line number of the block to replace.",
                },
                "replacement_content": {
                    "type": "string",
                    "description": "The exact string content to insert over the replaced lines.",
                },
            },
            ["path", "start_line", "end_line", "replacement_content"],
        ),
    ]

    if _bash_enabled():
        tools.append(
            _tool_definition(
                "run_bash_command",
                "Execute an allowlisted non-interactive command from the workspace root.",
                {
                    "command": {
                        "type": "string",
                        "description": "A simple command string with no shell control operators.",
                    }
                },
                ["command"],
            )
        )

    return tools


def get_tool_registry() -> Dict[str, Callable[..., str]]:
    registry: Dict[str, Callable[..., str]] = {
        "read_file": read_file,
        "write_to_file": write_to_file,
        "search_files": search_files,
        "list_project_structure": list_project_structure,
        "replace_file_lines": replace_file_lines,
    }
    if _bash_enabled():
        registry["run_bash_command"] = run_bash_command
    return registry


AGENT_TOOLS = get_agent_tools()


def execute_tool(tool_name: str, arguments: Dict[str, Any]) -> str:
    registry = get_tool_registry()
    if tool_name not in registry:
        return f"Error: Tool '{tool_name}' not found."

    try:
        func = registry[tool_name]
        return func(**arguments)
    except Exception as exc:
        return _format_exception("Error executing internal tool", exc)
