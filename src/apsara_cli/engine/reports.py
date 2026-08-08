"""Human-readable run reports generated from the durable journal."""

from pathlib import Path
from typing import Any

from apsara_cli.engine.runtime import latest_run


def render_run_report(run: dict[str, Any]) -> str:
    lines = [f"# Apsara run {run.get('run_id', '')}", "", f"- State: **{run.get('state', 'unknown')}**", f"- Model: `{run.get('model', '')}`", f"- Objective: {run.get('objective', '')}", "", "## Plan", ""]
    for step in run.get("steps", []):
        mark = "x" if step.get("status") == "completed" else " "
        lines.append(f"- [{mark}] {step.get('title', '')} — {step.get('status', 'pending')}")
    if run.get("changed_files"):
        lines.extend(["", "## Changed files", "", *[f"- `{p}`" for p in run["changed_files"]]])
    if run.get("verification"):
        lines.extend(["", "## Verification", "", *[f"- `{v}`" for v in run["verification"]]])
    if run.get("error"):
        lines.extend(["", "## Error", "", str(run["error"])])
    return "\n".join(lines) + "\n"


def export_latest_report(workspace: Path, destination: Path | None = None) -> Path:
    run = latest_run(workspace)
    if run is None:
        raise FileNotFoundError("No run journal is available")
    destination = destination or workspace / ".apsara" / "reports" / f"{run['run_id']}.md"
    if not destination.is_absolute():
        destination = workspace / destination
    destination.resolve().relative_to(workspace.resolve())
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(render_run_report(run), encoding="utf-8")
    return destination
