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
from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
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


MAX_FILE_SIZE_MB = 20
MAX_FILE_BYTES   = MAX_FILE_SIZE_MB * 1024 * 1024

ALLOWED_MIMES = {
    # Images
    "image/jpeg", "image/png", "image/webp", "image/gif", "image/bmp",
    # Audio
    "audio/ogg", "audio/mpeg", "audio/mp3", "audio/wav", "audio/x-wav",
    "audio/m4a", "audio/mp4", "audio/webm", "audio/aac",
    # Documents
    "application/pdf",
    "text/plain", "text/csv", "text/markdown",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/octet-stream",  # allow unknown — file_processor handles gracefully
}


async def _upload_event_stream(
    file:         UploadFile,
    message:      str,
    user:         UserClaims,
    session_id:   str | None,
    http_request: Request,
) -> AsyncIterator[str]:
    file_bytes = await file.read()

    if len(file_bytes) > MAX_FILE_BYTES:
        yield _sse({"type": "error",
                    "detail": f"File too large. Max size is {MAX_FILE_SIZE_MB} MB."})
        return

    async for payload in aiden_runner.run_with_trace_multimodal(
        user_id    = user.user_id,
        message    = message or "",
        file_bytes = file_bytes,
        mime_type  = file.content_type or "application/octet-stream",
        filename   = file.filename or "upload",
        session_id = session_id or None,
    ):
        if await http_request.is_disconnected():
            log.info("upload_sse_client_disconnected", user_id=user.user_id)
            break
        yield _sse(payload)


@router.post("/upload")
async def chat_upload(
    http_request: Request,
    file:         UploadFile = File(...),
    message:      str        = Form(default=""),
    session_id:   str        = Form(default=""),
    current_user: UserClaims = Depends(get_current_active_user),
) -> StreamingResponse:
    """
    Multimodal SSE chat — accepts one file attachment plus an optional text message.

    Supported file types: JPEG, PNG, WEBP, GIF, BMP (images), OGG, MP3, WAV,
    M4A, WEBM (audio), PDF, TXT, CSV, DOCX, XLSX (documents).

    The file and message are sent together to the AIDEN orchestrator which
    automatically routes to the best agent (VisionAgent for images, VoiceAgent
    for audio, or orchestrator-level analysis for documents).

    Returns the same SSE event stream as /chat.
    """
    log.info("chat_upload_sse_start",
             user_id=current_user.user_id,
             filename=file.filename,
             content_type=file.content_type,
             message_length=len(message))

    return StreamingResponse(
        _upload_event_stream(file, message, current_user,
                             session_id or None, http_request),
        media_type="text/event-stream",
        headers={
            "Cache-Control":     "no-cache",
            "X-Accel-Buffering": "no",
            "Connection":        "keep-alive",
        },
    )


@router.post("/upload/sync")
async def chat_upload_sync(
    file:         UploadFile = File(...),
    message:      str        = Form(default=""),
    session_id:   str        = Form(default=""),
    current_user: UserClaims = Depends(get_current_active_user),
) -> dict:
    """
    Non-streaming multimodal chat — used by Telegram bot and programmatic clients.
    Returns the final response dict directly.
    """
    file_bytes = await file.read()
    if len(file_bytes) > MAX_FILE_BYTES:
        return {"success": False, "error": f"File too large. Max size is {MAX_FILE_SIZE_MB} MB."}

    log.info("chat_upload_sync_start",
             user_id=current_user.user_id,
             filename=file.filename,
             content_type=file.content_type)

    return await aiden_runner.run_agent_multimodal(
        user_id    = current_user.user_id,
        message    = message or "",
        file_bytes = file_bytes,
        mime_type  = file.content_type or "application/octet-stream",
        filename   = file.filename or "upload",
        session_id = session_id or None,
    )
