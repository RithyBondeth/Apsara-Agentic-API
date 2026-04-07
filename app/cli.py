import argparse
import asyncio
import json
import os
import re
import select
import shutil
import sys
import tempfile
import textwrap
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Sequence, Set

from dotenv import dotenv_values

try:
    import termios
    import tty
except ImportError:  # pragma: no cover - Windows fallback
    termios = None
    tty = None

try:
    import msvcrt
except ImportError:  # pragma: no cover - Unix fallback
    msvcrt = None

from app.cli_config import CliConfig, CliDefaults, DEFAULT_CONFIG_PATH, load_cli_config
from app.services.agent.tools import (
    agent_runtime_context,
    execute_tool,
    get_agent_tools,
)


SESSION_ROOT_DIR = ".apsara-cli"
SESSIONS_DIR = "sessions"


@dataclass
class ResolvedOptions:
    workspace_root: Path
    model: str
    session: str
    stateless: bool
    allow_bash: bool
    allowed_commands: Optional[Set[str]]
    max_file_size: Optional[int]
    auto_approve: bool
    use_color: bool


@dataclass
class DoctorCheckResult:
    name: str
    status: str
    detail: str


@dataclass
class HiddenCliEvent:
    kind: str
    title: str
    detail: str


@dataclass
class ContextTrimResult:
    request_history: list[dict[str, Any]]
    dropped_turns: int
    dropped_messages: int
    original_tokens: int
    trimmed_tokens: int


SAFE_INPUT_TOKEN_BUDGET = 24_000


def resolve_workspace(path_str: str) -> Path:
    return Path(path_str).expanduser().resolve()


def sanitize_session_name(name: str) -> str:
    sanitized = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip(".-")
    if not sanitized:
        raise ValueError(
            "Session name must contain letters, numbers, dots, dashes, or underscores."
        )
    return sanitized


def get_sessions_dir(workspace_root: Path) -> Path:
    return workspace_root / SESSION_ROOT_DIR / SESSIONS_DIR


def get_session_path(workspace_root: Path, session_name: str) -> Path:
    sanitized_name = sanitize_session_name(session_name)
    return get_sessions_dir(workspace_root) / f"{sanitized_name}.json"


def load_session_messages(
    workspace_root: Path, session_name: str
) -> list[dict[str, Any]]:
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
            code_line = raw_line.rstrip()
            lines.append(("code", code_line))
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
            for wrapped in wrap_text_block(
                body,
                width,
                initial_indent="• ",
                subsequent_indent="  ",
            ):
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


def default_use_color() -> bool:
    return sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


def resolve_value(explicit: Any, config_value: Any, fallback: Any) -> Any:
    if explicit is not None:
        return explicit
    if config_value is not None:
        return config_value
    return fallback


def parse_allowed_commands(raw_commands: Any) -> Optional[Set[str]]:
    if raw_commands is None:
        return None
    if isinstance(raw_commands, str):
        commands = {part.strip() for part in raw_commands.split(",") if part.strip()}
    elif isinstance(raw_commands, list):
        commands = {str(item).strip() for item in raw_commands if str(item).strip()}
    else:
        raise ValueError("Allowed commands must be a comma-separated string or a list.")

    if not commands:
        raise ValueError("Allowed commands cannot be empty when provided.")
    return commands


def resolve_runtime_options(
    args: argparse.Namespace,
    config_defaults: CliDefaults,
) -> ResolvedOptions:
    workspace = resolve_value(args.workspace, config_defaults.workspace, ".")
    model = resolve_value(args.model, config_defaults.model, "gpt-4o")
    session = resolve_value(args.session, config_defaults.session, "default")
    stateless = bool(resolve_value(args.stateless, config_defaults.stateless, False))
    allow_bash = bool(resolve_value(args.allow_bash, config_defaults.allow_bash, False))
    allowed_commands = parse_allowed_commands(
        resolve_value(args.allowed_commands, config_defaults.allowed_commands, None)
    )
    max_file_size = resolve_value(
        args.max_file_size, config_defaults.max_file_size, None
    )
    auto_approve = bool(
        resolve_value(args.auto_approve, config_defaults.auto_approve, False)
    )
    use_color = bool(resolve_value(args.color, config_defaults.color, default_use_color()))

    return ResolvedOptions(
        workspace_root=resolve_workspace(str(workspace)),
        model=str(model),
        session=str(session),
        stateless=stateless,
        allow_bash=allow_bash,
        allowed_commands=allowed_commands,
        max_file_size=max_file_size,
        auto_approve=auto_approve,
        use_color=use_color,
    )


def load_cli_environment(args: argparse.Namespace, config: CliConfig) -> list[Path]:
    workspace = resolve_value(getattr(args, "workspace", None), config.defaults.workspace, ".")
    candidates = [
        resolve_workspace(str(workspace)),
        Path.cwd().resolve(),
    ]

    loaded_paths: list[Path] = []
    seen_paths: set[Path] = set()
    for base_path in candidates:
        env_path = base_path / ".env"
        if env_path in seen_paths or not env_path.exists():
            continue
        seen_paths.add(env_path)

        values = dotenv_values(env_path)
        loaded_any = False
        for key, value in values.items():
            if value is None or key in os.environ:
                continue
            os.environ[key] = value
            loaded_any = True

        if loaded_any:
            loaded_paths.append(env_path)

    return loaded_paths


