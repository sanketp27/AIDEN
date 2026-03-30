"""
Task management tools for ADK agents.
user_id is NEVER passed by the LLM — it is injected automatically from
ToolContext (which reads the ADK session's user_id set by the Runner).
This guarantees tasks are always saved under the authenticated user.
"""
from google.adk.tools import ToolContext
from src.repositories.task_repo import TaskRepository
from src.models.task import Task, Priority, TaskStatus, RecurringTask, RecurringRule, RecurrenceFrequency
from datetime import datetime, timezone
from typing import Optional
import structlog

log = structlog.get_logger()

task_repo = TaskRepository()


def _get_user_id(tool_context: ToolContext) -> str:
    """Extract user_id from ADK ToolContext — always returns the authenticated user."""
    return tool_context.user_id


async def create_task(
    title: str,
    tool_context: ToolContext,
    description: str = None,
    priority: str = "P3",
    due_date: str = None,
    tags: list[str] = None,
    recurring: str = None,   # "daily"|"weekly"|"weekdays"|"weekends"|"monthly" or None
) -> dict:
    """
    Create a new task for the authenticated user.

    Args:
        title: Task title (required)
        description: Optional detail
        priority: P0=Critical, P1=High, P2=Medium, P3=Low
        due_date: ISO date string YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS
        tags: List of categorisation tags
        recurring: Recurrence frequency. If set, creates a daily/weekly/etc recurring task.

    Returns:
        Created task info with task_id
    """
    user_id = _get_user_id(tool_context)
    tags = tags or []

    # Parse due_date
    due_date_obj = None
    if due_date:
        try:
            due_date_obj = datetime.fromisoformat(due_date.replace('Z', '+00:00'))
        except ValueError:
            log.warning("invalid_due_date", due_date=due_date)

    # Handle recurring tasks
    if recurring:
        try:
            freq = RecurrenceFrequency(recurring.lower())
        except ValueError:
            freq = RecurrenceFrequency.DAILY

        rt = RecurringTask(
            user_id=user_id,
            title=title,
            description=description,
            priority=Priority(priority),
            tags=tags + ["recurring"],
            rule=RecurringRule(frequency=freq),
            start_date=datetime.now(timezone.utc),
        )
        doc = await task_repo.create_recurring(rt)

        # Also create today's instance immediately
        today_task = Task(
            user_id=user_id,
            title=title,
            description=description,
            priority=Priority(priority),
            due_date=due_date_obj or datetime.now(timezone.utc).replace(
                hour=23, minute=59, second=0, microsecond=0
            ),
            tags=tags + ["recurring"],
            recurring_id=rt.recurring_id,
        )
        await task_repo.create_task(today_task)
        await task_repo.mark_recurring_created(rt.recurring_id)

        log.info("recurring_task_created_via_tool",
                 recurring_id=rt.recurring_id, user_id=user_id, title=title, freq=freq)
        return {
            "task_id": today_task.task_id,
            "recurring_id": rt.recurring_id,
            "title": title,
            "priority": priority,
            "status": "todo",
            "recurring": recurring,
            "message": f"Recurring task '{title}' created — repeats {freq.value}. Today's instance is in your task list. ✓"
        }

    # One-off task
    task = Task(
        user_id=user_id,
        title=title,
        description=description,
        priority=Priority(priority),
        due_date=due_date_obj,
        tags=tags,
    )
    result = await task_repo.create_task(task)
    log.info("task_created_via_tool", task_id=task.task_id, user_id=user_id, title=title)
    return {
        "task_id": result["task_id"],
        "title": result["title"],
        "priority": result["priority"],
        "status": result["status"],
        "due_date": str(result["due_date"]) if result.get("due_date") else None,
        "message": f"Task created ✓: {title}"
    }


