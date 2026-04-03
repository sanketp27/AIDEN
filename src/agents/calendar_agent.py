"""
CalendarBot Agent — Google Calendar via direct REST API
========================================================
Replaces the dead localhost:3000 MCP URL with real @tool functions
that call the Google Calendar API v3 directly.

OAuth setup (one-time per user):
  1. Add these scopes to your Google Cloud OAuth client alongside Gmail:
       https://www.googleapis.com/auth/calendar
       https://www.googleapis.com/auth/calendar.events
  2. In the UI Settings tab, click "Connect Google Calendar"
     (uses the same OAuth flow as Gmail — /auth/calendar/*)
  3. After connecting, CalendarBot can read and write events.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from google.adk.agents import Agent
from google.adk.tools import tool

from src.core.config import settings
from src.services.google_calendar import get_calendar_client

os.environ.setdefault("GOOGLE_API_KEY",  settings.GEMINI_API_KEY)
os.environ.setdefault("GEMINI_API_KEY",  settings.GEMINI_API_KEY)

@tool
async def get_todays_calendar(user_id: str) -> dict:
    """
    Return all calendar events for today.

    Args:
        user_id: The authenticated user's ID.

    Returns:
        dict with 'events' list and 'count'. Each event has title, start, end, attendees.
    """
    client = await get_calendar_client(user_id)
    if not client:
        return {
            "error": "Google Calendar not connected. Ask the user to go to Settings → Connect Google Calendar.",
            "events": [], "count": 0,
        }

    try:
        events = await client.get_todays_events()
        simplified = [_simplify(e) for e in events]
        return {"events": simplified, "count": len(simplified)}
    except Exception as exc:
        return {"error": str(exc), "events": [], "count": 0}


@tool
async def get_weeks_calendar(user_id: str) -> dict:
    """
    Return all calendar events for the next 7 days.

    Args:
        user_id: The authenticated user's ID.

    Returns:
        dict with 'events' list grouped implicitly by date.
    """
    client = await get_calendar_client(user_id)
    if not client:
        return {
            "error": "Google Calendar not connected. Ask the user to go to Settings → Connect Google Calendar.",
            "events": [], "count": 0,
        }

    try:
        events = await client.get_weeks_events()
        simplified = [_simplify(e) for e in events]
        return {"events": simplified, "count": len(simplified)}
    except Exception as exc:
        return {"error": str(exc), "events": [], "count": 0}


@tool
async def create_calendar_event(
    user_id:          str,
    title:            str,
    start_iso:        str,
    end_iso:          str,
    description:      str = "",
    attendee_emails:  list[str] | None = None,
    location:         str = "",
) -> dict:
    """
    Create a new Google Calendar event.

    Args:
        user_id:         The authenticated user's ID.
        title:           Event title / summary.
        start_iso:       Start datetime in ISO 8601 format (e.g. '2026-04-07T14:00:00Z').
        end_iso:         End datetime in ISO 8601 format.
        description:     Optional description / agenda.
        attendee_emails: Optional list of attendee email addresses.
        location:        Optional location or video call link.

    Returns:
        dict with 'event_id', 'title', 'html_link', or 'error'.
    """
    client = await get_calendar_client(user_id)
    if not client:
        return {"error": "Google Calendar not connected. Visit Settings → Connect Google Calendar."}

    try:
        start = datetime.fromisoformat(start_iso.replace("Z", "+00:00"))
        end   = datetime.fromisoformat(end_iso.replace("Z", "+00:00"))

        # Check for conflicts first
        conflicts = await client.check_conflicts(start, end)
        if conflicts:
            conflict_titles = [c.get("summary", "Unknown") for c in conflicts[:3]]
            return {
                "conflict": True,
                "conflict_events": conflict_titles,
                "message": f"Conflict detected with: {', '.join(conflict_titles)}. Event NOT created.",
            }

        event = await client.create_event(
            title=title, start=start, end=end,
            description=description,
            attendees=attendee_emails,
            location=location,
        )
        return {
            "event_id":  event.get("id"),
            "title":     event.get("summary"),
            "start":     event.get("start", {}).get("dateTime"),
            "end":       event.get("end",   {}).get("dateTime"),
            "html_link": event.get("htmlLink"),
            "conflict":  False,
        }
    except Exception as exc:
        return {"error": str(exc)}


@tool
async def find_free_slots(
    user_id:          str,
    date_iso:         str,
    duration_minutes: int = 60,
) -> dict:
    """
    Find available time slots on a given date.

    Args:
        user_id:          The authenticated user's ID.
        date_iso:         The date to check in ISO format (e.g. '2026-04-07').
        duration_minutes: Minimum slot length in minutes (default 60).

    Returns:
        dict with 'free_slots' list, each with start, end, duration_minutes.
    """
    client = await get_calendar_client(user_id)
    if not client:
        return {"error": "Google Calendar not connected."}

    try:
        date = datetime.fromisoformat(date_iso).replace(tzinfo=timezone.utc)
        slots = await client.find_free_slots(date, duration_minutes)
        return {"free_slots": slots, "count": len(slots), "date": date_iso}
    except Exception as exc:
        return {"error": str(exc), "free_slots": []}


@tool
async def delete_calendar_event(user_id: str, event_id: str) -> dict:
    """
    Delete a calendar event by its ID.

    Args:
        user_id:  The authenticated user's ID.
        event_id: The Google Calendar event ID.

    Returns:
        dict with 'deleted': True or 'error'.
    """
    client = await get_calendar_client(user_id)
    if not client:
        return {"error": "Google Calendar not connected."}

    try:
        await client.delete_event(event_id)
        return {"deleted": True, "event_id": event_id}
    except Exception as exc:
        return {"error": str(exc), "deleted": False}


def _simplify(event: dict) -> dict:
    """Flatten a raw Google Calendar event into a clean summary dict."""
    start = event.get("start", {})
    end   = event.get("end",   {})
    attendees = [
        a.get("email", "") for a in event.get("attendees", [])
        if not a.get("self", False)
    ]
    return {
        "event_id":    event.get("id"),
        "title":       event.get("summary", "(No title)"),
        "start":       start.get("dateTime", start.get("date", "")),
        "end":         end.get("dateTime",   end.get("date",   "")),
        "description": event.get("description", ""),
        "location":    event.get("location", ""),
        "attendees":   attendees,
        "html_link":   event.get("htmlLink", ""),
        "status":      event.get("status", ""),
    }


CALENDAR_INSTRUCTION = """You are CalendarBot, AIDEN's calendar management specialist.
You have direct access to the user's Google Calendar via secure API tools.

