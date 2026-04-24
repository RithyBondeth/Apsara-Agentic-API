import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SESSION_ROOT_DIR = ".apsara-cli"
SESSIONS_DIR = "sessions"


def sanitize_session_name(name: str) -> str:
    sanitized = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip(".-")
    if not sanitized:
        raise ValueError(
            "Session name must contain letters, numbers, dots, dashes, or underscores."
        )
    return sanitized


def get_sessions_dir(workspace_root: Path) -> Path:
    return workspace_root / SESSION_ROOT_DIR / SESSIONS_DIR


def get_session_path(workspace_root: Path, session_name: str) -> Path:
    return get_sessions_dir(workspace_root) / f"{sanitize_session_name(session_name)}.json"


def load_session_messages(workspace_root: Path, session_name: str) -> list[dict[str, Any]]:
    session_path = get_session_path(workspace_root, session_name)
    if not session_path.exists():
        return []

    payload = json.loads(session_path.read_text(encoding="utf-8"))
    messages = payload.get("messages", [])
    if not isinstance(messages, list):
        raise ValueError(f"Session file '{session_path}' is invalid.")
    return messages


def save_session_messages(
    workspace_root: Path,
    session_name: str,
    model: str,
    messages: list[dict[str, Any]],
) -> Path:
    session_path = get_session_path(workspace_root, session_name)
    session_path.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "session_name": sanitize_session_name(session_name),
        "workspace_root": str(workspace_root),
        "model": model,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "messages": messages,
    }
    session_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return session_path


def list_sessions(workspace_root: Path) -> list[Path]:
    sessions_dir = get_sessions_dir(workspace_root)
    if not sessions_dir.exists():
        return []
    return sorted(path for path in sessions_dir.glob("*.json") if path.is_file())
