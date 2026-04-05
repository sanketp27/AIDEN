from __future__ import annotations
import base64
import os
from typing import Optional, Any

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

log = structlog.get_logger()
router = APIRouter(prefix="/settings", tags=["Settings"])


def _get_fernet():
    try:
        from cryptography.fernet import Fernet
        raw = os.environ.get("JWT_SECRET", "default-secret-change-me")
        key_bytes = raw.encode()[:32].ljust(32, b"\x00")
        return Fernet(base64.urlsafe_b64encode(key_bytes))
    except ImportError:
        return None


def encrypt_token(token: str) -> str:
    f = _get_fernet()
    return f.encrypt(token.encode()).decode() if f else token


def decrypt_token(encrypted: str) -> str:
    f = _get_fernet()
    if not f:
        return encrypted
    try:
        return f.decrypt(encrypted.encode()).decode()
    except Exception:
        return encrypted

async def get_current_user_dep() -> dict:
    """Replace with: from src.api.middleware import get_current_active_user"""
    return {"user_id": "demo_user", "email": "demo@aiden.ai"}


async def get_user_repo_dep() -> Any:
    """Replace with: from src.repositories.user_repo import user_repo"""
    from src.repositories.user_repo import user_repo as _repo
    return _repo

class DeveloperSettingsPayload(BaseModel):
    enabled: bool
    github_token: Optional[str] = None

    class Config:
        json_schema_extra = {
            "example": {"enabled": True, "github_token": "ghp_xxxx"}
        }


@router.get("/developer", summary="Get developer mode status")
async def get_developer_settings(
    current_user: dict = Depends(get_current_user_dep),
    user_repo: Any    = Depends(get_user_repo_dep),
):
    """Return current developer mode status for the authenticated user."""
    user_id = current_user["user_id"]
    user    = await user_repo.get_by_id(user_id)
    if not user:
        return {"developer_mode": False, "github_connected": False}
    return {
        "developer_mode":   getattr(user, 'is_developer', False),
        "github_connected": bool(getattr(user, 'github_token', None)),
        "notion_connected": getattr(user, 'notion_connected', False),
    }


@router.patch("/developer", summary="Enable or disable developer mode")
async def update_developer_settings(
    payload:      DeveloperSettingsPayload,
    current_user: dict = Depends(get_current_user_dep),
    user_repo:    Any  = Depends(get_user_repo_dep),
):
    """
    Enable/disable developer mode. When enabled with a github_token,
    the token is Fernet-encrypted and stored in MongoDB.
    GitHub MCP tools activate on the next conversation session.
    """
    user_id = current_user["user_id"]
    update: dict = {"is_developer": payload.enabled}

    if payload.enabled and payload.github_token:
        update["github_token"] = encrypt_token(payload.github_token)
        log.info("developer_settings.token_stored",
                 user_id=user_id,
                 prefix=payload.github_token[:8] + "...")
    elif not payload.enabled:
        update["github_token"] = None
        log.info("developer_settings.token_cleared", user_id=user_id)

    await user_repo.update(user_id, update)

    return {
        "developer_mode":   payload.enabled,
        "github_connected": bool(payload.github_token) and payload.enabled,
        "message": (
            "Developer mode enabled. GitHub MCP tools active on next session."
            if payload.enabled
            else "Developer mode disabled."
        ),
    }
