"""
Habits API — streak tracking for recurring tasks.
Exposes habit summaries and manually marks a habit completed for a given date.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from datetime import date, datetime, timezone
from src.models.user import UserClaims
from src.models.task import HabitSummary
from src.repositories.task_repo import TaskRepository
from src.api.middleware import get_current_active_user
import structlog

log = structlog.get_logger()

router = APIRouter(prefix="/habits", tags=["Habits"])
task_repo = TaskRepository()


def _doc_to_summary(doc: dict) -> HabitSummary:
    return HabitSummary(
        recurring_id=doc["recurring_id"],
        title=doc["title"],
        frequency=doc.get("frequency", "daily"),
        priority=doc.get("priority", "P3"),
        is_active=doc.get("is_active", True),
        current_streak=doc.get("current_streak", 0),
        longest_streak=doc.get("longest_streak", 0),
        total_completions=doc.get("total_completions", 0),
        last_completed_date=doc.get("last_completed_date"),
        completion_history=doc.get("completion_history", []),
        completion_rate_30d=doc.get("completion_rate_30d", 0.0),
    )


@router.get("", response_model=list[HabitSummary])
async def list_habits(
    current_user: UserClaims = Depends(get_current_active_user),
) -> list[HabitSummary]:
    """Return all recurring tasks with their habit/streak data."""
    docs = await task_repo.get_habit_summaries(current_user.user_id)
    return [_doc_to_summary(d) for d in docs]


@router.get("/{recurring_id}", response_model=HabitSummary)
async def get_habit(
    recurring_id: str,
    current_user: UserClaims = Depends(get_current_active_user),
) -> HabitSummary:
    """Get streak data for a single habit."""
    doc = await task_repo.get_habit_summary(current_user.user_id, recurring_id)
    if not doc:
        raise HTTPException(404, "Habit not found")
    return _doc_to_summary(doc)


class CheckInRequest(BaseModel):
    completed_date: Optional[str] = None   # "YYYY-MM-DD", defaults to today


@router.post("/{recurring_id}/checkin", response_model=HabitSummary)
async def habit_checkin(
    recurring_id: str,
    body: CheckInRequest = CheckInRequest(),
    current_user: UserClaims = Depends(get_current_active_user),
) -> HabitSummary:
    """
    Manually mark a habit as completed for a given date.
    Also used internally when a recurring task instance is completed via PATCH /tasks/{id}.
    """
    completed_date = body.completed_date or date.today().isoformat()

    streak = await task_repo.record_habit_completion(
        recurring_id=recurring_id,
        user_id=current_user.user_id,
        completed_date=completed_date,
    )
    if not streak:
        raise HTTPException(404, "Habit (recurring task) not found")

    doc = await task_repo.get_habit_summary(current_user.user_id, recurring_id)
    return _doc_to_summary(doc)