class ConsoleUI:
    def __init__(self, use_color: bool, auto_approve: bool = False):
        self.use_color = use_color
        self.auto_approve = auto_approve
        self.approve_all = auto_approve
        self.hidden_events: list[HiddenCliEvent] = []
        self.latest_hidden_events: list[HiddenCliEvent] = []
        self.current_turn_hidden_events: list[HiddenCliEvent] = []
        self.work_notice_shown = False

    def style(self, text: str, *codes: str) -> str:
        if not self.use_color:
            return text
        joined_codes = ";".join(codes)
        return f"\033[{joined_codes}m{text}\033[0m"

    def print_line(self, text: str = "") -> None:
        print(text)

    def badge(self, text: str, fg_code: str = "30", bg_code: str = "47") -> str:
        if not self.use_color:
            return f"[{text.upper()}]"
        return self.style(f" {text.upper()} ", "1", fg_code, bg_code)

    def muted(self, text: str) -> str:
        return self.style(text, "2", "38;2;170;176;189")

    def prompt(self, label: str = "you") -> str:
        return f"\n{self.badge(label, '15', '48;2;49;104;194')} "

    def print_block(self, text: str, color_code: Optional[str] = None) -> None:
        for raw_line in text.splitlines() or [""]:
            line = f"  {raw_line}"
            self.print_line(self.style(line, color_code) if color_code else line)

    def content_width(self, fallback: int = 84) -> int:
        terminal = terminal_width()
        return max(44, min(fallback, terminal - 8))

    def render_rich_text(self, text: str) -> None:
        width = self.content_width()
        for line_type, line in format_rich_text_lines(text, width):
            if line_type == "blank":
                self.print_line()
            elif line_type == "heading":
                self.print_line(f"  {self.style(line, '1', '38;2;250;216;143')}")
            elif line_type == "list":
                self.print_line(f"  {self.style(line, '38;2;237;232;225')}")
            elif line_type == "code":
                self.print_line(f"  {self.style(line, '38;2;173;203;255')}")
            else:
                self.print_line(f"  {self.style(line, '38;2;240;236;231')}")

    def render_diff_text(self, diff_text: str) -> None:
        for raw_line in diff_text.splitlines() or [""]:
            if raw_line.startswith(("---", "+++")):
                self.print_line(f"  {self.style(raw_line, '38;2;140;191;255')}")
            elif raw_line.startswith("@@"):
                self.print_line(f"  {self.style(raw_line, '38;2;250;216;143')}")
            elif raw_line.startswith("+") and not raw_line.startswith("+++"):
                self.print_line(f"  {self.style(raw_line, '38;2;152;224;171')}")
            elif raw_line.startswith("-") and not raw_line.startswith("---"):
                self.print_line(f"  {self.style(raw_line, '38;2;255;168;168')}")
            elif raw_line.startswith("... ["):
                self.print_line(f"  {self.muted(raw_line)}")
            else:
                self.print_line(f"  {self.style(raw_line, '38;2;220;225;235')}")

    def print_notice(self, label: str, text: str, fg_code: str, bg_code: str, body_color: str) -> None:
        self.print_line(f"{self.badge(label, fg_code, bg_code)} {self.style(text, body_color)}")

    def begin_turn(self) -> None:
        self.current_turn_hidden_events = []
        self.work_notice_shown = False

    def note_working(self) -> None:
        if self.work_notice_shown:
            return
        self.print_notice("work", "Apsara is working...", "17", "48;2;242;201;76", "38;2;236;220;184")
        self.work_notice_shown = True

    def hide_event(self, kind: str, title: str, detail: str = "") -> None:
        event = HiddenCliEvent(kind=kind, title=title, detail=detail)
        self.current_turn_hidden_events.append(event)
        self.hidden_events.append(event)
        self.hidden_events = self.hidden_events[-80:]

    def finish_turn(self) -> None:
        self.latest_hidden_events = list(self.current_turn_hidden_events)
        if self.latest_hidden_events:
            self.info(
                f"Hidden {len(self.latest_hidden_events)} internal event(s). Type /details to inspect."
            )

    def show_hidden_events(self) -> None:
        events = self.latest_hidden_events or self.hidden_events[-12:]
        if not events:
            self.info("No hidden internal activity yet.")
            return

        self.print_line()
        self.print_notice(
            "details",
            f"Showing {len(events)} hidden internal event(s)",
            "15",
            "48;2;93;108;137",
            "38;2;217;226;242",
        )
        for index, event in enumerate(events, start=1):
            self.print_line(
                f"  {self.badge(event.kind, '15', '48;2;82;94;120')} "
                f"{self.style(event.title, '38;2;230;234;242')}"
            )
            if event.detail:
                self.render_rich_text(truncate_text(event.detail, max_lines=18, max_chars=1600))
            if index < len(events):
                self.print_line()

    def status(self, text: str) -> None:
        self.print_notice("status", text, "17", "48;2;242;201;76", "38;2;236;220;184")

    def info(self, text: str) -> None:
        self.print_notice("info", text, "15", "48;2;73;127;221", "38;2;188;218;255")

    def success(self, text: str) -> None:
        self.print_notice("ok", text, "15", "48;2;61;153;117", "38;2;186;239;203")

    def warning(self, text: str) -> None:
        self.print_notice("warn", text, "17", "48;2;239;167;74", "38;2;247;223;181")

    def error(self, text: str) -> None:
        self.print_notice("error", text, "15", "48;2;191;87;84", "38;2;255;205;205")

    def assistant(self, text: str) -> None:
        self.print_line()
        self.print_line(
            f"{self.badge('apsara', '15', '48;2;133;92;219')} "
            f"{self.style('Apsara by Bondeth', '38;2;233;220;255')}"
        )
        self.render_rich_text(text)

    def tool_call(self, name: str, arguments: dict[str, Any]) -> None:
        arguments_text = json.dumps(arguments, ensure_ascii=True)
        self.print_line(
            f"{self.badge('tool', '15', '48;2;64;128;191')} "
            f"{self.style(name, '38;2;201;231;255')}"
        )
        self.print_block(arguments_text, "38;2;169;200;224")

    def tool_result(self, result: str) -> None:
        self.print_line(
            f"{self.badge('result', '15', '48;2;53;106;167')} "
            f"{self.style('Tool output', '38;2;201;231;255')}"
        )
        self.print_block(result, "38;2;219;229;240")

    def blocked(self, text: str) -> None:
        self.warning(f"Blocked: {text}")

    def usage(self, usage_data: dict[str, Any]) -> None:
        self.success(
            "Tokens "
            f"prompt={usage_data.get('prompt_tokens', '?')} "
            f"completion={usage_data.get('completion_tokens', '?')} "
            f"total={usage_data.get('total_tokens', '?')}"
        )

    def session_saved(self, session_path: Path) -> None:
        self.info(f"Session saved to {session_path}")

    def read_single_key(self) -> str:
        if msvcrt is not None:  # pragma: no cover - Windows fallback
            key = msvcrt.getwch()
            if key in {"\x00", "\xe0"}:
                key += msvcrt.getwch()
            return key

        if termios is not None and tty is not None and sys.stdin.isatty():
            file_descriptor = sys.stdin.fileno()
            original_settings = termios.tcgetattr(file_descriptor)
            try:
                tty.setraw(file_descriptor)
                key = sys.stdin.read(1)
                if key == "\x1b" and select.select([sys.stdin], [], [], 0.02)[0]:
                    key += sys.stdin.read(1)
                    if select.select([sys.stdin], [], [], 0.02)[0]:
                        key += sys.stdin.read(1)
                return key
            finally:
                termios.tcsetattr(file_descriptor, termios.TCSADRAIN, original_settings)

        return input().strip()[:1]

    def prompt_confirmation_choice(self, *, allow_view: bool = False) -> str:
        options = [
            f"{self.badge('enter', '17', '48;2;121;210;184')} approve",
            f"{self.badge('n', '17', '48;2;239;167;74')} reject",
            f"{self.badge('a', '17', '48;2;111;154;255')} always approve",
        ]
        if allow_view:
            options.append(
                f"{self.badge('v', '17', '48;2;93;108;137')} view full diff"
            )
        self.print_line(f"  {'   '.join(options)}")

        while True:
            key = self.read_single_key()
            if key in {"", "\r", "\n", "y", "Y"}:
                self.print_line(f"  {self.muted('approved')}")
                return "approve"
            if key in {"a", "A"}:
                self.print_line(f"  {self.muted('always approve enabled')}")
                return "always"
            if allow_view and key in {"v", "V"}:
                return "view"
            if key in {"n", "N", "\x1b", "q", "Q", "\x03"}:
                self.print_line(f"  {self.muted('rejected')}")
                return "reject"

    def confirm_action(self, action: str, payload: dict[str, Any]) -> bool:
        if self.approve_all:
            return True

        if not sys.stdin.isatty():
            self.error(
                f"Approval required for {action}, but stdin is not interactive. "
                "Re-run with --auto-approve if you trust this action."
            )
            return False

        title, preview, diff_preview, diff_full = describe_action(action, payload)
        self.print_line()
        self.print_line(
            f"{self.badge('approve', '17', '48;2;255;196;108')} "
            f"{self.style(title, '1', '38;2;247;237;222')}"
        )
        if diff_preview:
            self.render_diff_text(diff_preview)
        elif preview:
            self.print_block(
                truncate_text(preview, max_lines=12, max_chars=900),
                "38;2;205;211;222",
            )

        while True:
            choice = self.prompt_confirmation_choice(allow_view=bool(diff_full and diff_full != diff_preview))
            if choice == "view":
                self.print_line()
                self.print_notice(
                    "diff",
                    "Full change preview",
                    "15",
                    "48;2;93;108;137",
                    "38;2;217;226;242",
                )
                self.render_diff_text(diff_full)
                continue
            if choice == "always":
                self.approve_all = True
                return True
            return choice == "approve"


