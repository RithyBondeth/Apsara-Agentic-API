from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from uuid import UUID

from app.api.deps import get_db
from app.models.conversation import ConversationModel, MessageModel
from app.services.agent.executor import run_agent

router = APIRouter()

class AgentRequest(BaseModel):
    instruction: str

@router.post("/{conversation_id}/run")
async def execute_agent_for_conversation(
    conversation_id: UUID,
    request: AgentRequest,
    db: Session = Depends(get_db)
):
    # 1. Validate conversation exists
    convo = db.query(ConversationModel).filter(ConversationModel.id == conversation_id).first()
    if not convo:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # 2. Add user instruction to DB
    user_msg = MessageModel(
        conversation_id=conversation_id,
        role="user",
        content=request.instruction
    )
    db.add(user_msg)
    db.commit()

    # 3. Call Agent
    # Currently run_agent only takes the immediate instruction,
    # but in a complete setup we would load historical messages here.
    new_messages = await run_agent(request.instruction)

    # 4. Save new messages (assistant and tools) to DB
    # We skip the first 2 messages because they are the System Prompt and User Prompt
    for msg in new_messages[2:]:
        role = msg["role"]
        content = msg.get("content", "")
        # Extract tool calls or results manually referencing the schemas
        tool_data = None
        if "tool_calls" in msg:
            tool_data = {"tool_calls": msg["tool_calls"]}
        elif "tool_call_id" in msg:
            tool_data = {
                "tool_call_id": msg["tool_call_id"],
                "name": msg.get("name")
            }

        db_msg = MessageModel(
            conversation_id=conversation_id,
            role=role,
            content=content,
            tool_data=tool_data
        )
        db.add(db_msg)
    
    db.commit()

    return {"status": "success", "new_messages": new_messages[2:]}
