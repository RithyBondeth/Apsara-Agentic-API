import argparse
import asyncio
from types import SimpleNamespace

from apsara_cli.cli import workspace


def test_init_honors_no_color(tmp_path, monkeypatch):
    observed = []

    class FakeUI:
        def __init__(self, *, use_color, auto_approve):
            observed.append((use_color, auto_approve))

        def info(self, message):
            pass

        def success(self, message):
            pass

    monkeypatch.setattr(workspace, "ConsoleUI", FakeUI)
    args = argparse.Namespace(
        workspace=str(tmp_path),
        color=False,
        force=False,
        no_chat=True,
    )
    config = SimpleNamespace(defaults=SimpleNamespace(color=True))

    assert asyncio.run(workspace.init_workspace(args, config)) == 0
    assert observed == [(False, True)]
