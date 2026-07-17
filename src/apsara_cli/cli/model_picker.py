"""Arrow-key interactive model picker for the /models command."""

from typing import Optional

try:
    from prompt_toolkit.application import Application
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout import Layout
    from prompt_toolkit.layout.containers import HSplit, Window
    from prompt_toolkit.layout.controls import FormattedTextControl
    from prompt_toolkit.formatted_text import ANSI
    HAS_PROMPT_TOOLKIT = True
except ImportError:
    HAS_PROMPT_TOOLKIT = False


def pick_model(
    rows: list[tuple[str, Optional[str]]],
    current_model: str,
    ui: "object",
) -> Optional[str]:
    """
    Show an inline, arrow-key-navigable list of models and return the
    model_id the user selects, or None if they cancel.

    ``rows`` is a list of ``(styled_line, model_id)`` tuples in display
    order — ``styled_line`` may contain raw ANSI escape codes (as produced
    by ``ui.style`` / ``ui.dim`` / ``ui.badge``). A row with ``model_id``
    set to ``None`` is treated as a non-selectable header/separator line
    (e.g. a provider group label) and is skipped during navigation.

    Falls back to returning None (caller should fall back to the
    type-to-switch flow) when prompt_toolkit isn't available.
    """
    selectable = [i for i, (_, model_id) in enumerate(rows) if model_id is not None]
    if not HAS_PROMPT_TOOLKIT or not selectable:
        return None

    selected = selectable[0]
    for i in selectable:
        if rows[i][1] == current_model:
            selected = i
            break

    result: dict = {"model_id": None}

    def get_text():
        lines = []
        for i, (line_text, model_id) in enumerate(rows):
            if model_id is None:
                lines.append(line_text)
            elif i == selected:
                lines.append(ui.style("❯ ", "1", "38;2;120;200;150") + line_text)
            else:
                lines.append("  " + line_text)
        lines.append("")
        lines.append(ui.dim("  ↑/↓ or j/k move   enter select   esc/q cancel"))
        return ANSI("\n".join(lines))

    control = FormattedTextControl(get_text, focusable=True)
    window = Window(content=control, always_hide_cursor=True)

    kb = KeyBindings()

    def _move(delta: int) -> None:
        nonlocal selected
        pos = selectable.index(selected)
        selected = selectable[(pos + delta) % len(selectable)]

    @kb.add("up")
    @kb.add("k")
    def _up(event) -> None:
        _move(-1)

    @kb.add("down")
    @kb.add("j")
    def _down(event) -> None:
        _move(1)

    @kb.add("enter")
    def _accept(event) -> None:
        result["model_id"] = rows[selected][1]
        event.app.exit()

    @kb.add("escape")
    @kb.add("c-c")
    @kb.add("q")
    def _cancel(event) -> None:
        event.app.exit()

    app = Application(
        layout=Layout(HSplit([window])),
        key_bindings=kb,
        full_screen=False,
        mouse_support=False,
        erase_when_done=True,
    )
    app.run(in_thread=True)
    return result["model_id"]
