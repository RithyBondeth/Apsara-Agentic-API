"""
Full-screen split-pane TUI (opt-in via --tui), modeled on OpenCode's layout:
a scrollable chat pane, a persistent sidebar, and a bottom status bar, all
inside one `prompt_toolkit` full-screen Application.

Design note: this file does NOT reimplement any of ConsoleUI's formatting
logic (badges, diffs, markdown/code rendering, confirm-dialog boxes) --
`TuiConsoleUI` only swaps *where* that already-styled output goes (into an
in-memory transcript buffer that gets redrawn, instead of straight to
stdout). Blocking, synchronous calls that need the real terminal (single
keypress reads for confirmations, getpass, the /models arrow-key picker)
are safe to run as-is here: they are always invoked synchronously, inline,
from within the agent turn's execution (engine/tools.py calls
`execute_tool()` directly, without `await`), so the outer Application's
event loop is never concurrently polling the terminal at that moment --
there is no real contention to arbitrate. We just mark those stretches as
"passthrough" (real terminal I/O) and force a full repaint of the outer
app when they finish.
"""

import asyncio
from pathlib import Path
from typing import Any, Optional

from prompt_toolkit.application import Application
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.filters import Condition
from prompt_toolkit.formatted_text import ANSI
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import Layout
from prompt_toolkit.layout.containers import Float, FloatContainer, HSplit, VSplit, Window
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
from prompt_toolkit.layout.menus import CompletionsMenu

from apsara_cli.cli.chat import (
    build_status_line,
    execute_instruction,
    handle_chat_command,
    save_if_needed,
)
from apsara_cli.cli.input import SlashCompleter
from apsara_cli.cli.options import resolve_runtime_options
from apsara_cli.cli.session import load_session_messages, sanitize_session_name
from apsara_cli.engine.models import format_context_window, is_key_available, lookup_model
from apsara_cli.shared.ui import ConsoleUI, Theme


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
        asst_lbl = self.style("apsara", self.theme.assistant_label)
        self.lines.append("")
        self.lines.append(f"  {asst_lbl}")
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

    # ── Spinner: asyncio ticker instead of a raw-stdout thread ───────────

    def start_spinner(self, message: str) -> None:
        if self._passthrough or self.app is None:
            super().start_spinner(message)
            return
        self.spinner_message = message
        self.spinner_stop_event.clear()
        if self._spinner_task is None or self._spinner_task.done():
            self._spinner_task = asyncio.get_event_loop().create_task(self._spinner_loop())

    async def _spinner_loop(self) -> None:
        frames = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
        i = 0
        while not self.spinner_stop_event.is_set():
            self._spinner_frame = frames[i % len(frames)]
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


def run_passthrough_modal(ui: TuiConsoleUI, fn):
    """Public helper for callers outside TuiConsoleUI (e.g. the /models picker)."""
    return ui._run_passthrough(fn)


# ── Sidebar / status bar rendering ────────────────────────────────────────

def _sidebar_text(ui: TuiConsoleUI, options: Any, current_model: str, session_label: str) -> ANSI:
    lines: list[str] = []
    lines.append(ui.style(" Getting started", "1", "38;2;190;200;220"))
    lines.append("")
    lines.append(f" {ui.dim('workspace')}")
    lines.append(f" {options.workspace_root}")
    lines.append("")
    lines.append(f" {ui.dim('session')}")
    lines.append(f" {session_label}")
    entry = lookup_model(current_model)
    if entry:
        lines.append("")
        lines.append(f" {ui.dim('model')}")
        lines.append(f" {entry.display_name}")
        lines.append(f" {ui.dim(format_context_window(entry.context_window) + ' ctx')}")
        key_ok = is_key_available(entry) or entry.tier == "local"
        key_text = (
            ui.style("✓ key set", "38;2;120;200;150")
            if key_ok
            else ui.style(f"✗ needs {entry.env_var}", "38;2;220;120;100")
        )
        lines.append(f" {key_text}")
    lines.append("")
    lines.append(f" {ui.dim('commands')}")
    for cmd, desc in [
        ("/models", "browse models"),
        ("/key set <provider>", "add an API key"),
        ("/status", "session status"),
        ("/help", "full command list"),
        ("/exit", "quit"),
    ]:
        lines.append(f" {ui.style(cmd, '1', '38;2;180;210;255')}")
        lines.append(f"   {ui.dim(desc)}")
    return ANSI("\n".join(lines))


