"""Recoverable file checkpoints for agent mutations."""

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


def create_checkpoint(workspace: Path, paths: list[Path], label: str) -> str:
    checkpoint_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:6]
    root = workspace / ".apsara" / "checkpoints" / checkpoint_id
    files_root = root / "files"
    entries = []
    for path in paths:
        resolved = path.resolve()
        try:
            relative = resolved.relative_to(workspace.resolve())
        except ValueError:
            continue
        existed = resolved.is_file()
        entries.append({"path": str(relative), "existed": existed})
        if existed:
            destination = files_root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(resolved, destination)
    root.mkdir(parents=True, exist_ok=True)
    (root / "manifest.json").write_text(
        json.dumps({"id": checkpoint_id, "label": label, "files": entries}, indent=2),
        encoding="utf-8",
    )
    return checkpoint_id


def list_checkpoints(workspace: Path) -> list[dict]:
    base = workspace / ".apsara" / "checkpoints"
    if not base.is_dir():
        return []
    results = []
    for manifest_path in sorted(base.glob("*/manifest.json"), reverse=True):
        try:
            results.append(json.loads(manifest_path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    return results


def restore_checkpoint(workspace: Path, checkpoint_id: str | None = None) -> dict:
    checkpoints = list_checkpoints(workspace)
    chosen = next(
        (item for item in checkpoints if checkpoint_id is None or item.get("id") == checkpoint_id),
        None,
    )
    if chosen is None:
        raise FileNotFoundError("No matching checkpoint exists")
    root = workspace / ".apsara" / "checkpoints" / chosen["id"]
    restored = []
    removed = []
    for entry in chosen.get("files", []):
        target = (workspace / entry["path"]).resolve()
        target.relative_to(workspace.resolve())
        if entry.get("existed"):
            source = root / "files" / entry["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            restored.append(entry["path"])
        elif target.exists() and target.is_file():
            target.unlink()
            removed.append(entry["path"])
    return {"id": chosen["id"], "label": chosen.get("label", ""), "restored": restored, "removed": removed}
