from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from datetime import datetime

from src.models.user import UserClaims
from src.api.middleware import get_current_active_user
from src.core.session import session_service
from src.core.config import settings
from motor.motor_asyncio import AsyncIOMotorClient
import structlog

log = structlog.get_logger()
router = APIRouter(prefix="/sessions", tags=["Sessions"])


class SessionSummary(BaseModel):
    session_id:       str
    app_name:         str
    source:           str           # "chat" | "telegram" | "voice"
    message_count:    int
    last_update:      str           # ISO datetime
    last_message_preview: Optional[str] = None


class SessionDetail(BaseModel):
    session_id:   str
    app_name:     str
    source:       str
    messages:     list[dict]
    state:        dict
    last_update:  str


def _source_from_session(doc: dict) -> str:
    """Infer session source from stored metadata or state."""
    state = doc.get("state", {})
    if state.get("source") == "telegram":
        return "telegram"
    if state.get("source") == "voice":
        return "voice"
    # Check events for author hints
    events = doc.get("events", [])
    for e in events:
        if "voice" in str(e).lower():
            return "voice"
    return "chat"


def _last_preview(events: list) -> Optional[str]:
    """Extract text preview from the last user/agent event."""
    for ev in reversed(events):
        content = ev.get("content") or {}
        parts = content.get("parts") or []
        for part in parts:
            if isinstance(part, dict) and part.get("text"):
                text = part["text"]
                return text[:80] + "…" if len(text) > 80 else text
    return None


@router.get("", response_model=list[SessionSummary])
async def list_sessions(
    limit: int = 20,
    source: Optional[str] = None,   # filter by "chat"|"telegram"|"voice"
    current_user: UserClaims = Depends(get_current_active_user),
) -> list[SessionSummary]:
    """
    List all conversation sessions for the current user.
    Includes sessions from web chat, Telegram bot, and voice interface.
    All sessions are stored in MongoDB `adk_sessions`.
    """
    db  = AsyncIOMotorClient(settings.MONGO_URI)[settings.MONGO_DB]
    col = db["adk_sessions"]

    query: dict = {"user_id": current_user.user_id}
    cursor = col.find(
        query,
        {"session_id": 1, "app_name": 1, "state": 1,
         "events": 1, "last_update_time": 1, "_id": 0}
    ).sort("last_update_time", -1).limit(limit)

    summaries = []
    async for doc in cursor:
        src = _source_from_session(doc)
        if source and src != source:
            continue

        ts = doc.get("last_update_time", 0)
        try:
            dt = datetime.fromtimestamp(float(ts)).isoformat()
        except Exception:
            dt = ""

        summaries.append(SessionSummary(
            session_id=doc["session_id"],
            app_name=doc.get("app_name", "aiden"),
            source=src,
            message_count=len(doc.get("events", [])),
            last_update=dt,
            last_message_preview=_last_preview(doc.get("events", [])),
        ))

    log.info("sessions_listed", user_id=current_user.user_id, count=len(summaries))
    return summaries


@router.get("/{session_id}", response_model=SessionDetail)
async def get_session(
    session_id: str,
    current_user: UserClaims = Depends(get_current_active_user),
) -> SessionDetail:
    """Get full detail of a single session including all messages."""
    db  = AsyncIOMotorClient(settings.MONGO_URI)[settings.MONGO_DB]
    doc = await db["adk_sessions"].find_one({
        "session_id": session_id,
        "user_id": current_user.user_id,
    })
    if not doc:
        raise HTTPException(404, "Session not found")
    doc.pop("_id", None)

    ts = doc.get("last_update_time", 0)
    try:
        dt = datetime.fromtimestamp(float(ts)).isoformat()
    except Exception:
        dt = ""

    return SessionDetail(
        session_id=doc["session_id"],
        app_name=doc.get("app_name", "aiden"),
        source=_source_from_session(doc),
        messages=doc.get("events", []),
        state=doc.get("state", {}),
        last_update=dt,
    )


@router.delete("/{session_id}", status_code=204)
async def delete_session(
    session_id: str,
    current_user: UserClaims = Depends(get_current_active_user),
) -> None:
    """Delete a session and its full message history."""
    await session_service.delete_session(
        app_name="aiden",
        user_id=current_user.user_id,
        session_id=session_id,
    )
    return None