TOOLS AVAILABLE:
- get_todays_calendar(user_id)              → Today's events
- get_weeks_calendar(user_id)               → Next 7 days of events
- create_calendar_event(...)                → Create event (auto-checks conflicts)
- find_free_slots(user_id, date, duration)  → Available time slots on a date
- delete_calendar_event(user_id, event_id)  → Remove an event

BEHAVIOUR RULES:
1. ALWAYS call get_todays_calendar or get_weeks_calendar before answering questions about schedule
2. When creating events, the tool automatically checks for conflicts — report them clearly
3. Format event lists with time, title, duration, and attendees
4. When asked to find a meeting time, use find_free_slots then propose the best options
5. If Calendar is not connected, tell the user to go to Settings → Connect Google Calendar

IF CALENDAR NOT CONNECTED:
Explain clearly: "Your Google Calendar is not yet connected. Please go to Settings and click
'Connect Google Calendar' to link your account. This uses the same secure OAuth flow as Gmail."

OUTPUT FORMAT:
- Events: [Time] Title (Duration) — Attendees if any
- Show conflicts with ⚠️ CONFLICT
- Group by day when showing multiple days
- Always include the event_id when referencing specific events

IMPORTANT: Always pass the user_id field to every tool call.
The user_id comes from the session context — use it exactly as provided.
"""

calendar_bot_agent = Agent(
    name="calendar_bot",
    model=settings.CALENDAR_AGENT_MODEL,
    instruction=CALENDAR_INSTRUCTION,
    tools=[
        get_todays_calendar,
        get_weeks_calendar,
        create_calendar_event,
        find_free_slots,
        delete_calendar_event,
    ],
)
