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


def test_assistant_renders_markdown_in_a_panel(capsys):
    ui = ConsoleUI(use_color=False, typing_delay=0)

    ui.assistant(
        "# Result\n\n- first item\n- second item\n\n"
        "```python\nprint('ready')\n```"
    )

    output = capsys.readouterr().out
    assert "╭─ Apsara " in output
    assert "╰" in output
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
    assert "╭─ Apsara " in output
    assert "Summary" in output
    assert "Ready." in output
    assert "**" not in output


def test_tui_uses_the_same_markdown_panel_renderer():
    ui = TuiConsoleUI(use_color=False, typing_delay=0)
    ui.app = _FakeApplication()
    ui.sidebar_visible = False

    ui.stream_text_start()
    ui.stream_text_chunk("### TUI Ready\n\n- shared renderer")
    ui.stream_text_end()

    output = "\n".join(ui.lines)
    assert "╭─ Apsara " in output
    assert "TUI Ready" in output
    assert "• shared renderer" in output
    assert max(len(line) for line in ui.lines) <= 76


def test_tui_user_turn_has_a_clear_role_label():
    ui = TuiConsoleUI(use_color=False, typing_delay=0)
    ui.app = _FakeApplication()

    ui.append_user_message("Explain this code")

    output = "\n".join(ui.lines)
    assert "❯ You" in output
    assert "▌ Explain this code" in output


def test_big_pickle_usage_is_zero_cost_not_an_estimate(capsys):
    ui = ConsoleUI(use_color=False, typing_delay=0)
    ui.usage({
        "prompt_tokens": 800,
        "completion_tokens": 200,
        "total_tokens": 1000,
        "apsara_model": "opencode/big-pickle",
    })

    assert ui.calculate_session_cost() == 0.0
    assert "$0.0000" in capsys.readouterr().out


def test_unknown_model_usage_is_provider_billed_not_guessed(capsys):
    ui = ConsoleUI(use_color=False, typing_delay=0)
    ui.usage({
        "prompt_tokens": 800,
        "completion_tokens": 200,
        "total_tokens": 1000,
        "apsara_model": "custom/paid-model",
    })

    assert ui.calculate_session_cost() is None
    output = capsys.readouterr().out
    assert "provider billed" in output
    assert "$0.0100" not in output


def test_aggregated_usage_costs_each_model_without_double_counting(capsys):
    ui = ConsoleUI(use_color=False, typing_delay=0)
    ui.usage({
        "prompt_tokens": 150,
        "completion_tokens": 50,
        "total_tokens": 200,
        "model_usage": {
            "opencode/big-pickle": {
                "prompt_tokens": 100,
                "completion_tokens": 50,
                "total_tokens": 150,
            },
            "ollama/llama3.2": {
                "prompt_tokens": 50,
                "completion_tokens": 0,
                "total_tokens": 50,
            },
        },
    })

    assert ui._session_total_tokens == 200
    assert ui.calculate_session_cost() == 0.0
    capsys.readouterr()


def test_native_approval_overlay_renders_diff_and_shortcuts():
    ui = TuiConsoleUI(use_color=False, typing_delay=0)
    approval = {
        "title": "Edit src/app.py",
        "preview": "-old\n+new",
        "full": "@@ -1 +1 @@\n-old\n+new",
        "show_full": False,
    }

    body = fragment_list_to_text(to_formatted_text(_approval_text(ui, approval)))
    footer = fragment_list_to_text(to_formatted_text(_approval_footer(ui, approval)))

    assert "Approve this action?" in body
    assert "Edit src/app.py" in body
    assert "-old" in body and "+new" in body
    assert "enter/y approve" in footer
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
    assert "❯ You" in output and "Fix the bug" in output
    assert "Fixed" in output and "The bug is resolved." in output
    assert "I will inspect it" not in output
    assert "secret tool output" not in output
