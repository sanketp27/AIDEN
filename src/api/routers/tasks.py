"""
Task management API endpoints — one-off and recurring tasks.
"""
from fastapi import APIRouter, Depends, HTTPException
from src.models.task import Task, TaskCreate, TaskUpdate, TaskFilter, RecurringTask, RecurringRule
from src.models.user import UserClaims
from src.repositories.task_repo import TaskRepository
from src.api.middleware import get_current_active_user
from datetime import datetime, timezone
import structlog

log = structlog.get_logger()

router = APIRouter(prefix="/tasks", tags=["Tasks"])
task_repo = TaskRepository()


@router.post("", response_model=Task, status_code=201)
async def create_task(
    task_create: TaskCreate,
    current_user: UserClaims = Depends(get_current_active_user),
) -> Task:
    """Create a one-off task. If `recurring` is set, also creates a recurring template."""
    if task_create.recurring:
        # Create recurring template
        rt = RecurringTask(
            user_id=current_user.user_id,
            title=task_create.title,
            description=task_create.description,
            priority=task_create.priority,
            tags=task_create.tags + ["recurring"],
            rule=task_create.recurring,
            start_date=datetime.now(timezone.utc),
        )
        await task_repo.create_recurring(rt)
        # Fall through to also create today's instance
        task = Task(
            user_id=current_user.user_id,
            recurring_id=rt.recurring_id,
            **task_create.model_dump(exclude={"recurring"}),
        )
    else:
        task = Task(user_id=current_user.user_id, **task_create.model_dump(exclude={"recurring"}))

    doc = await task_repo.create_task(task)
    return Task(**doc)


@router.get("", response_model=list[Task])
async def list_tasks(
    status: str | None = None,
    priority: str | None = None,
    limit: int = 100,
    offset: int = 0,
    current_user: UserClaims = Depends(get_current_active_user),
) -> list[Task]:
    filters = TaskFilter(status=status, priority=priority, limit=limit, offset=offset)
    return await task_repo.list_tasks(current_user.user_id, filters)


@router.get("/recurring", response_model=list[dict])
async def list_recurring(
    current_user: UserClaims = Depends(get_current_active_user),
) -> list[dict]:
    """List all recurring task templates for the current user."""
    return await task_repo.list_recurring(current_user.user_id)


@router.delete("/recurring/{recurring_id}", status_code=204)
async def cancel_recurring(
    recurring_id: str,
    current_user: UserClaims = Depends(get_current_active_user),
):
    """Deactivate a recurring task (stops future instances from being created)."""
    success = await task_repo.delete_recurring(current_user.user_id, recurring_id)
    if not success:
        raise HTTPException(404, "Recurring task not found")
    return None


@router.get("/{task_id}", response_model=Task)
async def get_task(
    task_id: str,
    current_user: UserClaims = Depends(get_current_active_user),
) -> Task:
    task = await task_repo.get_task(current_user.user_id, task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    return task


@router.patch("/{task_id}", response_model=Task)
async def update_task(
    task_id: str,
    task_update: TaskUpdate,
    current_user: UserClaims = Depends(get_current_active_user),
) -> Task:
    task = await task_repo.update_task(current_user.user_id, task_id, task_update)
    if not task:
        raise HTTPException(404, "Task not found")

    # Auto-update habit streak when a recurring task instance is completed
    if task_update.status == "completed" and task.recurring_id:
        from datetime import date
        try:
            await task_repo.record_habit_completion(
                recurring_id=task.recurring_id,
                user_id=current_user.user_id,
                completed_date=date.today().isoformat(),
            )
            log.info("habit_streak_auto_updated",
                     task_id=task_id, recurring_id=task.recurring_id,
                     user_id=current_user.user_id)
        except Exception as e:
            log.warning("habit_streak_update_failed", error=str(e))

    return task


@router.delete("/{task_id}", status_code=204)
async def delete_task(
    task_id: str,
    current_user: UserClaims = Depends(get_current_active_user),
):
    success = await task_repo.delete_task(current_user.user_id, task_id)
    if not success:
        raise HTTPException(404, "Task not found")
    return None
