import difflib
import glob as _glob
import os
import shlex
import shutil
import subprocess
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, Optional, Set

from apsara_cli.config.defaults import settings


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
MAX_CONFIRMATION_FILE_BYTES = 200_000
MAX_CONFIRMATION_DIFF_PREVIEW_LINES = 80
MAX_CONFIRMATION_DIFF_FULL_LINES = 240


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


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(_workspace_root()))
    except ValueError:
        return str(path)


def _read_confirmation_text(path: Path) -> str:
    if not path.exists() or not path.is_file():
        return ""
    if path.stat().st_size > MAX_CONFIRMATION_FILE_BYTES:
        return ""
    with path.open("r", encoding="utf-8") as file_handle:
        return file_handle.read()


def _build_text_diff(
    before_text: str,
    after_text: str,
    display_path: str,
) -> tuple[str, str, str, bool]:
    diff_lines = list(
        difflib.unified_diff(
            before_text.splitlines(),
            after_text.splitlines(),
            fromfile=f"a/{display_path}",
            tofile=f"b/{display_path}",
            lineterm="",
        )
    )
    if not diff_lines:
        diff_lines = [f"No textual changes for {display_path}."]
    editor_diff = "\n".join(diff_lines)

    preview_lines = diff_lines[:MAX_CONFIRMATION_DIFF_PREVIEW_LINES]
    preview_truncated = len(diff_lines) > MAX_CONFIRMATION_DIFF_PREVIEW_LINES
    if preview_truncated:
        preview_lines.append("... [diff preview truncated]")

    full_lines = diff_lines[:MAX_CONFIRMATION_DIFF_FULL_LINES]
    full_truncated = len(diff_lines) > MAX_CONFIRMATION_DIFF_FULL_LINES
    if full_truncated:
        full_lines.append("... [full diff truncated]")

    return (
        "\n".join(preview_lines),
        "\n".join(full_lines),
        editor_diff,
        full_truncated,
    )


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


def read_file_lines(path: str, start_line: int, end_line: int) -> str:
    """Read a specific line range from a file (1-indexed, inclusive).
    Returns lines prefixed with their line number so the model can use
    replace_file_lines accurately."""
    try:
        resolved_path = _resolve_path(path, must_exist=True)
        if not resolved_path.is_file():
            return f"Error: '{path}' is not a file."

        if start_line < 1:
            return "Error: start_line must be >= 1."
        if end_line < start_line:
            return "Error: end_line must be >= start_line."

        with resolved_path.open("r", encoding="utf-8") as fh:
            all_lines = fh.readlines()

        total = len(all_lines)
        if start_line > total:
            return f"Error: start_line {start_line} exceeds file length ({total} lines)."

        actual_end = min(end_line, total)
        selected = all_lines[start_line - 1 : actual_end]

        numbered = "".join(
            f"{start_line + i:4d}: {line}" for i, line in enumerate(selected)
        )
        header = f"# {_display_path(resolved_path)}  (lines {start_line}–{actual_end} of {total})\n"
        return header + numbered
    except Exception as exc:
        return _format_exception("Error reading file lines", exc)


def create_directory(path: str) -> str:
    """Create a directory (and any missing parents) inside the workspace."""
    try:
        resolved_path = _resolve_path(path)
        if resolved_path.exists() and resolved_path.is_dir():
            return f"Directory already exists: {_display_path(resolved_path)}"
        resolved_path.mkdir(parents=True, exist_ok=True)
        return f"Created directory: {_display_path(resolved_path)}"
    except Exception as exc:
        return _format_exception("Error creating directory", exc)


def delete_file(path: str) -> str:
    """Delete a file inside the workspace (requires confirmation)."""
    try:
        resolved_path = _resolve_path(path, must_exist=True)
        if not resolved_path.is_file():
            return f"Error: '{path}' is not a file. Use the bash tool to remove directories."

        display = _display_path(resolved_path)
        preview = _read_confirmation_text(resolved_path)

        if not _confirm_action(
            "delete_file",
            {
                "path": str(resolved_path),
                "display_path": display,
                "content_preview": preview[:800] if preview else "(binary or unreadable)",
            },
        ):
            return f"Error: deletion of '{display}' was not approved."

        resolved_path.unlink()
        return f"Deleted: {display}"
    except Exception as exc:
        return _format_exception("Error deleting file", exc)


