from apsara_cli.shared.ui import ConsoleUI
from prompt_toolkit.formatted_text import fragment_list_to_text, to_formatted_text

from apsara_cli.cli.tui import TuiConsoleUI, _approval_footer, _approval_text, _restore_history


class _FakeApplication:
    class _Output:
        class _Size:
            columns = 80

        def get_size(self):
            return self._Size()

    output = _Output()

    def invalidate(self):
        pass


def test_assistant_renders_markdown_in_a_padded_transcript_card(capsys):
    ui = ConsoleUI(use_color=False, typing_delay=0)

    ui.assistant(
        "# Result\n\n- first item\n- second item\n\n"
        "```python\nprint('ready')\n```"
    )

    output = capsys.readouterr().out
    assert "apsara" in output
    assert "▌" in output
    assert "  ▌    • first item" in output
    assert "╭" not in output and "╰" not in output
    assert "Result" in output
    assert "• first item" in output
    assert "print('ready')" in output
    assert "```" not in output


def test_streamed_answer_is_buffered_then_rendered_as_markdown(capsys):
    ui = ConsoleUI(use_color=False, typing_delay=0)

    ui.stream_text_start()
    ui.stream_text_chunk("## Summary\n\n")
    assert capsys.readouterr().out == ""

    ui.stream_text_chunk("**Ready.**")
    ui.stream_text_end()

    output = capsys.readouterr().out
    assert "apsara" in output
    assert "▌" in output
    assert "Summary" in output
    assert "Ready." in output
    assert "**" not in output


def test_tui_uses_the_same_padded_markdown_card():
    ui = TuiConsoleUI(use_color=False, typing_delay=0)
    ui.app = _FakeApplication()
    ui.sidebar_visible = False

    ui.stream_text_start()
    ui.stream_text_chunk("### TUI Ready\n\n- shared renderer")
    ui.stream_text_end()

    output = "\n".join(ui.lines)
    assert "apsara" in output
    assert "▌" in output
    assert "TUI Ready" in output
    assert "• shared renderer" in output
    assert max(len(line) for line in ui.lines) <= 76


def test_tui_user_turn_has_a_clear_role_label():
    ui = TuiConsoleUI(use_color=False, typing_delay=0)
    ui.app = _FakeApplication()

    ui.append_user_message("Explain this code")

    output = "\n".join(ui.lines)
    assert "▌" in output
    assert "  ▌   Explain this code" in output
    assert "you" in output


def test_native_approval_overlay_renders_diff_and_shortcuts():
    ui = TuiConsoleUI(use_color=False, typing_delay=0)
    approval = {
        "action": "edit file",
        "title": "Edit src/app.py",
        "preview": "-old\n+new",
        "full": "@@ -1 +1 @@\n-old\n+new",
        "show_full": False,
        "is_trust": False,
    }

    body = fragment_list_to_text(to_formatted_text(_approval_text(ui, approval)))
    footer = fragment_list_to_text(to_formatted_text(_approval_footer(ui, approval)))

    assert "Permission required" in body
    assert "Edit src/app.py" in body
    assert "-old" in body and "+new" in body
    assert "enter  allow once" in footer
    assert "n/esc  deny" in footer
    assert "a  always allow" in footer
    assert "v full diff" in footer


def test_restored_history_shows_conversation_but_hides_tool_internals():
    ui = TuiConsoleUI(use_color=False, typing_delay=0)
    ui.app = _FakeApplication()
    ui.sidebar_visible = False
    history = [
        {"role": "user", "content": "Fix the bug"},
        {
            "role": "assistant",
            "content": "I will inspect it",
            "tool_calls": [{"function": {"name": "read_file"}}],
        },
        {"role": "tool", "content": "secret tool output"},
        {"role": "assistant", "content": "## Fixed\n\nThe bug is resolved."},
    ]

    _restore_history(ui, history)

    output = "\n".join(ui.lines)
    assert "Resumed 1 prior turn" in output
    assert "▌" in output and "Fix the bug" in output and "you" in output
    assert "Fixed" in output and "The bug is resolved." in output
    assert "I will inspect it" not in output
    assert "secret tool output" not in output
