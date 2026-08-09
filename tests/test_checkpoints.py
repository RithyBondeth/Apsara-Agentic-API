from pathlib import Path

from apsara_cli.engine.checkpoints import create_checkpoint, list_checkpoints, restore_checkpoint


def test_restore_existing_file(tmp_path: Path):
    target = tmp_path / "hello.txt"
    target.write_text("before", encoding="utf-8")
    checkpoint_id = create_checkpoint(tmp_path, [target], "before edit")
    target.write_text("after", encoding="utf-8")

    result = restore_checkpoint(tmp_path, checkpoint_id)

    assert target.read_text(encoding="utf-8") == "before"
    assert result["restored"] == ["hello.txt"]


def test_restore_removes_new_file(tmp_path: Path):
    target = tmp_path / "new.txt"
    checkpoint_id = create_checkpoint(tmp_path, [target], "before create")
    target.write_text("new", encoding="utf-8")

    result = restore_checkpoint(tmp_path, checkpoint_id)

    assert not target.exists()
    assert result["removed"] == ["new.txt"]
    assert list_checkpoints(tmp_path)[0]["id"] == checkpoint_id


def test_restore_rejects_unknown_checkpoint(tmp_path: Path):
    try:
        restore_checkpoint(tmp_path, "missing")
    except FileNotFoundError as exc:
        assert "No matching checkpoint" in str(exc)
    else:
        raise AssertionError("expected FileNotFoundError")
