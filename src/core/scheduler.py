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


async def generate_all_briefings():
    from src.analytics.briefing_generator import generate_briefing, COLL_BRIEFINGS
    from motor.motor_asyncio import AsyncIOMotorClient
    from src.core.config import settings
    from datetime import date

    client = AsyncIOMotorClient(settings.MONGO_URI)
    db = client[settings.MONGO_DB]

    # Find all users who have task collections
    collections = await db.list_collection_names()
    user_ids = set()
    for name in collections:
        if name.endswith("__tasks"):
            uid = name[:-7]   # strip "__tasks"
            user_ids.add(uid)

    log.info("briefing_generation_start", user_count=len(user_ids))

    for user_id in user_ids:
        try:
            briefing = await generate_briefing(user_id=user_id, task_repo=task_repo)
            doc = briefing.to_dict()
            today = date.today().isoformat()
            await db[COLL_BRIEFINGS].update_one(
                {"user_id": user_id, "date": today},
                {"$set": doc},
                upsert=True,
            )
            log.info("briefing_stored", user_id=user_id, risk=briefing.workload_risk)
        except Exception as e:
            log.error("briefing_failed", user_id=user_id, error=str(e))

    client.close()
    log.info("briefing_generation_complete", users=len(user_ids))


def start_scheduler():
    """Start the APScheduler background scheduler."""
    scheduler.add_job(
        spawn_recurring_tasks,
        trigger=CronTrigger(hour=0, minute=1),
        id="spawn_recurring_tasks",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    # Morning briefings — 6 AM UTC (adjust via TZ for local time)
    scheduler.add_job(
        generate_all_briefings,
        trigger=CronTrigger(hour=6, minute=0),
        id="generate_briefings",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    scheduler.start()
    log.info("recurring_task_scheduler_started")


def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown(wait=False)
        log.info("recurring_task_scheduler_stopped")
