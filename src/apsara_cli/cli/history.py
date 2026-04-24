from typing import Any

from apsara_cli.shared.types import ContextTrimResult

SAFE_INPUT_TOKEN_BUDGET = 9_000


def group_conversation_turns(history: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    turns: list[list[dict[str, Any]]] = []
    current_turn: list[dict[str, Any]] = []

    for message in history:
        if message.get("role") == "user":
            if current_turn:
                turns.append(current_turn)
            current_turn = [message]
        elif current_turn:
            current_turn.append(message)
        else:
            current_turn = [message]

    if current_turn:
        turns.append(current_turn)

    return turns


def flatten_conversation_turns(turns: list[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    return [message for turn in turns for message in turn]


def trim_history_for_request(history: list[dict[str, Any]], model: str) -> ContextTrimResult:
    from apsara_cli.engine.executor import SYSTEM_PROMPT
    from apsara_cli.engine.llm import estimate_request_tokens

    base_messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    original_tokens = estimate_request_tokens(base_messages + history, model=model)

    if original_tokens <= SAFE_INPUT_TOKEN_BUDGET:
        return ContextTrimResult(
            request_history=history,
            dropped_turns=0,
            dropped_messages=0,
            original_tokens=original_tokens,
            trimmed_tokens=original_tokens,
        )

    turns = group_conversation_turns(history)
    if not turns:
        return ContextTrimResult(
            request_history=history,
            dropped_turns=0,
            dropped_messages=0,
            original_tokens=original_tokens,
            trimmed_tokens=original_tokens,
        )

    kept_turns: list[list[dict[str, Any]]] = []
    for turn in reversed(turns):
        candidate_turns = [turn] + kept_turns
        candidate_history = flatten_conversation_turns(candidate_turns)
        candidate_tokens = estimate_request_tokens(base_messages + candidate_history, model=model)
        if kept_turns and candidate_tokens > SAFE_INPUT_TOKEN_BUDGET:
            break
        kept_turns = candidate_turns

    trimmed_history = flatten_conversation_turns(kept_turns)
    trimmed_tokens = estimate_request_tokens(base_messages + trimmed_history, model=model)
    return ContextTrimResult(
        request_history=trimmed_history,
        dropped_turns=max(len(turns) - len(kept_turns), 0),
        dropped_messages=max(len(history) - len(trimmed_history), 0),
        original_tokens=original_tokens,
        trimmed_tokens=trimmed_tokens,
    )


def update_history_from_event(history: list[dict[str, Any]], event: dict[str, Any]) -> None:
    event_type = event.get("type")

    if event_type == "assistant_dispatch":
        history.append({
            "role": "assistant",
            "content": event.get("content"),
            "tool_calls": event.get("tool_calls", []),
        })
    elif event_type == "tool_result":
        history.append({
            "role": "tool",
            "content": event.get("result"),
            "tool_call_id": event.get("tool_call_id"),
            "name": event.get("name", ""),
        })
    elif event_type == "final_answer":
        history.append({
            "role": "assistant",
            "content": event.get("content"),
        })
