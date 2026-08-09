"""Security boundaries for repository-controlled .env files."""

import argparse
import os
from types import SimpleNamespace

from apsara_cli.cli.options import load_cli_environment


def _args(workspace):
    return argparse.Namespace(workspace=str(workspace))


def _config():
    return SimpleNamespace(defaults=SimpleNamespace(workspace=None))


def test_workspace_dotenv_loads_provider_credentials(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OPENCODE_API_KEY", raising=False)
    (tmp_path / ".env").write_text("OPENCODE_API_KEY=test-key\n", encoding="utf-8")

    loaded = load_cli_environment(_args(tmp_path), _config())

    assert loaded == [tmp_path / ".env"]
    assert os.environ["OPENCODE_API_KEY"] == "test-key"


def test_workspace_dotenv_cannot_change_runtime_policy(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    blocked = {
        "APSARA_INPUT_TOKEN_BUDGET": "999999999",
        "APSARA_PRICING_CACHE": "/tmp/forged-pricing.json",
        "APSARA_FALLBACK_MODELS": "attacker/model",
        "OPENCODE_API_BASE": "https://example.invalid/v1",
    }
    for key in blocked:
        monkeypatch.delenv(key, raising=False)
    (tmp_path / ".env").write_text(
        "\n".join(f"{key}={value}" for key, value in blocked.items()) + "\n",
        encoding="utf-8",
    )

    loaded = load_cli_environment(_args(tmp_path), _config())

    assert loaded == []
    assert all(key not in os.environ for key in blocked)


def test_shell_environment_still_wins(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENCODE_API_KEY", "shell-key")
    (tmp_path / ".env").write_text("OPENCODE_API_KEY=project-key\n", encoding="utf-8")

    load_cli_environment(_args(tmp_path), _config())

    assert os.environ["OPENCODE_API_KEY"] == "shell-key"
