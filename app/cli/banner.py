import os
import sys
import textwrap
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.cli.ui import ConsoleUI
    from app.cli_config import CliConfig


def center_text(text: str, width: int) -> str:
    if len(text) >= width:
        return text
    return text.center(width)


def track_title(text: str) -> str:
    words = [word for word in text.strip().split() if word]
    if not words:
        return ""
    return "   ".join(" ".join(list(word.upper())) for word in words)


def render_block_word(word: str) -> list[str]:
    glyphs = {
        "A": ["   /\\   ", "  /  \\  ", " / /\\ \\ ", "/ ____ \\", "/_/  \\_\\"],
        "P": [" ____   ", "|  _ \\  ", "| |_) | ", "|  __/  ", "|_|     "],
        "S": [" ____   ", "/ ___|  ", "\\___ \\  ", " ___) | ", "|____/  "],
        "R": [" ____   ", "|  _ \\  ", "| |_) | ", "|  _ <  ", "|_| \\_\\ "],
        "G": ["  ____  ", " / ___| ", "| |  _  ", "| |_| | ", " \\____| "],
        "E": [" _____  ", "| ____| ", "|  _|   ", "| |___  ", "|_____| "],
        "N": [" _   _  ", "| \\ | | ", "|  \\| | ", "| |\\  | ", "|_| \\_| "],
        "T": [" _____  ", "|_   _| ", "  | |   ", "  | |   ", "  |_|   "],
        "I": [" ___  ", "|_ _| ", " | |  ", " | |  ", "|___| "],
        "C": ["  ____  ", " / ___| ", "| |     ", "| |___  ", " \\____| "],
        " ": ["   ", "   ", "   ", "   ", "   "],
    }

    rows = ["", "", "", "", ""]
    for letter in word.upper():
        glyph = glyphs.get(letter, glyphs[" "])
        for index, segment in enumerate(glyph):
            rows[index] += segment + "  "
    return [row.rstrip() for row in rows]


def build_big_title_rows(terminal: int) -> list[tuple[str, tuple[str, ...]]]:
    if terminal < 84:
        return [(track_title("Apsara Agentic"), ("1", "38;2;249;193;103"))]

    apsara_colors = [
        ("1", "38;2;111;154;255"),
        ("1", "38;2;121;184;255"),
        ("1", "38;2;122;210;222"),
        ("1", "38;2;166;216;168"),
        ("1", "38;2;238;206;124"),
    ]
    agentic_colors = [
        ("1", "38;2;255;196;108"),
        ("1", "38;2;255;171;112"),
        ("1", "38;2;239;150;155"),
        ("1", "38;2;197;154;244"),
        ("1", "38;2;132;182;255"),
    ]

    rows: list[tuple[str, tuple[str, ...]]] = []
    for line, codes in zip(render_block_word("APSARA"), apsara_colors):
        rows.append((line, codes))
    rows.append(("", ()))
    for line, codes in zip(render_block_word("AGENTIC"), agentic_colors):
        rows.append((line, codes))
    return rows


def should_animate_welcome(config: "CliConfig") -> bool:
    if config.ui.welcome_animation is False:
        return False
    if os.environ.get("CI"):
        return False
    return sys.stdout.isatty()


def welcome_frame_delay_seconds(config: "CliConfig") -> float:
    frame_delay_ms = config.ui.welcome_frame_delay_ms
    if frame_delay_ms is None:
        frame_delay_ms = 22
    return max(0, min(frame_delay_ms, 250)) / 1000.0


def wrap_banner_text(text: str, width: int) -> list[str]:
    wrapped_lines: list[str] = []
    for raw_line in text.splitlines() or [""]:
        line = raw_line.strip()
        if not line:
            wrapped_lines.append("")
            continue
        wrapped_lines.extend(
            textwrap.wrap(line, width=width, break_long_words=False, break_on_hyphens=False) or [""]
        )
    return wrapped_lines


def build_welcome_lines(config: "CliConfig") -> list[tuple[str, tuple[str, ...]]]:
    from app.cli.ui import terminal_width

    terminal = max(72, min(terminal_width(), 112))
    title = config.ui.welcome_title or "Welcome to Apsara Agentic"
    subtitle = config.ui.welcome_subtitle or "Elegant local coding assistance for your workspace"
    powered_by = config.ui.powered_by or "Powered by Bondeth"
    eyebrow = "BONDETH EDITION"
    badges = "workspace-aware  |  session memory  |  safe tools"

    wrap_width = max(36, min(68, terminal - 24))
    rows: list[tuple[str, tuple[str, ...]]] = [
        (eyebrow, ("1", "38;2;104;170;255")),
        ("", ()),
    ]

    rows.extend(build_big_title_rows(terminal))
    rows.extend([
        ("", ()),
        ("A premium Apsara experience for local flow", ("38;2;211;202;191",)),
        ("", ()),
    ])

    for line in wrap_banner_text(title, wrap_width):
        rows.append((line, ("1", "38;2;246;239;230")))
    for line in wrap_banner_text(subtitle, wrap_width):
        rows.append((line, ("38;2;211;202;191",)))

    rows.append(("", ()))
    for line in wrap_banner_text(badges, wrap_width):
        rows.append((line, ("38;2;121;210;184",)))

    rows.append(("", ()))
    for line in wrap_banner_text(powered_by, wrap_width):
        rows.append((line, ("38;2;219;171;116",)))

    return rows


def render_welcome_banner(ui: "ConsoleUI", config: "CliConfig") -> list[str]:
    from app.cli.ui import terminal_width

    border_codes = ("2", "38;2;119;103;88")
    terminal = max(72, min(terminal_width(), 112))
    rows = build_welcome_lines(config)
    content_width = max(44, min(max(len(text) for text, _codes in rows), terminal - 10))
    banner_width = content_width + 8
    left_padding = " " * max((terminal - banner_width) // 2, 0)

    rendered_lines = [
        left_padding + ui.style("." + "-" * (banner_width - 2) + ".", *border_codes),
        left_padding + ui.style("|" + " " * (banner_width - 2) + "|", *border_codes),
    ]

    for text, codes in rows:
        if text:
            content = center_text(text, content_width)
            rendered_lines.append(
                left_padding
                + ui.style("|   ", *border_codes)
                + ui.style(content, *codes)
                + ui.style("   |", *border_codes)
            )
        else:
            rendered_lines.append(
                left_padding + ui.style("|" + " " * (banner_width - 2) + "|", *border_codes)
            )

    rendered_lines.extend([
        left_padding + ui.style("|" + " " * (banner_width - 2) + "|", *border_codes),
        left_padding + ui.style("'" + "-" * (banner_width - 2) + "'", *border_codes),
    ])
    return rendered_lines


def print_welcome_banner(ui: "ConsoleUI", config: "CliConfig") -> None:
    lines = render_welcome_banner(ui, config)
    if not lines:
        return

    animate = should_animate_welcome(config)
    frame_delay = welcome_frame_delay_seconds(config)

    for index, line in enumerate(lines):
        ui.print_line(line)
        if animate and index < len(lines) - 1:
            time.sleep(frame_delay)

    if animate:
        time.sleep(frame_delay * 1.5)
    ui.print_line()