def describe_action(
    action: str, payload: dict[str, Any]
) -> tuple[str, Optional[str], Optional[str], Optional[str]]:
    if action == "write_to_file":
        path = payload.get("display_path") or payload.get("path", "<unknown>")
        preview = payload.get("content_preview")
        if payload.get("is_new_file"):
            title = f"Create file {path}"
        else:
            title = f"Update file {path}"
        return (
            title,
            preview if isinstance(preview, str) else None,
            payload.get("diff_preview") if isinstance(payload.get("diff_preview"), str) else None,
            payload.get("diff_full") if isinstance(payload.get("diff_full"), str) else None,
        )

    if action == "replace_file_lines":
        path = payload.get("display_path") or payload.get("path", "<unknown>")
        start_line = payload.get("start_line", "?")
        end_line = payload.get("end_line", "?")
        preview = payload.get("replacement_preview")
        return (
            f"Replace lines {start_line}-{end_line} in {path}",
            preview if isinstance(preview, str) else None,
            payload.get("diff_preview") if isinstance(payload.get("diff_preview"), str) else None,
            payload.get("diff_full") if isinstance(payload.get("diff_full"), str) else None,
        )

    if action == "run_bash_command":
        command = payload.get("command", "")
        cwd = payload.get("cwd", "")
        return (f"Run command in {cwd}: {command}", None, None, None)

    return (f"Approve action: {action}", None, None, None)


def terminal_width(default: int = 96) -> int:
    return shutil.get_terminal_size((default, 24)).columns


def center_text(text: str, width: int) -> str:
    if len(text) >= width:
        return text
    return text.center(width)


