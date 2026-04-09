from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from motor.motor_asyncio import AsyncIOMotorClient

from src.api.middleware import get_current_active_user
from src.core.config import settings

router = APIRouter(prefix="/settings", tags=["Settings"])

db = AsyncIOMotorClient(settings.MONGO_URI)[settings.MONGO_DB]


@router.get("/telegram/link-code")
async def get_telegram_link_code(current_user=Depends(get_current_active_user)):
    """Generate a one-time 10-minute code for linking web account to Telegram."""
    code = secrets.token_urlsafe(12)
    await db["telegram_link_codes"].insert_one(
        {
            "code": code,
            "user_id": current_user.user_id,
            "expires_at": datetime.now(timezone.utc) + timedelta(minutes=10),
            "used": False,
            "created_at": datetime.now(timezone.utc),
        }
    )
    return {
        "bot_url": "https://t.me/Aiden_v4_bot",
        "deep_link": f"https://t.me/Aiden_v4_bot?start=link_{code}",
        "code": code,
        "expires_in_minutes": 10,
        "instructions": "Open the link above in Telegram to connect your account.",
    }
