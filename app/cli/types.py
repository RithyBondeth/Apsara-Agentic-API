from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Set


@dataclass
class ResolvedOptions:
    workspace_root: Path
    model: str
    session: str
    stateless: bool
    allow_bash: bool
    allowed_commands: Optional[Set[str]]
    max_file_size: Optional[int]
    auto_approve: bool
    use_color: bool


@dataclass
class DoctorCheckResult:
    name: str
    status: str
    detail: str


@dataclass
class HiddenCliEvent:
    kind: str
    title: str
    detail: str


@dataclass
class ContextTrimResult:
    request_history: list[dict[str, Any]]
    dropped_turns: int
    dropped_messages: int
    original_tokens: int
    trimmed_tokens: int
