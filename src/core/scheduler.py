"""
AIDEN v2.0 — Recurring Task Scheduler
Uses APScheduler to spawn task instances from RecurringTask templates daily.
"""
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from src.repositories.task_repo import TaskRepository
from src.models.task import Task, Priority
from datetime import datetime, timezone
import structlog

log = structlog.get_logger()

task_repo = TaskRepository()
scheduler = AsyncIOScheduler(timezone="UTC")


def _should_run_today(rt: dict) -> bool:
    """Decide whether a recurring template should spawn a task today."""
    freq = rt.get("frequency", "daily")
    now = datetime.now(timezone.utc)
    weekday = now.weekday()  # 0=Mon, 6=Sun

    if freq == "daily":
        return True
    if freq == "weekdays":
        return weekday < 5          # Mon-Fri
    if freq == "weekends":
        return weekday >= 5         # Sat-Sun
    if freq == "weekly":
        days = rt.get("days_of_week") or [0]   # default Monday
        return weekday in days
    if freq == "monthly":
        # Run on the same day-of-month as the start_date
        start = rt.get("start_date")
        if isinstance(start, datetime):
            return now.day == start.day
        return now.day == 1
    return False


async def spawn_recurring_tasks():
    """
    Called once per day (at midnight UTC).
    Reads all due recurring templates and creates task instances.
    """
    log.info("recurring_task_scheduler_run")
    templates = await task_repo.get_due_recurring_tasks()

    spawned = 0
    for rt in templates:
        if not _should_run_today(rt):
            await task_repo.mark_recurring_created(rt["recurring_id"])  # skip but mark
            continue

        # Check end_date
        end = rt.get("end_date")
        if end and isinstance(end, datetime) and datetime.now(timezone.utc) > end:
            await task_repo.task_repo._recurring().update_one(
                {"recurring_id": rt["recurring_id"]},
                {"$set": {"is_active": False}}
            )
            continue

        task = Task(
            user_id=rt["user_id"],
            title=rt["title"],
            description=rt.get("description"),
            priority=Priority(rt.get("priority", "P3")),
            tags=rt.get("tags", []) + ["recurring"],
            recurring_id=rt["recurring_id"],
        )
        await task_repo.create_task(task)
        await task_repo.mark_recurring_created(rt["recurring_id"])
        spawned += 1
        log.info("recurring_task_spawned",
                 title=task.title, user_id=task.user_id,
                 recurring_id=rt["recurring_id"])

    log.info("recurring_task_scheduler_complete", spawned=spawned, total=len(templates))


def start_scheduler():
    """Start the APScheduler background scheduler."""
    # Run every day at 00:01 UTC
    scheduler.add_job(
        spawn_recurring_tasks,
        trigger=CronTrigger(hour=0, minute=1),
        id="spawn_recurring_tasks",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    scheduler.start()
    log.info("recurring_task_scheduler_started")


def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown(wait=False)
        log.info("recurring_task_scheduler_stopped")
