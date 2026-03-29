"""
Task repository for MongoDB operations
Per-user collection namespacing for data isolation
"""
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import ASCENDING, DESCENDING
from src.core.config import settings
from src.models.task import Task, TaskCreate, TaskUpdate, TaskFilter, TaskStatus
from datetime import datetime, timezone
from typing import Optional
import structlog

log = structlog.get_logger()


class TaskRepository:
    """Repository for task CRUD operations"""

    def __init__(self):
        self.client = AsyncIOMotorClient(settings.MONGO_URI)
        self.db = self.client[settings.MONGO_DB]

    def _get_collection(self, user_id: str):
        """Get user-specific task collection"""
        collection_name = f"{user_id}__tasks"
        return self.db[collection_name]

    async def ensure_indexes(self, user_id: str) -> None:
        """
        Fix Bug #7: Create indexes on first use for this user's task collection.
        Without these, list_tasks() performs a full collection scan on every call.
        Called lazily from create_task so indexes exist before any query runs.
        """
        collection = self._get_collection(user_id)
        await collection.create_index([("task_id", ASCENDING)], unique=True, background=True)
        await collection.create_index([("user_id", ASCENDING), ("status", ASCENDING)], background=True)
        await collection.create_index([("user_id", ASCENDING), ("due_date", ASCENDING)], background=True)
        await collection.create_index([("user_id", ASCENDING), ("priority", ASCENDING)], background=True)
        await collection.create_index([("tags", ASCENDING)], background=True)
        log.info("task_indexes_ensured", user_id=user_id)

    async def create_task(self, task: Task) -> dict:
        """Create a new task"""
        collection = self._get_collection(task.user_id)
        await self.ensure_indexes(task.user_id)
        task_dict = task.model_dump()

        await collection.insert_one(task_dict)
        log.info("task_created", task_id=task.task_id, user_id=task.user_id)

        return task_dict

    async def get_task(self, user_id: str, task_id: str) -> Optional[Task]:
        """Get a single task by ID"""
        collection = self._get_collection(user_id)
        task_dict = await collection.find_one({"task_id": task_id, "user_id": user_id})

        if task_dict:
            task_dict.pop("_id", None)  # Remove MongoDB _id
            return Task(**task_dict)
        return None

    async def list_tasks(self, user_id: str, filters: Optional[TaskFilter] = None) -> list[Task]:
        """List tasks with optional filters"""
        collection = self._get_collection(user_id)

        query = {"user_id": user_id}

        if filters:
            if filters.status:
                query["status"] = filters.status
            if filters.priority:
                query["priority"] = filters.priority
            if filters.due_before:
                query["due_date"] = {"$lte": filters.due_before}
            if filters.due_after:
                if "due_date" in query:
                    query["due_date"]["$gte"] = filters.due_after
                else:
                    query["due_date"] = {"$gte": filters.due_after}
            if filters.tags:
                query["tags"] = {"$in": filters.tags}

        cursor = collection.find(query)

        if filters:
            cursor = cursor.skip(filters.offset).limit(filters.limit)

        tasks = []
        async for task_dict in cursor:
            task_dict.pop("_id", None)
            tasks.append(Task(**task_dict))

        log.info("tasks_listed", user_id=user_id, count=len(tasks))
        return tasks

    async def update_task(self, user_id: str, task_id: str, updates: TaskUpdate) -> Optional[Task]:
        """Update a task"""
        collection = self._get_collection(user_id)

        # Fix Bug #10: exclude_unset=True so only explicitly provided fields are updated.
        # The old {if v is not None} filter prevented clearing a field to None intentionally.
        update_dict = updates.model_dump(exclude_unset=True)

        if not update_dict:
            return await self.get_task(user_id, task_id)

        update_dict["updated_at"] = datetime.now(timezone.utc)

        result = await collection.update_one(
            {"task_id": task_id, "user_id": user_id},
            {"$set": update_dict}
        )

        if result.modified_count > 0:
            log.info("task_updated", task_id=task_id, user_id=user_id)
            return await self.get_task(user_id, task_id)

        return None

    async def delete_task(self, user_id: str, task_id: str) -> bool:
        """Delete a task"""
        collection = self._get_collection(user_id)

        result = await collection.delete_one({"task_id": task_id, "user_id": user_id})

        if result.deleted_count > 0:
            log.info("task_deleted", task_id=task_id, user_id=user_id)
            return True

        return False

    async def count_tasks(self, user_id: str, status: Optional[TaskStatus] = None) -> int:
        """Count tasks for a user"""
        collection = self._get_collection(user_id)

        query = {"user_id": user_id}
        if status:
            query["status"] = status

        return await collection.count_documents(query)