def track_title(text: str) -> str:
    words = [word for word in text.strip().split() if word]
    if not words:
        return ""
    tracked_words = [" ".join(list(word.upper())) for word in words]
    return "   ".join(tracked_words)


def render_block_word(word: str) -> list[str]:
    glyphs = {
        "A": [
            "   /\\   ",
            "  /  \\  ",
            " / /\\ \\ ",
            "/ ____ \\",
            "/_/  \\_\\",
        ],
        "P": [
            " ____   ",
            "|  _ \\  ",
            "| |_) | ",
            "|  __/  ",
            "|_|     ",
        ],
        "S": [
            " ____   ",
            "/ ___|  ",
            "\\___ \\  ",
            " ___) | ",
            "|____/  ",
        ],
        "R": [
            " ____   ",
            "|  _ \\  ",
            "| |_) | ",
            "|  _ <  ",
            "|_| \\_\\ ",
        ],
        "G": [
            "  ____  ",
            " / ___| ",
            "| |  _  ",
            "| |_| | ",
            " \\____| ",
        ],
        "E": [
            " _____  ",
            "| ____| ",
            "|  _|   ",
            "| |___  ",
            "|_____| ",
        ],
        "N": [
            " _   _  ",
            "| \\ | | ",
            "|  \\| | ",
            "| |\\  | ",
            "|_| \\_| ",
        ],
        "T": [
            " _____  ",
            "|_   _| ",
            "  | |   ",
            "  | |   ",
            "  |_|   ",
        ],
        "I": [
            " ___  ",
            "|_ _| ",
            " | |  ",
            " | |  ",
            "|___| ",
        ],
        "C": [
            "  ____  ",
            " / ___| ",
            "| |     ",
            "| |___  ",
            " \\____| ",
        ],
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
        return [
            (track_title("Apsara Agentic"), ("1", "38;2;249;193;103")),
        ]

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


def should_animate_welcome(config: CliConfig) -> bool:
    if config.ui.welcome_animation is False:
        return False
    if os.environ.get("CI"):
        return False
    return sys.stdout.isatty()


def welcome_frame_delay_seconds(config: CliConfig) -> float:
    frame_delay_ms = config.ui.welcome_frame_delay_ms
    if frame_delay_ms is None:
        frame_delay_ms = 22
    frame_delay_ms = max(0, min(frame_delay_ms, 250))
    return frame_delay_ms / 1000.0


def wrap_banner_text(text: str, width: int) -> list[str]:
    wrapped_lines: list[str] = []
    for raw_line in text.splitlines() or [""]:
        line = raw_line.strip()
        if not line:
            wrapped_lines.append("")
            continue
        wrapped_lines.extend(
            textwrap.wrap(
                line,
                width=width,
                break_long_words=False,
                break_on_hyphens=False,
            )
            or [""]
        )
    return wrapped_lines


def build_welcome_lines(config: CliConfig) -> list[tuple[str, tuple[str, ...]]]:
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
    rows.extend(
        [
        ("", ()),
        ("A premium Apsara experience for local flow", ("38;2;211;202;191",)),
        ("", ()),
        ]
    )

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


def render_welcome_banner(ui: ConsoleUI, config: CliConfig) -> list[str]:
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

    rendered_lines.extend(
        [
            left_padding + ui.style("|" + " " * (banner_width - 2) + "|", *border_codes),
            left_padding + ui.style("'" + "-" * (banner_width - 2) + "'", *border_codes),
        ]
    )
    return rendered_lines


def print_welcome_banner(ui: ConsoleUI, config: CliConfig) -> None:
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


def print_event(event: dict[str, Any], ui: ConsoleUI) -> None:
    event_type = event.get("type")

    if event_type == "status":
        message = str(event.get("message", "")).strip() or "Apsara is thinking."
        ui.note_working()
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
                str(tool_call.get("function", {}).get("name", "unknown_tool"))
                for tool_call in tool_calls
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


def group_conversation_turns(
    conversation_history: list[dict[str, Any]]
) -> list[list[dict[str, Any]]]:
    turns: list[list[dict[str, Any]]] = []
    current_turn: list[dict[str, Any]] = []

    for message in conversation_history:
        if message.get("role") == "user":
            if current_turn:
                turns.append(current_turn)
            current_turn = [message]
        elif current_turn:
            current_turn.append(message)
        else:
            current_turn = [message]

    if current_turn:
        turns.append(current_turn)

    return turns


def flatten_conversation_turns(
    turns: list[list[dict[str, Any]]]
) -> list[dict[str, Any]]:
    return [message for turn in turns for message in turn]


def trim_history_for_request(
    conversation_history: list[dict[str, Any]],
    model: str,
) -> ContextTrimResult:
    from app.services.agent.executor import SYSTEM_PROMPT
    from app.services.agent.llm import estimate_request_tokens

    base_messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    original_tokens = estimate_request_tokens(
        base_messages + conversation_history,
        model=model,
    )
    if original_tokens <= SAFE_INPUT_TOKEN_BUDGET:
        return ContextTrimResult(
            request_history=conversation_history,
            dropped_turns=0,
            dropped_messages=0,
            original_tokens=original_tokens,
            trimmed_tokens=original_tokens,
        )

    turns = group_conversation_turns(conversation_history)
    if not turns:
        return ContextTrimResult(
            request_history=conversation_history,
            dropped_turns=0,
            dropped_messages=0,
            original_tokens=original_tokens,
            trimmed_tokens=original_tokens,
        )

    kept_turns: list[list[dict[str, Any]]] = []
    for turn in reversed(turns):
        candidate_turns = [turn] + kept_turns
        candidate_history = flatten_conversation_turns(candidate_turns)
        candidate_tokens = estimate_request_tokens(
            base_messages + candidate_history,
            model=model,
        )
        if kept_turns and candidate_tokens > SAFE_INPUT_TOKEN_BUDGET:
            break
        kept_turns = candidate_turns

    trimmed_history = flatten_conversation_turns(kept_turns)
    trimmed_tokens = estimate_request_tokens(
        base_messages + trimmed_history,
        model=model,
    )
    return ContextTrimResult(
        request_history=trimmed_history,
        dropped_turns=max(len(turns) - len(kept_turns), 0),
        dropped_messages=max(len(conversation_history) - len(trimmed_history), 0),
        original_tokens=original_tokens,
        trimmed_tokens=trimmed_tokens,
    )


async def execute_instruction(
    instruction: str,
    model: str,
    history: list[dict[str, Any]],
    options: ResolvedOptions,
    ui: ConsoleUI,
) -> tuple[list[dict[str, Any]], Optional[dict[str, Any]]]:
    from app.services.agent.executor import run_agent_stream
    from app.services.agent.llm import DEFAULT_MAX_COMPLETION_TOKENS

    next_history = list(history)
    next_history.append({"role": "user", "content": instruction})
    latest_usage = None
    ui.begin_turn()

    with agent_runtime_context(
        workspace_root=options.workspace_root,
        enable_bash=options.allow_bash,
        allowed_commands=options.allowed_commands,
        max_file_size_bytes=options.max_file_size,
        confirmation_callback=None if options.auto_approve else ui.confirm_action,
    ):
        trim_result = trim_history_for_request(next_history, model=model)
        if trim_result.dropped_turns:
            ui.warning(
                "Trimmed "
                f"{trim_result.dropped_turns} earlier turn(s) "
                f"({trim_result.dropped_messages} messages) to stay within the request budget."
            )
            ui.info(
                f"Estimated input tokens: {trim_result.original_tokens} -> {trim_result.trimmed_tokens}. "
                f"Response budget capped at about {DEFAULT_MAX_COMPLETION_TOKENS} tokens."
            )
        if trim_result.trimmed_tokens > SAFE_INPUT_TOKEN_BUDGET:
            ui.warning(
                "This prompt is still very large. If rate-limit errors continue, try /clear or --stateless."
            )

        async for chunk_str in run_agent_stream(trim_result.request_history, model=model):
            event = json.loads(chunk_str)
            if event.get("type") == "usage":
                latest_usage = event.get("data")
            else:
                print_event(event, ui)
                update_history_from_event(next_history, event)

    ui.finish_turn()
    return next_history, latest_usage


def save_if_needed(
    history: list[dict[str, Any]],
    model: str,
    options: ResolvedOptions,
    ui: ConsoleUI,
) -> None:
    if options.stateless:
        return
    session_path = save_session_messages(
        workspace_root=options.workspace_root,
        session_name=options.session,
        model=model,
        messages=history,
    )
    ui.session_saved(session_path)


def print_chat_help(ui: ConsoleUI) -> None:
    ui.info("Slash commands:")
    ui.print_line("/help      Show available chat commands")
    ui.print_line("/details   Show hidden internal activity from the latest turn")
    ui.print_line("/history   Show recent conversation turns")
    ui.print_line("/tools     Show enabled tools for this session")
    ui.print_line("/model     Show the current model")
    ui.print_line("/model X   Switch to a different model for later turns")
    ui.print_line("/session   Show session and workspace details")
    ui.print_line("/save      Save the current session now")
    ui.print_line("/clear     Clear in-memory conversation history")
    ui.print_line("/exit      Quit the chat session")


def handle_chat_command(
    command_text: str,
    history: list[dict[str, Any]],
    current_model: str,
    options: ResolvedOptions,
    config: CliConfig,
    ui: ConsoleUI,
) -> tuple[bool, str]:
    if command_text in {"/exit", "/quit"}:
        return False, current_model

    if command_text == "/help":
        print_chat_help(ui)
        return True, current_model

    if command_text == "/details":
        ui.show_hidden_events()
        return True, current_model

    if command_text == "/clear":
        history.clear()
        ui.latest_hidden_events = []
        ui.warning("Session cleared in memory")
        return True, current_model

    if command_text == "/history":
        summaries = summarize_history(history)
        if not summaries:
            ui.info("No conversation history yet.")
        else:
            for line in summaries:
                ui.print_line(line)
        return True, current_model

    if command_text == "/tools":
        with agent_runtime_context(
            workspace_root=options.workspace_root,
            enable_bash=options.allow_bash,
            allowed_commands=options.allowed_commands,
            max_file_size_bytes=options.max_file_size,
        ):
            tools = [tool["function"]["name"] for tool in get_agent_tools()]
        ui.info("Enabled tools:")
        for tool_name in tools:
            ui.print_line(f"- {tool_name}")
        return True, current_model

    if command_text == "/model":
        ui.info(f"Current model: {current_model}")
        return True, current_model

    if command_text.startswith("/model "):
        next_model = command_text[len("/model ") :].strip()
        if not next_model:
            ui.error("Usage: /model <model-name>")
            return True, current_model
        ui.info(f"Model changed to {next_model}")
        return True, next_model

    if command_text == "/session":
        ui.info(f"Workspace: {options.workspace_root}")
        if options.stateless:
            ui.info("Session mode: stateless")
        else:
            ui.info(f"Session: {sanitize_session_name(options.session)}")
        ui.info(f"Config: {config.path} ({'loaded' if config.exists else 'default values'})")
        return True, current_model

    if command_text == "/save":
        save_if_needed(history, current_model, options, ui)
        return True, current_model

    ui.error("Unknown slash command. Type /help for a list of commands.")
    return True, current_model


def detect_model_credentials(model: str) -> tuple[str, Optional[list[str]], str]:
    raw_model = model.strip()
    provider = None
    model_name = raw_model

    if "/" in raw_model:
        provider, model_name = raw_model.split("/", 1)
        provider = provider.lower()
    normalized_name = model_name.lower()

    if provider in {"openai", "azure", "azure_openai"} or normalized_name.startswith(
        ("gpt-", "o1", "o3", "o4", "o5", "codex-", "text-embedding-")
    ):
        if provider in {"azure", "azure_openai"}:
            return (
                "azure-openai",
                ["AZURE_OPENAI_API_KEY", "AZURE_API_KEY"],
                "Azure OpenAI-style model detected.",
            )
        return ("openai", ["OPENAI_API_KEY"], "OpenAI-style model detected.")

    if provider == "anthropic" or normalized_name.startswith("claude"):
        return ("anthropic", ["ANTHROPIC_API_KEY"], "Anthropic-style model detected.")

    if provider in {"gemini", "google"} or normalized_name.startswith("gemini"):
        return (
            "gemini",
            ["GEMINI_API_KEY", "GOOGLE_API_KEY"],
            "Gemini-style model detected.",
        )

    if provider == "groq":
        return ("groq", ["GROQ_API_KEY"], "Groq-style model detected.")

    if provider in {"together", "together_ai"}:
        return ("together", ["TOGETHER_API_KEY"], "Together-style model detected.")

    if provider == "mistral" or normalized_name.startswith("mistral"):
        return ("mistral", ["MISTRAL_API_KEY"], "Mistral-style model detected.")

    if provider == "xai":
        return ("xai", ["XAI_API_KEY"], "xAI-style model detected.")

    if provider == "deepseek" or normalized_name.startswith("deepseek"):
        return ("deepseek", ["DEEPSEEK_API_KEY"], "DeepSeek-style model detected.")

    if provider == "openrouter":
        return (
            "openrouter",
            ["OPENROUTER_API_KEY"],
            "OpenRouter-style model detected.",
        )

    if provider in {"fireworks", "fireworks_ai"}:
        return (
            "fireworks",
            ["FIREWORKS_API_KEY"],
            "Fireworks-style model detected.",
        )

    if provider == "cohere" or normalized_name.startswith("command"):
        return ("cohere", ["COHERE_API_KEY"], "Cohere-style model detected.")

    if provider == "cerebras":
        return ("cerebras", ["CEREBRAS_API_KEY"], "Cerebras-style model detected.")

    if provider == "bedrock":
        return (
            "bedrock",
            ["AWS_ACCESS_KEY_ID", "AWS_PROFILE"],
            "Bedrock-style model detected.",
        )

    if provider == "vertex_ai":
        return (
            "vertex_ai",
            ["GOOGLE_APPLICATION_CREDENTIALS"],
            "Vertex AI-style model detected.",
        )

    if provider == "ollama":
        return ("ollama", None, "Ollama-style local model detected; no API key required.")

    return (
        "unknown",
        None,
        f"Could not infer credentials for model '{model}'.",
    )


def render_doctor_result(ui: ConsoleUI, result: DoctorCheckResult) -> None:
    label = f"[{result.status.upper()}] {result.name}: {result.detail}"
    if result.status == "pass":
        ui.success(label)
    elif result.status == "warn":
        ui.warning(label)
    else:
        ui.error(label)


def run_workspace_checks(
    options: ResolvedOptions,
    config: CliConfig,
    args: argparse.Namespace,
) -> list[DoctorCheckResult]:
    results = []

    if sys.version_info >= (3, 9):
        results.append(
            DoctorCheckResult(
                "python",
                "pass",
                f"Python {sys.version.split()[0]} is supported.",
            )
        )
    else:
        results.append(
            DoctorCheckResult(
                "python",
                "fail",
                f"Python {sys.version.split()[0]} is below the required 3.9+.",
            )
        )

    if config.exists:
        results.append(
            DoctorCheckResult(
                "config",
                "pass",
                f"Loaded config from {config.path}.",
            )
        )
    elif args.config:
        results.append(
            DoctorCheckResult(
                "config",
                "fail",
                f"Config file was requested but not found at {config.path}.",
            )
        )
    else:
        results.append(
            DoctorCheckResult(
                "config",
                "warn",
                f"No config file found at {config.path}; using defaults and CLI flags.",
            )
        )

    if options.workspace_root.exists() and options.workspace_root.is_dir():
        results.append(
            DoctorCheckResult(
                "workspace",
                "pass",
                f"Workspace exists at {options.workspace_root}.",
            )
        )
    elif options.workspace_root.exists():
        results.append(
            DoctorCheckResult(
                "workspace",
                "fail",
                f"Workspace path exists but is not a directory: {options.workspace_root}.",
            )
        )
    else:
        results.append(
            DoctorCheckResult(
                "workspace",
                "fail",
                f"Workspace does not exist: {options.workspace_root}.",
            )
        )
        return results

    try:
        session_dir = get_sessions_dir(options.workspace_root)
        session_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            dir=str(session_dir),
            prefix="doctor-",
            suffix=".tmp",
            delete=False,
        ) as temp_file:
            temp_file.write("ok")
            temp_path = Path(temp_file.name)
        temp_path.unlink(missing_ok=True)
        detail = (
            f"Session storage is writable at {session_dir}."
            if not options.stateless
            else f"Session storage is writable at {session_dir}, but stateless mode is enabled."
        )
        status = "pass" if not options.stateless else "warn"
        results.append(DoctorCheckResult("session-store", status, detail))
    except Exception as exc:
        results.append(
            DoctorCheckResult(
                "session-store",
                "fail",
                f"Could not write session data: {exc}",
            )
        )

    with agent_runtime_context(
        workspace_root=options.workspace_root,
        enable_bash=options.allow_bash,
        allowed_commands=options.allowed_commands,
        max_file_size_bytes=options.max_file_size,
        confirmation_callback=lambda action, payload: False,
    ):
        tool_names = [tool["function"]["name"] for tool in get_agent_tools()]
        results.append(
            DoctorCheckResult(
                "tools",
                "pass",
                f"Enabled tools: {', '.join(tool_names)}",
            )
        )

        structure_result = execute_tool("list_project_structure", {"root_dir": "."})
        if structure_result.startswith("Error"):
            results.append(
                DoctorCheckResult(
                    "workspace-scan",
                    "fail",
                    structure_result,
                )
            )
        else:
            results.append(
                DoctorCheckResult(
                    "workspace-scan",
                    "pass",
                    "Workspace structure scan succeeded.",
                )
            )

        if options.allow_bash:
            default_command = "pwd"
            if options.allowed_commands and default_command not in options.allowed_commands:
                default_command = sorted(options.allowed_commands)[0]
            command_result = execute_tool(
                "run_bash_command",
                {"command": default_command},
            )
            if "not approved" in command_result:
                results.append(
                    DoctorCheckResult(
                        "bash-tool",
                        "pass",
                        (
                            f"Bash tool is enabled with allowlist "
                            f"{', '.join(sorted(options.allowed_commands or set()))}; "
                            "approval prompt would be required during normal use."
                        ),
                    )
                )
            elif command_result.startswith("Error"):
                results.append(
                    DoctorCheckResult(
                        "bash-tool",
                        "fail",
                        command_result,
                    )
                )
            else:
                results.append(
                    DoctorCheckResult(
                        "bash-tool",
                        "pass",
                        f"Bash tool is enabled and command '{default_command}' succeeded.",
                    )
                )
        else:
            results.append(
                DoctorCheckResult(
                    "bash-tool",
                    "warn",
                    "Bash tool is disabled. Use --allow-bash if you want command execution.",
                )
            )

    provider, env_vars, note = detect_model_credentials(options.model)
    if env_vars is None:
        status = "pass" if provider == "ollama" else "warn"
        results.append(
            DoctorCheckResult(
                "credentials",
                status,
                note,
            )
        )
    else:
        present = [env_var for env_var in env_vars if os.environ.get(env_var)]
        if present:
            results.append(
                DoctorCheckResult(
                    "credentials",
                    "pass",
                    f"{note} Found {', '.join(present)}.",
                )
            )
        else:
            results.append(
                DoctorCheckResult(
                    "credentials",
                    "fail",
                    f"{note} Missing any of: {', '.join(env_vars)}.",
                )
            )

    return results


