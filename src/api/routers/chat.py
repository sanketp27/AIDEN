"""
Chat API — SSE streaming with real-time agent trace
====================================================
The /chat endpoint is now a Server-Sent Events stream.
Each turn emits:

  data: {"type":"trace_step",   "step":{...}}     ← one per agent event
  data: {"type":"agent_active", "agent":"...", ...} ← current agent label
  data: {"type":"done",         "response":"...", "trace":{...}}
  data: {"type":"error",        "detail":"..."}

The /chat/history endpoint returns stored traces from MongoDB.

Legacy /chat/sync (non-streaming) is kept for programmatic clients.
"""
from __future__ import annotations

import asyncio
import json
from typing import AsyncIterator

import structlog
from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from src.api.middleware import get_current_active_user
from src.core.config import settings
from src.core.runner import aiden_runner, run_agent
from src.core.tracer import COLL_TRACES
from src.models.user import UserClaims

log = structlog.get_logger()
router = APIRouter(prefix="/chat", tags=["Chat"])

class ChatRequest(BaseModel):
    message:    str
    session_id: str | None = None


class ChatSyncResponse(BaseModel):
    """Returned by /chat/sync — legacy non-streaming path."""
    response:    str
    session_id:  str
    agents_used: list[str] = []
    success:     bool = True

def _sse(payload: dict) -> str:
    """Encode a dict as a single SSE data line."""
    return f"data: {json.dumps(payload, default=str)}\n\n"


async def _chat_event_stream(
    request: ChatRequest,
    user: UserClaims,
    http_request: Request,
) -> AsyncIterator[str]:
    """
    Core generator: runs the AIDEN orchestrator and yields SSE strings.

    The generator monitors `http_request.is_disconnected()` so it stops
    producing events if the browser tab is closed mid-stream.
    """
    async for payload in aiden_runner.run_with_trace(
        user_id=user.user_id,
        message=request.message,
        session_id=request.session_id,
    ):
        # Stop streaming if the client disconnected
        if await http_request.is_disconnected():
            log.info("sse_client_disconnected", user_id=user.user_id)
            break
        yield _sse(payload)


@router.post("")
async def chat(
    request:      ChatRequest,
    http_request: Request,
    current_user: UserClaims = Depends(get_current_active_user),
) -> StreamingResponse:
    """
    SSE chat endpoint.

    Returns a `text/event-stream` response.  Each SSE event is a JSON
    object; the frontend accumulates trace_step events and renders the
    trace panel when it receives the final `done` event.
    """
    log.info(
        "chat_sse_start",
        user_id=current_user.user_id,
        message_length=len(request.message),
        session_id=request.session_id,
    )

    return StreamingResponse(
        _chat_event_stream(request, current_user, http_request),
        media_type="text/event-stream",
        headers={
            # Keep the connection alive through proxies / load balancers
            "Cache-Control":  "no-cache",
            "X-Accel-Buffering": "no",           # Nginx: disable proxy buffering
            "Connection":    "keep-alive",
        },
    )


@router.post("/sync", response_model=ChatSyncResponse)
async def chat_sync(
    request:      ChatRequest,
    current_user: UserClaims = Depends(get_current_active_user),
) -> ChatSyncResponse:
    """
    Non-streaming chat — for programmatic / API clients.
    Returns the final response only (no trace steps).
    """
    result = await run_agent(
        user_id=current_user.user_id,
        message=request.message,
        session_id=request.session_id,
    )
    return ChatSyncResponse(
        response=result["response"],
        session_id=result["session_id"],
        agents_used=result.get("agents_used", []),
        success=result.get("success", True),
    )


@router.get("/history")
async def get_trace_history(
    limit:        int  = 20,
    current_user: UserClaims = Depends(get_current_active_user),
) -> list[dict]:
    """
    Return the last N agent traces for the current user.
    Used by the Workflow History tab in the UI.
    """
    try:
        from motor.motor_asyncio import AsyncIOMotorClient
        col = AsyncIOMotorClient(settings.MONGO_URI)[settings.MONGO_DB][COLL_TRACES]
        docs = await col.find(
            {"user_id": current_user.user_id},
            {"_id": 0},
        ).sort("started_at", -1).limit(limit).to_list(limit)
        return docs
    except Exception as exc:
        log.warning("trace_history_failed", error=str(exc))
        return []
