"""
Task management API endpoints
"""
from fastapi import APIRouter, Depends, HTTPException
from src.models.task import Task, TaskCreate, TaskUpdate, TaskFilter
from src.models.user import UserClaims
from src.repositories.task_repo import TaskRepository
from src.api.middleware import get_current_active_user
import structlog

log = structlog.get_logger()

router = APIRouter(prefix="/tasks", tags=["Tasks"])
task_repo = TaskRepository()


@router.post("", response_model=Task, status_code=201)
async def create_task(
    task_create: TaskCreate,
    current_user: UserClaims = Depends(get_current_active_user)
) -> Task:
    """Create a new task"""
    task = Task(user_id=current_user.user_id, **task_create.model_dump())

    task_dict = await task_repo.create_task(task)

    return Task(**task_dict)


@router.get("", response_model=list[Task])
async def list_tasks(
    status: str | None = None,
    priority: str | None = None,
    limit: int = 100,
    offset: int = 0,
    current_user: UserClaims = Depends(get_current_active_user)
) -> list[Task]:
    """List tasks with optional filters"""
    filters = TaskFilter(
        status=status,
        priority=priority,
        limit=limit,
        offset=offset
    )

    return await task_repo.list_tasks(current_user.user_id, filters)


@router.get("/{task_id}", response_model=Task)
async def get_task(
    task_id: str,
    current_user: UserClaims = Depends(get_current_active_user)
) -> Task:
    """Get a single task by ID"""
    task = await task_repo.get_task(current_user.user_id, task_id)

    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    return task


@router.patch("/{task_id}", response_model=Task)
async def update_task(
    task_id: str,
    task_update: TaskUpdate,
    current_user: UserClaims = Depends(get_current_active_user)
) -> Task:
    """Update a task"""
    task = await task_repo.update_task(current_user.user_id, task_id, task_update)

    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    return task


@router.delete("/{task_id}", status_code=204)
async def delete_task(
    task_id: str,
    current_user: UserClaims = Depends(get_current_active_user)
):
    """Delete a task"""
    success = await task_repo.delete_task(current_user.user_id, task_id)

    if not success:
        raise HTTPException(status_code=404, detail="Task not found")

    return None
