from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from datetime import date, timedelta, datetime, timezone

from src.models.user import UserClaims
from src.repositories.task_repo import TaskRepository
from src.api.middleware import get_current_active_user
from src.analytics.workload_forecaster import (
    TaskFeatures,
    WorkloadForecast,
    build_forecast,
    FORECAST_DAYS,
)
import structlog

log = structlog.get_logger()

router = APIRouter(prefix="/forecast", tags=["Forecast"])
task_repo = TaskRepository()


class DayForecastResponse(BaseModel):
    date:            str
    load_score:      float
    capacity:        float
    overloaded:      bool
    utilisation_pct: int
    task_count:      int
    suggested_moves: list[dict]


class ForecastResponse(BaseModel):
    user_id:                str
    generated_at:           str
    personal_capacity:      float
    overloaded_days:        int
    peak_load_date:         Optional[str]
    risk_score:             int
    risk_label:             str   # "Low" | "Medium" | "High" | "Critical"
    completion_rate_trend:  str
    reschedule_suggestions: list[dict]
    day_forecasts:          list[DayForecastResponse]
    # Chart data
    dates:                  list[str]
    load_scores:            list[float]
    capacity_line:          list[float]
    # Summary stats
    open_task_count:        int
    overdue_count:          int
    p0_p1_count:            int



def _risk_label(score: int) -> str:
    if score < 25: return "Low"
    if score < 50: return "Medium"
    if score < 75: return "High"
    return "Critical"


async def _gather_completion_history(user_id: str, days: int = 30) -> list[float]:
    """
    Build a list of daily completion counts from the past `days` days.
    Uses task updated_at + status=completed as a proxy for completion date.
    Returns oldest-first list suitable for EWMA warm-up.
    """
    today = date.today()
    bucket: dict[str, int] = {}

    # Initialise all days to 0
    for i in range(days):
        bucket[(today - timedelta(days=days - i - 1)).isoformat()] = 0

    # Query completed tasks from the last N days
    from src.models.task import TaskFilter, TaskStatus
    filters = TaskFilter(status=TaskStatus.COMPLETED, limit=500)
    completed_tasks = await task_repo.list_tasks(user_id, filters)

    for task in completed_tasks:
        ts = task.updated_at
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        day_str = ts.date().isoformat()
        if day_str in bucket:
            bucket[day_str] += 1

    return [float(bucket[k]) for k in sorted(bucket)]


@router.get("", response_model=ForecastResponse)
async def get_workload_forecast(
    current_user: UserClaims = Depends(get_current_active_user),
) -> ForecastResponse:
    """
    14-day workload forecast for the authenticated user.

    Algorithm:
    - EWMA on 30 days of completion history → personal daily capacity
    - Weighted load matrix (priority × urgency decay) across open tasks
    - DP rescheduling for overloaded days
    - Composite risk score (0-100)

    No LLM is invoked. Runs in < 50ms.
    """
    user_id = current_user.user_id
    log.info("workload_forecast_start", user_id=user_id)

    # 1. Fetch open tasks
    from src.models.task import TaskFilter, TaskStatus
    open_filters = TaskFilter(limit=500)
    all_tasks = await task_repo.list_tasks(user_id, open_filters)

    open_tasks = [t for t in all_tasks if t.status not in ("completed", "cancelled")]
    today = date.today()

    # 2. Convert to TaskFeatures
    features = [
        TaskFeatures(
            task_id=t.task_id,
            title=t.title,
            priority=t.priority.value,
            status=t.status.value,
            due_date=t.due_date.date() if t.due_date else None,
            created_at=t.created_at.date() if t.created_at else today,
            tags=t.tags,
        )
        for t in all_tasks
    ]

    # 3. Fetch completion history for EWMA
    completion_history = await _gather_completion_history(user_id, days=30)

    # 4. Run the ML/DP forecaster
    forecast: WorkloadForecast = build_forecast(
        tasks=features,
        completed_per_day_history=completion_history,
        user_id=user_id,
    )

    # 5. Count overdue and high-priority
    overdue = sum(
        1 for t in open_tasks
        if t.due_date and t.due_date.date() < today
    )
    p0p1 = sum(1 for t in open_tasks if t.priority.value in ("P0", "P1"))

    log.info("workload_forecast_complete",
             user_id=user_id,
             risk_score=forecast.risk_score,
             overloaded_days=forecast.overloaded_days,
             suggestions=len(forecast.reschedule_suggestions))

    return ForecastResponse(
        user_id=user_id,
        generated_at=forecast.generated_at.isoformat(),
        personal_capacity=forecast.personal_capacity,
        overloaded_days=forecast.overloaded_days,
        peak_load_date=forecast.peak_load_date,
        risk_score=forecast.risk_score,
        risk_label=_risk_label(forecast.risk_score),
        completion_rate_trend=forecast.completion_rate_trend,
        reschedule_suggestions=forecast.reschedule_suggestions,
        day_forecasts=[
            DayForecastResponse(
                date=d.date.isoformat(),
                load_score=d.load_score,
                capacity=d.capacity,
                overloaded=d.overloaded,
                utilisation_pct=d.utilisation_pct,
                task_count=len(d.task_ids),
                suggested_moves=d.suggested_moves,
            )
            for d in forecast.forecast_days
        ],
        dates=forecast.dates,
        load_scores=forecast.load_scores,
        capacity_line=forecast.capacity_line,
        open_task_count=len(open_tasks),
        overdue_count=overdue,
        p0_p1_count=p0p1,
    )


@router.get("/explain", tags=["Forecast"])
async def explain_forecast_model(
    current_user: UserClaims = Depends(get_current_active_user),
) -> dict:
    """Returns a plain-English explanation of how the forecast was computed."""
    return {
        "algorithm": "EWMA + Dynamic Programming",
        "steps": [
            "1. Reads your last 30 days of task completions from MongoDB.",
            "2. Fits an Exponential Weighted Moving Average (α=0.3) to learn your personal "
               "daily completion rate — no LLM, just math.",
            "3. Converts your completion rate to load-unit capacity (1 task ≈ 2 load units at P2).",
            "4. Builds a 14-day load matrix: each open task spreads its weight across its remaining "
               "days (triangular distribution, peak at due date). Priority weights: P0=8, P1=4, P2=2, P3=1.",
            "5. Flags days where projected load > 120% of your personal capacity.",
            "6. Runs a DP rescheduling pass: for each overloaded day, the lowest-priority tasks "
               "are moved to the nearest day with spare capacity (forward-first, up to 7 days; "
               "backward fallback up to 3 days).",
            "7. Computes a 0–100 risk score from: peak load severity (60%), overloaded-day "
               "fraction (30%), overdue penalty (10%).",
        ],
        "no_llm": True,
        "latency_target": "< 50ms",
    }
