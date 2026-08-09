"""Tests for the string-matching edit_file tool."""
import sys
import os
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from apsara_cli.engine.tools import (
    agent_runtime_context,
    edit_file,
    get_agent_tools,
    get_tool_registry,
)


def _ctx(tmp: Path, approve: bool = True, **kwargs):
    return agent_runtime_context(
        workspace_root=tmp,
        confirmation_callback=lambda action, payload: approve,
        **kwargs,
    )


# ── happy path ────────────────────────────────────────────────────────────────

def test_edit_replaces_unique_match(tmp_path):
    target = tmp_path / "calc.py"
    target.write_text("def add(a, b):\n    return a + b\n")
    with _ctx(tmp_path):
        result = edit_file("calc.py", "a + b", "a - b")
    assert "Successfully replaced 1 occurrence" in result
    assert target.read_text() == "def add(a, b):\n    return a - b\n"


def test_edit_preserves_surrounding_content(tmp_path):
    target = tmp_path / "app.py"
    target.write_text("import os\n\nVALUE = 1\n\nprint(VALUE)\n")
    with _ctx(tmp_path):
        edit_file("app.py", "VALUE = 1", "VALUE = 42")
    assert target.read_text() == "import os\n\nVALUE = 42\n\nprint(VALUE)\n"


def test_edit_can_delete_a_snippet(tmp_path):
    target = tmp_path / "a.txt"
    target.write_text("keep\nremove me\nkeep\n")
    with _ctx(tmp_path):
        edit_file("a.txt", "remove me\n", "")
    assert target.read_text() == "keep\nkeep\n"


def test_edit_multiline_snippet(tmp_path):
    target = tmp_path / "m.py"
    target.write_text("def f():\n    x = 1\n    return x\n")
    with _ctx(tmp_path):
        result = edit_file("m.py", "    x = 1\n    return x\n", "    return 1\n")
    assert "Successfully" in result
    assert target.read_text() == "def f():\n    return 1\n"


# ── uniqueness enforcement ────────────────────────────────────────────────────

def test_edit_rejects_ambiguous_match(tmp_path):
    target = tmp_path / "dup.py"
    original = "x = 1\ny = 1\n"
    target.write_text(original)
    with _ctx(tmp_path):
        result = edit_file("dup.py", "= 1", "= 2")
    assert result.startswith("Error")
    assert "appears 2 times" in result
    assert target.read_text() == original, "file must be untouched on ambiguity"


def test_edit_replace_all_changes_every_occurrence(tmp_path):
    target = tmp_path / "dup.py"
    target.write_text("x = 1\ny = 1\n")
    with _ctx(tmp_path):
        result = edit_file("dup.py", "= 1", "= 2", replace_all=True)
    assert "Successfully replaced 2 occurrences" in result
    assert target.read_text() == "x = 2\ny = 2\n"


def test_edit_missing_string_fails_loudly(tmp_path):
    target = tmp_path / "a.py"
    original = "value = 1\n"
    target.write_text(original)
    with _ctx(tmp_path):
        result = edit_file("a.py", "not present", "whatever")
    assert result.startswith("Error")
    assert "not found" in result
    assert target.read_text() == original


def test_edit_is_whitespace_sensitive(tmp_path):
    """Indentation mismatches must fail, not silently match."""
    target = tmp_path / "a.py"
    original = "def f():\n    return 1\n"
    target.write_text(original)
    with _ctx(tmp_path):
        result = edit_file("a.py", "return 1\n    ", "return 2\n    ")
    assert result.startswith("Error")
    assert target.read_text() == original


# ── guards ────────────────────────────────────────────────────────────────────

def test_edit_rejects_empty_old_string(tmp_path):
    (tmp_path / "a.txt").write_text("content")
    with _ctx(tmp_path):
        result = edit_file("a.txt", "", "new")
    assert result.startswith("Error")
    assert "must not be empty" in result


def test_edit_rejects_identical_strings(tmp_path):
    (tmp_path / "a.txt").write_text("content")
    with _ctx(tmp_path):
        result = edit_file("a.txt", "same", "same")
    assert result.startswith("Error")
    assert "identical" in result


def test_edit_missing_file(tmp_path):
    with _ctx(tmp_path):
        result = edit_file("nope.txt", "a", "b")
    assert result.startswith("Error")


def test_edit_outside_workspace_blocked(tmp_path):
    with _ctx(tmp_path):
        result = edit_file("/etc/hosts", "localhost", "pwned")
    assert result.startswith("Error")


def test_edit_blocked_in_read_only_mode(tmp_path):
    target = tmp_path / "a.txt"
    target.write_text("before")
    with _ctx(tmp_path, read_only=True):
        result = edit_file("a.txt", "before", "after")
    assert result.startswith("Error")
    assert target.read_text() == "before"


def test_edit_respects_rejected_confirmation(tmp_path):
    target = tmp_path / "a.txt"
    target.write_text("before")
    with _ctx(tmp_path, approve=False):
        result = edit_file("a.txt", "before", "after")
    assert result.startswith("Error")
    assert "not approved" in result
    assert target.read_text() == "before"


def test_edit_dry_run_does_not_write(tmp_path):
    target = tmp_path / "a.txt"
    target.write_text("before")
    with _ctx(tmp_path, dry_run=True):
        result = edit_file("a.txt", "before", "after")
    assert "[Dry Run]" in result
    assert target.read_text() == "before"


def test_edit_respects_max_file_size(tmp_path):
    target = tmp_path / "big.txt"
    target.write_text("x" * 100)
    with _ctx(tmp_path, max_file_size_bytes=10):
        result = edit_file("big.txt", "x", "y")
    assert result.startswith("Error")
    assert "exceeds" in result


# ── confirmation payload ──────────────────────────────────────────────────────

def test_edit_confirmation_payload_carries_diff(tmp_path):
    target = tmp_path / "a.txt"
    target.write_text("before\n")
    seen = {}

    def capture(action, payload):
        seen["action"] = action
        seen["payload"] = payload
        return True

    with agent_runtime_context(workspace_root=tmp_path, confirmation_callback=capture):
        edit_file("a.txt", "before", "after")

    assert seen["action"] == "edit_file"
    payload = seen["payload"]
    assert payload["display_path"] == "a.txt"
    assert payload["occurrences"] == 1
    assert payload["replace_all"] is False
    assert "-before" in payload["diff_preview"]
    assert "+after" in payload["diff_preview"]


# ── registration ──────────────────────────────────────────────────────────────

def test_edit_file_is_registered():
    assert "edit_file" in get_tool_registry()
    names = [t["function"]["name"] for t in get_agent_tools()]
    assert "edit_file" in names


def test_edit_file_declared_before_replace_file_lines():
    """The model should meet the safer tool first."""
    names = [t["function"]["name"] for t in get_agent_tools()]
    assert names.index("edit_file") < names.index("replace_file_lines")
