"""
ADK Session Service with MongoDB persistence
Critical for conversation memory across all agents
"""
from google.adk.sessions import SessionService, Session
from motor.motor_asyncio import AsyncIOMotorClient
from src.core.config import settings
from typing import Optional
import structlog
import json

log = structlog.get_logger()


class MongoDBSessionService(SessionService):
    """
    MongoDB-backed session service for ADK
    Provides persistent conversation memory across sessions
    """

    def __init__(self):
        self.client = AsyncIOMotorClient(settings.MONGO_URI)
        self.db = self.client[settings.MONGO_DB]
        self.sessions = self.db.adk_sessions
        log.info("mongodb_session_service_initialized", db=settings.MONGO_DB)

    async def get_session(self, session_id: str, user_id: str) -> Session:
        """
        Retrieve session from MongoDB or create new one

        Args:
            session_id: Unique session identifier
            user_id: User identifier for data isolation

        Returns:
            Session object with conversation history
        """
        doc = await self.sessions.find_one({
            "session_id": session_id,
            "user_id": user_id
        })

        if doc:
            # Convert MongoDB document to Session
            doc.pop("_id", None)  # Remove MongoDB _id
            log.info("session_retrieved", session_id=session_id, user_id=user_id,
                    message_count=len(doc.get("messages", [])))
            return Session.from_dict(doc)

        # Create new session
        new_session = Session(session_id=session_id, user_id=user_id, messages=[])
        log.info("session_created", session_id=session_id, user_id=user_id)
        return new_session

    async def save_session(self, session: Session) -> None:
        """
        Persist session to MongoDB

        Args:
            session: Session object to save
        """
        session_dict = session.to_dict()

        await self.sessions.update_one(
            {
                "session_id": session.session_id,
                "user_id": session.user_id
            },
            {"$set": session_dict},
            upsert=True
        )

        log.info("session_saved",
                session_id=session.session_id,
                user_id=session.user_id,
                message_count=len(session.messages))

    async def delete_session(self, session_id: str, user_id: str) -> None:
        """
        Delete session from MongoDB

        Args:
            session_id: Session to delete
            user_id: User identifier
        """
        result = await self.sessions.delete_one({
            "session_id": session_id,
            "user_id": user_id
        })

        if result.deleted_count > 0:
            log.info("session_deleted", session_id=session_id, user_id=user_id)
        else:
            log.warning("session_not_found", session_id=session_id, user_id=user_id)

    async def list_sessions(self, user_id: str, limit: int = 50) -> list[dict]:
        """
        List recent sessions for a user

        Args:
            user_id: User identifier
            limit: Maximum number of sessions to return

        Returns:
            List of session metadata
        """
        cursor = self.sessions.find(
            {"user_id": user_id},
            {"session_id": 1, "user_id": 1, "created_at": 1, "_id": 0}
        ).sort("created_at", -1).limit(limit)

        sessions = []
        async for doc in cursor:
            sessions.append(doc)

        return sessions


# Singleton instance for use across the application
session_service = MongoDBSessionService()
