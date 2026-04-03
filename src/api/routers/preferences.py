from fastapi import APIRouter, Depends
from src.models.user import UserClaims
from src.models.user_prefs import UserPreferences, UserPreferencesUpdate
from src.repositories.prefs_repo import prefs_repo
from src.api.middleware import get_current_active_user

router = APIRouter(prefix="/preferences", tags=["Preferences"])


@router.get("", response_model=UserPreferences)
async def get_preferences(
    current_user: UserClaims = Depends(get_current_active_user),
) -> UserPreferences:
    """Get all preferences for the current user."""
    return await prefs_repo.get_or_create(current_user.user_id)


@router.patch("", response_model=UserPreferences)
async def update_preferences(
    updates: UserPreferencesUpdate,
    current_user: UserClaims = Depends(get_current_active_user),
) -> UserPreferences:
    """
    Update preferences. Send only the fields you want to change.

    Examples:
      Add an ignored sender:
        PATCH /preferences {"gmail": {"ignored_senders": ["noreply@github.com"]}}

      Change briefing time:
        PATCH /preferences {"notifications": {"briefing_time": "07:30"}}

      Disable Telegram notifications:
        PATCH /preferences {"telegram": {"notify_on_task": false}}
    """
    return await prefs_repo.update(current_user.user_id, updates)


@router.post("/gmail/ignore-sender")
async def add_ignored_sender(
    sender: str,
    current_user: UserClaims = Depends(get_current_active_user),
) -> dict:
    """Add an email address to the Gmail ignore list (no tasks created from these)."""
    await prefs_repo.add_ignored_sender(current_user.user_id, sender)
    return {"status": "added", "sender": sender}


@router.delete("/gmail/ignore-sender")
async def remove_ignored_sender(
    sender: str,
    current_user: UserClaims = Depends(get_current_active_user),
) -> dict:
    """Remove an email address from the Gmail ignore list."""
    await prefs_repo.remove_ignored_sender(current_user.user_id, sender)
    return {"status": "removed", "sender": sender}
