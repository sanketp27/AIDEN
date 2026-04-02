"""
Per-user preferences and integration settings.
Stored in MongoDB `user_preferences` collection.
"""
from pydantic import BaseModel, Field
from datetime import datetime, timezone
from typing import Optional
import uuid


class GmailPreferences(BaseModel):
    """User-level Gmail pipeline configuration."""
    enabled:              bool = True
    poll_interval_minutes: int = 15
    max_emails_per_run:   int = 30
    mark_read_after_task: bool = True
    ignored_senders:      list[str] = Field(default_factory=list)   # e.g. ["noreply@github.com"]
    ignored_domains:      list[str] = Field(default_factory=list)   # e.g. ["newsletters.com"]
    ignored_subject_keywords: list[str] = Field(default_factory=list)  # e.g. ["unsubscribe", "promo"]
    custom_query:         str = "is:unread -from:noreply -from:no-reply"
    connected_email:      Optional[str] = None     # which Gmail account is linked
    connected_at:         Optional[datetime] = None


class TelegramPreferences(BaseModel):
    """User-level Telegram bot configuration."""
    enabled:         bool = True
    chat_id:         Optional[int] = None          # Telegram chat_id once /start is called
    connected_at:    Optional[datetime] = None
    language:        str = "en-US"
    notify_on_task:  bool = True    # send Telegram message when new tasks are created
    notify_briefing: bool = False   # send morning briefing to Telegram


class NotificationPreferences(BaseModel):
    """General notification settings."""
    briefing_time:           str = "08:00"   # HH:MM in user's local time
    briefing_enabled:        bool = True
    overdue_alert_enabled:   bool = True


class UserPreferences(BaseModel):
    """Full user preferences document."""
    pref_id:      str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id:      str
    gmail:        GmailPreferences = Field(default_factory=GmailPreferences)
    telegram:     TelegramPreferences = Field(default_factory=TelegramPreferences)
    notifications: NotificationPreferences = Field(default_factory=NotificationPreferences)
    created_at:   datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at:   datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ── Update models ─────────────────────────────────────────────────────────────

class GmailPrefsUpdate(BaseModel):
    enabled:              Optional[bool] = None
    poll_interval_minutes: Optional[int] = None
    max_emails_per_run:   Optional[int] = None
    mark_read_after_task: Optional[bool] = None
    ignored_senders:      Optional[list[str]] = None
    ignored_domains:      Optional[list[str]] = None
    ignored_subject_keywords: Optional[list[str]] = None
    custom_query:         Optional[str] = None


class TelegramPrefsUpdate(BaseModel):
    enabled:         Optional[bool] = None
    notify_on_task:  Optional[bool] = None
    notify_briefing: Optional[bool] = None
    language:        Optional[str] = None


class NotificationPrefsUpdate(BaseModel):
    briefing_time:           Optional[str] = None
    briefing_enabled:        Optional[bool] = None
    overdue_alert_enabled:   Optional[bool] = None


class UserPreferencesUpdate(BaseModel):
    gmail:        Optional[GmailPrefsUpdate] = None
    telegram:     Optional[TelegramPrefsUpdate] = None
    notifications: Optional[NotificationPrefsUpdate] = None
