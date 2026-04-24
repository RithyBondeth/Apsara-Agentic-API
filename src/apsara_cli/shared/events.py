import json
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from apsara_cli.shared.ui import ConsoleUI

from apsara_cli.shared.text import truncate_text


def _tool_spinner_label(tool_name: str, arguments: dict[str, Any]) -> str:
    """Return a short human-readable label for what a tool is doing."""
    n = tool_name.lower()

    def _first(*keys: str) -> str:
        for k in keys:
            v = arguments.get(k)
            if v and isinstance(v, str):
                display = v if len(v) <= 40 else v[:37] + "…"
                return f'"{display}"'
        return ""

    if n in {"read_file", "read_file_lines"}:
        return f"reading {_first('path', 'file_path')}"
    if n == "write_to_file":
        return f"writing {_first('path', 'file_path')}"
    if n == "replace_file_lines":
        return f"editing {_first('path', 'file_path')}"
    if n in {"search_in_file", "search_codebase", "grep_search"}:
        return f"searching {_first('query', 'pattern', 'search_term')}"
    if n == "run_bash_command":
        cmd = arguments.get("command", "")
        short = cmd if len(cmd) <= 36 else cmd[:33] + "…"
        return f"running  {short}"
    if n == "list_project_structure":
        return "scanning workspace"
    if n == "create_directory":
        return f"creating dir {_first('path', 'directory')}"
    if n == "delete_file":
        return f"deleting {_first('path')}"
    if n == "move_file":
        return f"moving file"
    return f"calling {tool_name}"


def _tool_result_summary(tool_name: str, result: str) -> tuple[bool, str]:
    """Return (success, short summary) for a tool result."""
    is_error = result.startswith("Error") or result.startswith("error")
    if is_error:
        short = result.split("\n")[0][:60]
        return False, short

    lines = result.splitlines()
    line_count = len(lines)
    char_count = len(result)

    n = tool_name.lower()
    if n in {"read_file", "read_file_lines"}:
        return True, f"{line_count} line{'s' if line_count != 1 else ''} read"
    if n == "write_to_file":
        return True, f"written  ({char_count} chars)"
    if n == "replace_file_lines":
        return True, "lines replaced"
    if n in {"search_in_file", "search_codebase", "grep_search"}:
        return True, f"{line_count} result{'s' if line_count != 1 else ''}"
    if n == "run_bash_command":
        return True, f"exit ok  ({line_count} lines output)"
    if n == "list_project_structure":
        return True, f"{line_count} paths"
    return True, "done"


def print_event(event: dict[str, Any], ui: "ConsoleUI") -> None:
    event_type = event.get("type")

    if event_type == "retry_notice":
        delay = event.get("delay", 5)
        attempt = event.get("attempt", 1)
        ui.stop_spinner()
        ui.warning(f"Rate limited — retrying in {delay}s (attempt {attempt}/3)...")
        return

    if event_type == "status":
        message = str(event.get("message", "")).strip() or "Apsara is thinking"
        normalized = "Apsara is thinking" if "thinking" in message.lower() else "Apsara is working"
        ui.note_working(normalized)
        ui.hide_event("status", message, message)
        return

    if event_type == "assistant_dispatch":
        content = str(event.get("content") or "").strip()
        tool_calls = event.get("tool_calls", [])
        detail_parts: list[str] = []
        if content:
            detail_parts.append(content)
        if tool_calls:
            tool_names = ", ".join(
                str(tc.get("function", {}).get("name", "unknown_tool")) for tc in tool_calls
            )
            detail_parts.append(f"Tool calls: {tool_names}")
        ui.note_working()
        ui.hide_event(
            "thinking",
            f"Apsara planned {len(tool_calls)} tool call(s)" if tool_calls else "Apsara drafted an internal step",
            "\n\n".join(part for part in detail_parts if part),
        )
        return

    if event_type == "tool_call":
        tool_name = str(event.get("name", "unknown_tool"))
        args = event.get("arguments", {})
        if not isinstance(args, dict):
            args = {}

        # Update spinner to show which tool is running
        label = _tool_spinner_label(tool_name, args)
        ui.update_spinner_action(label)
        ui.note_working(label)

        ui.hide_event(
            "tool",
            f"Tool call: {tool_name}",
            json.dumps(args, ensure_ascii=True, indent=2),
        )
        return

    if event_type == "tool_result":
        tool_name = str(event.get("name", "unknown_tool"))
        result = str(event.get("result", ""))
        success, summary = _tool_result_summary(tool_name, result)

        # Show compact inline indicator
        ui.stop_spinner()
        ui.tool_activity(tool_name, "")
        ui.tool_result_activity(tool_name, success, summary)

        # Resume spinner for next step
        ui.update_spinner_action("Apsara is working")
        ui.note_working()
        # Reset work_notice_shown so spinner restarts fresh
        ui.work_notice_shown = False
        ui.start_spinner("Apsara is working")

        ui.hide_event(
            "result",
            f"Tool result: {tool_name}",
            truncate_text(result, max_lines=20, max_chars=1800),
        )
        return

    if event_type == "response_start":
        ui.stream_text_start()
        return

    if event_type == "text_chunk":
        ui.stream_text_chunk(str(event.get("content", "")))
        return

    if event_type == "response_end":
        ui.stream_text_end()
        return

    if event_type == "final_answer":
        ui.stop_spinner()
        ui.assistant(str(event.get("content", "")))
        return

    if event_type == "blocked":
        ui.blocked(str(event.get("message", "")))
        return

    if event_type == "error":
        ui.error(str(event.get("message", "")))
        return
