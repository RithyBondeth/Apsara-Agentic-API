import os
import sys
import textwrap
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from apsara_cli.shared.ui import ConsoleUI
    from apsara_cli.config.cli_config import CliConfig


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
        for i, segment in enumerate(glyph):
            rows[i] += segment + "  "
    return [row.rstrip() for row in rows]


def should_animate_welcome(config: "CliConfig") -> bool:
    if config.ui.welcome_animation is False:
        return False
    if os.environ.get("CI"):
        return False
    return sys.stdout.isatty()


def welcome_frame_delay_seconds(config: "CliConfig") -> float:
    ms = config.ui.welcome_frame_delay_ms
    if ms is None:
        ms = 18
    return max(0, min(ms, 250)) / 1000.0


def wrap_banner_text(text: str, width: int) -> list[str]:
    wrapped: list[str] = []
    for raw_line in text.splitlines() or [""]:
        line = raw_line.strip()
        if not line:
            wrapped.append("")
            continue
        wrapped.extend(textwrap.wrap(line, width=width, break_long_words=False, break_on_hyphens=False) or [""])
    return wrapped


def _build_big_title_rows(terminal: int) -> list[tuple[str, tuple[str, ...]]]:
    if terminal < 84:
        return [(track_title("Apsara Agentic"), ("1", "38;2;249;193;103"))]

    # Per-row gradient: APSARA fades blue→cyan, AGENTIC fades gold→purple
    apsara_colors = [
        ("1", "38;2;132;182;255"),
        ("1", "38;2;122;200;240"),
        ("1", "38;2;138;214;210"),
        ("1", "38;2;158;220;180"),
        ("1", "38;2;200;214;148"),
    ]
    agentic_colors = [
        ("1", "38;2;255;210;100"),
        ("1", "38;2;255;185;108"),
        ("1", "38;2;245;158;148"),
        ("1", "38;2;210;148;240"),
        ("1", "38;2;150;168;255"),
    ]

    rows: list[tuple[str, tuple[str, ...]]] = []
    for line, codes in zip(render_block_word("APSARA"), apsara_colors):
        rows.append((line, codes))
    rows.append(("", ()))
    for line, codes in zip(render_block_word("AGENTIC"), agentic_colors):
        rows.append((line, codes))
    return rows


def _build_welcome_content(config: "CliConfig") -> list[tuple[str, tuple[str, ...]]]:
    from apsara_cli.shared.ui import terminal_width

    terminal = max(72, min(terminal_width(), 112))
    title     = config.ui.welcome_title    or "Welcome to Apsara Agentic"
    subtitle  = config.ui.welcome_subtitle or "Elegant local coding assistance for your workspace"
    powered   = config.ui.powered_by       or "Powered by Bondeth"
    wrap_w    = max(36, min(68, terminal - 24))

    rows: list[tuple[str, tuple[str, ...]]] = [
        ("BONDETH EDITION · ALPHA", ("1", "38;2;104;170;255")),
        ("", ()),
    ]
    rows.extend(_build_big_title_rows(terminal))
    rows.extend([
        ("", ()),
        ("project-first  ·  workspace-aware  ·  human-approved", ("38;2;190;196;214",)),
        ("", ()),
    ])
    for line in wrap_banner_text(title, wrap_w):
        rows.append((line, ("1", "38;2;246;239;230")))
    for line in wrap_banner_text(subtitle, wrap_w):
        rows.append((line, ("38;2;200;192;182",)))
    rows.append(("", ()))
    for line in wrap_banner_text(powered, wrap_w):
        rows.append((line, ("38;2;200;166;110",)))
    return rows


def render_welcome_banner(ui: "ConsoleUI", config: "CliConfig") -> list[str]:
    from apsara_cli.shared.ui import terminal_width

    border_color = ("2", "38;2;105;92;78")
    terminal = max(72, min(terminal_width(), 112))
    rows = _build_welcome_content(config)
    content_w = max(48, min(max(len(text) for text, _ in rows if text), terminal - 10))
    banner_w = content_w + 8
    left_pad = " " * max((terminal - banner_w) // 2, 0)

    def bline(inner: str) -> str:
        return left_pad + ui.style("│" + inner + "│", *border_color)

    rendered: list[str] = [
        left_pad + ui.style("╭" + "─" * (banner_w - 2) + "╮", *border_color),
        bline(" " * (banner_w - 2)),
    ]

    for text, codes in rows:
        if text:
            content = center_text(text, content_w)
            rendered.append(
                left_pad
                + ui.style("│   ", *border_color)
                + ui.style(content, *codes)
                + ui.style("   │", *border_color)
            )
        else:
            rendered.append(bline(" " * (banner_w - 2)))

    rendered.extend([
        bline(" " * (banner_w - 2)),
        left_pad + ui.style("╰" + "─" * (banner_w - 2) + "╯", *border_color),
    ])
    return rendered


def print_welcome_banner(ui: "ConsoleUI", config: "CliConfig") -> None:
    lines = render_welcome_banner(ui, config)
    if not lines:
        return

    animate = should_animate_welcome(config)
    delay = welcome_frame_delay_seconds(config)

    if animate:
        # Reveal the border first, then sweep content lines in
        for i, line in enumerate(lines):
            print(line)
            # Faster for border rows, slightly slower for content rows
            row_delay = delay * 0.4 if i in (0, 1, len(lines) - 2, len(lines) - 1) else delay
            time.sleep(row_delay)
        time.sleep(delay * 3)
    else:
        for line in lines:
            print(line)

    print()