async def list_tasks(
    tool_context: ToolContext,
    status: str = None,
    priority: str = None,
    due_before: str = None,
    tags: list[str] = None,
    limit: int = 50
) -> dict:
    """
    List tasks for the authenticated user.

    Args:
        status: todo | in_progress | completed | cancelled
        priority: P0 | P1 | P2 | P3
        due_before: ISO date string
        tags: Filter by any of these tags
        limit: Max results (default 50)
    """
    from src.models.task import TaskFilter
    user_id = _get_user_id(tool_context)

    due_before_obj = None
    if due_before:
        try:
            due_before_obj = datetime.fromisoformat(due_before.replace('Z', '+00:00'))
        except ValueError:
            pass

    filters = TaskFilter(
        status=TaskStatus(status) if status else None,
        priority=Priority(priority) if priority else None,
        due_before=due_before_obj,
        tags=tags,
        limit=limit,
    )
    tasks = await task_repo.list_tasks(user_id, filters)
    task_list = [
        {
            "task_id": t.task_id,
            "title": t.title,
            "priority": t.priority.value,
            "status": t.status.value,
            "due_date": str(t.due_date) if t.due_date else "No due date",
            "tags": t.tags,
            "recurring": t.recurring_id is not None,
        }
        for t in tasks
    ]
    log.info("tasks_listed_via_tool", user_id=user_id, count=len(task_list))
    return {"tasks": task_list, "count": len(task_list), "message": f"Found {len(task_list)} task(s)"}


async def update_task(
    task_id: str,
    tool_context: ToolContext,
    title: str = None,
    description: str = None,
    priority: str = None,
    status: str = None,
    due_date: str = None,
    tags: list[str] = None,
) -> dict:
    """Update an existing task."""
    from src.models.task import TaskUpdate
    user_id = _get_user_id(tool_context)

    due_date_obj = None
    if due_date:
        try:
            due_date_obj = datetime.fromisoformat(due_date.replace('Z', '+00:00'))
        except ValueError:
            pass

    updates = TaskUpdate(
        title=title,
        description=description,
        priority=Priority(priority) if priority else None,
        status=TaskStatus(status) if status else None,
        due_date=due_date_obj,
        tags=tags,
    )
    task = await task_repo.update_task(user_id, task_id, updates)
    if not task:
        return {"success": False, "message": f"Task not found: {task_id}"}

    log.info("task_updated_via_tool", task_id=task_id, user_id=user_id)
    return {"success": True, "task_id": task.task_id, "title": task.title,
            "status": task.status.value, "message": f"Task updated ✓: {task.title}"}


async def delete_task(task_id: str, tool_context: ToolContext) -> dict:
    """Delete a task permanently."""
    user_id = _get_user_id(tool_context)
    success = await task_repo.delete_task(user_id, task_id)
    if success:
        log.info("task_deleted_via_tool", task_id=task_id, user_id=user_id)
        return {"success": True, "message": f"Task deleted: {task_id}"}
    return {"success": False, "message": f"Task not found: {task_id}"}


async def get_task_by_id(task_id: str, tool_context: ToolContext) -> dict:
    """Get full details of a specific task."""
    user_id = _get_user_id(tool_context)
    task = await task_repo.get_task(user_id, task_id)
    if not task:
        return {"success": False, "message": f"Task not found: {task_id}"}
    return {
        "success": True,
        "task_id": task.task_id,
        "title": task.title,
        "description": task.description,
        "priority": task.priority.value,
        "status": task.status.value,
        "due_date": str(task.due_date) if task.due_date else None,
        "tags": task.tags,
        "recurring": task.recurring_id is not None,
        "created_at": str(task.created_at),
        "updated_at": str(task.updated_at),
    }


async def list_recurring_tasks(tool_context: ToolContext) -> dict:
    """List all recurring task templates for the authenticated user."""
    user_id = _get_user_id(tool_context)
    templates = await task_repo.list_recurring(user_id)
    return {
        "recurring_tasks": [
            {
                "recurring_id": rt["recurring_id"],
                "title": rt["title"],
                "frequency": rt.get("frequency"),
                "priority": rt.get("priority", "P3"),
                "is_active": rt.get("is_active", True),
            }
            for rt in templates
        ],
        "count": len(templates),
        "message": f"Found {len(templates)} recurring task(s)"
    }


async def cancel_recurring_task(recurring_id: str, tool_context: ToolContext) -> dict:
    """Stop a recurring task from creating new instances."""
    user_id = _get_user_id(tool_context)
    result = await task_repo.task_repo._recurring().update_one(
        {"recurring_id": recurring_id, "user_id": user_id},
        {"$set": {"is_active": False}}
    )
    if result.modified_count:
        return {"success": True, "message": f"Recurring task cancelled: {recurring_id}"}
    return {"success": False, "message": f"Recurring task not found: {recurring_id}"}
