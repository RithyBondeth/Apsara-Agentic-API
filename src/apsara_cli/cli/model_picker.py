"""
Arrow-key interactive model picker for the /models command.

Renders inline through the caller's ConsoleUI (print_line + read_single_key
+ redraw_block) instead of opening a separate prompt_toolkit Application —
so it stays inside the current terminal UI (the classic scrolling REPL or
the TUI's chat pane) exactly like every other command, rather than briefly
swapping in its own screen.
"""

from typing import Optional


# Escape sequences/keys that read_raw_key() can hand back for arrow keys.
# Two ANSI encodings exist for the same physical key: "\x1b[A" (CSI / normal
# cursor-key mode, the default most terminals start in) and "\x1bOA" (SS3 /
# DECCKM "application cursor key" mode, which full-screen TUI programs
# commonly trigger — prompt_toolkit's own parser maps both the same way, see
# ansi_escape_sequences.py, so this picker needs to accept both too or arrow
# keys silently do nothing whenever a terminal happens to be in application
# mode). Plus the Windows msvcrt path ("\xe0H" / "\x00H").
_UP_KEYS = {"\x1b[A", "\x1bOA", "\xe0H", "\x00H", "k", "K"}
_DOWN_KEYS = {"\x1b[B", "\x1bOB", "\xe0P", "\x00P", "j", "J"}
_ACCEPT_KEYS = {"\r", "\n", ""}
_CANCEL_KEYS = {"\x1b", "q", "Q", "\x03"}


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

    Returns None immediately (caller falls back to the type-to-switch flow)
    when there is nothing selectable.
    """
    selectable = [i for i, (_, model_id) in enumerate(rows) if model_id is not None]
    if not selectable:
        return None

    selected = selectable[0]
    for i in selectable:
        if rows[i][1] == current_model:
            selected = i
            break

    def render(hint: str) -> list[str]:
        lines = []
        for i, (line_text, model_id) in enumerate(rows):
            if model_id is None:
                lines.append(f"  {line_text}")
            elif i == selected:
                lines.append(f"  {ui.style('❯ ', '1', '38;2;120;200;150')}{line_text}")
            else:
                lines.append(f"    {line_text}")
        lines.append("")
        lines.append(f"  {ui.dim(hint)}")
        return lines

    frame = render("↑/↓ or j/k move   enter select   esc/q cancel")
    for line in frame:
        ui.print_line(line)
    prev_count = len(frame)

    def move(delta: int) -> None:
        nonlocal selected
        pos = selectable.index(selected)
        selected = selectable[(pos + delta) % len(selectable)]

    # Hold raw mode across the WHOLE loop rather than re-entering it on each
    # keystroke (read_single_key()'s default) — toggling raw/cooked mode
    # between reads, with a full-list redraw in between, opens a window
    # where the kernel can buffer an arrow key's escape bytes instead of
    # delivering them immediately, making navigation misfire as Cancel.
    with ui.raw_terminal():
        while True:
            key = ui.read_raw_key()

            if key in _ACCEPT_KEYS:
                ui.redraw_block(prev_count, [])
                return rows[selected][1]
            if key in _CANCEL_KEYS:
                ui.redraw_block(prev_count, [])
                return None

            if key in _UP_KEYS:
                move(-1)
            elif key in _DOWN_KEYS:
                move(1)
            else:
                continue

            frame = render("↑/↓ or j/k move   enter select   esc/q cancel")
            ui.redraw_block(prev_count, frame)
            prev_count = len(frame)
