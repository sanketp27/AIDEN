"""
AIDEN Connector Management API
Handles status, OAuth initiation, and disconnection for third-party integrations.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from src.api.middleware import get_current_active_user
from src.repositories.user_repo import user_repo

router = APIRouter(prefix="/settings/connectors", tags=["Connectors"])


@router.get("")
async def list_connectors(current_user=Depends(get_current_active_user)):
    """Return available connectors + connection status for the current user."""
    user = await user_repo.get_user(current_user.user_id)

    return {
        "connectors": [
            {
                "id": "google_workspace",
                "name": "Google Workspace",
                "description": "Calendar, Gmail, Drive, Google Tasks — all in one connection",
                "services": ["Calendar", "Gmail", "Drive", "Google Tasks"],
                "connected": bool(user.get("google_access_token")),
                "connected_email": user.get("google_email"),
                "oauth_url": "/auth/google/start",
                "icon": "google",
            },
            {
                "id": "notion",
                "name": "Notion",
                "description": "Team wiki, project databases, and shared knowledge base",
                "services": ["Pages", "Databases", "Team Wiki"],
                "connected": bool(user.get("notion_token_encrypted")),
                "connected_workspace": user.get("notion_workspace_name"),
                "oauth_url": "/auth/notion/start",
                "icon": "notion",
            },
            {
                "id": "telegram",
                "name": "Telegram",
                "description": "Chat with AIDEN, receive proactive alerts, and send voice notes",
                "services": ["Chat", "Push Notifications", "Voice Notes", "File Upload"],
                "connected": bool(user.get("telegram_chat_id")),
                "connected_username": user.get("telegram_username"),
                "bot_url": "https://t.me/Aiden_v4_bot",
                "link_code_url": "/settings/telegram/link-code",
                "icon": "telegram",
            },
            {
                "id": "github",
                "name": "GitHub",
                "description": "Issues, PRs, and repositories — developer mode only",
                "services": ["Issues", "Pull Requests", "Repositories"],
                "connected": user.get("is_developer", False) and bool(user.get("github_token")),
                "requires_developer_mode": True,
                "setup_url": "/settings/developer",
                "icon": "github",
            },
        ]
    }


@router.delete("/{connector_id}")
async def disconnect_connector(connector_id: str, current_user=Depends(get_current_active_user)):
    """Disconnect a connector and clear its stored tokens/metadata."""
    field_map = {
        "google_workspace": [
            "google_access_token",
            "google_refresh_token",
            "google_email",
            "calendar_connected",
            "gmail_connected",
            "google_connected_at",
        ],
        "notion": [
            "notion_token_encrypted",
            "notion_workspace_name",
            "notion_workspace_id",
            "notion_connected",
            "notion_connected_at",
        ],
    }
    fields = field_map.get(connector_id)
    if not fields:
        raise HTTPException(status_code=404, detail=f"Unknown connector: {connector_id}")

    await user_repo.clear_fields(current_user.user_id, fields)
    return {"disconnected": connector_id, "user_id": current_user.user_id}
