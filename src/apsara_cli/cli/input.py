import asyncio
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
    "/status", "/model", "/models",
    "/models openai", "/models anthropic", "/models groq",
    "/models google", "/models mistral", "/models deepseek", "/models ollama",
    "/key list",
    "/key set", "/key set openai", "/key set anthropic", "/key set groq",
    "/key set gemini", "/key set mistral", "/key set deepseek", "/key set xai",
    "/key remove",
    "/session", "/save",
    "/sessions", "/sessions clear",
    "/exit", "/quit",
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


async def get_password_async(prompt_text: str) -> str:
    """
    Read a masked secret (API key) using prompt_toolkit's password mode.
    Characters are hidden as the user types. Falls back to getpass when
    prompt_toolkit is unavailable.
    """
    if not HAS_PROMPT_TOOLKIT:
        import getpass as _gp
        return _gp.getpass(prompt_text)
    from prompt_toolkit import PromptSession as _PS
    from prompt_toolkit.formatted_text import ANSI as _ANSI
    session = _PS()
    try:
        return await session.prompt_async(_ANSI(prompt_text), is_password=True)
    except (EOFError, KeyboardInterrupt):
        return ""


async def get_input_async(prompt_text: str, workspace_root: Path) -> str:
    """
    Async input using prompt_toolkit's prompt_async() so it doesn't conflict
    with the outer asyncio event loop started by asyncio.run() in parser.py.
    Falls back to a thread-safe stdin read when prompt_toolkit is unavailable.
    Raises KeyboardInterrupt or EOFError as normal.
    """
    if not HAS_PROMPT_TOOLKIT:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, lambda: input(prompt_text))

    global _session
    if _session is None:
        _session = _build_session(workspace_root)

    return await _session.prompt_async(ANSI(prompt_text))
