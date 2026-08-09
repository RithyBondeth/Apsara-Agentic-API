from pathlib import Path

import pytest

from apsara_cli.engine.runtime import RunJournal
from apsara_cli.engine.tools import agent_runtime_context, write_to_file
from apsara_cli.engine.turn_checkpoints import (
    activate_turn_checkpoint,
    begin_turn_checkpoint,
    capture_turn_paths,
    capture_turn_workspace,
    deactivate_turn_checkpoint,
    finish_turn_checkpoint,
    list_turn_checkpoints,
    restore_turn_checkpoint,
)
from apsara_cli.shared.types import AgentRun, AgentRunState


def test_turn_checkpoint_restores_multiple_mutations(tmp_path: Path):
    existing = tmp_path / "existing.txt"
    created = tmp_path / "created.txt"
    directory = tmp_path / "new-directory"
    existing.write_text("before", encoding="utf-8")
    begin_turn_checkpoint(tmp_path, "turn-one", "change files")
    token = activate_turn_checkpoint("turn-one")
    try:
        capture_turn_paths(tmp_path, [existing, created, directory])
        existing.write_text("after", encoding="utf-8")
        created.write_text("created", encoding="utf-8")
        directory.mkdir()
    finally:
        deactivate_turn_checkpoint(token)

    manifest = finish_turn_checkpoint(tmp_path, "turn-one", "completed")
    assert manifest["changes"] == [
        {"path": "existing.txt", "action": "modified"},
        {"path": "created.txt", "action": "created"},
        {"path": "new-directory", "action": "created"},
    ]

    restored = restore_turn_checkpoint(tmp_path, "turn-one")
    assert existing.read_text(encoding="utf-8") == "before"
    assert not created.exists()
    assert not directory.exists()
    assert restored["status"] == "rolled_back"
    assert not restored["rollback"]["conflicts"]


def test_default_rollback_skips_already_rolled_back_latest_turn(tmp_path: Path):
    for turn_id, filename in (("first", "first.txt"), ("second", "second.txt")):
        target = tmp_path / filename
        begin_turn_checkpoint(tmp_path, turn_id, turn_id)
        token = activate_turn_checkpoint(turn_id)
        try:
            capture_turn_paths(tmp_path, [target])
            target.write_text(turn_id, encoding="utf-8")
        finally:
            deactivate_turn_checkpoint(token)
        finish_turn_checkpoint(tmp_path, turn_id, "completed")

    assert restore_turn_checkpoint(tmp_path, "second")["id"] == "second"
    assert restore_turn_checkpoint(tmp_path)["id"] == "first"


def test_turn_rollback_leaves_nonempty_created_directory_as_conflict(tmp_path: Path):
    directory = tmp_path / "created"
    begin_turn_checkpoint(tmp_path, "turn-conflict", "create directory")
    token = activate_turn_checkpoint("turn-conflict")
    try:
        capture_turn_paths(tmp_path, [directory])
        directory.mkdir()
        (directory / "later.txt").write_text("user data", encoding="utf-8")
    finally:
        deactivate_turn_checkpoint(token)
    finish_turn_checkpoint(tmp_path, "turn-conflict", "completed")

    result = restore_turn_checkpoint(tmp_path, "turn-conflict")
    assert directory.is_dir()
    assert result["rollback"]["conflicts"] == ["created"]


def test_active_manifest_supports_interrupted_turn_recovery(tmp_path: Path):
    begin_turn_checkpoint(tmp_path, "interrupted", "unfinished work")
    turns = list_turn_checkpoints(tmp_path)
    assert turns[0]["id"] == "interrupted"
    assert turns[0]["status"] == "active"


def test_turn_id_cannot_escape_checkpoint_directory(tmp_path: Path):
    with pytest.raises(ValueError, match="Unsafe turn checkpoint id"):
        begin_turn_checkpoint(tmp_path, "../escape", "unsafe")


