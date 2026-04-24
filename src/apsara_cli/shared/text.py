import re
import textwrap
from typing import Any


def truncate_text(text: str, max_lines: int = 16, max_chars: int = 1200) -> str:
    if len(text) > max_chars:
        text = text[:max_chars].rstrip() + "\n... [truncated]"

    lines = text.splitlines()
    if len(lines) > max_lines:
        lines = lines[:max_lines] + ["... [truncated]"]
    return "\n".join(lines)


def wrap_text_block(
    text: str,
    width: int,
    initial_indent: str = "",
    subsequent_indent: str = "",
) -> list[str]:
    if not text:
        return [initial_indent.rstrip()]

    wrapped = textwrap.wrap(
        text,
        width=max(width, 20),
        initial_indent=initial_indent,
        subsequent_indent=subsequent_indent,
        break_long_words=False,
        break_on_hyphens=False,
    )
    return wrapped or [initial_indent.rstrip()]


def clean_inline_markdown(text: str) -> str:
    cleaned = text.replace("**", "").replace("__", "")
    cleaned = re.sub(r"`([^`]+)`", r"\1", cleaned)
    return cleaned.strip()


def format_rich_text_lines(text: str, width: int) -> list[tuple[str, str]]:
    lines: list[tuple[str, str]] = []
    code_block = False
    paragraph_parts: list[str] = []

    def flush_paragraph() -> None:
        nonlocal paragraph_parts
        if not paragraph_parts:
            return
        paragraph = " ".join(part.strip() for part in paragraph_parts if part.strip())
        paragraph_parts = []
        for wrapped in wrap_text_block(paragraph, width):
            lines.append(("body", wrapped))

    for raw_line in text.splitlines():
        stripped = raw_line.strip()

        if stripped.startswith("```"):
            flush_paragraph()
            code_block = not code_block
            if not code_block:
                lines.append(("blank", ""))
            continue

        if code_block:
            lines.append(("code", raw_line.rstrip()))
            continue

        if not stripped:
            flush_paragraph()
            if lines and lines[-1][0] != "blank":
                lines.append(("blank", ""))
            continue

        ordered_match = re.match(r"^(\d+)\.\s+(.*)$", stripped)
        if ordered_match:
            flush_paragraph()
            number = ordered_match.group(1)
            body = clean_inline_markdown(ordered_match.group(2))
            for wrapped in wrap_text_block(
                body,
                width,
                initial_indent=f"{number}. ",
                subsequent_indent=" " * (len(number) + 2),
            ):
                lines.append(("list", wrapped))
            continue

        bullet_match = re.match(r"^[-*]\s+(.*)$", stripped)
        if bullet_match:
            flush_paragraph()
            body = clean_inline_markdown(bullet_match.group(1))
            for wrapped in wrap_text_block(body, width, initial_indent="• ", subsequent_indent="  "):
                lines.append(("list", wrapped))
            continue

        heading_match = re.match(r"^(?:#+\s*)?(.+?):\s*$", clean_inline_markdown(stripped))
        if heading_match and len(stripped) <= width:
            flush_paragraph()
            if lines and lines[-1][0] != "blank":
                lines.append(("blank", ""))
            lines.append(("heading", heading_match.group(1)))
            continue

        paragraph_parts.append(clean_inline_markdown(stripped))

    flush_paragraph()

    while lines and lines[-1][0] == "blank":
        lines.pop()

    return lines


def summarize_history(history: list[dict[str, Any]], limit: int = 10) -> list[str]:
    summaries = []
    for message in history[-limit:]:
        role = str(message.get("role", "unknown"))
        content = str(message.get("content") or "").strip().replace("\n", " ")
        if len(content) > 100:
            content = content[:97].rstrip() + "..."
        summaries.append(f"{role:>9}: {content or '[no content]'}")
    return summaries
