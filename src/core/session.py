from google.adk.sessions import BaseSessionService, Session
from google.adk.events import Event
from motor.motor_asyncio import AsyncIOMotorClient
from src.core.config import settings
from typing import Optional, Any
import time
import structlog

log = structlog.get_logger()


class MongoDBSessionService(BaseSessionService):
    """
    MongoDB-backed session service for ADK 1.x
    Implements the BaseSessionService interface:
      - create_session(app_name, user_id, state, session_id) -> Session
      - get_session(app_name, user_id, session_id) -> Optional[Session]
      - list_sessions(app_name, user_id) -> ListSessionsResponse
      - delete_session(app_name, user_id, session_id) -> None
      - append_event(session, event) -> Event
    """

    def __init__(self):
        self.client = AsyncIOMotorClient(settings.MONGO_URI)
        self.db = self.client[settings.MONGO_DB]
        self.sessions = self.db.adk_sessions
        log.info("mongodb_session_service_initialized", db=settings.MONGO_DB)

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    def _make_mongo_safe(self, obj):
        """Recursively convert types MongoDB cannot encode (set -> list)."""
        if isinstance(obj, set):
            return [self._make_mongo_safe(i) for i in obj]
        if isinstance(obj, dict):
            return {k: self._make_mongo_safe(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self._make_mongo_safe(i) for i in obj]
        return obj

    def _session_to_doc(self, session: Session) -> dict:
        """Serialize a Session to a MongoDB document."""
        raw_events = []
        for e in (session.events or []):
            try:
                # model_dump may contain set() in long_running_tool_ids — sanitize
                raw_events.append(self._make_mongo_safe(e.model_dump()))
            except Exception:
                pass  # skip unserializable events
        return {
            "session_id": session.id,
            "app_name": session.app_name,
            "user_id": session.user_id,
            "state": self._make_mongo_safe(session.state or {}),
            "events": raw_events,
            "last_update_time": session.last_update_time,
        }

    def _doc_to_session(self, doc: dict) -> Session:
        """Deserialize a MongoDB document back to a Session."""
        events = []
        for e_dict in doc.get("events", []):
            try:
                events.append(Event(**e_dict))
            except Exception:
                pass  # skip malformed events rather than crashing

        return Session(
            id=doc["session_id"],
            app_name=doc["app_name"],
            user_id=doc["user_id"],
            state=doc.get("state", {}),
            events=events,
            last_update_time=doc.get("last_update_time", 0.0),
        )

    # ------------------------------------------------------------------ #
    # BaseSessionService interface                                         #
    # ------------------------------------------------------------------ #

    async def create_session(
        self,
        *,
        app_name: str,
        user_id: str,
        state: Optional[dict[str, Any]] = None,
        session_id: Optional[str] = None,
    ) -> Session:
        """Create and persist a new session."""
        import uuid
        sid = session_id or str(uuid.uuid4())

        session = Session(
            id=sid,
            app_name=app_name,
            user_id=user_id,
            state=state or {},
            events=[],
            last_update_time=time.time(),
        )

        doc = self._session_to_doc(session)
        await self.sessions.update_one(
            {"session_id": sid, "app_name": app_name, "user_id": user_id},
            {"$set": doc},
            upsert=True,
        )

        log.info("session_created", session_id=sid, user_id=user_id, app_name=app_name)
        return session

    async def get_session(
        self,
        *,
        app_name: str,
        user_id: str,
        session_id: str,
        config=None,
    ) -> Optional[Session]:
        """Retrieve a session from MongoDB, or return None if not found."""
        doc = await self.sessions.find_one({
            "session_id": session_id,
            "app_name": app_name,
            "user_id": user_id,
        })

        if not doc:
            log.info("session_not_found", session_id=session_id, user_id=user_id)
            return None

        doc.pop("_id", None)
        session = self._doc_to_session(doc)
        log.info(
            "session_retrieved",
            session_id=session_id,
            user_id=user_id,
            events=len(session.events),
        )
        return session

    async def list_sessions(self, *, app_name: str, user_id: Optional[str] = None):
        """List sessions for a user (returns ADK ListSessionsResponse)."""
        from google.adk.sessions.base_session_service import ListSessionsResponse

        query: dict = {"app_name": app_name}
        if user_id:
            query["user_id"] = user_id

        cursor = self.sessions.find(
            query,
            {"session_id": 1, "user_id": 1, "app_name": 1, "last_update_time": 1, "_id": 0},
        ).sort("last_update_time", -1).limit(50)

        sessions = []
        async for doc in cursor:
            sessions.append(Session(
                id=doc["session_id"],
                app_name=doc["app_name"],
                user_id=doc.get("user_id", ""),
                last_update_time=doc.get("last_update_time", 0.0),
            ))

        return ListSessionsResponse(sessions=sessions)

    async def delete_session(
        self, *, app_name: str, user_id: str, session_id: str
    ) -> None:
        """Delete a session from MongoDB."""
        result = await self.sessions.delete_one({
            "session_id": session_id,
            "app_name": app_name,
            "user_id": user_id,
        })
        if result.deleted_count:
            log.info("session_deleted", session_id=session_id, user_id=user_id)
        else:
            log.warning("session_not_found_for_delete", session_id=session_id)

    async def append_event(self, session: Session, event: Event) -> Event:
        """Append an event to the session and persist it."""
        # Delegate state mutation to the base class (handles state delta merging)
        event = await super().append_event(session=session, event=event)

        # Persist updated session
        doc = self._session_to_doc(session)
        doc["last_update_time"] = time.time()
        await self.sessions.update_one(
            {
                "session_id": session.id,
                "app_name": session.app_name,
                "user_id": session.user_id,
            },
            {"$set": doc},
            upsert=True,
        )

        return event


# Singleton instance
session_service = MongoDBSessionService()