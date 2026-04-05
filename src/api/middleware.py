from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Annotated, Optional

import structlog
from fastapi import Depends, Header, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext

from src.core.config import settings
from src.models.user import UserClaims, UserRole

log = structlog.get_logger()

pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")

def hash_password(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)

_bearer = HTTPBearer(auto_error=False)


def create_access_token(
    user_id: str,
    role:    UserRole,
    email:   Optional[str] = None,
    name:    Optional[str] = None,
) -> tuple[str, int]:
    """Mint a signed JWT. Returns (token, expires_in_seconds)."""
    now    = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=settings.JWT_EXPIRE_MINUTES)
    payload = {
        "sub":   user_id,
        "role":  role.value,
        "email": email,
        "name":  name,
        "exp":   expire,
        "iat":   now,
    }
    token = jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
    log.info("jwt_token_created", user_id=user_id, expires_in=settings.JWT_EXPIRE_MINUTES)
    return token, settings.JWT_EXPIRE_MINUTES * 60


def _decode_jwt(token: str) -> UserClaims:
    """Decode a JWT and return UserClaims. Raises HTTP 401 on any failure."""
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(401, "Invalid token: missing user_id")
        return UserClaims(
            user_id=user_id,
            role=UserRole(payload.get("role", "user")),
            email=payload.get("email"),
            name=payload.get("name"),
        )
    except JWTError as exc:
        log.warning("jwt_validation_failed", error=str(exc))
        raise HTTPException(401, "Invalid or expired token")


async def _resolve_telegram_user(
    x_bot_secret:       Optional[str],
    x_telegram_chat_id: Optional[str],
) -> Optional[UserClaims]:
    """
    Validate bot headers and resolve the Telegram user to UserClaims.

    Returns None  — headers not present (not a bot request, try JWT path).
    Raises 503    — BOT_SERVICE_SECRET not configured on server.
    Raises 403    — wrong secret (possible spoofing attempt).
    Raises 400    — malformed chat_id header.
    Raises 404    — chat_id not registered (bot should show /register prompt).
    """
    # Neither header present → not a bot request
    if not x_bot_secret and not x_telegram_chat_id:
        return None

    # Secret not configured server-side
    if not settings.BOT_SERVICE_SECRET:
        raise HTTPException(503, "Telegram gateway not configured (BOT_SERVICE_SECRET missing in .env)")

    # Wrong secret
    if x_bot_secret != settings.BOT_SERVICE_SECRET:
        log.warning("bot_secret_invalid", hint="Check BOT_SERVICE_SECRET in .env")
        raise HTTPException(403, "Invalid bot service secret")

    # chat_id missing or malformed
    if not x_telegram_chat_id:
        raise HTTPException(400, "X-Telegram-Chat-Id header is required alongside X-Bot-Secret")
    try:
        chat_id = int(x_telegram_chat_id)
    except ValueError:
        raise HTTPException(400, "X-Telegram-Chat-Id must be an integer")

    # Lookup — lazy import avoids circular dependency at module load
    from src.repositories.user_repo import user_repo
    user = await user_repo.get_by_telegram_chat_id(chat_id)

    if not user:
        # 404 signals the bot: this chat_id has no account → show /register prompt
        raise HTTPException(
            404,
            "NOT_REGISTERED",   # bot reads this exact string to show the right message
        )

    if not user.is_active:
        raise HTTPException(403, "Account is deactivated")

    log.debug("telegram_gateway_ok", chat_id=chat_id, user_id=user.user_id)
    return UserClaims(
        user_id=user.user_id,
        role=user.role,
        email=user.email,
        name=user.name,
    )


async def get_current_user(
    request:            Request,
    credentials:        Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
    x_bot_secret:       Annotated[Optional[str], Header()] = None,
    x_telegram_chat_id: Annotated[Optional[str], Header()] = None,
) -> UserClaims:
    """
    Dual-path authentication. Used by every existing router unchanged.

    Priority:
      1. Telegram gateway (X-Bot-Secret + X-Telegram-Chat-Id headers)
      2. JWT bearer token
      3. Neither → HTTP 401
    """
    # Path 1 — Telegram bot
    tg_user = await _resolve_telegram_user(x_bot_secret, x_telegram_chat_id)
    if tg_user:
        return tg_user

    # Path 2 — JWT
    if credentials:
        return _decode_jwt(credentials.credentials)

    raise HTTPException(
        401,
        "Authentication required. Provide 'Authorization: Bearer <token>' "
        "or Telegram bot headers.",
    )


async def get_current_active_user(
    current_user: UserClaims = Depends(get_current_user),
) -> UserClaims:
    """Thin pass-through kept for backwards-compat with all existing routers."""
    return current_user


def require_role(*allowed_roles: UserRole):
    """Role-based access control decorator factory."""
    async def _check(current_user: UserClaims = Depends(get_current_user)) -> UserClaims:
        if current_user.role not in allowed_roles:
            log.warning(
                "access_denied",
                user_id=current_user.user_id,
                role=current_user.role,
                required=[r.value for r in allowed_roles],
            )
            raise HTTPException(
                403,
                f"Access denied. Required roles: {[r.value for r in allowed_roles]}",
            )
        return current_user
    return _check


# ── Per-user data isolation helpers ──────────────────────────────────────────

def get_user_collection(user_id: str, collection: str) -> str:
    """Namespaced MongoDB collection: '<user_id>__<collection>'."""
    return f"{user_id}__{collection}"

def get_user_chroma_collection(user_id: str) -> str:
    """Namespaced ChromaDB collection for semantic search."""
    return f"notes_{user_id}"
