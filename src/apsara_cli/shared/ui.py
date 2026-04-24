import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

try:
    import termios
    import tty
    import select as _select
except ImportError:
    termios = None
    tty = None
    _select = None

try:
    import msvcrt
except ImportError:
    msvcrt = None

from apsara_cli.cli.text import format_rich_text_lines, truncate_text


# ── Terminal helpers ──────────────────────────────────────────────────────────

def terminal_width(default: int = 96) -> int:
    return shutil.get_terminal_size((default, 24)).columns


def default_use_color() -> bool:
    return sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


# ── Spinner configuration ─────────────────────────────────────────────────────

_BRAILLE = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

# Gradient palettes per activity type
_PALETTE_THINKING = [
    "38;2;111;154;255", "38;2;128;168;255", "38;2;144;182;255",
    "38;2;158;174;248", "38;2;175;154;244", "38;2;197;154;244",
    "38;2;160;154;255", "38;2;132;182;255", "38;2;122;210;222",
    "38;2;140;200;220",
]
_PALETTE_EXECUTING = [
    "38;2;238;206;124", "38;2;248;216;130", "38;2;255;196;108",
    "38;2;255;185;100", "38;2;242;201;76",  "38;2;248;210;100",
    "38;2;255;220;120", "38;2;248;200;90",  "38;2;236;190;80",
    "38;2;244;206;110",
]
_PALETTE_WRITING = [
    "38;2;121;210;184", "38;2;130;220;190", "38;2;140;224;180",
    "38;2;150;216;168", "38;2;166;216;168", "38;2;140;200;140",
    "38;2;120;210;160", "38;2;110;200;180", "38;2;130;218;186",
    "38;2;142;222;174",
]


def _spinner_palette(message: str) -> list[str]:
    m = message.lower()
    if any(w in m for w in ("writ", "creat", "updat", "file", "saving")):
        return _PALETTE_WRITING
    if any(w in m for w in ("run", "execut", "command", "bash", "scan")):
        return _PALETTE_EXECUTING
    return _PALETTE_THINKING


# ── Action description helpers ────────────────────────────────────────────────

def describe_action(
    action: str, payload: dict[str, Any]
) -> tuple[str, Optional[str], Optional[str], Optional[str], Optional[str], Optional[str]]:
    if action == "write_to_file":
        path = payload.get("display_path") or payload.get("path", "<unknown>")
        preview = payload.get("content_preview")
        title = f"Create file {path}" if payload.get("is_new_file") else f"Update file {path}"
        return (
            title,
            preview if isinstance(preview, str) else None,
            payload.get("diff_preview") if isinstance(payload.get("diff_preview"), str) else None,
            payload.get("diff_full") if isinstance(payload.get("diff_full"), str) else None,
            payload.get("diff_editor") if isinstance(payload.get("diff_editor"), str) else None,
            path,
        )

    if action == "replace_file_lines":
        path = payload.get("display_path") or payload.get("path", "<unknown>")
        preview = payload.get("replacement_preview")
        return (
            f"Replace lines {payload.get('start_line', '?')}-{payload.get('end_line', '?')} in {path}",
            preview if isinstance(preview, str) else None,
            payload.get("diff_preview") if isinstance(payload.get("diff_preview"), str) else None,
            payload.get("diff_full") if isinstance(payload.get("diff_full"), str) else None,
            payload.get("diff_editor") if isinstance(payload.get("diff_editor"), str) else None,
            path,
        )

    if action == "run_bash_command":
        command = payload.get("command", "")
        cwd = payload.get("cwd", "")
        return (f"Run command in {cwd}: {command}", None, None, None, None, None)

    return (f"Approve action: {action}", None, None, None, None, None)


# ── ConsoleUI ─────────────────────────────────────────────────────────────────

