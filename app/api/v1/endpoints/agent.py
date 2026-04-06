import json
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel
from uuid import UUID

from app.api.deps import get_db
from app.models.conversation import ConversationModel, MessageModel
from app.models.usage import UsageModel
from app.services.agent.executor import run_agent_stream

router = APIRouter()

class AgentRequest(BaseModel):
    instruction: str

def get_conversation_history(db: Session, conversation_id: UUID) -> list:
    """Fetch previous conversation turns seamlessly from DB and convert to LLM standard map."""
    past_messages = db.query(MessageModel).filter(
        MessageModel.conversation_id == conversation_id
    ).order_by(MessageModel.created_at.asc()).all()
    
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

@router.post("/{conversation_id}/run")
async def execute_agent_for_conversation(
    conversation_id: UUID,
    request: AgentRequest,
    db: Session = Depends(get_db)
):
    # 1. Validate constraints
    convo = db.query(ConversationModel).filter(ConversationModel.id == conversation_id).first()
    if not convo:
        raise HTTPException(status_code=404, detail="Conversation not found")

    user_id = convo.user_id
    project_id = convo.project_id

    # 2. Extract Instruction
    # Check if this instruction is already in DB, skip if re-run, otherwise append:
    user_msg = MessageModel(
        conversation_id=conversation_id,
        role="user",
        content=request.instruction
    )
    db.add(user_msg)
    db.commit()

    # 3. Pull contextual memory (Codebase RAG memory)
    history = get_conversation_history(db, conversation_id)

    # 4. Stream generation via Server-Sent Events natively to UI
    async def event_generator():
        async for chunk_str in run_agent_stream(history):
            # Send immediate feed down to client UI
            yield f"data: {chunk_str}\n\n"
            
            # Inline extraction of token analytics strictly recording billing to PostgreSQL
            try:
                chunk = json.loads(chunk_str)
                if chunk.get("type") == "usage":
                    usage_data = chunk.get("data", {})
                    if "total_tokens" in usage_data:
                        usage_row = UsageModel(
                            user_id=user_id,
                            project_id=project_id,
                            conversation_id=conversation_id,
                            tokens_used=usage_data["total_tokens"],
                            model="gpt-4o"
                        )
                        db.add(usage_row)
                        db.commit()
            except Exception:
                pass

    return StreamingResponse(event_generator(), media_type="text/event-stream")
