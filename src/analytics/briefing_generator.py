from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Optional
from dataclasses import dataclass, field
import structlog

log = structlog.get_logger()

COLL_BRIEFINGS = "daily_briefings"


@dataclass
class BriefingTask:
    task_id:   str
    title:     str
    priority:  str
    status:    str
    due_date:  Optional[str]
    tags:      list[str]
    is_overdue: bool


@dataclass
class HabitStatus:
    recurring_id: str
    title:        str
    current_streak: int
    checked_today:  bool


@dataclass
class DailyBriefing:
    user_id:          str
    date:             str            # YYYY-MM-DD
    generated_at:     str            # ISO datetime
    is_read:          bool = False

    # Content sections
    overdue_tasks:     list[BriefingTask] = field(default_factory=list)
    due_today:         list[BriefingTask] = field(default_factory=list)
    high_priority:     list[BriefingTask] = field(default_factory=list)
    suggested_focus:   list[BriefingTask] = field(default_factory=list)
    habit_statuses:    list[HabitStatus]  = field(default_factory=list)

    # Summary metrics
    total_open:        int = 0
    total_overdue:     int = 0
    p0_p1_count:       int = 0
    workload_risk:     int = 0          # 0-100 from forecaster
    risk_label:        str = "Low"
    completion_trend:  str = "stable"

    # Greeting line (deterministic, no LLM)
    greeting:          str = ""
    focus_tip:         str = ""

    def to_dict(self) -> dict:
        return {
            "user_id":         self.user_id,
            "date":            self.date,
            "generated_at":    self.generated_at,
            "is_read":         self.is_read,
            "overdue_tasks":   [vars(t) for t in self.overdue_tasks],
            "due_today":       [vars(t) for t in self.due_today],
            "high_priority":   [vars(t) for t in self.high_priority],
            "suggested_focus": [vars(t) for t in self.suggested_focus],
            "habit_statuses":  [vars(h) for h in self.habit_statuses],
            "total_open":      self.total_open,
            "total_overdue":   self.total_overdue,
            "p0_p1_count":     self.p0_p1_count,
            "workload_risk":   self.workload_risk,
            "risk_label":      self.risk_label,
            "completion_trend": self.completion_trend,
            "greeting":        self.greeting,
            "focus_tip":       self.focus_tip,
        }


def _risk_label(score: int) -> str:
    if score < 25: return "Low"
    if score < 50: return "Medium"
    if score < 75: return "High"
    return "Critical"


def _greeting(today: date, open_count: int, overdue_count: int, risk: int) -> str:
    """Deterministic greeting — no LLM. Varies by day of week + workload state."""
    greetings = {
        0: "Good morning. New week, fresh start.",
        1: "Tuesday. Let's keep the momentum going.",
        2: "Midweek check-in.",
        3: "Thursday — the finish line is close.",
        4: "Friday. Time to close out the week.",
        5: "Saturday. Take it easy if you can.",
        6: "Sunday. A good day to plan the week ahead.",
    }
    base = greetings[today.weekday()]
    if overdue_count > 0:
        return f"{base} You have {overdue_count} overdue task{'s' if overdue_count > 1 else ''} — let's clear those first."
    if open_count == 0:
        return f"{base} Your task list is clear — well done."
    if risk >= 75:
        return f"{base} Your workload is critical today. Focus on P0/P1 tasks only."
    return f"{base} You have {open_count} open tasks. Here's your plan."


def _focus_tip(risk: int, overdue: int, p0p1: int) -> str:
    """Rule-based focus tip — no LLM."""
    if overdue > 3:
        return "Tip: Resolve overdue tasks before taking on new work."
    if p0p1 >= 5:
        return "Tip: You have many high-priority items — batch similar tasks to reduce context switching."
    if risk >= 75:
        return "Tip: Consider delegating or deferring P2/P3 tasks to reduce today's load."
    if risk < 25:
        return "Tip: Light day — good time to tackle that long-deferred note or documentation task."
    return "Tip: Work your highest-priority tasks first, before checking messages."


