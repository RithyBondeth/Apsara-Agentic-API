"""Deterministic run regression and optional live coding benchmarks."""

import asyncio
import hashlib
import json
import re
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from apsara_cli.engine.usage import add_usage, normalize_usage


@dataclass
class EvalResult:
    name: str
    passed: bool
    checks: list[str]


@dataclass
class BenchmarkResult:
    name: str
    language: str
    passed: bool
    score: int
    checks: list[str]
    details: dict[str, Any]


def evaluate_run(name: str, state: dict[str, Any], events: list[dict[str, Any]], expect: dict[str, Any]) -> EvalResult:
    tools = [event.get("name") for event in events if event.get("type") == "tool_result"]
    checks = []
    if "state" in expect:
        checks.append(f"state={state.get('state')} expected={expect['state']}")
    if "tools" in expect:
        missing = sorted(set(expect["tools"]) - set(tools))
        checks.append("tools present" if not missing else f"missing tools: {', '.join(missing)}")
    if "max_tool_calls" in expect:
        checks.append(f"tool_calls={len(tools)} max={expect['max_tool_calls']}")
    passed = (
        ("state" not in expect or state.get("state") == expect["state"])
        and ("tools" not in expect or set(expect["tools"]).issubset(tools))
        and ("max_tool_calls" not in expect or len(tools) <= int(expect["max_tool_calls"]))
    )
    return EvalResult(name, passed, checks)


def run_suite(suite_path: Path, workspace: Path) -> list[EvalResult]:
    suite = json.loads(suite_path.read_text(encoding="utf-8"))
    results = []
    for case in suite.get("cases", []):
        run_id = case["run_id"]
        root = workspace / ".apsara" / "runs" / run_id
        state = json.loads((root / "state.json").read_text(encoding="utf-8"))
        events = [json.loads(line) for line in (root / "events.jsonl").read_text(encoding="utf-8").splitlines() if line]
        results.append(evaluate_run(case.get("name", run_id), state, events, case.get("expect", {})))
    return results


def is_benchmark_suite(suite_path: Path) -> bool:
    payload = json.loads(suite_path.read_text(encoding="utf-8"))
    return payload.get("kind") == "coding-benchmark"


