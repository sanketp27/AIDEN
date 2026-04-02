from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from typing import Optional
from datetime import date, datetime, timezone

from src.models.user import UserClaims
from src.repositories.task_repo import TaskRepository
from src.api.middleware import get_current_active_user
from src.analytics.briefing_generator import (
    DailyBriefing, generate_briefing, COLL_BRIEFINGS
)
from motor.motor_asyncio import AsyncIOMotorClient
from src.core.config import settings
import structlog

log = structlog.get_logger()

router = APIRouter(prefix="/briefing", tags=["Briefing"])
task_repo = TaskRepository()


def _db():
    return AsyncIOMotorClient(settings.MONGO_URI)[settings.MONGO_DB]

class BriefingResponse(BaseModel):
    user_id:          str
    date:             str
    generated_at:     str
    is_read:          bool
    greeting:         str
    focus_tip:        str
    total_open:       int
    total_overdue:    int
    p0_p1_count:      int
    workload_risk:    int
    risk_label:       str
    completion_trend: str
    overdue_tasks:    list[dict]
    due_today:        list[dict]
    high_priority:    list[dict]
    suggested_focus:  list[dict]
    habit_statuses:   list[dict]


def _to_response(b: dict) -> BriefingResponse:
    return BriefingResponse(**{
        k: b.get(k, [] if k.endswith('tasks') or k.endswith('priority')
                        or k.endswith('focus') or k.endswith('statuses') else
                   0 if k in ('total_open','total_overdue','p0_p1_count','workload_risk') else
                   False if k == 'is_read' else '')
        for k in BriefingResponse.model_fields
    })


@router.get("/today", response_model=BriefingResponse)
async def get_today_briefing(
    refresh: bool = False,
    current_user: UserClaims = Depends(get_current_active_user),
) -> BriefingResponse:
    """
    Get today's briefing. Generated fresh on first call of the day,
    cached in MongoDB after that. Pass ?refresh=true to force regeneration.
    """
    today = date.today().isoformat()
    db = _db()
    col = db[COLL_BRIEFINGS]

    # Try cache first
    if not refresh:
        cached = await col.find_one({
            "user_id": current_user.user_id,
            "date": today,
        })
        if cached:
            cached.pop("_id", None)
            log.info("briefing_cache_hit", user_id=current_user.user_id)
            return _to_response(cached)

    # Generate fresh
    briefing = await generate_briefing(
        user_id=current_user.user_id,
        task_repo=task_repo,
    )
    doc = briefing.to_dict()

    # Upsert into MongoDB
    await col.update_one(
        {"user_id": current_user.user_id, "date": today},
        {"$set": doc},
        upsert=True,
    )

    return _to_response(doc)


@router.post("/today/read")
async def mark_briefing_read(
    current_user: UserClaims = Depends(get_current_active_user),
) -> dict:
    """Mark today's briefing as read."""
    today = date.today().isoformat()
    db = _db()
    await db[COLL_BRIEFINGS].update_one(
        {"user_id": current_user.user_id, "date": today},
        {"$set": {"is_read": True}},
    )
    return {"status": "ok"}


@router.get("/history", response_model=list[dict])
async def get_briefing_history(
    limit: int = 7,
    current_user: UserClaims = Depends(get_current_active_user),
) -> list[dict]:
    """Return the last N briefings (date + risk_score only — for history view)."""
    db = _db()
    cursor = db[COLL_BRIEFINGS].find(
        {"user_id": current_user.user_id},
        {"date": 1, "risk_label": 1, "workload_risk": 1, "total_open": 1,
         "total_overdue": 1, "is_read": 1, "_id": 0},
    ).sort("date", -1).limit(limit)

    results = []
    async for doc in cursor:
        results.append(doc)
    return results
