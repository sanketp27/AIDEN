"""
Task management tools for ADK agents
Uses @tool decorator for ADK integration
"""
from src.tools.tool_decorator import tool
from src.repositories.task_repo import TaskRepository
from src.models.task import Task, Priority, TaskStatus
from datetime import datetime
from typing import Optional
import structlog

log = structlog.get_logger()

# Repository instance
task_repo = TaskRepository()


@tool
async def create_task(
    user_id: str,
    title: str,
    description: str = None,
    priority: str = "P3",
    due_date: str = None,
    tags: list[str] = None
) -> dict:
    """
    Create a new task for the user.

    Args:
        user_id: User identifier
        title: Task title (required)
        description: Detailed task description
        priority: Priority level (P0=Critical, P1=High, P2=Medium, P3=Low)
        due_date: Due date in ISO format (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS)
        tags: List of tags for categorization

    Returns:
        Created task as dictionary with task_id
    """
    tags = tags or []

    # Parse due_date if provided
    due_date_obj = None
    if due_date:
        try:
            due_date_obj = datetime.fromisoformat(due_date.replace('Z', '+00:00'))
        except ValueError:
            log.warning("invalid_due_date_format", due_date=due_date)

    # Create task
    task = Task(
        user_id=user_id,
        title=title,
        description=description,
        priority=Priority(priority),
        due_date=due_date_obj,
        tags=tags
    )

    result = await task_repo.create_task(task)

    log.info("task_created_via_tool", task_id=result['task_id'], user_id=user_id, title=title)

    return {
        "task_id": result['task_id'],
        "title": result['title'],
        "priority": result['priority'],
        "status": result['status'],
        "due_date": str(result['due_date']) if result.get('due_date') else None,
        "message": f"Task created successfully: {title}"
    }


@tool
async def list_tasks(
    user_id: str,
    status: str = None,
    priority: str = None,
    due_before: str = None,
    tags: list[str] = None,
    limit: int = 50
) -> dict:
    """
    List tasks with optional filters.

    Args:
        user_id: User identifier
        status: Filter by status (todo, in_progress, completed, cancelled)
        priority: Filter by priority (P0, P1, P2, P3)
        due_before: Show tasks due before this date (ISO format)
        tags: Filter by tags (returns tasks matching any tag)
        limit: Maximum number of tasks to return (default: 50)

    Returns:
        Dictionary with task list and count
    """
    from src.models.task import TaskFilter

    # Parse due_before if provided
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
        limit=limit
    )

    tasks = await task_repo.list_tasks(user_id, filters)

    # Format tasks for agent response
    task_list = []
    for task in tasks:
        task_list.append({
            "task_id": task.task_id,
            "title": task.title,
            "priority": task.priority.value,
            "status": task.status.value,
            "due_date": str(task.due_date) if task.due_date else "No due date",
            "tags": task.tags
        })

    log.info("tasks_listed_via_tool", user_id=user_id, count=len(task_list))

    return {
        "tasks": task_list,
        "count": len(task_list),
        "message": f"Found {len(task_list)} task(s)"
    }


@tool
async def update_task(
    user_id: str,
    task_id: str,
    title: str = None,
    description: str = None,
    priority: str = None,
    status: str = None,
    due_date: str = None,
    tags: list[str] = None
) -> dict:
    """
    Update an existing task.

    Args:
        user_id: User identifier
        task_id: Task identifier
        title: New title
        description: New description
        priority: New priority (P0, P1, P2, P3)
        status: New status (todo, in_progress, completed, cancelled)
        due_date: New due date (ISO format)
        tags: New tags list

    Returns:
        Updated task information
    """
    from src.models.task import TaskUpdate

    # Parse due_date if provided
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
        tags=tags
    )

    task = await task_repo.update_task(user_id, task_id, updates)

    if not task:
        return {
            "success": False,
            "message": f"Task not found: {task_id}"
        }

    log.info("task_updated_via_tool", task_id=task_id, user_id=user_id)

    return {
        "success": True,
        "task_id": task.task_id,
        "title": task.title,
        "status": task.status.value,
        "message": f"Task updated: {task.title}"
    }


@tool
async def delete_task(
    user_id: str,
    task_id: str
) -> dict:
    """
    Delete a task permanently.

    Args:
        user_id: User identifier
        task_id: Task identifier to delete

    Returns:
        Confirmation message
    """
    success = await task_repo.delete_task(user_id, task_id)

    if success:
        log.info("task_deleted_via_tool", task_id=task_id, user_id=user_id)
        return {
            "success": True,
            "message": f"Task deleted: {task_id}"
        }
    else:
        return {
            "success": False,
            "message": f"Task not found: {task_id}"
        }


@tool
async def get_task_by_id(
    user_id: str,
    task_id: str
) -> dict:
    """
    Get detailed information about a specific task.

    Args:
        user_id: User identifier
        task_id: Task identifier

    Returns:
        Full task details
    """
    task = await task_repo.get_task(user_id, task_id)

    if not task:
        return {
            "success": False,
            "message": f"Task not found: {task_id}"
        }

    return {
        "success": True,
        "task_id": task.task_id,
        "title": task.title,
        "description": task.description,
        "priority": task.priority.value,
        "status": task.status.value,
        "due_date": str(task.due_date) if task.due_date else None,
        "tags": task.tags,
        "created_at": str(task.created_at),
        "updated_at": str(task.updated_at)
    }
