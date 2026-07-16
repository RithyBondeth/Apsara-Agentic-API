"""Tests for testable helpers in the chat surface (cli/chat.py)."""
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from apsara_cli.cli import chat
from apsara_cli.cli.session import load_session_messages


# ── _save_api_key_to_env ──────────────────────────────────────────────────────

def test_save_api_key_creates_env_file(tmp_path):
    path = chat._save_api_key_to_env(tmp_path, "OPENAI_API_KEY", "sk-1")
    assert path == tmp_path / ".env"
    assert path.read_text(encoding="utf-8") == "OPENAI_API_KEY=sk-1\n"


def test_save_api_key_appends_to_existing_env(tmp_path):
    (tmp_path / ".env").write_text("FOO=bar\n", encoding="utf-8")
    chat._save_api_key_to_env(tmp_path, "OPENAI_API_KEY", "sk-1")
    content = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "FOO=bar" in content
    assert "OPENAI_API_KEY=sk-1" in content


def test_save_api_key_updates_existing_value(tmp_path):
    (tmp_path / ".env").write_text("OPENAI_API_KEY=old\nFOO=bar\n", encoding="utf-8")
    chat._save_api_key_to_env(tmp_path, "OPENAI_API_KEY", "sk-new")
    content = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "OPENAI_API_KEY=sk-new" in content
    assert "OPENAI_API_KEY=old" not in content
    assert "FOO=bar" in content  # unrelated keys are preserved


# ── save_if_needed ────────────────────────────────────────────────────────────

class _StubUI:
    def __init__(self):
        self.saved_path = None

    def session_saved(self, path):
        self.saved_path = path


def test_save_if_needed_skips_when_stateless(tmp_path):
    ui = _StubUI()
    options = SimpleNamespace(stateless=True, workspace_root=tmp_path, session="default")
    chat.save_if_needed([{"role": "user", "content": "x"}], "gpt-4o", options, ui)
    assert ui.saved_path is None
    assert not (tmp_path / ".apsara-cli").exists()  # nothing written


def test_save_if_needed_persists_when_stateful(tmp_path):
    ui = _StubUI()
    options = SimpleNamespace(stateless=False, workspace_root=tmp_path, session="default")
    messages = [{"role": "user", "content": "x"}]
    chat.save_if_needed(messages, "gpt-4o", options, ui)

    assert ui.saved_path is not None and ui.saved_path.exists()
    assert load_session_messages(tmp_path, "default") == messages
