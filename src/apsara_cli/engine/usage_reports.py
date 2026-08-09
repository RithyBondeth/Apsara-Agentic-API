"""Local-only usage aggregation over saved Apsara sessions."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from apsara_cli.cli.session import list_sessions
from apsara_cli.engine.usage import add_usage, normalize_usage


def workspace_usage(workspace: Path) -> dict[str, Any]:
    aggregate: dict[str, Any] = {}
    models: dict[str, dict[str, Any]] = {}
    sessions: list[dict[str, Any]] = []
    for path in list_sessions(workspace):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        usage = payload.get("usage")
        if not isinstance(usage, dict):
            continue
        normalized = normalize_usage(usage)
        add_usage(aggregate, normalized)
        raw_models = usage.get("model_usage")
        if isinstance(raw_models, dict):
            for model, tokens in raw_models.items():
                if isinstance(tokens, dict):
                    add_usage(models.setdefault(str(model), {}), tokens)
        sessions.append({
            "name": payload.get("session_name") or path.stem,
            "model": payload.get("model") or "unknown",
            "updated_at": payload.get("updated_at") or "",
            **normalized,
        })
    sessions.sort(key=lambda item: str(item["updated_at"]), reverse=True)
    return {**normalize_usage(aggregate), "models": models, "sessions": sessions}


def format_usage_report(workspace: Path, current: dict[str, Any]) -> str:
    current_usage = normalize_usage(current)
    report = workspace_usage(workspace)
    lines = [
        "LOCAL USAGE · PROVIDER-REPORTED",
        (
            f"Current session  {current_usage['total_tokens']:,} tokens "
            f"(in {current_usage['prompt_tokens']:,} · out {current_usage['completion_tokens']:,})"
        ),
        (
            f"Saved sessions   {report['total_tokens']:,} tokens across "
            f"{len(report['sessions'])} session(s)"
        ),
    ]
    if current_usage["estimated_input_tokens"]:
        lines.append(
            f"Unreported calls {current_usage['unreported_calls']:,} call(s), "
            f"~{current_usage['estimated_input_tokens']:,} locally estimated input tokens"
        )
    if current_usage["interrupted_calls"]:
        lines.append(f"Interrupted      {current_usage['interrupted_calls']:,} call(s)")
    if current_usage["auxiliary_calls"]:
        lines.append(f"Auxiliary        {current_usage['auxiliary_calls']:,} summarization call(s)")
    if report["models"]:
        lines.append("")
        lines.append("BY MODEL")
        for model, tokens in sorted(
            report["models"].items(),
            key=lambda item: int(item[1].get("total_tokens") or 0),
            reverse=True,
        ):
            normalized = normalize_usage(tokens)
            lines.append(
                f"{model}  {normalized['total_tokens']:,} "
                f"(in {normalized['prompt_tokens']:,} · out {normalized['completion_tokens']:,})"
            )
    if report["sessions"]:
        lines.append("")
        lines.append("RECENT SESSIONS")
        for item in report["sessions"][:5]:
            updated = str(item["updated_at"])[:10] or "unknown date"
            lines.append(f"{item['name']}  {item['total_tokens']:,} · {item['model']} · {updated}")
    lines.extend([
        "",
        "Provider-reported totals are local telemetry, not a billing ledger or enforceable quota.",
        "Stored locally under .apsara-cli/sessions; no usage data is uploaded by Apsara.",
        "The provider dashboard remains authoritative.",
    ])
    return "\n".join(lines)
