import json

from apsara_cli.engine.runtime import RunJournal, latest_run
from apsara_cli.shared.types import AgentRun, AgentRunState, ToolResult


def test_tool_result_adapts_legacy_text():
    assert ToolResult.from_text("done").ok is True
    failed = ToolResult.from_text("Error: broken")
    assert failed.ok is False
    assert failed.to_text() == "Error: broken"


def test_run_journal_persists_state_and_events(tmp_path):
    run = AgentRun(objective="fix bug", model="test/model", workspace=str(tmp_path))
    journal = RunJournal(tmp_path, run)
    index = journal.add_step("inspect", "Inspect project")
    journal.update_step(index, "in_progress")
    journal.tool_result("read_file", ToolResult(ok=True, content="ok"), {"path": "a.py"})
    journal.transition(AgentRunState.COMPLETED)

    state = latest_run(tmp_path)
    assert state is not None
    assert state["run_id"] == run.run_id
    assert state["state"] == "completed"
    assert state["steps"][0]["status"] == "in_progress"

    events = [json.loads(line) for line in journal.events_path.read_text().splitlines()]
    assert {event["type"] for event in events} >= {
        "step_added", "step_updated", "tool_result", "state"
    }


def test_run_journal_redacts_secrets_and_omits_tool_content(tmp_path):
    secret = "sk-super-secret-value-123456"
    run = AgentRun(
        objective=f"debug with OPENAI_API_KEY={secret}",
        model="test/model",
        workspace=str(tmp_path),
    )
    journal = RunJournal(tmp_path, run)
    journal.tool_result(
        "write_to_file",
        ToolResult(ok=True, content=f"source contains {secret}"),
        {"path": "app.py", "content": f"password={secret}"},
    )

    persisted = journal.state_path.read_text() + journal.events_path.read_text()
    assert secret not in persisted
    assert "source contains" not in persisted
    assert "password=" not in persisted
    assert "[REDACTED]" in persisted
    assert "[OMITTED" in persisted
