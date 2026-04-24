import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
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

from app.cli.text import format_rich_text_lines, truncate_text


def terminal_width(default: int = 96) -> int:
    return shutil.get_terminal_size((default, 24)).columns


def default_use_color() -> bool:
    return sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


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


class ConsoleUI:
    def __init__(self, use_color: bool, auto_approve: bool = False):
        self.use_color = use_color
        self.auto_approve = auto_approve
        self.approve_all = auto_approve
        self.hidden_events: list[Any] = []
        self.latest_hidden_events: list[Any] = []
        self.current_turn_hidden_events: list[Any] = []
        self.work_notice_shown = False
        self.spinner_message = "Apsara is working"
        self.spinner_stop_event = threading.Event()
        self.spinner_thread: Optional[threading.Thread] = None
        self.spinner_lock = threading.Lock()

    def style(self, text: str, *codes: str) -> str:
        if not self.use_color:
            return text
        joined_codes = ";".join(codes)
        return f"\033[{joined_codes}m{text}\033[0m"

    def print_line(self, text: str = "") -> None:
        self.stop_spinner()
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
        return max(44, min(fallback, terminal_width() - 8))

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

    def resolve_editor_command(self) -> list[str]:
        editor = os.environ.get("VISUAL") or os.environ.get("EDITOR") or "vi"
        try:
            return shlex.split(editor)
        except ValueError:
            return [editor]

    def open_editor_preview(self, title: str, diff_text: str, path_hint: Optional[str] = None) -> bool:
        if not diff_text.strip():
            self.warning("No diff available to open in an editor.")
            return False

        editor_command = self.resolve_editor_command()
        if not editor_command:
            self.error("No editor command is configured. Set $EDITOR or $VISUAL first.")
            return False

        header_lines = [
            "Apsara by Bondeth",
            f"Review: {title}",
            "Close the editor to return to the approval prompt.",
        ]
        if path_hint:
            header_lines.append(f"Target: {path_hint}")
        review_text = "\n".join(header_lines) + "\n\n" + diff_text + "\n"

        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            suffix=".diff",
            prefix="apsara-review-",
            delete=False,
        ) as temp_file:
            temp_file.write(review_text)
            temp_path = Path(temp_file.name)

        try:
            self.print_notice(
                "editor",
                f"Opening review in {' '.join(editor_command)}",
                "15",
                "48;2;93;108;137",
                "38;2;217;226;242",
            )
            subprocess.run(editor_command + [str(temp_path)], check=False)
            return True
        except FileNotFoundError:
            self.error(f"Editor '{editor_command[0]}' was not found. Set $EDITOR or $VISUAL to a valid command.")
            return False
        except Exception as exc:
            self.error(f"Could not open editor preview: {exc}")
            return False
        finally:
            temp_path.unlink(missing_ok=True)

    def print_notice(self, label: str, text: str, fg_code: str, bg_code: str, body_color: str) -> None:
        self.print_line(f"{self.badge(label, fg_code, bg_code)} {self.style(text, body_color)}")

    def begin_turn(self) -> None:
        self.stop_spinner()
        self.current_turn_hidden_events = []
        self.work_notice_shown = False

    def spinner_enabled(self) -> bool:
        return sys.stdout.isatty() and os.environ.get("CI") is None

    def spinner_frames(self) -> list[str]:
        gold = "38;2;214;171;65"
        amber = "38;2;242;201;76"
        blue = "38;2;111;154;255"
        cyan = "38;2;122;210;222"
        text_color = "38;2;236;220;184"
        muted = "38;2;147;130;107"
        if not self.use_color:
            return [
                f"<> {self.spinner_message}   ",
                f"<> {self.spinner_message}.  ",
                f"<> {self.spinner_message}.. ",
                f"<> {self.spinner_message}...",
            ]
        return [
            f"{self.style('◜◈◝', gold)} {self.style(self.spinner_message, text_color)}{self.style('   ', muted)}",
            f"{self.style('◠◆◠', amber)} {self.style(self.spinner_message, text_color)}{self.style('.  ', muted)}",
            f"{self.style('◞◉◟', blue)} {self.style(self.spinner_message, text_color)}{self.style('.. ', muted)}",
            f"{self.style('◡◈◡', cyan)} {self.style(self.spinner_message, text_color)}{self.style('...', muted)}",
        ]

    def render_spinner_line(self, frame: str) -> str:
        return f"\r\033[2K{self.badge('apsara', '15', '48;2;133;92;219')} {frame}"

    def _spinner_worker(self) -> None:
        frames = self.spinner_frames()
        index = 0
        while not self.spinner_stop_event.is_set():
            with self.spinner_lock:
                sys.stdout.write(self.render_spinner_line(frames[index % len(frames)]))
                sys.stdout.flush()
            index += 1
            if self.spinner_stop_event.wait(0.12):
                break

    def start_spinner(self, message: str) -> None:
        self.spinner_message = message
        if not self.spinner_enabled():
            self.print_notice("work", f"{message}...", "17", "48;2;242;201;76", "38;2;236;220;184")
            return
        if self.spinner_thread and self.spinner_thread.is_alive():
            return
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

    def note_working(self, message: str = "Apsara is working") -> None:
        if self.work_notice_shown:
            return
        self.start_spinner(message)
        self.work_notice_shown = True

    def hide_event(self, kind: str, title: str, detail: str = "") -> None:
        from app.cli.types import HiddenCliEvent
        event = HiddenCliEvent(kind=kind, title=title, detail=detail)
        self.current_turn_hidden_events.append(event)
        self.hidden_events.append(event)
        self.hidden_events = self.hidden_events[-80:]

    def finish_turn(self) -> None:
        self.stop_spinner()
        self.latest_hidden_events = list(self.current_turn_hidden_events)
        if self.latest_hidden_events:
            self.info(f"Hidden {len(self.latest_hidden_events)} internal event(s). Type /details to inspect.")

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
            f"{self.badge('enter', '17', '48;2;121;210;184')} approve",
            f"{self.badge('n', '17', '48;2;239;167;74')} reject",
            f"{self.badge('a', '17', '48;2;111;154;255')} always approve",
        ]
        if allow_view:
            options.append(f"{self.badge('v', '17', '48;2;93;108;137')} view full diff")
        if allow_editor:
            options.append(f"{self.badge('e', '15', '48;2;133;92;219')} open in $EDITOR")
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
            if allow_editor and key in {"e", "E"}:
                return "editor"
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

        title, preview, diff_preview, diff_full, diff_editor, path_hint = describe_action(action, payload)
        self.print_line()
        self.print_line(
            f"{self.badge('approve', '17', '48;2;255;196;108')} "
            f"{self.style(title, '1', '38;2;247;237;222')}"
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
                self.print_notice("diff", "Full change preview", "15", "48;2;93;108;137", "38;2;217;226;242")
                self.render_diff_text(diff_full)
                continue
            if choice == "editor":
                self.open_editor_preview(title, diff_editor or diff_full or diff_preview or "", path_hint)
                continue
            if choice == "always":
                self.approve_all = True
                return True
            return choice == "approve"
