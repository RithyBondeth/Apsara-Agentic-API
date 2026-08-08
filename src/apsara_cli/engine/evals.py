"""Deterministic regression scoring for recorded agent runs."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class EvalResult:
    name: str
    passed: bool
    checks: list[str]


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
