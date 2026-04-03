from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
import structlog

from src.core.config import settings
from src.services.gmail_direct import cred_store   # reuse the same store

log = structlog.get_logger()

CAL_API = "https://www.googleapis.com/calendar/v3"
CALENDAR_SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/calendar.events",
]
OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"


class GoogleCalendarClient:
    """
    Thin async wrapper around Google Calendar REST API v3.
    Automatically refreshes the access token when it expires.
    """

    def __init__(
        self,
        user_id: str,
        access_token: str,
        refresh_token: str,
        expires_at: float,
    ) -> None:
        self.user_id       = user_id
        self.access_token  = access_token
        self.refresh_token = refresh_token
        self.expires_at    = expires_at

    async def _refresh_if_needed(self) -> None:
        if time.time() < self.expires_at - 60:
            return                     # still valid

        if not self.refresh_token:
            raise PermissionError("No refresh token available. User must reconnect Calendar.")

        async with httpx.AsyncClient() as c:
            resp = await c.post(OAUTH_TOKEN_URL, data={
                "client_id":     settings.GMAIL_CLIENT_ID,
                "client_secret": settings.GMAIL_CLIENT_SECRET,
                "refresh_token": self.refresh_token,
                "grant_type":    "refresh_token",
            })

        if resp.status_code != 200:
            raise PermissionError(f"Token refresh failed: {resp.text}")

        data             = resp.json()
        self.access_token = data["access_token"]
        self.expires_at   = time.time() + data.get("expires_in", 3600)

        # Persist refreshed token
        await cred_store.save(self.user_id, "calendar", {
            "access_token":  self.access_token,
            "refresh_token": self.refresh_token,
            "expires_at":    self.expires_at,
        })
        log.info("calendar_token_refreshed", user_id=self.user_id)

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.access_token}"}

    async def list_events(
        self,
        time_min: Optional[datetime] = None,
        time_max: Optional[datetime] = None,
        max_results: int = 20,
        calendar_id: str = "primary",
    ) -> list[dict]:
        """Return upcoming events in the given time window."""
        await self._refresh_if_needed()

        if time_min is None:
            time_min = datetime.now(timezone.utc)
        if time_max is None:
            time_max = time_min + timedelta(days=7)

        params = {
            "timeMin":    time_min.isoformat(),
            "timeMax":    time_max.isoformat(),
            "maxResults": max_results,
            "orderBy":    "startTime",
            "singleEvents": "true",
        }

        async with httpx.AsyncClient() as c:
            resp = await c.get(
                f"{CAL_API}/calendars/{calendar_id}/events",
                headers=self._headers(), params=params,
            )

        if resp.status_code != 200:
            log.error("calendar_list_failed", status=resp.status_code, body=resp.text)
            raise RuntimeError(f"Calendar API error: {resp.status_code}")

        return resp.json().get("items", [])

    async def get_todays_events(self) -> list[dict]:
        """Convenience: events for today (midnight → midnight local)."""
        now   = datetime.now(timezone.utc)
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end   = start + timedelta(days=1)
        return await self.list_events(start, end, max_results=50)

    async def get_weeks_events(self) -> list[dict]:
        """Convenience: events for the next 7 days."""
        now = datetime.now(timezone.utc)
        return await self.list_events(now, now + timedelta(days=7), max_results=50)

    async def create_event(
        self,
        title:       str,
        start:       datetime,
        end:         datetime,
        description: str = "",
        attendees:   Optional[list[str]] = None,
        location:    str = "",
        calendar_id: str = "primary",
    ) -> dict:
        """Create a calendar event. Returns the created event object."""
        await self._refresh_if_needed()

        body: dict = {
            "summary":     title,
            "description": description,
            "location":    location,
            "start": {"dateTime": start.isoformat(), "timeZone": "UTC"},
            "end":   {"dateTime": end.isoformat(),   "timeZone": "UTC"},
        }
        if attendees:
            body["attendees"] = [{"email": e} for e in attendees]

        async with httpx.AsyncClient() as c:
            resp = await c.post(
                f"{CAL_API}/calendars/{calendar_id}/events",
                headers=self._headers(), json=body,
            )

        if resp.status_code not in (200, 201):
            raise RuntimeError(f"Create event failed: {resp.status_code} {resp.text}")

        event = resp.json()
        log.info("calendar_event_created", event_id=event.get("id"), title=title)
        return event

    async def delete_event(self, event_id: str, calendar_id: str = "primary") -> None:
        """Delete a calendar event by ID."""
        await self._refresh_if_needed()
        async with httpx.AsyncClient() as c:
            resp = await c.delete(
                f"{CAL_API}/calendars/{calendar_id}/events/{event_id}",
                headers=self._headers(),
            )
        if resp.status_code not in (200, 204):
            raise RuntimeError(f"Delete event failed: {resp.status_code}")
        log.info("calendar_event_deleted", event_id=event_id)

    async def check_conflicts(
        self,
        start: datetime,
        end:   datetime,
        calendar_id: str = "primary",
    ) -> list[dict]:
        """Return any events that overlap with [start, end]."""
        events = await self.list_events(start, end, max_results=50)
        return events   # all events in the window are potential conflicts

    async def find_free_slots(
        self,
        date: datetime,
        duration_minutes: int = 60,
        business_hours: tuple[int, int] = (9, 18),
    ) -> list[dict]:
        """
        Return available time slots on `date` lasting at least `duration_minutes`.
        Simple algorithm: walks business hours and gaps between events.
        """
        start_of_day = date.replace(hour=business_hours[0], minute=0, second=0, microsecond=0, tzinfo=timezone.utc)
        end_of_day   = date.replace(hour=business_hours[1], minute=0, second=0, microsecond=0, tzinfo=timezone.utc)

        events = await self.list_events(start_of_day, end_of_day, max_results=50)

        # Build list of busy windows
        busy: list[tuple[datetime, datetime]] = []
        for ev in events:
            s = ev.get("start", {})
            e = ev.get("end",   {})
            try:
                t_start = datetime.fromisoformat(s.get("dateTime", s.get("date", "")))
                t_end   = datetime.fromisoformat(e.get("dateTime", e.get("date", "")))
                busy.append((t_start, t_end))
            except Exception:
                continue

        busy.sort(key=lambda x: x[0])

        free_slots = []
        cursor = start_of_day

        for b_start, b_end in busy:
            if cursor < b_start:
                gap_minutes = int((b_start - cursor).total_seconds() / 60)
                if gap_minutes >= duration_minutes:
                    free_slots.append({
                        "start": cursor.isoformat(),
                        "end":   b_start.isoformat(),
                        "duration_minutes": gap_minutes,
                    })
            cursor = max(cursor, b_end)

        # Trailing slot after last event
        if cursor < end_of_day:
            gap_minutes = int((end_of_day - cursor).total_seconds() / 60)
            if gap_minutes >= duration_minutes:
                free_slots.append({
                    "start": cursor.isoformat(),
                    "end":   end_of_day.isoformat(),
                    "duration_minutes": gap_minutes,
                })

        return free_slots


async def get_calendar_client(user_id: str) -> Optional[GoogleCalendarClient]:
    """
    Load stored OAuth credentials and return a ready-to-use client.
    Returns None if the user hasn't connected Calendar yet.
    """
    creds = await cred_store.load(user_id, "calendar")
    if not creds:
        return None

    return GoogleCalendarClient(
        user_id=user_id,
        access_token=creds["access_token"],
        refresh_token=creds.get("refresh_token", ""),
        expires_at=float(creds.get("expires_at", 0)),
    )
