"""Independent, read-only review pass for plans, patches, and verification."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any


def _safe_review_paths(workspace: Path, paths: list[str] | None) -> list[str]:
    safe: list[str] = []
    for raw in paths or []:
        candidate = (workspace / raw).resolve(strict=False)
        try:
            relative = candidate.relative_to(workspace.resolve())
        except ValueError:
            continue
        value = str(relative)
        if value and value != "." and value not in safe:
            safe.append(value)
    return safe


def _untracked_context(workspace: Path, paths: list[str]) -> str:
    command = ["git", "ls-files", "--others", "--exclude-standard", "-z"]
    if paths:
        command.extend(["--", *paths])
    try:
        result = subprocess.run(
            command,
            cwd=workspace,
            capture_output=True,
            timeout=15,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return ""
    sections: list[str] = []
    remaining = 12_000
    for raw in result.stdout.split(b"\0"):
        if not raw or remaining <= 0:
            continue
        relative = Path(raw.decode("utf-8", errors="surrogateescape"))
        candidate = (workspace / relative).resolve(strict=False)
        try:
            candidate.relative_to(workspace.resolve())
        except ValueError:
            continue
        if candidate.is_symlink() or not candidate.is_file():
            continue
        try:
            content = candidate.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        excerpt = content[:remaining]
        sections.append(f"NEW FILE {relative}:\n{excerpt}")
        remaining -= len(excerpt)
    return "\n\n".join(sections)


def _read_only_context(workspace: Path, changed_files: list[str] | None = None) -> str:
    paths = _safe_review_paths(workspace, changed_files)
    path_suffix = ["--", *paths] if paths else []
    sections: list[str] = []
    for command, label in (
        (["git", "status", "--short", *path_suffix], "STATUS"),
        (["git", "diff", "--stat", *path_suffix], "DIFF STAT"),
        (["git", "diff", *path_suffix], "DIFF"),
    ):
        try:
            result = subprocess.run(
                command,
                cwd=workspace,
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
        text = (result.stdout + result.stderr).strip()
        if text:
            sections.append(f"{label}:\n{text[-12000:]}")
    untracked = _untracked_context(workspace, paths)
    if untracked:
        sections.append(f"UNTRACKED CONTENT:\n{untracked}")
    return "\n\n".join(sections) or "No Git diff is available."


def _message_content(message: Any) -> str:
    if isinstance(message, dict):
        if message.get("error"):
            return f"Error: Critic unavailable: {message['error']}"
        return str(message.get("content") or "")
    return str(getattr(message, "content", "") or "")


async def request_critique(
    workspace: Path,
    *,
    objective: str,
    focus: str,
    model: str,
    changed_files: list[str] | None = None,
) -> tuple[str, dict[str, Any]]:
    from apsara_cli.engine.llm import call_llm

    prompt = (
        "You are Apsara's independent read-only coding critic. You cannot call tools or modify files. "
        "Find concrete correctness, security, maintainability, and test-coverage risks. "
        "Prioritize blockers, cite file paths from the supplied diff, and say APPROVED when there are no material issues.\n\n"
        f"OBJECTIVE:\n{objective}\n\nFOCUS:\n{focus or 'Final implementation review'}\n\n"
        f"WORKSPACE EVIDENCE:\n{_read_only_context(workspace, changed_files)}"
    )
    message, usage = await call_llm(
        [{"role": "user", "content": prompt}], model=model, with_tools=False
    )
    content = _message_content(message).strip()
    return content or "Error: Critic returned no review.", dict(usage or {})
