"""
UserPreferences repository.
Lazy-creates default prefs on first access.
"""
from motor.motor_asyncio import AsyncIOMotorClient
from src.core.config import settings
from src.models.user_prefs import UserPreferences, UserPreferencesUpdate, GmailPreferences
from datetime import datetime, timezone
from typing import Optional
import structlog

log = structlog.get_logger()
COLL = "user_preferences"


class PreferencesRepository:
    def __init__(self):
        self._db = AsyncIOMotorClient(settings.MONGO_URI)[settings.MONGO_DB]

    @property
    def _col(self):
        return self._db[COLL]

    async def get_or_create(self, user_id: str) -> UserPreferences:
        doc = await self._col.find_one({"user_id": user_id})
        if doc:
            doc.pop("_id", None)
            return UserPreferences(**doc)
        prefs = UserPreferences(user_id=user_id)
        await self._col.insert_one(prefs.model_dump())
        log.info("user_prefs_created", user_id=user_id)
        return prefs

    async def update(self, user_id: str, updates: UserPreferencesUpdate) -> UserPreferences:
        prefs = await self.get_or_create(user_id)
        delta: dict = {"updated_at": datetime.now(timezone.utc)}

        if updates.gmail:
            for k, v in updates.gmail.model_dump(exclude_unset=True).items():
                setattr(prefs.gmail, k, v)
            delta["gmail"] = prefs.gmail.model_dump()

        if updates.telegram:
            for k, v in updates.telegram.model_dump(exclude_unset=True).items():
                setattr(prefs.telegram, k, v)
            delta["telegram"] = prefs.telegram.model_dump()

        if updates.notifications:
            for k, v in updates.notifications.model_dump(exclude_unset=True).items():
                setattr(prefs.notifications, k, v)
            delta["notifications"] = prefs.notifications.model_dump()

        await self._col.update_one(
            {"user_id": user_id},
            {"$set": delta},
            upsert=True,
        )
        log.info("user_prefs_updated", user_id=user_id)
        return await self.get_or_create(user_id)

    async def add_ignored_sender(self, user_id: str, sender: str) -> None:
        await self._col.update_one(
            {"user_id": user_id},
            {"$addToSet": {"gmail.ignored_senders": sender.lower()},
             "$set": {"updated_at": datetime.now(timezone.utc)}},
            upsert=True,
        )

    async def remove_ignored_sender(self, user_id: str, sender: str) -> None:
        await self._col.update_one(
            {"user_id": user_id},
            {"$pull": {"gmail.ignored_senders": sender.lower()},
             "$set": {"updated_at": datetime.now(timezone.utc)}},
        )

    async def set_telegram_chat(self, user_id: str, chat_id: int) -> None:
        await self._col.update_one(
            {"user_id": user_id},
            {"$set": {
                "telegram.chat_id": chat_id,
                "telegram.connected_at": datetime.now(timezone.utc),
                "updated_at": datetime.now(timezone.utc),
            }},
            upsert=True,
        )

    async def set_gmail_connected(self, user_id: str, email: str) -> None:
        await self._col.update_one(
            {"user_id": user_id},
            {"$set": {
                "gmail.connected_email": email,
                "gmail.connected_at": datetime.now(timezone.utc),
                "updated_at": datetime.now(timezone.utc),
            }},
            upsert=True,
        )


prefs_repo = PreferencesRepository()
