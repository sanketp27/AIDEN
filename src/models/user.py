"""
AIDEN v3.0 — User & Authentication Models
==========================================
Merged from final project + v3.0 developer mode fields.

New in v3.0:
  - is_developer  (bool)  — unlocks GitHub MCP tools
  - github_token  (str)   — encrypted PAT stored in MongoDB
  - notion_connected (bool) — Notion workspace connection status
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional
import uuid

from pydantic import BaseModel, Field


class UserRole(str, Enum):
    EXECUTIVE = "executive"
    USER      = "user"
    DEVELOPER = "developer"
    GUEST     = "guest"


class UserClaims(BaseModel):
    """
    Resolved identity injected into every FastAPI endpoint
    via get_current_user().
    """
    user_id: str
    role:    UserRole
    email:   Optional[str] = None
    name:    Optional[str] = None


class User(BaseModel):
    """Full persisted user document (MongoDB `users` collection)."""
    user_id:  str = Field(default_factory=lambda: str(uuid.uuid4()))
    name:     str
    email:    str
    hashed_password: str

    # Telegram identity
    telegram_chat_id:  Optional[int] = None
    telegram_username: Optional[str] = None

    role:          UserRole    = UserRole.USER
    api_keys:      list[str]   = Field(default_factory=list)
    webhook_url:   Optional[str] = None
    briefing_time: str           = "08:00"
    is_active:     bool          = True
    created_at:    datetime      = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at:    datetime      = Field(default_factory=lambda: datetime.now(timezone.utc))

    gmail_connected:    bool = False
    calendar_connected: bool = False
    drive_connected:    bool = False

    notion_connected: bool          = False
    is_developer:     bool          = False    # Unlocks GitHub MCP tools
    github_token:     Optional[str] = None     # Fernet-encrypted PAT


class UserCreate(BaseModel):
    email:    str
    name:     str
    password: str
    role:     UserRole = UserRole.USER


class UserLogin(BaseModel):
    email:    str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type:   str = "bearer"
    expires_in:   int
    user_id:      str
    email:        Optional[str] = None
    name:         Optional[str] = None
    role:         str


class APIKeyCreate(BaseModel):
    description: Optional[str] = None


class APIKeyResponse(BaseModel):
    key:         str
    description: Optional[str] = None
    created_at:  str


class DeveloperSettingsUpdate(BaseModel):
    """Payload for PATCH /settings/developer"""
    enabled:      bool
    github_token: Optional[str] = Field(
        default=None,
        description="GitHub Personal Access Token (repo, read:user scopes)."
    )

    class Config:
        json_schema_extra = {
            "example": {
                "enabled": True,
                "github_token": "ghp_xxxxxxxxxxxxxxxxxxxx",
            }
        }