def _hashes(root: Path) -> dict[str, str]:
    ignored = {".git", ".apsara", ".apsara-cli", "node_modules", "target", "__pycache__"}
    result: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file() or any(part in ignored for part in path.relative_to(root).parts):
            continue
        result[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def _changed_files(before: dict[str, str], after: dict[str, str]) -> list[str]:
    return sorted(path for path in set(before) | set(after) if before.get(path) != after.get(path))


def _matches_any(path: str, patterns: list[str]) -> bool:
    return any(Path(path).match(pattern) for pattern in patterns)


def score_benchmark_case(case: dict[str, Any], details: dict[str, Any]) -> BenchmarkResult:
    """Score stored benchmark evidence without making a provider request."""
    checks: list[str] = []
    score = 0
    state_ok = details.get("agent_state") == "completed"
    score += 15 if state_ok else 0
    checks.append(f"agent state: {details.get('agent_state', 'unknown')}")

    verification = details.get("verification") or []
    verification_ok = bool(verification) and all(item.get("status") == "passed" for item in verification)
    score += 50 if verification_ok else 0
    checks.append("verification passed" if verification_ok else "verification failed or unavailable")
    baseline_valid = bool(details.get("baseline_failed", True))
    checks.append("fixture failed before agent" if baseline_valid else "invalid fixture: baseline already passed")

    changed = [str(path) for path in details.get("changed_files") or []]
    allowed = [str(pattern) for pattern in case.get("allowed_changes") or []]
    unexpected = [path for path in changed if allowed and not _matches_any(path, allowed)]
    change_ok = bool(changed) and not unexpected
    score += 15 if change_ok else 0
    checks.append(
        f"changes constrained ({len(changed)} file(s))"
        if change_ok else f"unexpected or missing changes: {', '.join(unexpected) or 'none recorded'}"
    )

    tool_calls = int(details.get("tool_calls") or 0)
    max_tools = int(case.get("max_tool_calls") or 25)
    tools_ok = tool_calls <= max_tools
    score += 10 if tools_ok else 0
    checks.append(f"tool calls: {tool_calls}/{max_tools}")

    usage = normalize_usage(details.get("usage") or {})
    max_tokens = int(case.get("max_tokens") or 100_000)
    tokens_ok = usage["total_tokens"] <= max_tokens
    score += 10 if tokens_ok else 0
    checks.append(f"tokens: {usage['total_tokens']}/{max_tokens}")

    passed = baseline_valid and verification_ok and change_ok and score >= int(case.get("pass_score") or 80)
    return BenchmarkResult(
        name=str(case.get("name") or "unnamed"),
        language=str(case.get("language") or "unknown"),
        passed=passed,
        score=score,
        checks=checks,
        details=details,
    )


def score_benchmark_results(suite_path: Path, results_path: Path) -> list[BenchmarkResult]:
    suite = json.loads(suite_path.read_text(encoding="utf-8"))
    evidence = json.loads(results_path.read_text(encoding="utf-8"))
    by_name = {str(item.get("name")): item for item in evidence.get("cases", [])}
    results: list[BenchmarkResult] = []
    for case in suite.get("cases", []):
        details = by_name.get(str(case.get("name")), {"agent_state": "missing", "verification": []})
        results.append(score_benchmark_case(case, details))
    return results


def _verification_command(raw: Any) -> list[str]:
    if isinstance(raw, list) and all(isinstance(item, str) for item in raw):
        return raw
    if isinstance(raw, str):
        return shlex.split(raw)
    raise ValueError("Verification commands must be a string or string array")


async def _run_verification_commands(
    commands: list[list[str]], workspace: Path, timeout: int
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for command in commands:
        executable = shutil.which(command[0]) if command else None
        if not command or not executable:
            results.append({"command": command, "status": "unavailable", "returncode": None})
            continue
        try:
            completed = await asyncio.to_thread(
                subprocess.run,
                command,
                cwd=workspace,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            results.append({
                "command": command,
                "status": "timeout",
                "returncode": None,
                "output": str(exc),
            })
            continue
        results.append({
            "command": command,
            "status": "passed" if completed.returncode == 0 else "failed",
            "returncode": completed.returncode,
            "output": (completed.stdout + completed.stderr)[-4000:],
        })
    return results


async def run_benchmark_suite(
    suite_path: Path,
    output_root: Path,
    model: str,
) -> tuple[list[BenchmarkResult], Path]:
    """Run live model benchmarks in disposable fixture copies and save evidence."""
    from apsara_cli.engine.executor import run_agent_stream
    from apsara_cli.engine.tools import agent_runtime_context

    suite_path = suite_path.resolve()
    suite = json.loads(suite_path.read_text(encoding="utf-8"))
    run_label = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:6]
    run_root = output_root.resolve() / run_label
    run_root.mkdir(parents=True, exist_ok=False)
    evidence_cases: list[dict[str, Any]] = []
    scored: list[BenchmarkResult] = []

    for case in suite.get("cases", []):
        name = str(case["name"])
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", name) or name in {".", ".."}:
            raise ValueError(f"Unsafe benchmark case name: {name!r}")
        fixture = (suite_path.parent / str(case["fixture"])).resolve()
        fixture.relative_to(suite_path.parent.resolve())
        if not fixture.is_dir():
            raise FileNotFoundError(f"Benchmark fixture does not exist: {fixture}")
        for candidate in fixture.rglob("*"):
            if candidate.is_symlink():
                candidate.resolve().relative_to(fixture)
        workspace = run_root / name
        shutil.copytree(fixture, workspace)
        commands = [_verification_command(item) for item in case.get("verify", [])]
        verify_timeout = int(case.get("verify_timeout") or 120)
        baseline_verification = await _run_verification_commands(commands, workspace, verify_timeout)
        # Baseline test commands may create harmless lockfiles or caches. Treat
        # that post-verification repository as the state the agent received.
        before = _hashes(workspace)
        allowed_commands = {command[0] for command in commands if command}
        events: list[dict[str, Any]] = []
        aggregate_usage: dict[str, Any] = {}

        with agent_runtime_context(
            workspace_root=workspace,
            enable_bash=bool(commands),
            allowed_commands=allowed_commands,
            confirmation_callback=lambda _action, _payload: True,
            trust_callback=lambda _action, _payload: True,
        ):
            async for raw_event in run_agent_stream(
                [{"role": "user", "content": str(case["instruction"])}], model=model
            ):
                event = json.loads(raw_event)
                events.append(event)
                if event.get("type") == "usage" and isinstance(event.get("data"), dict):
                    add_usage(aggregate_usage, event["data"])

        verification = await _run_verification_commands(commands, workspace, verify_timeout)

        after = _hashes(workspace)
        terminal_states = [event.get("state") for event in events if event.get("type") == "run_state"]
        if any(event.get("type") == "error" for event in events):
            agent_state = "failed"
        elif any(event.get("type") == "blocked" for event in events):
            agent_state = "blocked"
        else:
            agent_state = str(terminal_states[-1] if terminal_states else "unknown")
        details = {
            "name": name,
            "language": case.get("language"),
            "agent_state": agent_state,
            "changed_files": _changed_files(before, after),
            "tool_calls": sum(1 for event in events if event.get("type") == "tool_call"),
            "usage": normalize_usage(aggregate_usage),
            "verification": verification,
            "baseline_verification": baseline_verification,
            "baseline_failed": any(item.get("status") == "failed" for item in baseline_verification),
            "event_count": len(events),
        }
        evidence_cases.append(details)
        scored.append(score_benchmark_case(case, details))
        (workspace / ".apsara" / "benchmark-events.json").parent.mkdir(parents=True, exist_ok=True)
        (workspace / ".apsara" / "benchmark-events.json").write_text(
            json.dumps(events, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    results_path = run_root / "results.json"
    results_path.write_text(json.dumps({
        "suite": suite.get("name"),
        "model": model,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "cases": evidence_cases,
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    return scored, results_path