async def generate_briefing(
    user_id: str,
    task_repo,
    today: Optional[date] = None,
) -> DailyBriefing:
    """
    Build today's briefing from DB data.
    Called by the scheduler every morning OR on-demand via GET /briefing/today.
    """
    from src.models.task import TaskFilter, TaskStatus, Priority
    from src.analytics.workload_forecaster import (
        TaskFeatures, build_forecast, FORECAST_DAYS
    )

    if today is None:
        today = date.today()
    today_str = today.isoformat()
    tomorrow = today + timedelta(days=1)
    week_out = today + timedelta(days=7)

    all_open = await task_repo.list_tasks(
        user_id,
        TaskFilter(limit=500),
    )
    open_tasks = [t for t in all_open if t.status not in ("completed", "cancelled")]

    def _to_bt(t) -> BriefingTask:
        dd = t.due_date.date() if t.due_date else None
        return BriefingTask(
            task_id=t.task_id,
            title=t.title,
            priority=t.priority.value,
            status=t.status.value,
            due_date=dd.isoformat() if dd else None,
            tags=t.tags,
            is_overdue=bool(dd and dd < today),
        )

    overdue    = [_to_bt(t) for t in open_tasks if t.due_date and t.due_date.date() < today]
    due_today  = [_to_bt(t) for t in open_tasks if t.due_date and today <= t.due_date.date() < tomorrow]
    high_pri   = [_to_bt(t) for t in open_tasks
                  if t.priority.value in ("P0", "P1")
                  and (not t.due_date or today <= t.due_date.date() <= week_out)
                  and (not t.due_date or t.due_date.date() >= today)]

    # Sort all lists by priority
    priority_order = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
    for lst in (overdue, due_today, high_pri):
        lst.sort(key=lambda t: priority_order.get(t.priority, 9))

    features = [
        TaskFeatures(
            task_id=t.task_id, title=t.title, priority=t.priority.value,
            status=t.status.value,
            due_date=t.due_date.date() if t.due_date else None,
            created_at=t.created_at.date() if t.created_at else today,
            tags=t.tags,
        )
        for t in open_tasks
    ]

    scored = sorted(
        [(f.urgency(today), f) for f in features],
        key=lambda x: x[0], reverse=True
    )
    focus_ids = {f.task_id for _, f in scored[:3]}
    suggested = [_to_bt(t) for t in open_tasks if t.task_id in focus_ids]

    from src.api.routers.forecast import _gather_completion_history, _risk_label as rl
    history = await _gather_completion_history(user_id, days=30)
    forecast = build_forecast(features, history, user_id, today=today)
    risk = forecast.risk_score
    trend = forecast.completion_rate_trend

    habit_docs = await task_repo.get_habit_summaries(user_id)
    habits = [
        HabitStatus(
            recurring_id=h["recurring_id"],
            title=h["title"],
            current_streak=h.get("current_streak", 0),
            checked_today=h.get("last_completed_date") == today_str,
        )
        for h in habit_docs if h.get("is_active", True)
    ]

    p0p1 = sum(1 for t in open_tasks if t.priority.value in ("P0", "P1"))

    briefing = DailyBriefing(
        user_id=user_id,
        date=today_str,
        generated_at=datetime.now(timezone.utc).isoformat(),
        overdue_tasks=overdue,
        due_today=due_today,
        high_priority=high_pri[:10],
        suggested_focus=suggested,
        habit_statuses=habits,
        total_open=len(open_tasks),
        total_overdue=len(overdue),
        p0_p1_count=p0p1,
        workload_risk=risk,
        risk_label=rl(risk),
        completion_trend=trend,
        greeting=_greeting(today, len(open_tasks), len(overdue), risk),
        focus_tip=_focus_tip(risk, len(overdue), p0p1),
    )

    log.info("briefing_generated", user_id=user_id, date=today_str,
             overdue=len(overdue), due_today=len(due_today), risk=risk)
    return briefing
