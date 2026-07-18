"""
Full-screen split-pane TUI (opt-in via --tui), modeled on OpenCode's layout:
a scrollable chat pane with bordered message panels, a persistent sidebar
(session title + live context stats + tips), and a bottom status bar with the
working directory and token usage, all inside one `prompt_toolkit` full-screen
Application.

Design note: this file does NOT reimplement any of ConsoleUI's formatting
logic (badges, diffs, markdown/code rendering, confirm-dialog boxes, the
/models picker) -- `TuiConsoleUI` only swaps *where* that already-styled
output goes (into an in-memory transcript buffer that gets redrawn, instead
of straight to stdout). Most interactive flows (confirmations, the /models
picker) stay fully inline this way: they call ui.print_line()/read_single_key()
like any other command, and nothing ever leaves the running Application or
erases the screen.

A few blocking, synchronous calls genuinely need the real terminal (getpass
for API keys, in particular, since masked input has no inline equivalent
here). Those are safe to run as-is: whatever slash command or tool
confirmation triggers them runs synchronously inside a background task
(`_handle_submission`, or engine/tools.py calling `execute_tool()` directly
without `await`), so the outer Application's event loop is never
concurrently polling the terminal at that moment -- there is no real
contention to arbitrate. We mark those stretches as "passthrough" (real
terminal I/O, via `_run_passthrough`) and force a full repaint of the outer
app when they finish.
"""

import asyncio
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from prompt_toolkit.application import Application, run_in_terminal
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.data_structures import Point
from prompt_toolkit.filters import Condition
from prompt_toolkit.formatted_text import ANSI
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import Layout
from prompt_toolkit.layout.containers import (
    DynamicContainer,
    Float,
    FloatContainer,
    HSplit,
    VSplit,
    Window,
    WindowAlign,
)
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.layout.menus import CompletionsMenu
from prompt_toolkit.layout.processors import Processor, Transformation
from prompt_toolkit.styles import Style

from apsara_cli.cli.chat import (
    _switch_model,
    build_mode_line,
    build_model_rows,
    execute_instruction,
    handle_chat_command,
    save_if_needed,
)
from apsara_cli.cli.input import SlashCompleter
from apsara_cli.cli.options import resolve_runtime_options
from apsara_cli.cli.session import load_session_messages, sanitize_session_name
from apsara_cli.engine.models import format_context_window, is_key_available, lookup_model
from apsara_cli.shared.ui import ConsoleUI, Theme

# Accent / chrome colors (ANSI truecolor), kept in one place.
_ACCENT = "38;2;96;150;250"      # blue left-bar / user accent
_DIMTXT = "38;2;120;125;138"


