from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

import structlog
from motor.motor_asyncio import AsyncIOMotorClient

from src.api.middleware import create_access_token, hash_password, verify_password
from src.core.config import settings
from src.core.db_init import COLL_USERS, COLL_JWT_TOKENS
from src.models.user import User, UserCreate, UserRole

log = structlog.get_logger()


class UserRepository:
    """MongoDB-backed user store + JWT token lifecycle manager."""

    def __init__(self) -> None:
        db = AsyncIOMotorClient(settings.MONGO_URI)[settings.MONGO_DB]
        self._users = db[COLL_USERS]
        self._tokens = db[COLL_JWT_TOKENS]

    async def create(self, data: UserCreate) -> User:
        """Create a new user. Raises ValueError if email already exists."""
        existing = await self._users.find_one({"email": data.email})
        if existing:
            raise ValueError(f"Email already registered: {data.email}")

        user = User(
            email=data.email,
            name=data.name,
            hashed_password=hash_password(data.password),
            role=data.role,
        )
        doc = user.model_dump()
        # Convert datetime objects to proper BSON dates (motor handles this)
        await self._users.insert_one(doc)
        log.info("user_created", user_id=user.user_id, email=user.email)
        return user

    async def get_by_email(self, email: str) -> Optional[User]:
        """Fetch user by email address."""
        doc = await self._users.find_one({"email": email})
        if not doc:
            return None
        doc.pop("_id", None)
        return User(**doc)

    async def get_by_id(self, user_id: str) -> Optional[User]:
        """Fetch user by user_id."""
        doc = await self._users.find_one({"user_id": user_id})
        if not doc:
            return None
        doc.pop("_id", None)
        return User(**doc)

    async def authenticate(self, email: str, password: str) -> Optional[User]:
        """Verify credentials. Returns User on success, None on failure."""
        user = await self.get_by_email(email)
        if not user:
            return None
        if not verify_password(password, user.hashed_password):
            return None
        if not user.is_active:
            return None
        return user

    async def get_or_create_token(self, user: User) -> tuple[str, int]:
        """
        Return a valid JWT for the user.

        1. Look up jwt_tokens collection for an existing, non-expired token.
        2. If found → return it (no new JWT issued).
        3. If not found or expired → mint a new JWT, persist it, return it.

        Returns (token_string, expires_in_seconds).
        """
        now = datetime.now(timezone.utc)

        # Try to find an existing live token
        doc = await self._tokens.find_one({
            "user_id": user.user_id,
            "revoked": {"$ne": True},
            "expires_at": {"$gt": now},
        })

        if doc:
            expires_at: datetime = doc["expires_at"]
            # Make sure expires_at is timezone-aware
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            remaining = int((expires_at - now).total_seconds())
            log.info("jwt_token_reused", user_id=user.user_id, remaining_secs=remaining)
            return doc["token"], remaining

        # Mint a fresh token
        token, expires_in = create_access_token(
            user_id=user.user_id,
            role=user.role,
            email=user.email,
            name=user.name,
        )
        expires_at = now + timedelta(seconds=expires_in)

        await self._tokens.insert_one({
            "user_id":    user.user_id,
            "token":      token,
            "expires_at": expires_at,
            "created_at": now,
            "revoked":    False,
        })
        log.info("jwt_token_created", user_id=user.user_id, expires_in=expires_in)
        return token, expires_in

    async def revoke_all_tokens(self, user_id: str) -> int:
        """Revoke all active tokens for a user (e.g. on logout or password change)."""
        result = await self._tokens.update_many(
            {"user_id": user_id, "revoked": {"$ne": True}},
            {"$set": {"revoked": True}},
        )
        log.info("jwt_tokens_revoked", user_id=user_id, count=result.modified_count)
        return result.modified_count


# Singleton
user_repo = UserRepository()
