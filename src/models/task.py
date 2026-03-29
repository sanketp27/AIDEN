"""
Task data models for AIDEN v2.0
"""
from pydantic import BaseModel, Field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional
import uuid


class Priority(str, Enum):
    """Task priority levels"""
    P0 = "P0"  # Critical
    P1 = "P1"  # High
    P2 = "P2"  # Medium
    P3 = "P3"  # Low (default)


class TaskStatus(str, Enum):
    """Task status"""
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class Task(BaseModel):
    """Task model with full fields"""
    task_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str
    title: str
    description: Optional[str] = None
    priority: Priority = Priority.P3
    status: TaskStatus = TaskStatus.TODO
    due_date: Optional[datetime] = None
    tags: list[str] = Field(default_factory=list)
    linked_event_id: Optional[str] = None  # Link to calendar event
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Config:
        json_schema_extra = {
            "example": {
                "task_id": "550e8400-e29b-41d4-a716-446655440000",
                "user_id": "user123",
                "title": "Review Q1 report",
                "description": "Complete review of Q1 financial report",
                "priority": "P1",
                "status": "todo",
                "due_date": "2026-03-30T17:00:00Z",
                "tags": ["finance", "quarterly"],
                "linked_event_id": None
            }
        }


class TaskCreate(BaseModel):
    """Model for creating a new task"""
    title: str
    description: Optional[str] = None
    priority: Priority = Priority.P3
    due_date: Optional[datetime] = None
    tags: list[str] = Field(default_factory=list)


class TaskUpdate(BaseModel):
    """Model for updating a task"""
    title: Optional[str] = None
    description: Optional[str] = None
    priority: Optional[Priority] = None
    status: Optional[TaskStatus] = None
    due_date: Optional[datetime] = None
    tags: Optional[list[str]] = None
    linked_event_id: Optional[str] = None


class TaskFilter(BaseModel):
    """Model for filtering tasks"""
    status: Optional[TaskStatus] = None
    priority: Optional[Priority] = None
    due_before: Optional[datetime] = None
    due_after: Optional[datetime] = None
    tags: Optional[list[str]] = None
    limit: int = 100
    offset: int = 0
