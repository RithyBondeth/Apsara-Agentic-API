from types import SimpleNamespace

from prompt_toolkit.formatted_text import fragment_list_to_text, to_formatted_text

from apsara_cli.cli.tui import (
    TuiConsoleUI,
    _approval_footer,
    _approval_text,
    _restore_history,
    _status_right,
    _welcome_panel_width,
    _model_needs_key,
)
from apsara_cli.shared.ui import ConsoleUI, describe_action


class _FakeApplication:
    class _Output:
        class _Size:
            def __init__(self, columns):
                self.columns = columns

        def __init__(self, columns=80):
            self.columns = columns

        def get_size(self):
            return self._Size(self.columns)

    def __init__(self, columns=80):
        self.output = self._Output(columns)

    def invalidate(self):
        pass


def test_assistant_renders_markdown_in_the_rounded_apsara_box(capsys):
    ui = ConsoleUI(use_color=False, typing_delay=0)

    ui.assistant(
        "# Result\n\n- first item\n- second item\n\n"
        "```python\nprint('ready')\n```"
    )

    output = capsys.readouterr().out
    assert "Apsara" in output
    assert "╭" in output and "╰" in output
    assert "│" in output
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
    assert "Apsara" in output
    assert "│" in output
    assert "Summary" in output
    assert "Ready." in output
    assert "**" not in output


def test_tui_uses_the_same_rounded_markdown_box():
    ui = TuiConsoleUI(use_color=False, typing_delay=0)
    ui.app = _FakeApplication()
    ui.sidebar_visible = False

    ui.stream_text_start()
    ui.stream_text_chunk("### TUI Ready\n\n- shared renderer")
    ui.stream_text_end()

    lines = ui.rendered_lines()
    output = "\n".join(lines)
    assert "Apsara" in output
    assert "╭" in output and "╰" in output
    assert "TUI Ready" in output
    assert "• shared renderer" in output
    assert ui.content_width() == 80
    assert max(len(line) for line in lines) == 77

    ui.app.output.columns = 120
    resized_lines = ui.rendered_lines()
    assert ui.content_width() == 120
    assert max(len(line) for line in resized_lines) == 117


def test_responsive_markdown_card_is_cached_until_width_changes(monkeypatch):
    ui = TuiConsoleUI(use_color=False, typing_delay=0)
    ui.app = _FakeApplication(columns=80)
    ui.sidebar_visible = False
    calls = []
    original = ui._markdown_card_lines

    def counted(*args, **kwargs):
        calls.append(kwargs["width"])
        return original(*args, **kwargs)

    monkeypatch.setattr(ui, "_markdown_card_lines", counted)
    ui.render_markdown_panel("### Cached")

    ui.rendered_lines()
    ui.rendered_lines()
    assert calls == [77]

    ui.app.output.columns = 120
    ui.rendered_lines()
    assert calls == [77, 117]


def test_tui_user_turn_has_a_clear_role_label():
    ui = TuiConsoleUI(use_color=False, typing_delay=0)
    ui.app = _FakeApplication()

    ui.append_user_message("Explain this code")

    output = "\n".join(ui.rendered_lines())
    assert "▌" in output
    assert "  ▌ Explain this code" in output
    assert "You" in output
    assert ui.content_width() == 39
    assert max(len(line) for line in ui.rendered_lines()) <= 36


def test_tui_cards_fit_a_narrow_terminal():
    ui = TuiConsoleUI(use_color=False, typing_delay=0)
    ui.app = _FakeApplication(columns=30)
    ui.sidebar_visible = False
    ui.append_user_message("Explain this fairly long request without overflowing")
    ui.render_markdown_panel("## Result\n\nA fairly long response that must wrap.")

    lines = ui.rendered_lines()

    assert ui.content_width() == 30
    assert max(len(line) for line in lines) <= 27


def test_tui_hides_sidebar_when_it_would_starve_conversation():
    ui = TuiConsoleUI(use_color=False, typing_delay=0)
    ui.app = _FakeApplication(columns=60)
    ui.sidebar_visible = True

    assert ui.sidebar_is_rendered() is False
    assert ui.content_width() == 60

    ui.app.output.columns = 80
    assert ui.sidebar_is_rendered() is True
    assert ui.content_width() == 39


def test_tui_sidebar_is_enabled_by_default_on_wide_terminals():
    ui = TuiConsoleUI(use_color=False, typing_delay=0)
    ui.app = _FakeApplication(columns=100)

    assert ui.sidebar_visible is True
    assert ui.sidebar_is_rendered() is True
    assert ui.content_width() == 59


def test_tui_detects_when_default_model_needs_inline_key(monkeypatch):
    monkeypatch.delenv("OPENCODE_API_KEY", raising=False)

    assert _model_needs_key("opencode/big-pickle") is True

    monkeypatch.setenv("OPENCODE_API_KEY", "test-key")
    assert _model_needs_key("opencode/big-pickle") is False
    assert _model_needs_key("ollama/llama3.2") is False


