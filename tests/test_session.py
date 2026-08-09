"""Tests for session persistence (cli/session.py)."""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from apsara_cli.cli import session


# ── Name sanitization ─────────────────────────────────────────────────────────

def test_sanitize_keeps_valid_name():
    assert session.sanitize_session_name("my_session-1.2") == "my_session-1.2"


def test_sanitize_replaces_invalid_chars():
    assert session.sanitize_session_name("feature/login work!") == "feature-login-work"


def test_sanitize_strips_leading_trailing_punctuation():
    assert session.sanitize_session_name("--default..") == "default"


def test_sanitize_empty_after_cleanup_raises():
    with pytest.raises(ValueError):
        session.sanitize_session_name("!!!")


# ── Path helpers ──────────────────────────────────────────────────────────────

def test_sessions_dir_and_path(tmp_path):
    assert session.get_sessions_dir(tmp_path) == tmp_path / ".apsara-cli" / "sessions"
    assert session.get_session_path(tmp_path, "default").name == "default.json"


# ── Save / load round-trip ────────────────────────────────────────────────────

def test_load_missing_session_returns_empty(tmp_path):
    assert session.load_session_messages(tmp_path, "nope") == []


def test_save_and_load_roundtrip(tmp_path):
    messages = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "yo"}]
    path = session.save_session_messages(tmp_path, "default", "gpt-4o", messages)

    assert path.exists()
    assert session.load_session_messages(tmp_path, "default") == messages

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["model"] == "gpt-4o"
    assert payload["session_name"] == "default"
    assert "updated_at" in payload


def test_usage_roundtrip_and_legacy_default(tmp_path):
    assert session.load_session_usage(tmp_path, "missing") == {}
    usage = {
        "prompt_tokens": 100,
        "completion_tokens": 20,
        "total_tokens": 120,
        "cached_tokens": 40,
        "model_usage": {"opencode/big-pickle": {"total_tokens": 120}},
    }
    session.save_session_messages(tmp_path, "usage", "opencode/big-pickle", [], usage=usage)
    assert session.load_session_usage(tmp_path, "usage") == usage

    legacy = session.get_session_path(tmp_path, "legacy")
    legacy.write_text(json.dumps({"messages": []}), encoding="utf-8")
    assert session.load_session_usage(tmp_path, "legacy") == {}


def test_save_creates_parent_directories(tmp_path):
    path = session.save_session_messages(tmp_path, "s", "m", [])
    assert path.parent == session.get_sessions_dir(tmp_path)
    assert path.parent.is_dir()


def test_load_rejects_non_list_messages(tmp_path):
    path = session.get_session_path(tmp_path, "bad")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"messages": "not-a-list"}), encoding="utf-8")
    with pytest.raises(ValueError):
        session.load_session_messages(tmp_path, "bad")


# ── Listing ───────────────────────────────────────────────────────────────────

def test_list_sessions_empty(tmp_path):
    assert session.list_sessions(tmp_path) == []


def test_list_sessions_sorted(tmp_path):
    session.save_session_messages(tmp_path, "zeta", "m", [])
    session.save_session_messages(tmp_path, "alpha", "m", [])
    names = [p.stem for p in session.list_sessions(tmp_path)]
    assert names == ["alpha", "zeta"]
