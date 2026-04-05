"""
Google Drive service — thin async wrapper around Drive REST API v3.
Shares the same OAuth credential store as Gmail/Calendar.
"""
from __future__ import annotations

import time
from typing import Optional
import httpx
import structlog

from src.core.config import settings
from src.services.gmail_direct import cred_store  # reuse OAuth store

log = structlog.get_logger()

DRIVE_API = "https://www.googleapis.com/drive/v3"
OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"
DRIVE_SCOPES = [
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/drive.metadata.readonly",
]


class GoogleDriveClient:
    """
    Async Google Drive API v3 client with automatic token refresh.
    Covers file search, metadata retrieval, and content export.
    """

    def __init__(
        self,
        user_id: str,
        access_token: str,
        refresh_token: str,
        expires_at: float,
    ) -> None:
        self.user_id = user_id
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.expires_at = expires_at

    async def _refresh_if_needed(self) -> None:
        if time.time() < self.expires_at - 60:
            return

        if not self.refresh_token:
            raise PermissionError("No refresh token. User must reconnect Google Drive.")

        async with httpx.AsyncClient() as c:
            resp = await c.post(OAUTH_TOKEN_URL, data={
                "client_id":     settings.GMAIL_CLIENT_ID,
                "client_secret": settings.GMAIL_CLIENT_SECRET,
                "refresh_token": self.refresh_token,
                "grant_type":    "refresh_token",
            })

        if resp.status_code != 200:
            raise PermissionError(f"Token refresh failed: {resp.text}")

        data = resp.json()
        self.access_token = data["access_token"]
        self.expires_at   = time.time() + data.get("expires_in", 3600)

        await cred_store.save(self.user_id, "drive", {
            "access_token":  self.access_token,
            "refresh_token": self.refresh_token,
            "expires_at":    self.expires_at,
        })
        log.info("drive_token_refreshed", user_id=self.user_id)

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.access_token}"}

    async def search_files(
        self,
        query: str,
        max_results: int = 10,
        mime_type: Optional[str] = None,
    ) -> list[dict]:
        """
        Full-text search across user's Drive files.
        Returns list of file metadata dicts.
        """
        await self._refresh_if_needed()

        q_parts = [f"fullText contains '{query}'", "trashed = false"]
        if mime_type:
            q_parts.append(f"mimeType = '{mime_type}'")

        params = {
            "q":        " and ".join(q_parts),
            "pageSize": max_results,
            "fields":   "files(id,name,mimeType,modifiedTime,webViewLink,size)",
            "orderBy":  "modifiedTime desc",
        }

        async with httpx.AsyncClient() as c:
            resp = await c.get(f"{DRIVE_API}/files", headers=self._headers(), params=params)

        if resp.status_code != 200:
            log.warning("drive_search_failed", status=resp.status_code, query=query)
            return []

        files = resp.json().get("files", [])
        log.info("drive_search_complete", query=query, results=len(files))
        return files

    async def get_file_content(
        self,
        file_id: str,
        export_mime: str = "text/plain",
    ) -> str:
        """
        Export a Google Docs/Sheets/Slides file as plain text (or other mime).
        For binary files returns a placeholder message.
        """
        await self._refresh_if_needed()

        # First get metadata to determine mime type
        async with httpx.AsyncClient() as c:
            meta_resp = await c.get(
                f"{DRIVE_API}/files/{file_id}",
                headers=self._headers(),
                params={"fields": "id,name,mimeType"},
            )

        if meta_resp.status_code != 200:
            return f"Could not retrieve file metadata (status {meta_resp.status_code})"

        meta = meta_resp.json()
        mime = meta.get("mimeType", "")

        # Google Workspace files need export
        google_workspace_mimes = {
            "application/vnd.google-apps.document":     "text/plain",
            "application/vnd.google-apps.spreadsheet":  "text/csv",
            "application/vnd.google-apps.presentation": "text/plain",
        }

        if mime in google_workspace_mimes:
            export_mime = google_workspace_mimes[mime]
            async with httpx.AsyncClient() as c:
                resp = await c.get(
                    f"{DRIVE_API}/files/{file_id}/export",
                    headers=self._headers(),
                    params={"mimeType": export_mime},
                )
            if resp.status_code == 200:
                text = resp.text[:8000]  # cap at 8k chars for context window
                log.info("drive_file_exported", file_id=file_id, chars=len(text))
                return text
            return f"Could not export file (status {resp.status_code})"

        # Binary file — return a useful message rather than raw bytes
        return f"Binary file '{meta.get('name', file_id)}' (type: {mime}) — cannot display as text."

    async def list_recent_files(self, max_results: int = 15) -> list[dict]:
        """List the user's most recently modified files."""
        await self._refresh_if_needed()

        params = {
            "pageSize": max_results,
            "fields":   "files(id,name,mimeType,modifiedTime,webViewLink)",
            "orderBy":  "modifiedTime desc",
            "q":        "trashed = false",
        }

        async with httpx.AsyncClient() as c:
            resp = await c.get(f"{DRIVE_API}/files", headers=self._headers(), params=params)

        if resp.status_code != 200:
            log.warning("drive_list_failed", status=resp.status_code)
            return []

        return resp.json().get("files", [])


async def get_drive_client(user_id: str) -> Optional[GoogleDriveClient]:
    """
    Factory — loads saved OAuth credentials for the user.
    Returns None if the user has not connected Google Drive.
    """
    creds = await cred_store.load(user_id, "drive")
    if not creds:
        return None

    return GoogleDriveClient(
        user_id=user_id,
        access_token=creds.get("access_token", ""),
        refresh_token=creds.get("refresh_token", ""),
        expires_at=creds.get("expires_at", 0.0),
    )
