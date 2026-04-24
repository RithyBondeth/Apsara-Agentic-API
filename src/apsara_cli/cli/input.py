from pathlib import Path
from typing import Optional

try:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.history import FileHistory
    from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
    from prompt_toolkit.completion import WordCompleter
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.formatted_text import ANSI
    HAS_PROMPT_TOOLKIT = True
except ImportError:
    HAS_PROMPT_TOOLKIT = False

SLASH_COMMANDS = [
    "/help", "/details", "/clear", "/history", "/tools",
    "/model", "/session", "/save", "/exit", "/quit",
]

_session: Optional[object] = None


def _build_session(workspace_root: Path) -> object:
    history_dir = Path.home() / ".apsara"
    history_dir.mkdir(parents=True, exist_ok=True)

    completer = WordCompleter(SLASH_COMMANDS, sentence=True)

    kb = KeyBindings()

    @kb.add("enter")
    def _submit(event):
        event.current_buffer.validate_and_handle()

    @kb.add("escape", "enter")
    def _newline(event):
        event.current_buffer.insert_text("\n")

    return PromptSession(
        history=FileHistory(str(history_dir / "input_history")),
        auto_suggest=AutoSuggestFromHistory(),
        completer=completer,
        complete_while_typing=True,
        key_bindings=kb,
        multiline=True,
        prompt_continuation=lambda width, line_number, is_soft_wrap: "  ... ",
    )


def get_input(prompt_text: str, workspace_root: Path) -> str:
    """
    Read a line of input using prompt_toolkit if available, else plain input().
    Raises KeyboardInterrupt or EOFError as normal.
    """
    if not HAS_PROMPT_TOOLKIT:
        return input(prompt_text)

    global _session
    if _session is None:
        _session = _build_session(workspace_root)

    return _session.prompt(ANSI(prompt_text))