def move_file(src: str, dest: str) -> str:
    """Move or rename a file within the workspace (requires confirmation)."""
    try:
        resolved_src = _resolve_path(src, must_exist=True)
        resolved_dest = _resolve_path(dest)

        if not resolved_src.is_file():
            return f"Error: '{src}' is not a file."
        if resolved_dest.is_dir():
            resolved_dest = resolved_dest / resolved_src.name

        display_src = _display_path(resolved_src)
        display_dest = _display_path(resolved_dest)

        if not _confirm_action(
            "move_file",
            {
                "path": str(resolved_src),
                "display_path": display_src,
                "dest_path": str(resolved_dest),
                "display_dest": display_dest,
                "overwrites": resolved_dest.exists(),
            },
        ):
            return f"Error: move '{display_src}' → '{display_dest}' was not approved."

        resolved_dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(resolved_src), str(resolved_dest))
        return f"Moved: {display_src} → {display_dest}"
    except Exception as exc:
        return _format_exception("Error moving file", exc)


def glob_search(pattern: str, root_dir: str = ".") -> str:
    """Find files matching a glob pattern (e.g. **/*.py, src/**/*.ts).
    Returns paths relative to the workspace root, capped at 200 results."""
    try:
        resolved_root = _resolve_path(root_dir, must_exist=True)
        if not resolved_root.is_dir():
            return f"Error: '{root_dir}' is not a directory."

        matches = _glob.glob(
            str(resolved_root / pattern), recursive=True
        )
        # Filter to files only and enforce workspace boundary
        results: list[str] = []
        for m in sorted(matches):
            mp = Path(m)
            try:
                mp.relative_to(_workspace_root())
            except ValueError:
                continue
            if mp.is_file() or mp.is_dir():
                results.append(_display_path(mp))
            if len(results) >= 200:
                break

        if not results:
            return f"No matches for pattern '{pattern}' in '{root_dir}'."

        suffix = f"\n... (capped at 200)" if len(results) == 200 else ""
        return "\n".join(results) + suffix
    except Exception as exc:
        return _format_exception("Error in glob search", exc)


def write_to_file(path: str, content: str) -> str:
    try:
        resolved_path = _resolve_path(path)
        existing_content = _read_confirmation_text(resolved_path)
        display_path = _display_path(resolved_path)
        diff_preview, diff_full, diff_editor, diff_truncated = _build_text_diff(
            existing_content,
            content,
            display_path,
        )
        if not _confirm_action(
            "write_to_file",
            {
                "path": str(resolved_path),
                "display_path": display_path,
                "content_preview": content[:800],
                "existing_preview": existing_content[:800],
                "diff_preview": diff_preview,
                "diff_full": diff_full,
                "diff_editor": diff_editor,
                "diff_truncated": diff_truncated,
                "is_new_file": not resolved_path.exists(),
            },
        ):
            return f"Error writing file: write to '{resolved_path}' was not approved."
        resolved_path.parent.mkdir(parents=True, exist_ok=True)
        with resolved_path.open("w", encoding="utf-8") as file_handle:
            file_handle.write(content)
        return f"Successfully wrote to {resolved_path}"
    except Exception as exc:
        return _format_exception("Error writing file", exc)


def _extract_command_names(command: str) -> list[str]:
    """Return all command names used in a pipeline/chain (split on |, ||, &&, ;)."""
    import re
    segments = re.split(r"\|\|?|&&|;", command)
    names: list[str] = []
    for seg in segments:
        seg = seg.strip()
        if not seg:
            continue
        try:
            tokens = shlex.split(seg)
        except ValueError:
            tokens = seg.split()
        if tokens:
            names.append(tokens[0])
    return names


