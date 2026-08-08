"""Security tests for the bash-tool allowlist and denylist hardening.

These verify that known allowlist-bypass vectors are rejected before the command
ever reaches the shell. They run entirely offline (no real command executes,
because validation fails first).
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from apsara_cli.engine.tools import (
    agent_runtime_context,
    run_bash_command,
    _extract_command_names,
    _validate_bash_command,
    _redirection_target_escapes,
)

ALLOWED = {"ls", "cat", "find", "grep", "pwd", "wc", "head", "tail", "sed", "echo"}


def _ctx(tmp: Path):
    return agent_runtime_context(
        workspace_root=tmp,
        enable_bash=True,
        allowed_commands=ALLOWED,
        confirmation_callback=lambda action, payload: True,
    )


# ── _extract_command_names now splits on a single & (background) ───────────────

def test_extract_splits_background_ampersand():
    # The second command must be surfaced so it gets allowlist-checked.
    assert _extract_command_names("ls & rm -rf ~") == ["ls", "rm"]


def test_extract_still_splits_double_ampersand():
    assert _extract_command_names("cd /tmp && ls") == ["cd", "ls"]


# ── Bypass vectors rejected (validator level, no context needed) ───────────────

def test_process_substitution_blocked():
    assert _validate_bash_command("cat <(rm -rf /)") is not None
    assert _validate_bash_command("tee >(sh)") is not None


def test_command_substitution_blocked():
    assert _validate_bash_command("ls $(whoami)") is not None
    assert _validate_bash_command("ls `whoami`") is not None


def test_find_exec_blocked():
    assert _validate_bash_command("find . -exec rm {} ;") is not None
    assert _validate_bash_command("find . -execdir cat {} ;") is not None


def test_redirection_outside_workspace_blocked():
    assert _redirection_target_escapes(["cat", "x", ">", "/etc/passwd"]) is True
    assert _redirection_target_escapes(["cat", "x", ">>/etc/cron"]) is True
    assert _redirection_target_escapes(["echo", "hi", ">", "../escape"]) is True


def test_redirection_inside_workspace_allowed():
    # In-workspace relative redirection is fine, and fd-dup is not a path.
    assert _redirection_target_escapes(["echo", "hi", ">", "out.txt"]) is False
    assert _redirection_target_escapes(["ls", "2>&1"]) is False


# ── End-to-end through run_bash_command (bash enabled, auto-approved) ──────────

def test_run_bash_rejects_background_bypass(tmp_path):
    with _ctx(tmp_path):
        # `notacommand` is not allowlisted; hiding it behind & must not run it.
        result = run_bash_command("ls & notacommand")
    assert result.startswith("Error")
    assert "notacommand" in result


def test_run_bash_rejects_process_substitution(tmp_path):
    with _ctx(tmp_path):
        result = run_bash_command("cat <(echo hi)")
    assert result.startswith("Error")


def test_run_bash_rejects_find_exec(tmp_path):
    with _ctx(tmp_path):
        result = run_bash_command("find . -exec rm {} ;")
    assert result.startswith("Error")


def test_run_bash_rejects_escape_redirection(tmp_path):
    with _ctx(tmp_path):
        result = run_bash_command("echo pwned > /tmp/apsara_escape_test")
    assert result.startswith("Error")
    assert not Path("/tmp/apsara_escape_test").exists()


def test_run_bash_allows_normal_pipeline(tmp_path):
    (tmp_path / "a.txt").write_text("foo\nbar\n")
    with _ctx(tmp_path):
        result = run_bash_command("cat a.txt | grep foo")
    assert "foo" in result
    assert "EXIT CODE: 0" in result
