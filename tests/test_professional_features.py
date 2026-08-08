import asyncio
import json
import os
import sys
import time
from pathlib import Path

from apsara_cli.engine.evals import evaluate_run
from apsara_cli.engine.intelligence import find_symbol, repository_map
from apsara_cli.engine.memory import add_memory, read_memory
from apsara_cli.engine.processes import ProcessManager
from apsara_cli.engine.reports import render_run_report
from apsara_cli.engine.tools import (
    agent_runtime_context,
    execute_tool_async,
    mcp_manager_context,
    parallel_read_files,
)


def test_repository_intelligence_is_multilanguage(tmp_path: Path):
    (tmp_path / "app.py").write_text("class PythonThing:\n    pass\n", encoding="utf-8")
    (tmp_path / "web.ts").write_text("export function webThing() {}\n", encoding="utf-8")
    repo = repository_map(tmp_path)
    assert "PythonThing" in repo and "webThing" in repo
    assert "web.ts:1: webThing" in find_symbol(tmp_path, "web")


def test_memory_round_trip(tmp_path: Path):
    add_memory(tmp_path, "Use pytest for verification")
    assert "Use pytest" in read_memory(tmp_path)


def test_process_manager_captures_output(tmp_path: Path):
    manager = ProcessManager()
    item = manager.start(f'"{sys.executable}" -c "print(123)"', tmp_path)
    item.process.wait(timeout=5)
    # Reader completion can trail process exit very briefly; joining stdout by
    # consuming it is handled by the manager's daemon collector.
    for _ in range(1000):
        if item.output:
            break
        time.sleep(0.001)
    assert "123" in "\n".join(item.output)
    assert item.status == "exited(0)"


def test_process_manager_stops_process_group(tmp_path: Path):
    if os.name == "nt":
        return
    child_pid_file = tmp_path / "child.pid"
    manager = ProcessManager()
    item = manager.start(
        f"sh -c 'sleep 60 & echo $! > {child_pid_file.name}; wait'",
        tmp_path,
    )
    for _ in range(500):
        if child_pid_file.exists():
            break
        time.sleep(0.01)
    assert child_pid_file.exists()
    child_pid = int(child_pid_file.read_text().strip())

    manager.stop(item.process_id)
    for _ in range(500):
        try:
            os.kill(child_pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.01)
    else:
        raise AssertionError(f"child process {child_pid} survived process-group stop")


def test_parallel_reads_keep_runtime_workspace(tmp_path: Path):
    (tmp_path / "inside.txt").write_text("correct workspace", encoding="utf-8")
    with agent_runtime_context(workspace_root=tmp_path, max_file_size_bytes=8):
        result = parallel_read_files(["inside.txt", "../outside.txt"])

    assert "exceeds 8 bytes" in result
    assert "outside the configured workspace root" in result


def test_eval_and_report():
    state = {"run_id": "abc", "state": "completed", "model": "m", "objective": "fix", "steps": []}
    events = [{"type": "tool_result", "name": "read_file"}]
    result = evaluate_run("smoke", state, events, {"state": "completed", "tools": ["read_file"]})
    assert result.passed
    assert "# Apsara run abc" in render_run_report(state)


def test_mcp_write_requires_approval_and_read_does_not(tmp_path: Path):
    class Manager:
        def has_tool(self, name):
            return True

        async def call(self, name, arguments):
            return "called"

    approvals = []

    def confirm(action, payload):
        approvals.append((action, payload))
        return False

    async def run():
        with mcp_manager_context(Manager()), agent_runtime_context(workspace_root=tmp_path, confirmation_callback=confirm):
            read = await execute_tool_async("mcp__x__list_items", {})
            write = await execute_tool_async("mcp__x__create_item", {"name": "x"})
        return read, write

    read, write = asyncio.run(run())
    assert read == "called"
    assert "not approved" in write
    assert approvals[0][0] == "mcp_tool_call"
