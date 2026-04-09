"""
User repository — MongoDB CRUD + JWT lifecycle + Telegram account management.

Registration rules (mandatory for Telegram):
  Web UI   → POST /auth/register with name + email + password
  Telegram → /register <Name> <email> <password>  in the bot chat
  Both paths create a full account (email + hashed_password always set).

Telegram linking:
  A user registered on web can run /login in the bot to link their chat_id.
  A user registered via bot can log in to the web UI with the same credentials.
  Both point to the same user_id — one account, all data shared.
"""
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
    """MongoDB-backed user store with JWT lifecycle and Telegram account ops."""

    def __init__(self) -> None:
        db = AsyncIOMotorClient(settings.MONGO_URI)[settings.MONGO_DB]
        self._users  = db[COLL_USERS]
        self._tokens = db[COLL_JWT_TOKENS]

    async def create(self, data: UserCreate) -> User:
        """
        Create a web-UI user (email + password required).
        Raises ValueError if email already registered.
        """
        existing = await self._users.find_one({"email": data.email})
        if existing:
            raise ValueError(f"Email already registered: {data.email}")

        user = User(
            name=data.name,
            email=data.email,
            hashed_password=hash_password(data.password),
            role=data.role,
        )
        await self._users.insert_one(user.model_dump())
        log.info("user_created", user_id=user.user_id, email=user.email)
        return user

    async def get_by_id(self, user_id: str) -> Optional[User]:
        doc = await self._users.find_one({"user_id": user_id})
        if not doc:
            return None
        doc.pop("_id", None)
        return User(**doc)

    async def get_user(self, user_id: str) -> dict:
        """Return raw user document as a dict (empty dict when not found)."""
        doc = await self._users.find_one({"user_id": user_id})
        if not doc:
            return {}
        doc.pop("_id", None)
        return doc

    async def get_by_email(self, email: str) -> Optional[User]:
        doc = await self._users.find_one({"email": email})
        if not doc:
            return None
        doc.pop("_id", None)
        return User(**doc)

    async def authenticate(self, email: str, password: str) -> Optional[User]:
        """Verify email + password. Returns User on success, None on failure."""
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
        Return a live JWT for this user — reuse existing if still valid,
        otherwise mint a fresh one and persist it.
        Returns (token_string, expires_in_seconds).
        """
        now = datetime.now(timezone.utc)

        doc = await self._tokens.find_one({
            "user_id":    user.user_id,
            "revoked":    {"$ne": True},
            "expires_at": {"$gt": now},
        })

        if doc:
            expires_at: datetime = doc["expires_at"]
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            remaining = int((expires_at - now).total_seconds())
            log.info("jwt_token_reused", user_id=user.user_id, remaining_secs=remaining)
            return doc["token"], remaining

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
        log.info("jwt_token_minted", user_id=user.user_id, expires_in=expires_in)
        return token, expires_in

    async def revoke_all_tokens(self, user_id: str) -> int:
        """Revoke all tokens for a user (logout / password change)."""
        result = await self._tokens.update_many(
            {"user_id": user_id, "revoked": {"$ne": True}},
            {"$set": {"revoked": True}},
        )
        log.info("jwt_tokens_revoked", user_id=user_id, count=result.modified_count)
        return result.modified_count

    async def update(self, user_id: str, update_fields: dict) -> bool:
        """Update fields on a user document."""
        if not update_fields:
            return False
        payload = dict(update_fields)
        payload["updated_at"] = datetime.now(timezone.utc)
        res = await self._users.update_one(
            {"user_id": user_id},
            {"$set": payload},
        )
        return res.modified_count > 0

    async def update_user(self, user_id: str, update_fields: dict) -> bool:
        """Alias for update(), kept for router compatibility."""
        return await self.update(user_id, update_fields)

    async def clear_fields(self, user_id: str, fields: list[str]) -> bool:
        """Unset a list of fields for the user."""
        if not fields:
            return False
        unset_payload = {f: "" for f in fields}
        res = await self._users.update_one(
            {"user_id": user_id},
            {
                "$unset": unset_payload,
                "$set": {"updated_at": datetime.now(timezone.utc)},
            },
        )
        return res.modified_count > 0


    async def get_by_telegram_chat_id(self, chat_id: int) -> Optional[User]:
        """
        Look up a registered user by their Telegram chat_id.
        Returns None if this chat_id has not been registered yet.
        """
        doc = await self._users.find_one({"telegram_chat_id": chat_id})
        if not doc:
            return None
        doc.pop("_id", None)
        return User(**doc)

    async def register_via_telegram(
        self,
        chat_id:          int,
        name:             str,
        email:            str,
        password:         str,
        telegram_username: Optional[str] = None,
    ) -> User:
        """
        Create a new AIDEN account initiated from the Telegram bot.

        Registration is MANDATORY — no account is created without explicit
        name + email + password from the user.

        Raises ValueError if:
          - email already exists (use /login instead)
          - chat_id already linked to another account
        """
        # Check email uniqueness
        existing_email = await self._users.find_one({"email": email})
        if existing_email:
            raise ValueError(
                f"Email '{email}' is already registered. "
                "Use /login to link this Telegram chat to your account."
            )

        # Check chat_id uniqueness (shouldn't happen, but guard it)
        existing_chat = await self._users.find_one({"telegram_chat_id": chat_id})
        if existing_chat:
            raise ValueError(
                "This Telegram account is already registered. "
                "Use /me to see your account details."
            )

        user = User(
            name=name,
            email=email,
            hashed_password=hash_password(password),
            telegram_chat_id=chat_id,
            telegram_username=telegram_username,
            role=UserRole.USER,
        )
        await self._users.insert_one(user.model_dump())
        log.info(
            "telegram_user_registered",
            chat_id=chat_id,
            user_id=user.user_id,
            email=email,
        )
        return user

    async def login_via_telegram(
        self,
        chat_id:           int,
        email:             str,
        password:          str,
        telegram_username: Optional[str] = None,
    ) -> Optional[User]:
        """
        Link an existing AIDEN account to this Telegram chat_id.

        Used by existing web-UI users who want to access AIDEN via bot.
        Validates email + password, then writes chat_id to their document.

        Returns User on success.
        Returns None if credentials are wrong.
        Raises ValueError if chat_id is already linked to a DIFFERENT account.
        """
        # Validate credentials
        user = await self.authenticate(email, password)
        if not user:
            return None   # wrong email or password

        # Guard: chat_id already linked to a different user
        existing_chat = await self._users.find_one({
            "telegram_chat_id": chat_id,
            "user_id": {"$ne": user.user_id},
        })
        if existing_chat:
            raise ValueError(
                "This Telegram account is already linked to a different AIDEN account. "
                "Use /unlink first if you want to switch."
            )

        # Link chat_id to this account
        await self._users.update_one(
            {"user_id": user.user_id},
            {"$set": {
                "telegram_chat_id":  chat_id,
                "telegram_username": telegram_username,
                "updated_at":        datetime.now(timezone.utc),
            }},
        )
        log.info("telegram_login_linked", chat_id=chat_id, user_id=user.user_id)
        return await self.get_by_id(user.user_id)

    async def unlink_telegram(self, user_id: str) -> None:
        """
        Remove telegram_chat_id from this user's account.
        After unlinking, the user must /register or /login again in the bot.
        """
        await self._users.update_one(
            {"user_id": user_id},
            {"$set": {
                "telegram_chat_id":  None,
                "telegram_username": None,
                "updated_at":        datetime.now(timezone.utc),
            }},
        )
        log.info("telegram_unlinked", user_id=user_id)


# Singleton — imported by middleware, routers, and the bot
user_repo = UserRepository()