async def run_live_probe(
    options: ResolvedOptions,
) -> DoctorCheckResult:
    from app.services.agent.llm import call_llm

    probe_messages = [
        {
            "role": "user",
            "content": "Reply with the single word READY.",
        }
    ]

    with agent_runtime_context(
        workspace_root=options.workspace_root,
        enable_bash=options.allow_bash,
        allowed_commands=options.allowed_commands,
        max_file_size_bytes=options.max_file_size,
        confirmation_callback=lambda action, payload: False,
    ):
        response_message, usage = await asyncio.wait_for(
            call_llm(probe_messages, model=options.model),
            timeout=15,
        )

    if isinstance(response_message, dict) and "error" in response_message:
        return DoctorCheckResult(
            "live-probe",
            "fail",
            f"Live model probe failed: {response_message['error']}",
        )

    content = str(getattr(response_message, "content", "") or "").strip()
    usage_detail = ""
    if usage and usage.get("total_tokens") is not None:
        usage_detail = f" (total tokens: {usage.get('total_tokens')})"
    return DoctorCheckResult(
        "live-probe",
        "pass",
        f"Model responded with: {content or '[empty response]'}{usage_detail}",
    )


async def run_once(
    args: argparse.Namespace,
    config: CliConfig,
) -> int:
    options = resolve_runtime_options(args, config.defaults)
    ui = ConsoleUI(use_color=options.use_color, auto_approve=options.auto_approve)
    history: list[dict[str, Any]] = []

    if not options.stateless:
        history = load_session_messages(options.workspace_root, options.session)

    updated_history, latest_usage = await execute_instruction(
        instruction=args.instruction,
        model=options.model,
        history=history,
        options=options,
        ui=ui,
    )

    save_if_needed(updated_history, options.model, options, ui)
    if latest_usage and latest_usage.get("total_tokens") is not None:
        ui.usage(latest_usage)

    return 0


