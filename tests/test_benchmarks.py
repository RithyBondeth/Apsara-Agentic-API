import json
import asyncio

import pytest

from apsara_cli.cli.parser import build_parser
from apsara_cli.engine.evals import (
    is_benchmark_suite,
    run_benchmark_suite,
    score_benchmark_case,
    score_benchmark_results,
)


def _case():
    return {
        "name": "python-fix",
        "language": "python",
        "allowed_changes": ["src/*.py"],
        "max_tool_calls": 10,
        "max_tokens": 1000,
        "pass_score": 80,
    }


def test_benchmark_score_requires_verification_and_constrained_changes():
    result = score_benchmark_case(_case(), {
        "agent_state": "completed",
        "verification": [{"status": "passed"}],
        "changed_files": ["src/calc.py"],
        "tool_calls": 4,
        "usage": {"prompt_tokens": 100, "completion_tokens": 50},
    })
    assert result.passed is True
    assert result.score == 100


def test_benchmark_score_detects_test_edit_and_failed_verification():
    result = score_benchmark_case(_case(), {
        "agent_state": "completed",
        "verification": [{"status": "failed"}],
        "changed_files": ["src/calc.py", "tests/test_calc.py"],
        "tool_calls": 11,
        "usage": {"total_tokens": 1200},
    })
    assert result.passed is False
    assert result.score == 15
    assert "tests/test_calc.py" in " ".join(result.checks)


def test_benchmark_cannot_pass_when_fixture_baseline_was_already_green():
    result = score_benchmark_case(_case(), {
        "agent_state": "completed",
        "baseline_failed": False,
        "verification": [{"status": "passed"}],
        "changed_files": ["src/calc.py"],
        "tool_calls": 2,
        "usage": {"total_tokens": 100},
    })
    assert result.score == 100
    assert result.passed is False
    assert "baseline already passed" in " ".join(result.checks)


def test_existing_evidence_can_be_rescored_without_api_calls(tmp_path):
    suite = tmp_path / "suite.json"
    suite.write_text(json.dumps({
        "kind": "coding-benchmark",
        "cases": [_case()],
    }), encoding="utf-8")
    evidence = tmp_path / "results.json"
    evidence.write_text(json.dumps({"cases": [{
        "name": "python-fix",
        "agent_state": "completed",
        "verification": [{"status": "passed"}],
        "changed_files": ["src/calc.py"],
        "tool_calls": 3,
        "usage": {"total_tokens": 200},
    }]}), encoding="utf-8")

    assert is_benchmark_suite(suite) is True
    results = score_benchmark_results(suite, evidence)
    assert len(results) == 1 and results[0].passed


def test_live_benchmark_rejects_case_name_path_traversal(tmp_path):
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    (fixture / "file.py").write_text("x = 1\n", encoding="utf-8")
    suite = tmp_path / "suite.json"
    suite.write_text(json.dumps({
        "kind": "coding-benchmark",
        "cases": [{
            "name": "../escape",
            "language": "python",
            "fixture": "fixture",
            "instruction": "do nothing",
            "verify": [],
        }],
    }), encoding="utf-8")

    with pytest.raises(ValueError, match="Unsafe benchmark case name"):
        asyncio.run(run_benchmark_suite(suite, tmp_path / "output", "test/model"))


def test_eval_cli_accepts_live_and_offline_benchmark_modes():
    parser = build_parser()
    live = parser.parse_args(["eval", "suite.json", "--live", "--model", "model/id"])
    offline = parser.parse_args(["eval", "suite.json", "--results", "results.json"])
    assert live.live is True and live.model == "model/id"
    assert offline.results == "results.json" and offline.live is False
