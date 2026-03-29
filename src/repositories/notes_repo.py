"""
Notes repository for MongoDB operations
Per-user collection namespacing for data isolation
"""
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import ASCENDING, DESCENDING
from src.core.config import settings
from src.models.note import Note, NoteCreate, NoteUpdate, NoteFilter
from datetime import datetime, timezone
from typing import Optional
import structlog

log = structlog.get_logger()


class NotesRepository:
    """Repository for note CRUD operations"""

    def __init__(self):
        self.client = AsyncIOMotorClient(settings.MONGO_URI)
        self.db = self.client[settings.MONGO_DB]

    def _get_collection(self, user_id: str):
        """Get user-specific notes collection"""
        collection_name = f"{user_id}__notes"
        return self.db[collection_name]

    async def ensure_indexes(self, user_id: str) -> None:
        """
        Fix Bug #7: Create indexes on first use for this user's notes collection.
        Without these, list_notes() and search by tag/project are full scans.
        """
        collection = self._get_collection(user_id)
        await collection.create_index([("note_id", ASCENDING)], unique=True, background=True)
        await collection.create_index([("user_id", ASCENDING), ("created_at", DESCENDING)], background=True)
        await collection.create_index([("tags", ASCENDING)], background=True)
        await collection.create_index([("project", ASCENDING)], background=True)
        log.info("note_indexes_ensured", user_id=user_id)

    async def create_note(self, note: Note) -> dict:
        """Create a new note"""
        collection = self._get_collection(note.user_id)
        await self.ensure_indexes(note.user_id)
        note_dict = note.model_dump()

        await collection.insert_one(note_dict)
        log.info("note_created", note_id=note.note_id, user_id=note.user_id)

        return note_dict

    async def get_note(self, user_id: str, note_id: str) -> Optional[Note]:
        """Get a single note by ID"""
        collection = self._get_collection(user_id)
        note_dict = await collection.find_one({"note_id": note_id, "user_id": user_id})

        if note_dict:
            note_dict.pop("_id", None)
            return Note(**note_dict)
        return None

    async def get_notes_by_ids(self, user_id: str, note_ids: list[str]) -> list[Note]:
        """Get multiple notes by IDs (for semantic search results)"""
        collection = self._get_collection(user_id)

        cursor = collection.find({"note_id": {"$in": note_ids}, "user_id": user_id})

        notes = []
        async for note_dict in cursor:
            note_dict.pop("_id", None)
            notes.append(Note(**note_dict))

        return notes

    async def list_notes(self, user_id: str, filters: Optional[NoteFilter] = None) -> list[Note]:
        """List notes with optional filters"""
        collection = self._get_collection(user_id)

        query = {"user_id": user_id}

        if filters:
            if filters.tags:
                query["tags"] = {"$in": filters.tags}
            if filters.project:
                query["project"] = filters.project

        cursor = collection.find(query).sort("created_at", -1)

        if filters:
            cursor = cursor.skip(filters.offset).limit(filters.limit)

        notes = []
        async for note_dict in cursor:
            note_dict.pop("_id", None)
            notes.append(Note(**note_dict))

        log.info("notes_listed", user_id=user_id, count=len(notes))
        return notes

    async def update_note(self, user_id: str, note_id: str, updates: NoteUpdate) -> Optional[Note]:
        """Update a note"""
        collection = self._get_collection(user_id)

        # Fix Bug #10: exclude_unset=True so only explicitly provided fields are updated.
        update_dict = updates.model_dump(exclude_unset=True)

        if not update_dict:
            return await self.get_note(user_id, note_id)

        update_dict["updated_at"] = datetime.now(timezone.utc)

        result = await collection.update_one(
            {"note_id": note_id, "user_id": user_id},
            {"$set": update_dict}
        )

        if result.modified_count > 0:
            log.info("note_updated", note_id=note_id, user_id=user_id)
            return await self.get_note(user_id, note_id)

        return None

    async def delete_note(self, user_id: str, note_id: str) -> bool:
        """Delete a note"""
        collection = self._get_collection(user_id)

        result = await collection.delete_one({"note_id": note_id, "user_id": user_id})

        if result.deleted_count > 0:
            log.info("note_deleted", note_id=note_id, user_id=user_id)
            return True

        return False

    async def count_notes(self, user_id: str) -> int:
        """Count notes for a user"""
        collection = self._get_collection(user_id)
        return await collection.count_documents({"user_id": user_id})