async def chat_loop(
    args: argparse.Namespace,
    config: CliConfig,
) -> int:
    options = resolve_runtime_options(args, config.defaults)
    ui = ConsoleUI(use_color=options.use_color, auto_approve=options.auto_approve)
    history: list[dict[str, Any]] = []
    current_model = options.model

    if not options.stateless:
        history = load_session_messages(options.workspace_root, options.session)

    print_welcome_banner(ui, config)
    ui.info(f"Workspace: {options.workspace_root}")
    if options.stateless:
        ui.info("Session mode: stateless")
    else:
        ui.info(f"Session: {sanitize_session_name(options.session)}")
    ui.info(f"Model: {current_model}")
    ui.info("Type /help for chat commands.")

    while True:
        try:
            instruction = input(ui.prompt("you")).strip()
        except EOFError:
            ui.print_line()
            break

        if not instruction:
            continue
        if instruction.startswith("/"):
            should_continue, current_model = handle_chat_command(
                instruction,
                history,
                current_model,
                options,
                config,
                ui,
            )
            if not should_continue:
                break
            continue

        history, latest_usage = await execute_instruction(
            instruction=instruction,
            model=current_model,
            history=history,
            options=options,
            ui=ui,
        )

        save_if_needed(history, current_model, options, ui)
        if latest_usage and latest_usage.get("total_tokens") is not None:
            ui.usage(latest_usage)

    return 0