def test_command_snapshot_restores_deleted_files_and_removes_new_tree(tmp_path: Path):
    original = tmp_path / "original.txt"
    original.write_text("before", encoding="utf-8")
    begin_turn_checkpoint(tmp_path, "command-turn", "run formatter")
    token = activate_turn_checkpoint("command-turn")
    try:
        capture_turn_workspace(tmp_path)
        original.unlink()
        generated = tmp_path / "generated" / "artifact.txt"
        generated.parent.mkdir()
        generated.write_text("generated", encoding="utf-8")
        finish_turn_checkpoint(tmp_path, "command-turn", "completed")
    finally:
        deactivate_turn_checkpoint(token)

    result = restore_turn_checkpoint(tmp_path, "command-turn")
    assert original.read_text(encoding="utf-8") == "before"
    assert not (tmp_path / "generated").exists()
    assert result["rollback"]["conflicts"] == []


def test_command_rollback_unlinks_new_symlink_without_touching_target(tmp_path: Path):
    outside = tmp_path.parent / f"{tmp_path.name}-outside.txt"
    outside.write_text("keep", encoding="utf-8")
    begin_turn_checkpoint(tmp_path, "symlink-turn", "create link")
    token = activate_turn_checkpoint("symlink-turn")
    link = tmp_path / "outside-link"
    try:
        capture_turn_workspace(tmp_path)
        try:
            link.symlink_to(outside)
        except OSError:
            pytest.skip("symlinks are unavailable on this platform")
        finish_turn_checkpoint(tmp_path, "symlink-turn", "completed")
    finally:
        deactivate_turn_checkpoint(token)

    restore_turn_checkpoint(tmp_path, "symlink-turn")
    assert not link.exists() and not link.is_symlink()
    assert outside.read_text(encoding="utf-8") == "keep"


def test_file_restore_replaces_symlink_without_writing_outside(tmp_path: Path):
    target = tmp_path / "source.txt"
    outside = tmp_path.parent / f"{tmp_path.name}-protected.txt"
    target.write_text("original", encoding="utf-8")
    outside.write_text("protected", encoding="utf-8")
    begin_turn_checkpoint(tmp_path, "swap-turn", "replace file")
    token = activate_turn_checkpoint("swap-turn")
    try:
        capture_turn_paths(tmp_path, [target])
        target.unlink()
        try:
            target.symlink_to(outside)
        except OSError:
            pytest.skip("symlinks are unavailable on this platform")
        finish_turn_checkpoint(tmp_path, "swap-turn", "completed")
    finally:
        deactivate_turn_checkpoint(token)

    restore_turn_checkpoint(tmp_path, "swap-turn")
    assert not target.is_symlink()
    assert target.read_text(encoding="utf-8") == "original"
    assert outside.read_text(encoding="utf-8") == "protected"


def test_failed_turn_can_automatically_roll_back(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("APSARA_ROLLBACK_FAILED_TURNS", "1")
    target = tmp_path / "value.txt"
    target.write_text("original", encoding="utf-8")
    run = AgentRun(objective="change value", model="test/model", workspace=str(tmp_path))
    journal = RunJournal(tmp_path, run)
    token = activate_turn_checkpoint(run.run_id)
    try:
        with agent_runtime_context(workspace_root=tmp_path, confirmation_callback=lambda *_: True):
            assert not write_to_file("value.txt", "changed").startswith("Error")
        journal.transition(AgentRunState.FAILED, "verification failed")
    finally:
        deactivate_turn_checkpoint(token)

    assert target.read_text(encoding="utf-8") == "original"
    manifest = list_turn_checkpoints(tmp_path)[0]
    assert manifest["status"] == "rolled_back"


def test_tool_transaction_removes_new_parent_directories(tmp_path: Path):
    run = AgentRun(objective="create nested file", model="test/model", workspace=str(tmp_path))
    journal = RunJournal(tmp_path, run)
    token = activate_turn_checkpoint(run.run_id)
    try:
        with agent_runtime_context(workspace_root=tmp_path, confirmation_callback=lambda *_: True):
            assert not write_to_file("new/parent/value.txt", "value").startswith("Error")
        journal.transition(AgentRunState.COMPLETED)
    finally:
        deactivate_turn_checkpoint(token)

    restore_turn_checkpoint(tmp_path, run.run_id)
    assert not (tmp_path / "new").exists()
