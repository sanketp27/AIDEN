"""
Chat API endpoint with AIDEN Core orchestrator integration
Powered by Google ADK with intelligent agent routing
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from src.models.user import UserClaims
from src.api.middleware import get_current_active_user
from src.core.runner import run_agent
import structlog

log = structlog.get_logger()

router = APIRouter(prefix="/chat", tags=["Chat"])


# Request/Response models
class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None


class ChatResponse(BaseModel):
    response: str
    session_id: str
    agents_used: list[str] = []
    success: bool = True


@router.post("", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    current_user: UserClaims = Depends(get_current_active_user)
) -> ChatResponse:
    """
    Send message to AIDEN Core orchestrator

    AIDEN intelligently routes your request to specialized agents:
    - TaskMaster: For task management
    - CalendarBot: For calendar operations
    - NoteKeeper: For notes and semantic search

    The orchestrator can coordinate multiple agents for complex workflows
    like meeting preparation or task scheduling.
    """
    log.info("chat_request",
            user_id=current_user.user_id,
            message_length=len(request.message),
            session_id=request.session_id)

    # Execute AIDEN Core with ADK Runner
    result = await run_agent(
        user_id=current_user.user_id,
        message=request.message,
        session_id=request.session_id
    )

    return ChatResponse(
        response=result["response"],
        session_id=result["session_id"],
        agents_used=result.get("agents_used", []),
        success=result.get("success", True)
    )
