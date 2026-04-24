import json
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from app.cli.ui import ConsoleUI

from app.cli.text import truncate_text


def print_event(event: dict[str, Any], ui: "ConsoleUI") -> None:
    event_type = event.get("type")

    if event_type == "status":
        message = str(event.get("message", "")).strip() or "Apsara is thinking."
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
        ui.note_working()
        ui.hide_event(
            "tool",
            f"Tool call: {tool_name}",
            json.dumps(event.get("arguments", {}), ensure_ascii=True, indent=2),
        )
        return

    if event_type == "tool_result":
        tool_name = str(event.get("name", "unknown_tool"))
        ui.note_working()
        ui.hide_event(
            "result",
            f"Tool result: {tool_name}",
            truncate_text(str(event.get("result", "")), max_lines=20, max_chars=1800),
        )
        return

    if event_type == "final_answer":
        ui.assistant(str(event.get("content", "")))
        return

    if event_type == "blocked":
        ui.blocked(str(event.get("message", "")))
        return

    if event_type == "error":
        ui.error(str(event.get("message", "")))
        return
