import sys
from types import SimpleNamespace

from apsara_cli.cli.options import resolve_runtime_options
from apsara_cli.cli.parser import _argv_with_default_command, build_parser


def test_empty_command_line_defaults_to_interactive_chat():
    args = build_parser().parse_args(_argv_with_default_command([]))

    assert args.command == "chat"
    assert args.model is None
    assert args.tui is False


def test_explicit_commands_and_process_arguments_are_preserved(monkeypatch):
    assert _argv_with_default_command(["doctor"]) == ["doctor"]
    assert _argv_with_default_command(["--help"]) == ["--help"]

    monkeypatch.setattr(sys, "argv", ["apsara"])
    assert _argv_with_default_command(None) == ["chat"]


def test_bare_interactive_options_are_attached_to_default_chat():
    normalized = _argv_with_default_command([
        "--model", "opencode/big-pickle", "--read-only"
    ])
    args = build_parser().parse_args(normalized)

    assert normalized == [
        "chat", "--model", "opencode/big-pickle", "--read-only"
    ]
    assert args.command == "chat"
    assert args.model == "opencode/big-pickle"
    assert args.read_only is True


def test_global_config_stays_before_implicit_chat():
    normalized = _argv_with_default_command([
        "--config", "custom.toml", "--workspace", "/tmp/project"
    ])
    args = build_parser().parse_args(normalized)

    assert normalized == [
        "--config", "custom.toml", "chat", "--workspace", "/tmp/project"
    ]
    assert args.config == "custom.toml"
    assert args.workspace == "/tmp/project"


def test_missing_global_config_value_is_left_for_argparse_to_reject():
    assert _argv_with_default_command(["--config"]) == ["--config"]


def test_interactive_start_uses_big_pickle_without_hidden_auth_default(tmp_path):
    args = build_parser().parse_args(["chat", "--workspace", str(tmp_path)])
    defaults = SimpleNamespace(
        workspace=None,
        model=None,
        session=None,
        stateless=None,
        allow_bash=None,
        allowed_commands=None,
        bash_timeout=None,
        max_file_size=None,
        auto_approve=None,
        color=None,
    )

    options = resolve_runtime_options(args, defaults)

    assert options.model == "opencode/big-pickle"