class TuiConsoleUI(ConsoleUI):
    """
    ConsoleUI backend for the full-screen TUI. All higher-level formatting
    methods are inherited unchanged from ConsoleUI; only the low-level
    output primitives are overridden here.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.lines: list[str] = []
        self.app: Optional[Application] = None
        self._passthrough = False
        self._spinner_frame = ""
        self._spinner_tick = 0
        self._spinner_task: Optional[asyncio.Task] = None

    def attach(self, app: Application) -> None:
        self.app = app

    def _invalidate(self) -> None:
        if self.app is not None:
            try:
                self.app.invalidate()
            except Exception:
                pass

    # ── Output primitives ─────────────────────────────────────────────────

    def print_line(self, text: str = "") -> None:
        if self._passthrough or self.app is None:
            super().print_line(text)
            return
        self._stop_spinner_tick()
        self.lines.extend(text.split("\n") if text else [""])
        self._invalidate()

    def _print_typed(self, prefix: str, content: str, color_code: str, delay: float) -> None:
        # No fake per-character typing effect inside the pane -- the LLM's
        # real token stream already provides the incremental feel via
        # stream_text_chunk. Append the fully-styled line in one shot.
        if self._passthrough or self.app is None:
            super()._print_typed(prefix, content, color_code, delay)
            return
        self._stop_spinner_tick()
        self.lines.append(f"{prefix}{self.style(content, color_code)}")
        self._invalidate()

    def stream_text_start(self) -> None:
        if self._passthrough or self.app is None:
            super().stream_text_start()
            return
        self._stop_spinner_tick()
        # The base-class "+ Thought: <elapsed>" marker writes through our
        # overridden print_line, straight into the transcript buffer.
        self._print_thought_marker()
        self.lines.append("")
        self.lines.append("  ")
        self._invalidate()

    def stream_text_chunk(self, chunk: str) -> None:
        if self._passthrough or self.app is None:
            super().stream_text_chunk(chunk)
            return
        if not self.lines:
            self.lines.append("")
        color = self.theme.body
        parts = chunk.split("\n")
        self.lines[-1] += self.style(parts[0], color) if parts[0] else ""
        for extra in parts[1:]:
            self.lines.append(f"  {self.style(extra, color)}" if extra else "  ")
        self._invalidate()

    def stream_text_end(self) -> None:
        if self._passthrough or self.app is None:
            super().stream_text_end()
            return
        self._invalidate()

    def redraw_block(self, prev_line_count: int, new_lines: list[str]) -> None:
        """Splice the transcript buffer in place instead of touching real
        stdout — keeps inline pickers (e.g. /models) inside the scrolling
        chat pane rather than a separate screen."""
        if self._passthrough or self.app is None:
            super().redraw_block(prev_line_count, new_lines)
            return
        if prev_line_count:
            del self.lines[-prev_line_count:]
        self.lines.extend(new_lines)
        self._invalidate()

    # ── Spinner: asyncio ticker instead of a raw-stdout thread ───────────

    def start_spinner(self, message: str) -> None:
        if self._passthrough or self.app is None:
            super().start_spinner(message)
            return
        self.spinner_message = message
        self._spinner_start_time = time.monotonic()
        self.spinner_stop_event.clear()
        if self._spinner_task is None or self._spinner_task.done():
            self._spinner_task = asyncio.get_event_loop().create_task(self._spinner_loop())

    async def _spinner_loop(self) -> None:
        frames = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
        i = 0
        while not self.spinner_stop_event.is_set():
            self._spinner_frame = frames[i % len(frames)]
            self._spinner_tick = i
            i += 1
            self._invalidate()
            await asyncio.sleep(0.08)
        self._spinner_frame = ""
        self._invalidate()

    def _stop_spinner_tick(self) -> None:
        self.spinner_stop_event.set()
        self._spinner_frame = ""

    def stop_spinner(self) -> None:
        if self._passthrough or self.app is None:
            super().stop_spinner()
            return
        self._stop_spinner_tick()
        self._invalidate()

    def update_spinner_action(self, action: str) -> None:
        if self._passthrough or self.app is None:
            super().update_spinner_action(action)
            return
        self.spinner_message = action

    # ── Transcript panels (used by the submit handler) ────────────────────

    def append_user_message(self, text: str) -> None:
        """A user turn: a left-accent-bordered panel."""
        bar = self.style("▌", _ACCENT)
        self.lines.append("")
        for raw in text.split("\n"):
            self.lines.append(f"  {bar} {self.style(raw, '1', '38;2;225;230;242')}")
        self._invalidate()

    # ── Blocking, real-terminal calls (confirmations, key entry, picker) ──

    def read_single_key(self) -> str:
        was = self._passthrough
        self._passthrough = True
        try:
            return super().read_single_key()
        finally:
            self._passthrough = was

    def confirm_action(self, action: str, payload: dict) -> bool:
        return self._run_passthrough(lambda: super(TuiConsoleUI, self).confirm_action(action, payload))

    def prompt_confirmation_choice(self, **kwargs: Any) -> str:
        return self._run_passthrough(lambda: super(TuiConsoleUI, self).prompt_confirmation_choice(**kwargs))

    def _run_passthrough(self, fn):
        """
        Hand the real terminal to a blocking call, then force the outer
        full-screen app to fully repaint once it's done.
        """
        self._passthrough = True
        if self.app is not None:
            try:
                self.app.renderer.erase()
            except Exception:
                pass
        try:
            return fn()
        finally:
            self._passthrough = False
            self._invalidate()


class _PlaceholderProcessor(Processor):
    """OpenCode-style dim hint text shown inside the input box while empty."""

    def __init__(self, text: str) -> None:
        self.text = text

    def apply_transformation(self, ti):
        if ti.lineno == 0 and not ti.document.text:
            return Transformation([("class:placeholder", self.text)])
        return Transformation(ti.fragments)


# ── Sidebar / status bar rendering ────────────────────────────────────────

def _shorten_path(path: str, width: int = 29) -> str:
    if len(path) <= width:
        return path
    return "…" + path[-(width - 1):]


# Sidebar accent colors — one hue per section, plus tier/health colors.
_C_CONTEXT = "38;2;110;200;235"   # cyan
_C_MODEL = "38;2;190;150;250"     # violet
_C_SESSION = "38;2;130;210;160"   # green
_C_WORKSPACE = "38;2;240;190;110" # gold
_C_CARD = "38;2;130;170;250"      # blue
_C_VALUE = "38;2;225;230;242"     # bright values
_TIER_COLORS = {"free": "38;2;130;210;160", "paid": "38;2;240;190;110", "local": "38;2;140;180;250"}

_SIDEBAR_RULE_W = 27


def _section(ui: "ConsoleUI", icon: str, title: str, color: str) -> str:
    """Colored section header with a faint trailing rule: '◍ Context ────'."""
    rule = "─" * max(_SIDEBAR_RULE_W - len(title) - len(icon) - 2, 0)
    return f" {ui.style(icon + ' ' + title, '1', color)} {ui.style(rule, '2', color)}"


def _meter(ui: "ConsoleUI", pct: int, width: int = 10) -> str:
    """Colored usage meter: '▰▰▰▱▱▱▱▱▱▱ 30%'."""
    filled = max(0, min(width, round(pct / 100 * width)))
    if pct < 70:
        color = "38;2;120;200;150"
    elif pct < 90:
        color = "38;2;247;200;100"
    else:
        color = "38;2;235;110;100"
    bar = ui.style("▰" * filled, color) + ui.style("▱" * (width - filled), "38;2;62;68;86")
    return f"{bar} {ui.style(f'{pct}%', color)}"


def _sidebar_text(
    ui: TuiConsoleUI,
    options: Any,
    current_model: str,
    session_label: str,
    history: list[dict[str, Any]],
    session_started: str,
) -> ANSI:
    from apsara_cli import __version__

    body: list[str] = []
    lines = body.append

    # Session title + start time, like OpenCode's 'New session – <ts>'.
    lines("")
    lines(f" {ui.style('◆', ui.theme.accent)} {ui.style(session_label, '1', _C_VALUE)}")
    lines(f"   {ui.style(session_started, _DIMTXT)}")
    lines("")

    # Context: usage meter + tokens + cost.
    total = ui._session_total_tokens
    entry = lookup_model(current_model)
    lines(_section(ui, "◍", "Context", _C_CONTEXT))
    if entry and entry.context_window:
        pct = min(100, int(total / entry.context_window * 100))
        lines(f"   {_meter(ui, pct)}")
    tok_str = f"{total:,}" if total else "0"
    lines(f"   {ui.style(tok_str, _C_VALUE)} {ui.style('tokens', _DIMTXT)}")
    lines(f"   {ui.style(f'${ui.calculate_session_cost():.2f}', '38;2;130;210;160')} {ui.style('spent', _DIMTXT)}")
    lines("")

    # Model: name, provider · tier, context window, key status.
    key_ok = True
    if entry:
        key_ok = is_key_available(entry) or entry.tier == "local"
        tier_color = _TIER_COLORS.get(entry.tier, _DIMTXT)
        lines(_section(ui, "✦", "Model", _C_MODEL))
        lines(f"   {ui.style(entry.display_name, '1', _C_VALUE)}")
        lines(
            f"   {ui.style(entry.provider.capitalize(), '38;2;190;200;220')}"
            f" {ui.style('·', _DIMTXT)} {ui.style(entry.tier, tier_color)}"
        )
        lines(f"   {ui.style(format_context_window(entry.context_window) + ' ctx', _DIMTXT)}")
        lines(
            f"   {ui.style('✓ key set', '38;2;120;200;150')}"
            if key_ok
            else f"   {ui.style(f'✗ needs {entry.env_var}', '38;2;235;110;100')}"
        )
        lines("")

    # Session detail: turns, messages, mode and governance flags.
    turns = sum(1 for m in history if m.get("role") == "user")
    turn_word = "turns" if turns != 1 else "turn"
    lines(_section(ui, "❯", "Session", _C_SESSION))
    lines(
        f"   {ui.style(str(turns), _C_VALUE)} {ui.style(turn_word, _DIMTXT)}"
        f" {ui.style('·', _DIMTXT)} {ui.style(str(len(history)), _C_VALUE)} {ui.style('messages', _DIMTXT)}"
    )
    if options.dry_run:
        lines(f"   {ui.style('mode', _DIMTXT)}  {ui.style('Dry-run', '1', '38;2;247;200;100')}")
    elif options.read_only:
        lines(f"   {ui.style('mode', _DIMTXT)}  {ui.style('Read-only', '1', '38;2;240;170;90')}")
    else:
        lines(f"   {ui.style('mode', _DIMTXT)}  {ui.style('Build', '1', ui.theme.accent)}")
    bash_state = (
        ui.style("enabled", "38;2;130;210;160") if options.allow_bash else ui.style("off", _DIMTXT)
    )
    lines(f"   {ui.style('bash', _DIMTXT)}  {bash_state}")
    if options.auto_approve:
        lines(f"   {ui.style('auto-approve', _DIMTXT)}  {ui.style('on', '38;2;247;200;100')}")
    steps = len(ui.latest_hidden_events)
    if steps:
        step_word = "steps" if steps != 1 else "step"
        lines(
            f"   {ui.style('last turn', _DIMTXT)} {ui.style(str(steps), _C_VALUE)}"
            f" {ui.style(step_word + ' · /details', _DIMTXT)}"
        )
    lines("")

    # Workspace.
    lines(_section(ui, "⌂", "Workspace", _C_WORKSPACE))
    lines(f"   {ui.style(_shorten_path(str(options.workspace_root)), _DIMTXT)}")
    lines("")

    # Getting-started card — only while no key is configured, OpenCode style.
    if not key_ok:
        lines(_section(ui, "◇", "Getting started", _C_CARD))
        for text in (
            "Apsara includes free-tier and",
            "local models so you can start",
            "quickly.",
            "",
            "Connect a provider to use",
            "other models, including",
            "Claude, GPT, Gemini etc",
        ):
            lines(f"   {ui.style(text, _DIMTXT)}" if text else "")
        lines("")
        lines(
            f"   {ui.style('Connect provider', '1', _C_VALUE)}  "
            f"{ui.style('/key set', '1', '38;2;140;180;255')}"
        )
        lines("")

    # Shortcuts.
    for cmd, desc in [
        ("/models", "switch models"),
        ("/status", "session status"),
        ("/help", "all commands"),
    ]:
        lines(f"   {ui.style(cmd, '1', '38;2;140;180;255')}  {ui.style(desc, _DIMTXT)}")

    # Footer: brand + version + developer credit.
    lines("")
    lines(
        f" {ui.style('●', '38;2;120;200;150')} "
        f"{ui.style('Apsara', '1', _C_VALUE)} "
        f"{ui.style('v' + __version__, _C_MODEL)}"
    )
    lines(f"   {ui.style('by Bondeth', _C_WORKSPACE)}")

    return ANSI("\n".join(body))


def _chat_text(ui: TuiConsoleUI) -> ANSI:
    body_lines = list(ui.lines)
    if ui._spinner_frame:
        body_lines.append("")
        body_lines.append(f"  {ui.compose_spinner_line(ui._spinner_tick)}")
    return ANSI("\n".join(body_lines))


def _status_left(options: Any) -> ANSI:
    return ANSI(
        f" \x1b[{_C_WORKSPACE}m⌂\x1b[0m \x1b[{_DIMTXT}m{options.workspace_root}\x1b[0m"
    )


def _status_right(ui: TuiConsoleUI, current_model: str) -> ANSI:
    total = ui._session_total_tokens
    tok = f"{total / 1000:.1f}K" if total >= 1000 else str(total)
    entry = lookup_model(current_model)
    pct = ""
    if entry and entry.context_window and total:
        pct = f" ({min(100, int(total / entry.context_window * 100))}%)"
    right = (
        f"\x1b[{_DIMTXT}m{tok}{pct}\x1b[0m   "
        f"\x1b[1;38;2;210;216;228mctrl+p\x1b[0m \x1b[{_DIMTXT}mcommands\x1b[0m "
    )
    return ANSI(right)


async def tui_loop(args: object, config: object) -> int:
    options = resolve_runtime_options(args, config.defaults)

    from apsara_cli.cli.chat import _load_stored_keys
    _load_stored_keys()

    theme = Theme()
    config_theme = getattr(config, "theme", None)
    if config_theme is not None:
        config_theme.apply_to(theme)

    ui = TuiConsoleUI(use_color=True, auto_approve=options.auto_approve, theme=theme)

    history: list[dict[str, Any]] = []
    if not options.stateless:
        history = load_session_messages(options.workspace_root, options.session)
    session_label = sanitize_session_name(options.session) if not options.stateless else "stateless"

    # First run (nothing to resume) opens on the OpenCode-style welcome
    # screen: centered logo with the message box directly below it. The
    # split chat/sidebar layout takes over on the first submission.
    state = {"model": options.model, "welcome": not history}

    # /models runs as a NATIVE in-app picker in the TUI (not the blocking
    # stdin-reading pick_model, which can't work while the Application owns
    # the terminal): the list is appended to the transcript and navigated
    # via the app's own key bindings, with an asyncio.Future bridging the
    # background submission coroutine to those key presses.
    picker: dict[str, Any] = {
        "active": False, "rows": [], "selectable": [],
        "selected": 0, "block_len": 0, "future": None,
    }
    picker_active = Condition(lambda: picker["active"])

    from apsara_cli.cli.banner import banner_taglines, logo_width, small_logo_line, styled_logo_lines
    from apsara_cli.shared.ui import terminal_width

    _subtitle, _powered = banner_taglines(config)

    # The transcript always opens with the banner (logo + description +
    # credit), so the chat view keeps it after the welcome screen hands
    # over (and on resumed sessions).
    pane_w = max(44, terminal_width() - 35)  # chat pane = terminal - sidebar - sep
    ui.lines.append("")
    if pane_w >= logo_width() + 4:
        ui.lines.extend(styled_logo_lines(ui, max((pane_w - logo_width()) // 2, 2)))
    else:
        ui.lines.append(" " * max((pane_w - 11) // 2, 2) + small_logo_line(ui))
    ui.lines.append("")
    ui.lines.append(
        " " * max((pane_w - len(_subtitle)) // 2, 2) + ui.style(_subtitle, "38;2;168;172;205")
    )
    ui.lines.append(
        " " * max((pane_w - len(_powered)) // 2, 2) + ui.style(_powered, "38;2;200;166;110")
    )
    # No 'resumed N prior turns' line here — the sidebar's Session section
    # already shows the turn/message counts and the resumed/new state.

    # ── Layout ─────────────────────────────────────────────────────────────

    # Sidebar session subtitle: 'resumed · <ts>' or 'new · <ts>', OpenCode's
    # 'New session – <timestamp>' equivalent.
    session_started = (
        ("resumed · " if history else "new · ") + datetime.now().strftime("%Y-%m-%d %H:%M")
    )

    def _chat_cursor_position() -> Point:
        # The Window clamps its scroll to keep this 'cursor' visible on every
        # render — so pointing it at the last line implements follow-bottom,
        # pointing it at the current scroll row freezes manual browsing, and
        # (while the /models picker is open) pointing it at the highlighted
        # row keeps the selection on screen as you arrow through a long list.
        if picker["active"] and picker["block_len"]:
            block_start = len(ui.lines) - picker["block_len"]
            return Point(x=0, y=max(block_start + picker["selected"], 0))
        total = len(ui.lines) + (2 if ui._spinner_frame else 0)
        if follow["on"]:
            return Point(x=0, y=max(total - 1, 0))
        return Point(x=0, y=max(chat_window.vertical_scroll, 0))

    chat_control = FormattedTextControl(
        lambda: _chat_text(ui), focusable=False, get_cursor_position=_chat_cursor_position
    )
    chat_window = Window(content=chat_control, wrap_lines=True, always_hide_cursor=True)

    sidebar_control = FormattedTextControl(
        lambda: _sidebar_text(ui, options, state["model"], session_label, history, session_started),
        focusable=False,
    )
    sidebar_window = Window(content=sidebar_control, width=34, wrap_lines=True, style="class:sidebar")

    status_bar = VSplit([
        Window(content=FormattedTextControl(lambda: _status_left(options)), height=1),
        Window(
            content=FormattedTextControl(lambda: _status_right(ui, state["model"])),
            height=1,
            align=WindowAlign.RIGHT,
            dont_extend_width=True,
        ),
    ], height=1, style="class:statusbar")

    history_dir = Path.home() / ".apsara"
    history_dir.mkdir(parents=True, exist_ok=True)
    input_buffer = Buffer(
        completer=SlashCompleter(),
        auto_suggest=AutoSuggestFromHistory(),
        history=FileHistory(str(history_dir / "input_history")),
        multiline=True,
    )
    # ── Typing box (shared builder for the welcome and chat layouts) ──────
    # OpenCode-style: a rounded border, a blue accent bar on the inside-left
    # edge, a placeholder while empty, and the 'Build · Model Provider' mode
    # line inside the box, under the text.
    _placeholder = _PlaceholderProcessor('Ask anything... "What is the tech stack of this project?"')

    def _make_input_box(input_height, width=None):
        control_window = Window(
            content=BufferControl(buffer=input_buffer, input_processors=[_placeholder]),
            height=input_height,
        )
        mode_window = Window(
            content=FormattedTextControl(
                lambda: ANSI(build_mode_line(ui, options, state["model"])), focusable=False
            ),
            height=1,
        )

        def _edge(left: str, right: str) -> VSplit:
            return VSplit([
                Window(width=1, char=left, style="class:inputborder"),
                Window(char="─", style="class:inputborder"),
                Window(width=1, char=right, style="class:inputborder"),
            ], height=1)

        def _row(content: Window, height) -> VSplit:
            return VSplit([
                Window(width=1, char="│", style="class:inputborder"),
                Window(width=1, char="▌", style="class:accent"),
                Window(width=1, char=" "),
                content,
                Window(width=1, char="│", style="class:inputborder"),
            ], height=height)

        box = HSplit([
            _edge("╭", "╮"),
            _row(control_window, input_height),
            _row(Window(char=" ", height=1), 1),  # breathing room above the mode line
            _row(mode_window, 1),
            _edge("╰", "╯"),
        ], width=width)
        return box, control_window

    chat_box, chat_input_window = _make_input_box(3)

    # ── Chat layout: transcript + detail sidebar + boxed input + status bar ─
    chat_root = HSplit([
        VSplit([
            chat_window,
            Window(width=1, char="│", style="class:sep"),
            sidebar_window,
        ]),
        Window(height=1, char=" "),
        chat_box,
        status_bar,
    ])

    # ── Welcome layout: everything vertically centered, OpenCode-style ─────
    from apsara_cli import __version__

    box_w = max(50, min(terminal_width() - 16, 84))
    welcome_box, welcome_input_window = _make_input_box(
        Dimension(min=1, preferred=1, max=4), width=box_w
    )

    if terminal_width() >= logo_width() + 2:
        logo_ansi = ANSI("\n".join(styled_logo_lines(ui, 0)))
        logo_height = 5
    else:
        logo_ansi = ANSI(small_logo_line(ui))
        logo_height = 1
    logo_window = Window(
        FormattedTextControl(logo_ansi, focusable=False),
        height=logo_height,
        align=WindowAlign.CENTER,
    )
    subtitle_window = Window(
        FormattedTextControl(ANSI(ui.style(_subtitle, "38;2;168;172;205")), focusable=False),
        height=1,
        align=WindowAlign.CENTER,
    )
    powered_window = Window(
        FormattedTextControl(ANSI(ui.style(_powered, "38;2;200;166;110")), focusable=False),
        height=1,
        align=WindowAlign.CENTER,
    )

    _key = "1", "38;2;140;180;255"
    hints_ansi = ANSI(
        f"{ui.style('/', *_key)} {ui.style('commands', _DIMTXT)}   "
        f"{ui.style('esc+enter', *_key)} {ui.style('newline', _DIMTXT)}   "
        f"{ui.style('↑↓', *_key)} {ui.style('history', _DIMTXT)}"
    )
    hints_row = VSplit([
        Window(),
        Window(FormattedTextControl(hints_ansi, focusable=False), width=box_w, height=1),
        Window(),
    ], height=1)

    _entry = lookup_model(options.model)
    _key_ok = _entry is None or is_key_available(_entry) or _entry.tier == "local"
    if not _key_ok:
        tip_ansi = ANSI(
            f"{ui.style('●', '38;2;240;170;90')} {ui.style('Tip', '1', '38;2;240;170;90')} "
            f"{ui.style('Run', '38;2;200;205;215')} "
            f"{ui.style(f'/key set {_entry.provider}', '1', '38;2;225;230;242')} "
            f"{ui.style('to add an AI provider and start coding', '38;2;200;205;215')}"
        )
    else:
        tip_ansi = ANSI(
            f"{ui.style('●', '38;2;240;170;90')} {ui.style('Tip', '1', '38;2;240;170;90')} "
            f"{ui.style('Ask anything, or type', '38;2;200;205;215')} "
            f"{ui.style('/', '1', '38;2;225;230;242')} "
            f"{ui.style('to browse commands', '38;2;200;205;215')}"
        )
    tip_window = Window(
        FormattedTextControl(tip_ansi, focusable=False), height=1, align=WindowAlign.CENTER
    )

    _home = str(Path.home())
    _ws = str(options.workspace_root)
    _ws_display = "~" + _ws[len(_home):] if _ws.startswith(_home) else _ws
    welcome_bar = VSplit([
        Window(
            FormattedTextControl(ANSI(" " + ui.style(_ws_display, _DIMTXT)), focusable=False),
            height=1,
        ),
        Window(
            FormattedTextControl(ANSI(ui.style(__version__, _DIMTXT) + " "), focusable=False),
            height=1,
            align=WindowAlign.RIGHT,
            dont_extend_width=True,
        ),
    ], height=1)

    welcome_root = HSplit([
        Window(height=Dimension(weight=2)),
        logo_window,
        Window(height=1, char=" "),
        subtitle_window,
        powered_window,
        Window(height=2, char=" "),
        VSplit([Window(), welcome_box, Window()]),
        Window(height=1, char=" "),
        hints_row,
        Window(height=2, char=" "),
        tip_window,
        Window(height=Dimension(weight=3)),
        welcome_bar,
    ])

    body = FloatContainer(
        content=DynamicContainer(lambda: welcome_root if state["welcome"] else chat_root),
        floats=[Float(xcursor=True, ycursor=True, content=CompletionsMenu(max_height=16, scroll_offset=1))],
    )

    # ── Chat-pane scrolling: auto-follow the newest line, but let PageUp/
    # PageDown and the mouse wheel browse history (e.g. long /help output) ──
    follow = {"on": True, "last_set": 0}

    def _chat_max_scroll() -> int:
        ri = chat_window.render_info
        if ri is None:
            return 0
        return max(ri.content_height - ri.window_height, 0)

    def _before_render(app_) -> None:
        # While the /models picker is open, _chat_cursor_position drives the
        # scroll (keeping the highlighted row visible) — don't fight it.
        if state["welcome"] or picker["active"]:
            return
        max_scroll = _chat_max_scroll()
        cur = chat_window.vertical_scroll
        if follow["on"]:
            if cur < follow["last_set"]:
                follow["on"] = False  # mouse wheel scrolled up — stop following
            else:
                chat_window.vertical_scroll = max_scroll
                follow["last_set"] = max_scroll
        elif cur >= max_scroll:
            follow["on"] = True  # reached the bottom again — resume following
            follow["last_set"] = cur

    def _after_render(app_) -> None:
        # render_info is only fresh AFTER a render, so when following we may
        # discover the true bottom just now — snap to it and repaint once.
        if state["welcome"] or picker["active"] or not follow["on"]:
            return
        max_scroll = _chat_max_scroll()
        if chat_window.vertical_scroll != max_scroll:
            chat_window.vertical_scroll = max_scroll
            follow["last_set"] = max_scroll
            app_.invalidate()

    style = Style.from_dict({
        "accent": "fg:#6096fa",
        "sep": "fg:#3d4668",
        "inputborder": "fg:#5a6cb4",
        "placeholder": "fg:#5a616e",
        "sidebar": "bg:#0e1015",
        "statusbar": "bg:#12141a",
        "completion-menu.completion": "bg:#1c1f27 fg:#c8cede",
        "completion-menu.completion.current": "bg:#f7b76a fg:#1a1a1a",
    })

    # ── /models native in-app picker ─────────────────────────────────────
    _PICKER_CURSOR = ("1", "38;2;120;200;150")
    _PICKER_HINT = "↑/↓ or j/k move   enter select   esc cancel"

    def _picker_row(txt: str, model_id, highlighted: bool) -> str:
        if model_id is None:               # provider group header
            return f"  {txt}"
        if highlighted:
            return f"  {ui.style('❯ ', *_PICKER_CURSOR)}{txt}"
        return f"    {txt}"

    def _render_picker() -> None:
        lines = [
            _picker_row(txt, mid, i == picker["selected"])
            for i, (txt, mid) in enumerate(picker["rows"])
        ]
        lines.append("")
        lines.append(f"  {ui.dim(_PICKER_HINT)}")
        if picker["block_len"]:
            del ui.lines[-picker["block_len"]:]
        ui.lines.extend(lines)
        picker["block_len"] = len(lines)
        ui._invalidate()

    def _finalize_picker(chosen) -> None:
        # Replace the live block with a static listing (chosen row keeps the
        # ❯, no hint) so it reads cleanly in scrollback.
        if picker["block_len"]:
            del ui.lines[-picker["block_len"]:]
        for txt, mid in picker["rows"]:
            ui.lines.append(_picker_row(txt, mid, mid is not None and mid == chosen))
        picker["block_len"] = 0
        ui._invalidate()

    def _picker_move(delta: int) -> None:
        sel = picker["selectable"]
        if not sel:
            return
        pos = sel.index(picker["selected"])
        picker["selected"] = sel[(pos + delta) % len(sel)]
        _render_picker()

    def _picker_resolve(model_id) -> None:
        fut = picker["future"]
        if fut is not None and not fut.done():
            fut.set_result(model_id)

    async def _run_model_picker(filt: str) -> None:
        header_parts, rows, shown_any = build_model_rows(state["model"], filt, ui)
        ui.lines.append("")
        ui.lines.append("  " + "  ".join(header_parts))
        ui.lines.append("")
        if not shown_any:
            ui.warning(f"No models match '{filt}'. Try a provider like 'openai', 'groq', 'anthropic'.")
            return

        selectable = [i for i, (_, mid) in enumerate(rows) if mid is not None]
        picker["rows"] = rows
        picker["selectable"] = selectable
        picker["selected"] = next(
            (i for i in selectable if rows[i][1] == state["model"]), selectable[0]
        )
        picker["block_len"] = 0
        picker["future"] = asyncio.get_event_loop().create_future()
        picker["active"] = True
        _render_picker()
        try:
            chosen = await picker["future"]
        finally:
            picker["active"] = False
            picker["future"] = None

        input_buffer.reset()  # drop any stray keys that reached the input box
        _finalize_picker(chosen)
        if chosen is None:
            ui.info("No change — model selection cancelled.")
            return

        # _switch_model prompts (getpass) only when the target lacks a key.
        # That key-entry flow needs the real terminal, so run it via
        # prompt_toolkit's run_in_terminal — it cleanly suspends the
        # full-screen app, hands over the terminal for getpass, then
        # restores the app (banner + transcript) intact. The old
        # _run_passthrough did a raw renderer.erase() that wiped the banner
        # and never redrew it properly. When the key IS present there's no
        # prompt, so we just switch inline into the transcript.
        entry = lookup_model(chosen)
        needs_key = entry is not None and not (is_key_available(entry) or entry.tier == "local")
        if needs_key:
            def _switch_with_key_prompt() -> str:
                was = ui._passthrough
                ui._passthrough = True  # route output to the real terminal
                try:
                    return _switch_model(chosen, state["model"], options, ui)
                finally:
                    ui._passthrough = was
            state["model"] = await run_in_terminal(_switch_with_key_prompt)
            ui._invalidate()
        else:
            state["model"] = _switch_model(chosen, state["model"], options, ui)

    kb = KeyBindings()

    @kb.add("c-c")
    def _interrupt(event) -> None:
        event.app.exit()

    @kb.add("c-d")
    def _eof(event) -> None:
        event.app.exit()

    @kb.add("escape", "enter", filter=~picker_active)
    def _newline(event) -> None:
        event.current_buffer.insert_text("\n")

    # ── /models picker navigation (only while the picker is open) ─────────
    @kb.add("up", filter=picker_active, eager=True)
    @kb.add("k", filter=picker_active, eager=True)
    def _picker_up(event) -> None:
        _picker_move(-1)

    @kb.add("down", filter=picker_active, eager=True)
    @kb.add("j", filter=picker_active, eager=True)
    def _picker_down(event) -> None:
        _picker_move(1)

    @kb.add("enter", filter=picker_active, eager=True)
    def _picker_accept(event) -> None:
        _picker_resolve(picker["rows"][picker["selected"]][1])

    @kb.add("escape", filter=picker_active, eager=True)
    @kb.add("q", filter=picker_active, eager=True)
    @kb.add("c-c", filter=picker_active, eager=True)
    def _picker_cancel(event) -> None:
        _picker_resolve(None)

    @kb.add("c-p")
    def _command_palette(event) -> None:
        """ctrl+p: browse every slash command in the completion menu."""
        if not input_buffer.text.startswith("/"):
            input_buffer.reset()
            input_buffer.insert_text("/")
        input_buffer.start_completion(select_first=False)

    @kb.add("pageup")
    def _scroll_up(event) -> None:
        ri = chat_window.render_info
        page = max((ri.window_height if ri else 10) - 1, 1)
        follow["on"] = False
        chat_window.vertical_scroll = max(chat_window.vertical_scroll - page, 0)

    @kb.add("pagedown")
    def _scroll_down(event) -> None:
        ri = chat_window.render_info
        page = max((ri.window_height if ri else 10) - 1, 1)
        max_scroll = _chat_max_scroll()
        new_scroll = min(chat_window.vertical_scroll + page, max_scroll)
        chat_window.vertical_scroll = new_scroll
        if new_scroll >= max_scroll:
            follow["on"] = True
            follow["last_set"] = new_scroll

    async def _handle_submission(text: str) -> None:
        ui.append_user_message(text)

        # /models needs the native async picker (not the blocking pick_model
        # inside handle_chat_command, which can't read keys under the TUI).
        if text == "/models" or text.startswith("/models "):
            await _run_model_picker(text[len("/models"):].strip().lower())
            return

        if text.startswith("/"):
            keep, new_model = handle_chat_command(text, history, state["model"], options, config, ui)
            state["model"] = new_model
            if not keep:
                app.exit()
            return

        # execute_instruction drives begin_turn/finish_turn, which render the
        # '+ Thought:' marker and the '◼ Build · model · 7.0s' footer.
        new_history, _usage = await execute_instruction(text, state["model"], history, options, ui)
        history[:] = new_history

        save_if_needed(history, state["model"], options, ui)
        ui._invalidate()

    @kb.add("enter", filter=Condition(lambda: not input_buffer.complete_state) & ~picker_active)
    def _submit(event) -> None:
        text = input_buffer.text.strip()
        input_buffer.reset()
        if not text:
            return
        if state["welcome"]:
            # First message: swap the centered welcome for the chat layout.
            state["welcome"] = False
            event.app.layout.focus(chat_input_window)
        event.app.create_background_task(_handle_submission(text))

    app = Application(
        layout=Layout(
            body,
            focused_element=welcome_input_window if state["welcome"] else chat_input_window,
        ),
        key_bindings=kb,
        style=style,
        full_screen=True,
        mouse_support=True,
        before_render=_before_render,
        after_render=_after_render,
    )
    ui.attach(app)

    await app.run_async()
    return 0