async def doctor(
    args: argparse.Namespace,
    config: CliConfig,
) -> int:
    options = resolve_runtime_options(args, config.defaults)
    ui = ConsoleUI(use_color=options.use_color, auto_approve=True)
    results = run_workspace_checks(options, config, args)

    if args.live:
        credentials_status = next(
            (result.status for result in results if result.name == "credentials"),
            "warn",
        )
        workspace_status = next(
            (result.status for result in results if result.name == "workspace"),
            "fail",
        )
        if credentials_status == "fail" or workspace_status == "fail":
            results.append(
                DoctorCheckResult(
                    "live-probe",
                    "warn",
                    "Live probe skipped because workspace or credentials checks failed.",
                )
            )
        else:
            results.append(await run_live_probe(options))

    pass_count = 0
    warn_count = 0
    fail_count = 0

    for result in results:
        render_doctor_result(ui, result)
        if result.status == "pass":
            pass_count += 1
        elif result.status == "warn":
            warn_count += 1
        else:
            fail_count += 1

    ui.print_line()
    if fail_count:
        ui.error(
            f"Doctor finished with {pass_count} passed, {warn_count} warnings, and {fail_count} failures."
        )
        return 1

    ui.success(
        f"Doctor finished with {pass_count} passed and {warn_count} warnings."
    )
    return 0


