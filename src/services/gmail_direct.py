"""
Gmail Direct API Client (replaces GmailMCPClient)
===================================================
Uses the Gmail REST API with OAuth2 access tokens directly.
No MCP server required.

Auth flow:
  1. User visits GET /auth/gmail  → redirected to Google consent screen
  2. Google redirects to GET /auth/gmail/callback?code=...
  3. Server exchanges code for access_token + refresh_token
  4. Tokens stored in `user_credentials` MongoDB collection (encrypted at rest)
  5. GmailDirectClient auto-refreshes the access_token when it expires

Scopes needed:
  https://www.googleapis.com/auth/gmail.readonly
  https://www.googleapis.com/auth/gmail.modify   (to mark as read)
"""
from __future__ import annotations

import base64
import json
import time
from datetime import datetime, timezone
from typing import Optional

import httpx
import structlog

from src.core.config import settings

log = structlog.get_logger()

GMAIL_API_BASE  = "https://gmail.googleapis.com/gmail/v1"
OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"
OAUTH_AUTH_URL  = "https://accounts.google.com/o/oauth2/v2/auth"
GMAIL_SCOPES    = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.modify",
]

class CredentialStore:
    """Stores per-user OAuth tokens in MongoDB `user_credentials` collection."""

    def __init__(self):
        from motor.motor_asyncio import AsyncIOMotorClient
        self._col = AsyncIOMotorClient(settings.MONGO_URI)[settings.MONGO_DB]["user_credentials"]

    async def save(self, user_id: str, service: str, creds: dict) -> None:
        creds["saved_at"] = datetime.now(timezone.utc)
        await self._col.update_one(
            {"user_id": user_id, "service": service},
            {"$set": {"user_id": user_id, "service": service, **creds}},
            upsert=True,
        )

    async def load(self, user_id: str, service: str) -> Optional[dict]:
        doc = await self._col.find_one({"user_id": user_id, "service": service})
        if doc:
            doc.pop("_id", None)
        return doc

    async def delete(self, user_id: str, service: str) -> None:
        await self._col.delete_one({"user_id": user_id, "service": service})

    async def list_connected_users(self, service: str) -> list[str]:
        cursor = self._col.find({"service": service}, {"user_id": 1})
        return [doc["user_id"] async for doc in cursor]


cred_store = CredentialStore()

class GmailDirectClient:
    """
    Async Gmail REST API client.
    Accepts an OAuth2 access_token (short-lived) and a refresh_token to
    automatically renew it.
    """

    def __init__(
        self,
        access_token:  str,
        refresh_token: str,
        expires_at:    float = 0,   # unix timestamp
        user_id:       str = "",
    ) -> None:
        self.access_token  = access_token
        self.refresh_token = refresh_token
        self.expires_at    = expires_at
        self.user_id       = user_id
        self._http: Optional[httpx.AsyncClient] = None

    @property
    def _client(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=30)
        return self._http

    async def _ensure_token(self) -> None:
        """Refresh the access token if it expires within 60 seconds."""
        if time.time() < self.expires_at - 60:
            return
        if not settings.GMAIL_CLIENT_ID or not settings.GMAIL_CLIENT_SECRET:
            log.warning("gmail_token_refresh_skipped", reason="no client credentials configured")
            return

        resp = await self._client.post(OAUTH_TOKEN_URL, data={
            "client_id":     settings.GMAIL_CLIENT_ID,
            "client_secret": settings.GMAIL_CLIENT_SECRET,
            "refresh_token": self.refresh_token,
            "grant_type":    "refresh_token",
        })
        if resp.status_code == 200:
            data = resp.json()
            self.access_token = data["access_token"]
            self.expires_at   = time.time() + data.get("expires_in", 3600)
            # Persist refreshed token
            if self.user_id:
                await cred_store.save(self.user_id, "gmail", {
                    "access_token":  self.access_token,
                    "refresh_token": self.refresh_token,
                    "expires_at":    self.expires_at,
                })
            log.info("gmail_token_refreshed", user_id=self.user_id)
        else:
            log.error("gmail_token_refresh_failed",
                      status=resp.status_code, body=resp.text[:200])

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.access_token}"}

    async def list_messages(
        self,
        max_results: int = 20,
        query: str = "is:unread",
    ) -> list[dict]:
        await self._ensure_token()
        resp = await self._client.get(
            f"{GMAIL_API_BASE}/users/me/messages",
            headers=self._headers(),
            params={"maxResults": max_results, "q": query},
        )
        resp.raise_for_status()
        return resp.json().get("messages", [])   # [{id, threadId}, ...]

    async def get_message(self, msg_id: str) -> dict:
        await self._ensure_token()
        resp = await self._client.get(
            f"{GMAIL_API_BASE}/users/me/messages/{msg_id}",
            headers=self._headers(),
            params={"format": "full"},
        )
        resp.raise_for_status()
        return resp.json()

    async def mark_as_read(self, msg_id: str) -> None:
        await self._ensure_token()
        await self._client.post(
            f"{GMAIL_API_BASE}/users/me/messages/{msg_id}/modify",
            headers=self._headers(),
            json={"removeLabelIds": ["UNREAD"]},
        )

    async def close(self) -> None:
        if self._http:
            await self._http.aclose()
            self._http = None


def extract_email_parts(msg: dict) -> tuple[str, str, str, str, str]:
    """
    Returns (subject, sender, date, body_text, snippet) from a full Gmail message.
    """
    headers = {
        h["name"].lower(): h["value"]
        for h in msg.get("payload", {}).get("headers", [])
    }
    subject = headers.get("subject", "(no subject)")
    sender  = headers.get("from", "")
    date    = headers.get("date", "")
    snippet = msg.get("snippet", "")
    body    = _extract_text(msg.get("payload", {}))
    return subject, sender, date, body or snippet, snippet


def _extract_text(payload: dict) -> str:
    mime = payload.get("mimeType", "")
    if mime == "text/plain":
        data = payload.get("body", {}).get("data", "")
        if data:
            return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")
    for part in payload.get("parts", []):
        result = _extract_text(part)
        if result:
            return result
    return ""


async def get_gmail_client_for_user(user_id: str) -> Optional[GmailDirectClient]:
    """Load stored credentials and return a ready-to-use GmailDirectClient."""
    creds = await cred_store.load(user_id, "gmail")
    if not creds:
        return None
    return GmailDirectClient(
        access_token=creds["access_token"],
        refresh_token=creds["refresh_token"],
        expires_at=creds.get("expires_at", 0),
        user_id=user_id,
    )
