"""Tests for the verification loop: command presets and the bash timeout.

Together these decide whether the agent can run the project's tests to check
its own work, which is the difference between iterating and guessing.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from apsara_cli.cli.options import (
    COMMAND_PRESETS,
    expand_command_presets,
    parse_allowed_commands,
)
from apsara_cli.engine.tools import (
    _bash_timeout,
    agent_runtime_context,
    run_bash_command,
)


# ── command presets ───────────────────────────────────────────────────────────

def test_verify_preset_includes_a_test_runner():
    """The whole point: the agent must be able to run the suite."""
    verify = COMMAND_PRESETS["verify"]
    assert "pytest" in verify
    assert "npm" in verify
    assert {"go", "cargo", "make"} <= verify


def test_preset_expands():
    assert expand_command_presets({"@verify"}) == COMMAND_PRESETS["verify"]


def test_presets_mix_with_plain_commands():
    result = expand_command_presets({"@git", "docker"})
    assert "git" in result
    assert "docker" in result


def test_multiple_presets_union():
    result = expand_command_presets({"@read", "@git"})
    assert result == COMMAND_PRESETS["read"] | COMMAND_PRESETS["git"]


def test_unknown_preset_is_a_clear_error():
    with pytest.raises(ValueError) as exc:
        expand_command_presets({"@nope"})
    assert "@nope" in str(exc.value)
    assert "@verify" in str(exc.value), "should list what is available"


def test_parse_allowed_commands_expands_presets():
    parsed = parse_allowed_commands("@verify,git")
    assert "pytest" in parsed
    assert "git" in parsed


def test_parse_allowed_commands_accepts_a_list():
    parsed = parse_allowed_commands(["@git", "rg"])
    assert parsed == {"git", "rg"}


def test_plain_command_lists_still_work():
    assert parse_allowed_commands("ls,cat") == {"ls", "cat"}


def test_none_stays_none():
    assert parse_allowed_commands(None) is None


# ── bash timeout ──────────────────────────────────────────────────────────────

def test_default_timeout_allows_a_real_test_suite():
    """30s was too short to run most suites; the default must be generous."""
    with agent_runtime_context(workspace_root=Path.cwd()):
        assert _bash_timeout() >= 120


def test_timeout_is_overridable():
    with agent_runtime_context(workspace_root=Path.cwd(), bash_timeout_seconds=7):
        assert _bash_timeout() == 7


def test_timeout_floor_is_one_second():
    with agent_runtime_context(workspace_root=Path.cwd(), bash_timeout_seconds=0):
        assert _bash_timeout() == 1


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX sleep")
def test_command_exceeding_the_timeout_is_killed(tmp_path):
    with agent_runtime_context(
        workspace_root=tmp_path,
        enable_bash=True,
        allowed_commands={"sleep"},
        bash_timeout_seconds=1,
        confirmation_callback=lambda action, payload: True,
    ):
        result = run_bash_command("sleep 5")
    assert result.startswith("Error")
    assert "timed out after 1 seconds" in result
    assert "--bash-timeout" in result, "error should say how to raise it"


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX echo")
def test_command_within_the_timeout_succeeds(tmp_path):
    with agent_runtime_context(
        workspace_root=tmp_path,
        enable_bash=True,
        allowed_commands={"echo"},
        bash_timeout_seconds=30,
        confirmation_callback=lambda action, payload: True,
    ):
        result = run_bash_command("echo hello")
    assert "hello" in result
    assert "EXIT CODE: 0" in result


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX tooling")
def test_verify_preset_actually_permits_running_the_suite(tmp_path):
    """End to end: @verify must let a pytest invocation through the allowlist."""
    (tmp_path / "test_sample.py").write_text("def test_ok():\n    assert True\n")

    with agent_runtime_context(
        workspace_root=tmp_path,
        enable_bash=True,
        allowed_commands=parse_allowed_commands("@verify"),
        bash_timeout_seconds=120,
        confirmation_callback=lambda action, payload: True,
    ):
        result = run_bash_command(f'"{sys.executable}" -m pytest -q test_sample.py')

    assert "EXIT CODE: 0" in result, result
    assert not result.startswith("Error")


def test_default_allowlist_cannot_run_tests():
    """Documents why the preset exists."""
    from apsara_cli.config.defaults import settings

    assert "pytest" not in settings.agent_allowed_commands
    assert "npm" not in settings.agent_allowed_commands


# ── path-qualified commands ───────────────────────────────────────────────────

@pytest.mark.skipif(sys.platform == "win32", reason="POSIX paths")
def test_project_local_tooling_is_permitted(tmp_path):
    """`.venv/bin/pytest` is how real projects invoke their test runner."""
    from apsara_cli.engine.tools import _command_is_allowed

    with agent_runtime_context(
        workspace_root=tmp_path, allowed_commands={"pytest", "jest"}
    ):
        assert _command_is_allowed("pytest")
        assert _command_is_allowed(".venv/bin/pytest")
        assert _command_is_allowed("./node_modules/.bin/jest")
        assert _command_is_allowed("/usr/local/bin/pytest")


def test_path_matching_does_not_admit_other_commands(tmp_path):
    from apsara_cli.engine.tools import _command_is_allowed

    with agent_runtime_context(
        workspace_root=tmp_path, allowed_commands={"pytest"}
    ):
        assert not _command_is_allowed("rm")
        assert not _command_is_allowed("/bin/rm")
        assert not _command_is_allowed("./scripts/deploy.sh")


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX tooling")
def test_venv_python_can_run_the_suite(tmp_path):
    """The failure that prompted path matching: an interpreter by full path."""
    (tmp_path / "test_sample.py").write_text("def test_ok():\n    assert True\n")

    with agent_runtime_context(
        workspace_root=tmp_path,
        enable_bash=True,
        allowed_commands=parse_allowed_commands("@verify"),
        bash_timeout_seconds=120,
        confirmation_callback=lambda action, payload: True,
    ):
        result = run_bash_command(f'"{sys.executable}" -m pytest -q test_sample.py')

    assert "EXIT CODE: 0" in result, result
