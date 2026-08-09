"""Read-only, Git-aware workspace change summaries for the CLI."""

from __future__ import annotations

import subprocess
from pathlib import Path


def _git(workspace: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(workspace), *args],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )


def workspace_diff(workspace: Path) -> str:
    """Return status plus staged and unstaged patches without mutating Git."""
    probe = _git(workspace, "rev-parse", "--is-inside-work-tree")
    if probe.returncode != 0 or probe.stdout.strip() != "true":
        return "This workspace is not a Git repository. Automatic snapshots are still available with /checkpoints."

    status = _git(workspace, "status", "--short", "--untracked-files=all")
    staged = _git(workspace, "diff", "--cached", "--no-ext-diff", "--")
    unstaged = _git(workspace, "diff", "--no-ext-diff", "--")
    failed = next((result for result in (status, staged, unstaged) if result.returncode), None)
    if failed is not None:
        return f"Error reading Git changes: {(failed.stderr or failed.stdout).strip()}"

    sections: list[str] = []
    if status.stdout.strip():
        sections.append("STATUS\n" + status.stdout.rstrip())
    if staged.stdout.strip():
        sections.append("STAGED\n" + staged.stdout.rstrip())
    if unstaged.stdout.strip():
        sections.append("UNSTAGED\n" + unstaged.stdout.rstrip())
    return "\n\n".join(sections) if sections else "Workspace is clean — no staged, unstaged, or untracked changes."
