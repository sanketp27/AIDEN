"""
Task repository — MongoDB CRUD for tasks and recurring task templates.
Per-user collection namespacing ensures data isolation.
"""
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import ASCENDING, DESCENDING
from src.core.config import settings
from src.models.task import Task, TaskUpdate, TaskFilter, TaskStatus, RecurringTask
from src.core.db_init import COLL_RECURRING
from datetime import datetime, timezone, timedelta
from typing import Optional
import structlog

log = structlog.get_logger()


class TaskRepository:
    """CRUD for per-user task collections and the global recurring_tasks collection."""

    def __init__(self):
        self.client = AsyncIOMotorClient(settings.MONGO_URI)
        self.db = self.client[settings.MONGO_DB]

    # ── Per-user collection helpers ─────────────────────────────────────────

    def _tasks(self, user_id: str):
        return self.db[f"{user_id}__tasks"]

    async def ensure_indexes(self, user_id: str) -> None:
        """Lazily create per-user task collection indexes on first write."""
        col = self._tasks(user_id)
        await col.create_index([("task_id", ASCENDING)], unique=True, background=True)
        await col.create_index([("user_id", ASCENDING), ("status", ASCENDING)], background=True)
        await col.create_index([("user_id", ASCENDING), ("due_date", ASCENDING)], background=True)
        await col.create_index([("user_id", ASCENDING), ("priority", ASCENDING)], background=True)
        await col.create_index([("tags", ASCENDING)], background=True)
        await col.create_index([("recurring_id", ASCENDING)], background=True)

    # ── One-off task CRUD ───────────────────────────────────────────────────

    async def create_task(self, task: Task) -> dict:
        col = self._tasks(task.user_id)
        await self.ensure_indexes(task.user_id)
        doc = task.model_dump()
        await col.insert_one(doc)
        log.info("task_created", task_id=task.task_id, user_id=task.user_id)
        return doc

    async def get_task(self, user_id: str, task_id: str) -> Optional[Task]:
        doc = await self._tasks(user_id).find_one({"task_id": task_id, "user_id": user_id})
        if doc:
            doc.pop("_id", None)
            return Task(**doc)
        return None

    async def list_tasks(self, user_id: str, filters: Optional[TaskFilter] = None) -> list[Task]:
        col = self._tasks(user_id)
        query: dict = {"user_id": user_id}

        if filters:
            if filters.status:
                query["status"] = filters.status
            if filters.priority:
                query["priority"] = filters.priority
            if filters.due_before:
                query.setdefault("due_date", {})["$lte"] = filters.due_before
            if filters.due_after:
                query.setdefault("due_date", {})["$gte"] = filters.due_after
            if filters.tags:
                query["tags"] = {"$in": filters.tags}
            if filters.recurring is True:
                query["recurring_id"] = {"$ne": None}
            elif filters.recurring is False:
                query["recurring_id"] = None

        cursor = col.find(query).sort("created_at", DESCENDING)
        if filters:
            cursor = cursor.skip(filters.offset).limit(filters.limit)

        tasks = []
        async for doc in cursor:
            doc.pop("_id", None)
            tasks.append(Task(**doc))

        log.info("tasks_listed", user_id=user_id, count=len(tasks))
        return tasks

    async def update_task(self, user_id: str, task_id: str, updates: TaskUpdate) -> Optional[Task]:
        col = self._tasks(user_id)
        update_dict = updates.model_dump(exclude_unset=True)
        if not update_dict:
            return await self.get_task(user_id, task_id)

        update_dict["updated_at"] = datetime.now(timezone.utc)
        result = await col.update_one(
            {"task_id": task_id, "user_id": user_id},
            {"$set": update_dict}
        )
        if result.modified_count > 0:
            log.info("task_updated", task_id=task_id, user_id=user_id)
            return await self.get_task(user_id, task_id)
        return None

    async def delete_task(self, user_id: str, task_id: str) -> bool:
        result = await self._tasks(user_id).delete_one({"task_id": task_id, "user_id": user_id})
        if result.deleted_count > 0:
            log.info("task_deleted", task_id=task_id, user_id=user_id)
            return True
        return False

    async def count_tasks(self, user_id: str, status: Optional[TaskStatus] = None) -> int:
        q: dict = {"user_id": user_id}
        if status:
            q["status"] = status
        return await self._tasks(user_id).count_documents(q)

    # ── Recurring task templates ────────────────────────────────────────────

    def _recurring(self):
        return self.db[COLL_RECURRING]

    async def create_recurring(self, rt: RecurringTask) -> dict:
        doc = rt.model_dump()
        # Flatten the rule sub-model into top-level fields for storage
        rule = doc.pop("rule")
        doc.update({
            "frequency":   rule["frequency"],
            "interval":    rule.get("interval", 1),
            "days_of_week": rule.get("days_of_week"),
            "time_of_day": rule.get("time_of_day"),
            "end_date":    rule.get("end_date"),
        })
        await self._recurring().insert_one(doc)
        log.info("recurring_task_created", recurring_id=rt.recurring_id, user_id=rt.user_id)
        return doc

    async def get_recurring(self, user_id: str, recurring_id: str) -> Optional[dict]:
        doc = await self._recurring().find_one({"recurring_id": recurring_id, "user_id": user_id})
        if doc:
            doc.pop("_id", None)
        return doc

    async def list_recurring(self, user_id: str, active_only: bool = True) -> list[dict]:
        q: dict = {"user_id": user_id}
        if active_only:
            q["is_active"] = True
        cursor = self._recurring().find(q).sort("created_at", DESCENDING)
        results = []
        async for doc in cursor:
            doc.pop("_id", None)
            results.append(doc)
        return results

    async def delete_recurring(self, user_id: str, recurring_id: str) -> bool:
        result = await self._recurring().delete_one({"recurring_id": recurring_id, "user_id": user_id})
        return result.deleted_count > 0

    async def mark_recurring_created(self, recurring_id: str) -> None:
        """Update last_created timestamp after spawning a task instance."""
        await self._recurring().update_one(
            {"recurring_id": recurring_id},
            {"$set": {"last_created": datetime.now(timezone.utc)}}
        )

    async def get_due_recurring_tasks(self) -> list[dict]:
        """
        Return all active recurring templates that are due to spawn a new task today.
        Called by the scheduler every morning.
        """
        now = datetime.now(timezone.utc)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

        # Due = never created, OR last_created before today
        q = {
            "is_active": True,
            "$or": [
                {"last_created": None},
                {"last_created": {"$lt": today_start}},
            ]
        }
        cursor = self._recurring().find(q)
        results = []
        async for doc in cursor:
            doc.pop("_id", None)
            results.append(doc)
        return results

    # ── Streak tracking ──────────────────────────────────────────────────────

    async def record_habit_completion(self, recurring_id: str, user_id: str, completed_date: str) -> dict:
        """
        Called when a recurring task instance is marked `completed`.
        Updates current_streak, longest_streak, total_completions, last_completed_date,
        and appends to completion_history. Returns the updated streak fields.

        Streak logic:
          - If last_completed_date == yesterday  → streak += 1
          - If last_completed_date == today      → idempotent (already counted)
          - If last_completed_date is older/None → reset streak to 1
        """
        from datetime import date, timedelta

        doc = await self._recurring().find_one({"recurring_id": recurring_id, "user_id": user_id})
        if not doc:
            return {}

        doc.pop("_id", None)
        today_str = completed_date   # "YYYY-MM-DD"
        today = date.fromisoformat(today_str)
        yesterday_str = (today - timedelta(days=1)).isoformat()

        current_streak  = doc.get("current_streak", 0)
        longest_streak  = doc.get("longest_streak", 0)
        total           = doc.get("total_completions", 0)
        last_date       = doc.get("last_completed_date")
        history: list   = doc.get("completion_history", [])

        # Idempotency — already recorded today
        if last_date == today_str:
            return {
                "current_streak": current_streak,
                "longest_streak": longest_streak,
                "total_completions": total,
                "last_completed_date": last_date,
            }

        # Streak arithmetic
        if last_date == yesterday_str:
            current_streak += 1
        else:
            current_streak = 1          # broken or first time

        total += 1
        longest_streak = max(longest_streak, current_streak)

        # Append to history, keep last 365 days only
        if today_str not in history:
            history.append(today_str)
        cutoff = (today - timedelta(days=365)).isoformat()
        history = [d for d in history if d >= cutoff]

        update = {
            "current_streak": current_streak,
            "longest_streak": longest_streak,
            "total_completions": total,
            "last_completed_date": today_str,
            "completion_history": history,
        }
        await self._recurring().update_one(
            {"recurring_id": recurring_id, "user_id": user_id},
            {"$set": update}
        )
        log.info("habit_streak_updated",
                 recurring_id=recurring_id, current_streak=current_streak, total=total)
        return update

    async def get_habit_summaries(self, user_id: str) -> list[dict]:
        """
        Return all recurring tasks for the user with streak/habit data.
        Used by the GET /habits endpoint.
        """
        from datetime import date, timedelta

        cursor = self._recurring().find({"user_id": user_id})
        results = []
        today = date.today()
        thirty_days_ago = (today - timedelta(days=30)).isoformat()

        async for doc in cursor:
            doc.pop("_id", None)
            history = doc.get("completion_history", [])
            # 30-day completion rate
            expected = min(30, (today - date.fromisoformat(
                doc.get("start_date", today.isoformat())[:10]
            )).days + 1) if doc.get("start_date") else 30
            completed_in_30 = sum(1 for d in history if d >= thirty_days_ago)
            rate = round(completed_in_30 / max(expected, 1), 2)
            doc["completion_rate_30d"] = min(rate, 1.0)
            results.append(doc)

        return results

    async def get_habit_summary(self, user_id: str, recurring_id: str) -> Optional[dict]:
        """Get a single habit's full streak data."""
        from datetime import date, timedelta
        doc = await self._recurring().find_one({"recurring_id": recurring_id, "user_id": user_id})
        if not doc:
            return None
        doc.pop("_id", None)
        history = doc.get("completion_history", [])
        thirty_days_ago = (date.today() - timedelta(days=30)).isoformat()
        completed_in_30 = sum(1 for d in history if d >= thirty_days_ago)
        doc["completion_rate_30d"] = min(round(completed_in_30 / 30, 2), 1.0)
        return doc