def print_sessions(args: argparse.Namespace, config: CliConfig) -> int:
    workspace_value = resolve_value(args.workspace, config.defaults.workspace, ".")
    workspace_root = resolve_workspace(str(workspace_value))
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
        description="Local CLI for Apsara.",
    )
    parser.add_argument(
        "--config",
        default=None,
        help=(
            "Path to a TOML config file. Defaults to "
            f"{DEFAULT_CONFIG_PATH}"
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_shared_options(subparser: argparse.ArgumentParser) -> None:
        subparser.add_argument(
            "--workspace",
            default=None,
            help="Workspace root the agent is allowed to access.",
        )
        subparser.add_argument(
            "--model",
            default=None,
            help="Model name to send through LiteLLM.",
        )
        subparser.add_argument(
            "--session",
            default=None,
            help="Session name for local conversation persistence.",
        )
        subparser.add_argument(
            "--stateless",
            dest="stateless",
            action="store_true",
            default=None,
            help="Run without loading or saving local session history.",
        )
        subparser.add_argument(
            "--stateful",
            dest="stateless",
            action="store_false",
            help="Force session history on even if the config enables stateless mode.",
        )
        subparser.add_argument(
            "--allow-bash",
            dest="allow_bash",
            action="store_true",
            default=None,
            help="Enable the local bash tool for allowlisted non-interactive commands.",
        )
        subparser.add_argument(
            "--no-bash",
            dest="allow_bash",
            action="store_false",
            help="Disable the local bash tool for this run.",
        )
        subparser.add_argument(
            "--allowed-commands",
            default=None,
            help="Comma-separated command allowlist used with bash tool access.",
        )
        subparser.add_argument(
            "--max-file-size",
            type=int,
            default=None,
            help="Override the maximum readable file size in bytes for this run.",
        )
        subparser.add_argument(
            "--auto-approve",
            dest="auto_approve",
            action="store_true",
            default=None,
            help="Skip interactive confirmations for writes and local commands.",
        )
        subparser.add_argument(
            "--confirm",
            dest="auto_approve",
            action="store_false",
            help="Require confirmations even if the config auto-approves actions.",
        )
        subparser.add_argument(
            "--color",
            dest="color",
            action="store_true",
            default=None,
            help="Force colored terminal output.",
        )
        subparser.add_argument(
            "--no-color",
            dest="color",
            action="store_false",
            help="Disable colored terminal output.",
        )

    run_parser = subparsers.add_parser(
        "run", help="Run one instruction against the local workspace."
    )
    run_parser.add_argument("instruction", help="Instruction to send to the agent.")
    add_shared_options(run_parser)

    chat_parser = subparsers.add_parser(
        "chat", help="Open an interactive local chat session."
    )
    add_shared_options(chat_parser)

    sessions_parser = subparsers.add_parser(
        "sessions", help="List saved local sessions for a workspace."
    )
    sessions_parser.add_argument(
        "--workspace",
        default=None,
        help="Workspace root whose saved sessions should be listed.",
    )

    doctor_parser = subparsers.add_parser(
        "doctor",
        help="Validate config, workspace access, tool readiness, and likely model credentials.",
    )
    add_shared_options(doctor_parser)
    doctor_parser.add_argument(
        "--live",
        action="store_true",
        help="Attempt a short live model probe after offline checks pass.",
    )

    return parser


async def dispatch_command(args: argparse.Namespace, config: CliConfig) -> int:
    if args.command == "run":
        return await run_once(args, config)
    if args.command == "chat":
        return await chat_loop(args, config)
    if args.command == "sessions":
        return print_sessions(args, config)
    if args.command == "doctor":
        return await doctor(args, config)
    raise ValueError(f"Unknown command: {args.command}")


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        config = load_cli_config(args.config)
        load_cli_environment(args, config)
        return asyncio.run(dispatch_command(args, config))
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