class ConsoleUI:
    def __init__(
        self,
        use_color: bool,
        auto_approve: bool = False,
        typing_delay: float = 0.008,
    ):
        self.use_color = use_color
        self.auto_approve = auto_approve
        self.approve_all = auto_approve
        self.typing_delay = typing_delay if sys.stdout.isatty() and not os.environ.get("CI") else 0.0

        self.hidden_events: list[Any] = []
        self.latest_hidden_events: list[Any] = []
        self.current_turn_hidden_events: list[Any] = []
        self.work_notice_shown = False

        self.spinner_message = "Apsara is working"
        self.spinner_stop_event = threading.Event()
        self.spinner_thread: Optional[threading.Thread] = None
        self.spinner_lock = threading.Lock()
        self._spinner_start_time: float = 0.0
        self._spinner_frame_index: int = 0
        self._spinner_color_index: int = 0

    # ── Low-level styling ─────────────────────────────────────────────────────

    def style(self, text: str, *codes: str) -> str:
        if not self.use_color or not codes:
            return text
        return f"\033[{';'.join(codes)}m{text}\033[0m"

    def badge(self, text: str, fg_code: str = "30", bg_code: str = "47") -> str:
        if not self.use_color:
            return f"[{text.upper()}]"
        return self.style(f" {text.upper()} ", "1", fg_code, bg_code)

    def muted(self, text: str) -> str:
        return self.style(text, "2", "38;2;160;166;178")

    def dim(self, text: str) -> str:
        return self.style(text, "38;2;140;130;118")

    # ── Output primitives ─────────────────────────────────────────────────────

    def print_line(self, text: str = "") -> None:
        self.stop_spinner()
        print(text)

    def print_block(self, text: str, color_code: Optional[str] = None) -> None:
        for raw_line in text.splitlines() or [""]:
            line = f"  {raw_line}"
            self.print_line(self.style(line, color_code) if color_code else line)

    def content_width(self, fallback: int = 84) -> int:
        return max(44, min(fallback, terminal_width() - 8))

    def _print_typed(self, prefix: str, content: str, color_code: str, delay: float) -> None:
        """Print a styled line with optional character-by-character animation."""
        self.stop_spinner()
        if not delay or not sys.stdout.isatty() or os.environ.get("CI"):
            print(f"{prefix}{self.style(content, color_code)}")
            return
        ansi_open = f"\033[{color_code}m" if color_code and self.use_color else ""
        ansi_close = "\033[0m" if color_code and self.use_color else ""
        sys.stdout.write(prefix + ansi_open)
        sys.stdout.flush()
        for char in content:
            sys.stdout.write(char)
            sys.stdout.flush()
            time.sleep(delay)
        sys.stdout.write(ansi_close + "\n")
        sys.stdout.flush()

    def _print_box_line(self, left: str, content: str, right: str, color_code: str = "") -> None:
        """Print one line inside a box."""
        self.stop_spinner()
        if color_code:
            print(f"  {self.style(left, color_code)}{content}{self.style(right, color_code)}")
        else:
            print(f"  {left}{content}{right}")

    # ── Rich text renderer ────────────────────────────────────────────────────

    def render_rich_text(self, text: str, typing_delay: float = 0.0) -> None:
        width = self.content_width()
        lines = format_rich_text_lines(text, width)
        in_code_block = False
        code_lines: list[str] = []

        def flush_code(lines_buf: list[str]) -> None:
            if not lines_buf:
                return
            box_w = max((len(l) for l in lines_buf), default=0) + 4
            border_color = "38;2;80;100;140"
            top    = self.style("╭" + "─" * box_w + "╮", border_color)
            bottom = self.style("╰" + "─" * box_w + "╯", border_color)
            self.print_line(f"  {top}")
            for cl in lines_buf:
                pad = " " * (box_w - len(cl) - 2)
                left  = self.style("│ ", border_color)
                right = self.style(" │", border_color)
                print(f"  {left}{self.style(cl, '38;2;173;203;255')}{pad}{right}")
            self.print_line(f"  {bottom}")

        for line_type, line in lines:
            if line_type == "code":
                in_code_block = True
                code_lines.append(line)
                continue
            if in_code_block and line_type != "code":
                flush_code(code_lines)
                code_lines = []
                in_code_block = False

            if line_type == "blank":
                self.print_line()
            elif line_type == "heading":
                self.print_line()
                self.print_line(f"  {self.style(line, '1', '38;2;250;216;143')}")
            elif line_type == "list":
                self._print_typed("  ", line, "38;2;220;226;240", typing_delay * 0.5)
            else:
                self._print_typed("  ", line, "38;2;240;236;231", typing_delay)

        if code_lines:
            flush_code(code_lines)

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

    # ── Spinner ───────────────────────────────────────────────────────────────

    def spinner_enabled(self) -> bool:
        return sys.stdout.isatty() and os.environ.get("CI") is None

    def _spinner_worker(self) -> None:
        palette = _spinner_palette(self.spinner_message)
        frame_idx = 0
        color_idx = 0
        start = time.monotonic()

        while not self.spinner_stop_event.is_set():
            # Recompute palette if message changed
            palette = _spinner_palette(self.spinner_message)

            frame = _BRAILLE[frame_idx % len(_BRAILLE)]
            color = palette[color_idx % len(palette)]
            elapsed = time.monotonic() - start
            elapsed_str = self.style(f"  {elapsed:.0f}s", "38;2;130;120;110") if elapsed >= 2 else ""

            msg_color = "38;2;228;218;205"
            dot_color = "38;2;150;140;130"

            if self.use_color:
                spinner_char = f"\033[{color}m{frame}\033[0m"
            else:
                spinner_char = frame

            with self.spinner_lock:
                msg = self.spinner_message
                line = (
                    f"\r\033[2K"
                    f"  {self.badge('apsara', '15', '48;2;133;92;219')} "
                    f"{spinner_char} "
                    f"{self.style(msg, msg_color)}"
                    f"{self.style('...', dot_color)}"
                    f"{elapsed_str}"
                )
                sys.stdout.write(line)
                sys.stdout.flush()

            frame_idx += 1
            color_idx += 1
            if self.spinner_stop_event.wait(0.08):
                break

    def start_spinner(self, message: str) -> None:
        self.spinner_message = message
        if not self.spinner_enabled():
            self.print_notice("work", f"{message}...", "17", "48;2;242;201;76", "38;2;236;220;184")
            return
        if self.spinner_thread and self.spinner_thread.is_alive():
            return
        self._spinner_start_time = time.monotonic()
        self.spinner_stop_event.clear()
        self.spinner_thread = threading.Thread(target=self._spinner_worker, daemon=True)
        self.spinner_thread.start()

    def stop_spinner(self) -> None:
        if not self.spinner_thread:
            return
        self.spinner_stop_event.set()
        self.spinner_thread.join(timeout=0.3)
        with self.spinner_lock:
            sys.stdout.write("\r\033[2K")
            sys.stdout.flush()
        self.spinner_thread = None

    def update_spinner_action(self, action: str) -> None:
        """Update the spinner message without restarting (thread-safe)."""
        with self.spinner_lock:
            self.spinner_message = action

    def note_working(self, message: str = "Apsara is working") -> None:
        if self.work_notice_shown:
            return
        self.start_spinner(message)
        self.work_notice_shown = True

    # ── Turn structure ────────────────────────────────────────────────────────

    def print_turn_separator(self, turn: int = 0) -> None:
        """Print a visual separator between conversation turns."""
        self.stop_spinner()
        w = min(terminal_width(), 88)
        now = datetime.now().strftime("%H:%M:%S")
        label = f" turn {turn} · {now} " if turn > 0 else f" {now} "
        side = max((w - len(label) - 4) // 2, 4)
        line = "─" * side + label + "─" * side
        print(f"\n  {self.style(line, '2', '38;2;110;100;90')}\n")

    def print_rule(self, text: str = "") -> None:
        """Thin separator rule, optionally labeled."""
        w = min(terminal_width(), 88)
        if text:
            side = max((w - len(text) - 6) // 2, 2)
            line = "─" * side + f"  {text}  " + "─" * side
        else:
            line = "─" * (w - 4)
        print(f"  {self.style(line, '2', '38;2;110;100;90')}")

    # ── Notification methods ──────────────────────────────────────────────────

    def print_notice(self, label: str, text: str, fg_code: str, bg_code: str, body_color: str) -> None:
        self.print_line(f"  {self.badge(label, fg_code, bg_code)} {self.style(text, body_color)}")

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

    def blocked(self, text: str) -> None:
        self.print_line()
        border = "38;2;200;140;60"
        w = min(self.content_width(), 72)
        label = self.badge("blocked", "17", "48;2;200;120;40")
        self.print_line(f"  {label} {self.style(text, '38;2;247;223;181')}")

    def prompt(self, label: str = "you") -> str:
        return f"\n  {self.badge(label, '15', '48;2;49;104;194')} "

    def session_saved(self, session_path: Path) -> None:
        self.print_line(f"  {self.dim(f'  ↳ saved to {session_path}')}")

    def usage(self, usage_data: dict[str, Any]) -> None:
        p = usage_data.get("prompt_tokens", "?")
        c = usage_data.get("completion_tokens", "?")
        t = usage_data.get("total_tokens", "?")
        self.print_line(
            f"  {self.dim(f'  tokens  {p} in · {c} out · {t} total')}"
        )

    # ── Assistant message ─────────────────────────────────────────────────────

    def assistant(self, text: str) -> None:
        self.print_line()
        # Header bar
        header_line = (
            f"  {self.badge('apsara', '15', '48;2;133;92;219')}  "
            f"{self.style('Apsara by Bondeth', '1', '38;2;215;200;255')}"
        )
        self.print_line(header_line)
        self.print_line()
        self.render_rich_text(text, typing_delay=self.typing_delay)

    # ── Tool activity (inline compact) ───────────────────────────────────────

    def tool_activity(self, tool_name: str, summary: str) -> None:
        """Show a compact inline tool call indicator."""
        icon = self.style("◆", "38;2;100;150;220")
        name = self.style(tool_name, "38;2;180;210;255")
        args = self.dim(f"  {summary}") if summary else ""
        self.print_line(f"    {icon} {name}{args}")

    def tool_result_activity(self, tool_name: str, success: bool, summary: str) -> None:
        """Show a compact inline tool result indicator."""
        if success:
            icon = self.style("✓", "38;2;120;200;150")
            color = "38;2;160;220;180"
        else:
            icon = self.style("✗", "38;2;220;100;100")
            color = "38;2;255;168;168"
        self.print_line(f"    {icon} {self.style(summary, color)}")

    # ── Hidden events log ─────────────────────────────────────────────────────

    def begin_turn(self) -> None:
        self.stop_spinner()
        self.current_turn_hidden_events = []
        self.work_notice_shown = False

    def finish_turn(self) -> None:
        self.stop_spinner()
        self.latest_hidden_events = list(self.current_turn_hidden_events)
        count = len(self.latest_hidden_events)
        if count:
            plural = "s" if count != 1 else ""
            self.print_line(
                f"  {self.dim(f'  /details to inspect {count} internal step{plural}')}"
            )

    def hide_event(self, kind: str, title: str, detail: str = "") -> None:
        from apsara_cli.cli.types import HiddenCliEvent
        event = HiddenCliEvent(kind=kind, title=title, detail=detail)
        self.current_turn_hidden_events.append(event)
        self.hidden_events.append(event)
        self.hidden_events = self.hidden_events[-80:]

    def show_hidden_events(self) -> None:
        events = self.latest_hidden_events or self.hidden_events[-12:]
        if not events:
            self.info("No hidden internal activity yet.")
            return

        self.print_line()
        count = len(events)
        plural = "s" if count != 1 else ""
        self.print_line(
            f"  {self.badge('details', '15', '48;2;70;85;115')}  "
            f"{self.style(f'{count} internal step{plural}', '38;2;200;210;230')}"
        )
        self.print_line()

        border_color = "38;2;80;95;125"
        for index, event in enumerate(events, start=1):
            kind_badge = self.badge(event.kind, "15", "48;2;60;75;105")
            title_text = self.style(event.title, "38;2;210;218;235")

            # Box top
            box_w = min(self.content_width() - 4, 72)
            self.print_line(f"  {self.style('╭' + '─' * (box_w), border_color)}")
            self.print_line(f"  {self.style('│', border_color)}  {kind_badge} {title_text}")

            if event.detail:
                self.print_line(f"  {self.style('│', border_color)}")
                for dl in truncate_text(event.detail, max_lines=12, max_chars=900).splitlines():
                    padded = dl[:box_w - 3]
                    self.print_line(f"  {self.style('│', border_color)}  {self.style(padded, '38;2;175;182;200')}")

            self.print_line(f"  {self.style('╰' + '─' * (box_w), border_color)}")
            if index < count:
                self.print_line()

    # ── Input confirmation ────────────────────────────────────────────────────

    def read_single_key(self) -> str:
        if msvcrt is not None:
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
                if key == "\x1b" and _select.select([sys.stdin], [], [], 0.02)[0]:
                    key += sys.stdin.read(1)
                    if _select.select([sys.stdin], [], [], 0.02)[0]:
                        key += sys.stdin.read(1)
                return key
            finally:
                termios.tcsetattr(file_descriptor, termios.TCSADRAIN, original_settings)

        return input().strip()[:1]

    def prompt_confirmation_choice(self, *, allow_view: bool = False, allow_editor: bool = False) -> str:
        options = [
            f"{self.badge('↵', '17', '48;2;80;170;140')} approve",
            f"{self.badge('n', '17', '48;2;200;100;80')} reject",
            f"{self.badge('a', '17', '48;2;80;120;200')} always",
        ]
        if allow_view:
            options.append(f"{self.badge('v', '17', '48;2;80;95;125')} full diff")
        if allow_editor:
            options.append(f"{self.badge('e', '15', '48;2;110;80;180')} $EDITOR")
        self.print_line(f"  {'  '.join(options)}")

        while True:
            key = self.read_single_key()
            if key in {"", "\r", "\n", "y", "Y"}:
                self.print_line(f"  {self.style('  ↳ approved', '38;2;120;200;150')}")
                return "approve"
            if key in {"a", "A"}:
                self.print_line(f"  {self.style('  ↳ always approve enabled', '38;2;120;180;255')}")
                return "always"
            if allow_view and key in {"v", "V"}:
                return "view"
            if allow_editor and key in {"e", "E"}:
                return "editor"
            if key in {"n", "N", "\x1b", "q", "Q", "\x03"}:
                self.print_line(f"  {self.style('  ↳ rejected', '38;2;220;120;100')}")
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

        title, preview, diff_preview, diff_full, diff_editor, path_hint = describe_action(action, payload)
        self.print_line()
        border = "38;2;180;140;60"
        self.print_line(
            f"  {self.badge('approve', '17', '48;2;180;130;40')}  "
            f"{self.style(title, '1', '38;2;247;230;190')}"
        )
        if diff_preview:
            self.render_diff_text(diff_preview)
        elif preview:
            self.print_block(truncate_text(preview, max_lines=12, max_chars=900), "38;2;205;211;222")

        while True:
            choice = self.prompt_confirmation_choice(
                allow_view=bool(diff_full and diff_full != diff_preview),
                allow_editor=bool(diff_editor),
            )
            if choice == "view":
                self.print_line()
                self.print_notice("diff", "Full change preview", "15", "48;2;80;95;125", "38;2;210;220;240")
                self.render_diff_text(diff_full)
                continue
            if choice == "editor":
                self._open_editor_preview(title, diff_editor or diff_full or diff_preview or "", path_hint)
                continue
            if choice == "always":
                self.approve_all = True
                return True
            return choice == "approve"

    # ── Editor preview ────────────────────────────────────────────────────────

    def resolve_editor_command(self) -> list[str]:
        editor = os.environ.get("VISUAL") or os.environ.get("EDITOR") or "vi"
        try:
            return shlex.split(editor)
        except ValueError:
            return [editor]

    def _open_editor_preview(self, title: str, diff_text: str, path_hint: Optional[str] = None) -> bool:
        if not diff_text.strip():
            self.warning("No diff available to open in an editor.")
            return False

        editor_command = self.resolve_editor_command()
        if not editor_command:
            self.error("No editor command is configured. Set $EDITOR or $VISUAL first.")
            return False

        header_lines = ["Apsara by Bondeth", f"Review: {title}", "Close the editor to return."]
        if path_hint:
            header_lines.append(f"Target: {path_hint}")
        review_text = "\n".join(header_lines) + "\n\n" + diff_text + "\n"

        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", suffix=".diff", prefix="apsara-review-", delete=False,
        ) as temp_file:
            temp_file.write(review_text)
            temp_path = Path(temp_file.name)

        try:
            self.print_notice("editor", f"Opening in {editor_command[0]}", "15", "48;2;80;95;125", "38;2;210;220;240")
            subprocess.run(editor_command + [str(temp_path)], check=False)
            return True
        except FileNotFoundError:
            self.error(f"Editor '{editor_command[0]}' not found. Set $EDITOR or $VISUAL.")
            return False
        except Exception as exc:
            self.error(f"Could not open editor preview: {exc}")
            return False
        finally:
            temp_path.unlink(missing_ok=True)

    # ── Misc display helpers ──────────────────────────────────────────────────

    def tool_call(self, name: str, arguments: dict[str, Any]) -> None:
        arguments_text = json.dumps(arguments, ensure_ascii=True)
        self.print_line(
            f"  {self.badge('tool', '15', '48;2;50;100;170')} "
            f"{self.style(name, '38;2;180;210;255')}"
        )
        self.print_block(arguments_text, "38;2;160;190;220")

    def tool_result(self, result: str) -> None:
        self.print_line(
            f"  {self.badge('result', '15', '48;2;40;90;155')} "
            f"{self.style('Tool output', '38;2;180;210;255')}"
        )
        self.print_block(result, "38;2;210;220;235")