def _chat_text(ui: TuiConsoleUI) -> ANSI:
    body_lines = list(ui.lines)
    if ui._spinner_frame:
        body_lines.append(
            ui.style(f"  {ui._spinner_frame} {ui.spinner_message}...", ui.theme.dim)
        )
    return ANSI("\n".join(body_lines))


def _status_text(ui: TuiConsoleUI, options: Any, current_model: str, session_label: str) -> ANSI:
    line = build_status_line(options, current_model, session_label)
    return ANSI(f" {line}")


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

    state = {"model": options.model, "turn": 0}

    ui.lines.append(ui.style("  Apsara Agentic", "1", "38;2;220;225;240"))
    ui.lines.append(f"  {ui.dim('/help for commands  ·  /exit to quit  ·  Esc+Enter for newline')}")
    if history:
        prior_turns = sum(1 for m in history if m.get("role") == "user")
        plural = "s" if prior_turns != 1 else ""
        ui.lines.append(f"  {ui.dim(f'resumed {prior_turns} prior turn{plural}')}")
        state["turn"] = prior_turns

    # ── Layout ─────────────────────────────────────────────────────────────

    chat_control = FormattedTextControl(lambda: _chat_text(ui), focusable=False)
    chat_window = Window(content=chat_control, wrap_lines=True, always_hide_cursor=True)

    sidebar_control = FormattedTextControl(
        lambda: _sidebar_text(ui, options, state["model"], session_label), focusable=False
    )
    sidebar_window = Window(content=sidebar_control, width=34, wrap_lines=True)

    status_control = FormattedTextControl(
        lambda: _status_text(ui, options, state["model"], session_label), focusable=False
    )
    status_window = Window(content=status_control, height=1)

    history_dir = Path.home() / ".apsara"
    history_dir.mkdir(parents=True, exist_ok=True)
    input_buffer = Buffer(
        completer=SlashCompleter(),
        auto_suggest=AutoSuggestFromHistory(),
        history=FileHistory(str(history_dir / "input_history")),
        multiline=True,
    )
    input_window = Window(content=BufferControl(buffer=input_buffer), height=3)

    root_container = HSplit([
        VSplit([chat_window, Window(width=1, char="│"), sidebar_window]),
        Window(height=1, char="─"),
        status_window,
        Window(height=1, char="─"),
        input_window,
    ])

    body = FloatContainer(
        content=root_container,
        floats=[Float(xcursor=True, ycursor=True, content=CompletionsMenu(max_height=8, scroll_offset=1))],
    )

    kb = KeyBindings()

    @kb.add("c-c")
    def _interrupt(event) -> None:
        event.app.exit()

    @kb.add("c-d")
    def _eof(event) -> None:
        event.app.exit()

    @kb.add("escape", "enter")
    def _newline(event) -> None:
        event.current_buffer.insert_text("\n")

    async def _handle_submission(text: str) -> None:
        ui.lines.append("")
        ui.lines.append(ui.style(f"  › {text}", "1", "38;2;150;190;255"))
        ui._invalidate()

        if text.startswith("/"):
            keep, new_model = handle_chat_command(text, history, state["model"], options, config, ui)
            state["model"] = new_model
            if not keep:
                app.exit()
            return

        state["turn"] += 1
        new_history, _usage = await execute_instruction(text, state["model"], history, options, ui)
        history[:] = new_history
        save_if_needed(history, state["model"], options, ui)
        ui._invalidate()

    @kb.add("enter", filter=Condition(lambda: not input_buffer.complete_state))
    def _submit(event) -> None:
        text = input_buffer.text.strip()
        input_buffer.reset()
        if not text:
            return
        event.app.create_background_task(_handle_submission(text))

    app = Application(
        layout=Layout(body, focused_element=input_window),
        key_bindings=kb,
        full_screen=True,
        mouse_support=True,
    )
    ui.attach(app)

    await app.run_async()
    return 0