def run_bash_command(command: str) -> str:
    if not _bash_enabled():
        return "Error: The bash tool is disabled by configuration."

    try:
        if not command.strip():
            return "Error: Command cannot be empty."

        # Block only command-substitution patterns that can escape the allowlist
        if "`" in command or "$(" in command or "\n" in command:
            return "Error: Command substitution (backtick / $()) is not allowed."

        command_names = _extract_command_names(command)
        if not command_names:
            return "Error: Command cannot be empty."

        disallowed = [n for n in command_names if n not in _allowed_commands()]
        if disallowed:
            allowed = ", ".join(sorted(_allowed_commands()))
            return (
                f"Error: Command(s) not allowed: {', '.join(disallowed)}. "
                f"Allowed: {allowed}"
            )

        if not _confirm_action(
            "run_bash_command",
            {
                "command": command,
                "command_name": command_names[0],
                "cwd": str(_workspace_root()),
            },
        ):
            return f"Error executing command: command '{command}' was not approved."

        result = subprocess.run(
            command,
            shell=True,
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

        original_content = "".join(lines)
        original_slice = "".join(lines[start_line - 1 : end_line])
        prefix = lines[: start_line - 1]
        suffix = lines[end_line:] if end_line <= len(lines) else []
        updated_content = "".join(prefix)
        if replacement_content:
            updated_content += replacement_content
            if not replacement_content.endswith("\n"):
                updated_content += "\n"
        updated_content += "".join(suffix)
        display_path = _display_path(resolved_path)
        diff_preview, diff_full, diff_editor, diff_truncated = _build_text_diff(
            original_content,
            updated_content,
            display_path,
        )

        if not _confirm_action(
            "replace_file_lines",
            {
                "path": str(resolved_path),
                "display_path": display_path,
                "start_line": start_line,
                "end_line": end_line,
                "original_preview": original_slice[:800],
                "replacement_preview": replacement_content[:800],
                "diff_preview": diff_preview,
                "diff_full": diff_full,
                "diff_editor": diff_editor,
                "diff_truncated": diff_truncated,
            },
        ):
            return (
                "Error replacing lines: "
                f"update to '{resolved_path}' was not approved."
            )

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
            "Read the complete text contents of a file inside the workspace.",
            {
                "path": {
                    "type": "string",
                    "description": "The file path to read. Relative paths resolve from the workspace root.",
                }
            },
            ["path"],
        ),
        _tool_definition(
            "read_file_lines",
            "Read a specific range of lines from a file (1-indexed, inclusive). "
            "Use this instead of read_file when you only need part of a large file. "
            "Returns lines prefixed with their line numbers.",
            {
                "path": {
                    "type": "string",
                    "description": "The file path to read.",
                },
                "start_line": {
                    "type": "integer",
                    "description": "First line to read (1-indexed).",
                },
                "end_line": {
                    "type": "integer",
                    "description": "Last line to read (1-indexed, inclusive).",
                },
            },
            ["path", "start_line", "end_line"],
        ),
        _tool_definition(
            "glob_search",
            "Find files or directories matching a glob pattern inside the workspace "
            "(e.g. '**/*.py', 'src/**/*.ts', 'tests/test_*.py'). Returns up to 200 matches.",
            {
                "pattern": {
                    "type": "string",
                    "description": "Glob pattern. Use ** for recursive matching.",
                },
                "root_dir": {
                    "type": "string",
                    "description": "Directory to search from. Defaults to workspace root.",
                },
            },
            ["pattern"],
        ),
        _tool_definition(
            "create_directory",
            "Create a directory (and any missing parent directories) inside the workspace.",
            {
                "path": {
                    "type": "string",
                    "description": "Directory path to create. Relative paths resolve from the workspace root.",
                }
            },
            ["path"],
        ),
        _tool_definition(
            "delete_file",
            "Delete a file inside the workspace. Requires user confirmation.",
            {
                "path": {
                    "type": "string",
                    "description": "Path of the file to delete.",
                }
            },
            ["path"],
        ),
        _tool_definition(
            "move_file",
            "Move or rename a file within the workspace. Requires user confirmation.",
            {
                "src": {
                    "type": "string",
                    "description": "Current path of the file.",
                },
                "dest": {
                    "type": "string",
                    "description": "Destination path or directory.",
                },
            },
            ["src", "dest"],
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
                "Execute an allowlisted shell command from the workspace root. Pipes (|), &&, ||, and ; are supported as long as every command name is in the allowlist. Command substitution ($() and backticks) is not allowed.",
                {
                    "command": {
                        "type": "string",
                        "description": "Shell command string. Pipes and &&/||/; chaining are allowed between allowlisted commands.",
                    }
                },
                ["command"],
            )
        )

    return tools


def get_tool_registry() -> Dict[str, Callable[..., str]]:
    registry: Dict[str, Callable[..., str]] = {
        "read_file": read_file,
        "read_file_lines": read_file_lines,
        "write_to_file": write_to_file,
        "search_files": search_files,
        "glob_search": glob_search,
        "list_project_structure": list_project_structure,
        "replace_file_lines": replace_file_lines,
        "create_directory": create_directory,
        "delete_file": delete_file,
        "move_file": move_file,
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
