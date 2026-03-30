"""
Task data models for AIDEN v2.0
Includes recurring task support.
"""
from pydantic import BaseModel, Field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional
import uuid


class Priority(str, Enum):
    P0 = "P0"  # Critical
    P1 = "P1"  # High
    P2 = "P2"  # Medium
    P3 = "P3"  # Low (default)


class TaskStatus(str, Enum):
    TODO       = "todo"
    IN_PROGRESS = "in_progress"
    COMPLETED  = "completed"
    CANCELLED  = "cancelled"


class RecurrenceFrequency(str, Enum):
    DAILY    = "daily"
    WEEKLY   = "weekly"
    MONTHLY  = "monthly"
    WEEKDAYS = "weekdays"   # Mon-Fri
    WEEKENDS = "weekends"   # Sat-Sun


class RecurringRule(BaseModel):
    """Recurrence configuration embedded in a task template."""
    frequency: RecurrenceFrequency
    interval: int = 1                        # every N units (e.g. every 2 weeks)
    days_of_week: Optional[list[int]] = None # [0=Mon … 6=Sun]
    time_of_day: Optional[str] = None        # "HH:MM"
    end_date: Optional[datetime] = None      # stop creating after this date


class Task(BaseModel):
    """Full task record stored in MongoDB."""
    task_id:        str      = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id:        str
    title:          str
    description:    Optional[str] = None
    priority:       Priority = Priority.P3
    status:         TaskStatus = TaskStatus.TODO
    due_date:       Optional[datetime] = None
    tags:           list[str] = Field(default_factory=list)
    linked_event_id: Optional[str] = None
    recurring_id:   Optional[str] = None     # populated for instances of a recurring template
    created_at:     datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at:     datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Config:
        json_schema_extra = {
            "example": {
                "task_id": "550e8400-e29b-41d4-a716-446655440000",
                "user_id": "john",
                "title": "Review Q1 report",
                "priority": "P1",
                "status": "todo",
                "due_date": "2026-03-30T17:00:00Z",
                "tags": ["finance"],
            }
        }


class RecurringTask(BaseModel):
    """
    Recurring task template stored in the 'recurring_tasks' collection.
    A background scheduler reads these and creates Task instances on the correct days.
    Also tracks habit streaks — consecutive days on which the spawned task was completed.
    """
    recurring_id:        str      = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id:             str
    title:               str
    description:         Optional[str] = None
    priority:            Priority = Priority.P3
    tags:                list[str] = Field(default_factory=list)
    rule:                RecurringRule
    is_active:           bool = True
    last_created:        Optional[datetime] = None
    start_date:          datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    created_at:          datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # ── Streak / habit tracking ─────────────────────────────────────────────
    current_streak:      int = 0                    # consecutive completions right now
    longest_streak:      int = 0                    # all-time best
    total_completions:   int = 0                    # lifetime count
    last_completed_date: Optional[str] = None       # "YYYY-MM-DD" of most recent completion
    # Compact calendar: list of "YYYY-MM-DD" strings for every completed day (last 365)
    completion_history:  list[str] = Field(default_factory=list)


class TaskCreate(BaseModel):
    """Payload for POST /tasks."""
    title:       str
    description: Optional[str] = None
    priority:    Priority = Priority.P3
    due_date:    Optional[datetime] = None
    tags:        list[str] = Field(default_factory=list)
    # If provided, creates a recurring template instead of a one-off task
    recurring:   Optional[RecurringRule] = None


class TaskUpdate(BaseModel):
    """Payload for PATCH /tasks/{id}."""
    title:           Optional[str]        = None
    description:     Optional[str]        = None
    priority:        Optional[Priority]   = None
    status:          Optional[TaskStatus] = None
    due_date:        Optional[datetime]   = None
    tags:            Optional[list[str]]  = None
    linked_event_id: Optional[str]        = None


class TaskFilter(BaseModel):
    """Query parameters for listing tasks."""
    status:     Optional[TaskStatus] = None
    priority:   Optional[Priority]   = None
    due_before: Optional[datetime]   = None
    due_after:  Optional[datetime]   = None
    tags:       Optional[list[str]]  = None
    recurring:  Optional[bool]       = None   # True = only recurring instances
    limit:      int = 100
    offset:     int = 0


class StreakUpdate(BaseModel):
    """Internal payload for updating streak after a task completion."""
    completed_date: str   # "YYYY-MM-DD"
    recurring_id:   str
    user_id:        str


class HabitSummary(BaseModel):
    """API response model for a single habit's streak data."""
    recurring_id:        str
    title:               str
    frequency:           str
    priority:            str
    is_active:           bool
    current_streak:      int
    longest_streak:      int
    total_completions:   int
    last_completed_date: Optional[str]
    completion_history:  list[str]   # YYYY-MM-DD list (last 365 days)
    completion_rate_30d: float        # 0.0–1.0
