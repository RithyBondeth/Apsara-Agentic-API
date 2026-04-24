import json
from typing import Any, Optional
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel
from uuid import UUID

from app.api.deps import get_current_user, get_db
from app.models.conversation import ConversationModel, MessageModel
from app.models.usage import UsageModel
from app.models.user import UserModel
from app.services.agent.executor import run_agent_stream

router = APIRouter()


class AgentRequest(BaseModel):
    instruction: str
    model: str = "gpt-4o"


def get_conversation_history(db: Session, conversation_id: UUID) -> list:
    """Fetch previous conversation turns seamlessly from DB and convert to LLM standard map."""
    past_messages = db.query(MessageModel).filter(
        MessageModel.conversation_id == conversation_id
    ).order_by(MessageModel.created_at.asc(), MessageModel.id.asc()).all()

    history = []
    for msg in past_messages:
        # Ignore raw system prompts if they were logged, else format normal
        if msg.role not in ["user", "assistant", "tool"]:
            continue

        payload = {"role": msg.role, "content": msg.content}
        if msg.tool_data:
            if msg.role == "assistant" and "tool_calls" in msg.tool_data:
                payload["tool_calls"] = msg.tool_data["tool_calls"]
            elif msg.role == "tool" and "tool_call_id" in msg.tool_data:
                payload["tool_call_id"] = msg.tool_data["tool_call_id"]
                payload["name"] = msg.tool_data.get("name", "")
        history.append(payload)
    return history


def persist_message(
    db: Session,
    conversation_id: UUID,
    role: str,
    content: Optional[str] = None,
    tool_data: Optional[dict[str, Any]] = None,
) -> None:
    message = MessageModel(
        conversation_id=conversation_id,
        role=role,
        content=content,
        tool_data=tool_data,
    )
    db.add(message)
    db.commit()


@router.post("/{conversation_id}/run")
async def execute_agent_for_conversation(
    conversation_id: UUID,
    request: AgentRequest,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
):
    # 1. Validate constraints
    convo = (
        db.query(ConversationModel)
        .filter(
            ConversationModel.id == conversation_id,
            ConversationModel.user_id == current_user.id,
        )
        .first()
    )
    if not convo:
        raise HTTPException(status_code=404, detail="Conversation not found")

    user_id = convo.user_id
    project_id = convo.project_id

    # 2. Extract Instruction
    persist_message(
        db=db,
        conversation_id=conversation_id,
        role="user",
        content=request.instruction,
    )

    # 3. Pull contextual memory (Codebase RAG memory)
    history = get_conversation_history(db, conversation_id)

    # 4. Stream generation via Server-Sent Events natively to UI
    async def event_generator():
        try:
            async for chunk_str in run_agent_stream(history, model=request.model):
                # Send immediate feed down to client UI
                yield f"data: {chunk_str}\n\n"

                # Inline extraction of token analytics strictly recording billing to PostgreSQL
                try:
                    chunk = json.loads(chunk_str)
                    chunk_type = chunk.get("type")

                    if chunk_type == "assistant_dispatch":
                        persist_message(
                            db=db,
                            conversation_id=conversation_id,
                            role="assistant",
                            content=chunk.get("content"),
                            tool_data={"tool_calls": chunk.get("tool_calls", [])},
                        )
                    elif chunk_type == "tool_result":
                        persist_message(
                            db=db,
                            conversation_id=conversation_id,
                            role="tool",
                            content=chunk.get("result"),
                            tool_data={
                                "tool_call_id": chunk.get("tool_call_id"),
                                "name": chunk.get("name", ""),
                            },
                        )
                    elif chunk_type == "final_answer":
                        persist_message(
                            db=db,
                            conversation_id=conversation_id,
                            role="assistant",
                            content=chunk.get("content"),
                        )
                    elif chunk_type == "usage":
                        usage_data = chunk.get("data", {})
                        if "total_tokens" in usage_data:
                            usage_row = UsageModel(
                                user_id=user_id,
                                project_id=project_id,
                                conversation_id=conversation_id,
                                tokens_used=usage_data["total_tokens"],
                                model=request.model,
                            )
                            db.add(usage_row)
                            db.commit()
                except Exception:
                    db.rollback()
        except Exception as exc:
            error_event = json.dumps({"type": "error", "message": f"Stream failed: {exc}"})
            yield f"data: {error_event}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