def test_welcome_panel_never_exceeds_terminal_width():
    assert _welcome_panel_width(120) == 84
    assert _welcome_panel_width(80) == 64
    assert 1 <= _welcome_panel_width(30) < 30
    assert _welcome_panel_width(1) == 1


def test_big_pickle_usage_is_zero_cost_not_an_estimate(capsys):
    ui = ConsoleUI(use_color=False, typing_delay=0)
    ui.usage({
        "prompt_tokens": 800,
        "completion_tokens": 200,
        "total_tokens": 1000,
        "apsara_model": "opencode/big-pickle",
    })

    assert ui.calculate_session_cost() == 0.0
    assert "$0.0000 promo" in capsys.readouterr().out


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


def test_detailed_usage_and_rate_limits_are_rendered_and_restorable(capsys):
    ui = ConsoleUI(use_color=False, typing_delay=0)
    ui.usage({
        "prompt_tokens": 100,
        "completion_tokens": 30,
        "total_tokens": 130,
        "prompt_tokens_details": {"cached_tokens": 40},
        "completion_tokens_details": {"reasoning_tokens": 10},
        "rate_limits": {"remaining_requests": "9", "reset": "3s"},
        "apsara_model": "opencode/big-pickle",
    })
    output = capsys.readouterr().out
    assert "in 100 · out 30 · cached 40 · reasoning 10" in output
    assert "9 requests left · reset 3s" in output

    restored = ConsoleUI(use_color=False, typing_delay=0)
    restored.restore_usage(ui.usage_snapshot())
    assert restored._session_total_tokens == 130
    assert restored._session_cached_tokens == 40
    assert restored._session_reasoning_tokens == 10
    assert restored.rate_limit_label() == "9 requests left · reset 3s"


def test_unreported_usage_stays_separate_from_provider_totals(capsys):
    ui = ConsoleUI(use_color=False, typing_delay=0)
    ui.usage({
        "estimated_input_tokens": 900,
        "unreported_calls": 1,
        "apsara_model": "opencode/big-pickle",
    })

    assert ui._session_total_tokens == 0
    assert ui._session_estimated_tokens == 900
    assert ui.usage_snapshot()["unreported_calls"] == 1
    assert "~900 estimated input/unreported" in capsys.readouterr().out


def test_inline_approval_card_renders_diff_and_shortcuts():
    ui = TuiConsoleUI(use_color=False, typing_delay=0)
    ui.sidebar_visible = False
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


def test_command_approval_card_does_not_offer_always_allow():
    ui = TuiConsoleUI(use_color=False, typing_delay=0)
    ui.sidebar_visible = False
    approval = {
        "title": "Run command",
        "preview": "$ pytest -q",
        "full": "$ pytest -q",
        "is_trust": False,
        "allow_always": False,
    }

    footer = fragment_list_to_text(to_formatted_text(_approval_footer(ui, approval)))

    assert "allow once" in footer
    assert "always allow" not in footer


def test_narrow_approval_footer_keeps_allow_and_deny_visible():
    ui = TuiConsoleUI(use_color=False, typing_delay=0)
    ui.app = _FakeApplication(columns=30)
    ui.sidebar_visible = False
    approval = {
        "preview": "-old\n+new",
        "full": "@@ -1 +1 @@\n-old\n+new",
        "allow_always": True,
    }

    footer = fragment_list_to_text(to_formatted_text(_approval_footer(ui, approval)))

    assert "allow" in footer
    assert "n deny" in footer
    assert len(footer) <= ui.content_width() - 12


def test_status_bar_handles_unpriced_model_usage():
    ui = TuiConsoleUI(use_color=False, typing_delay=0)
    ui.app = _FakeApplication(columns=100)
    ui.sidebar_visible = False
    ui.usage({
        "prompt_tokens": 8,
        "completion_tokens": 2,
        "total_tokens": 10,
        "apsara_model": "custom/unpriced-model",
    })
    options = SimpleNamespace(dry_run=False, read_only=False)

    status = fragment_list_to_text(
        to_formatted_text(_status_right(ui, options, "custom/unpriced-model"))
    )

    assert "provider billed" in status


def test_bash_approval_includes_command_and_working_directory():
    title, preview, *_ = describe_action(
        "run_bash_command",
        {"command": "pytest -q", "cwd": "/workspace"},
    )

    assert title == "Run command"
    assert preview == "$ pytest -q\n  in /workspace"


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

    output = "\n".join(ui.rendered_lines())
    assert "Resumed 1 prior turn" in output
    assert "▌" in output and "Fix the bug" in output and "You" in output
    assert "Fixed" in output and "The bug is resolved." in output
    assert "I will inspect it" not in output
    assert "secret tool output" not in output
