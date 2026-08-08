"""Small, transparent project memory stored inside .apsara."""

from datetime import datetime, timezone
from pathlib import Path


def memory_path(workspace: Path) -> Path:
    return workspace / ".apsara" / "memory.md"


def read_memory(workspace: Path, max_chars: int = 12000) -> str:
    path = memory_path(workspace)
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")[-max_chars:]


def add_memory(workspace: Path, note: str) -> Path:
    path = memory_path(workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    prefix = "# Apsara project memory\n\n" if not path.exists() else ""
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"{prefix}- [{stamp}] {note.strip()}\n")
    return path
