"""
Auth & OAuth router
====================
Handles:
  - POST /auth/token          — create JWT from user_id + role (dev convenience)
  - GET  /auth/gmail           — start Gmail OAuth2 flow (redirects to Google)
  - GET  /auth/gmail/callback  — receive code, exchange for tokens, store + redirect
  - DELETE /auth/gmail         — disconnect Gmail
  - GET  /auth/me              — current user info + connection status

Gmail OAuth requires GMAIL_CLIENT_ID + GMAIL_CLIENT_SECRET in .env.
Get them from Google Cloud Console → APIs & Services → Credentials → OAuth 2.0 Client.
Scopes: gmail.readonly + gmail.modify
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse, JSONResponse
from pydantic import BaseModel
from typing import Optional
import time, httpx, structlog

from src.api.middleware import get_current_active_user, create_access_token
from src.models.user import UserClaims, UserRole
from src.core.config import settings
from src.services.gmail_direct import (
    cred_store, OAUTH_AUTH_URL, OAUTH_TOKEN_URL,
    GMAIL_SCOPES, GmailDirectClient,
)
from src.repositories.prefs_repo import prefs_repo
from src.models.user_prefs import UserPreferences, UserPreferencesUpdate

log = structlog.get_logger()
router = APIRouter(prefix="/auth", tags=["Auth"])

class TokenRequest(BaseModel):
    user_id: str
    role:    str = "user"
    email:   Optional[str] = None


@router.post("/token")
async def create_token(body: TokenRequest) -> dict:
    """
    Create a JWT token for a user_id.
    Development convenience — in production use your identity provider.
    """
    try:
        role = UserRole(body.role)
    except ValueError:
        raise HTTPException(400, f"Invalid role. Must be: {[r.value for r in UserRole]}")

    token, expires_in = create_access_token(body.user_id, role, body.email)
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": expires_in,
        "user_id": body.user_id,
        "role": body.role,
        "hint": "Add header: Authorization: Bearer <token>",
    }

@router.get("/me")
async def get_me(current_user: UserClaims = Depends(get_current_active_user)) -> dict:
    """
    Returns current user info + connection status for Gmail and Telegram.
    This is the dashboard initialization call — tells the frontend which
    integrations are active for this user.
    """
    prefs = await prefs_repo.get_or_create(current_user.user_id)
    gmail_creds  = await cred_store.load(current_user.user_id, "gmail")

    from src.integrations.telegram_bot import _sessions
    tg_session = None
    for sess in _sessions.values():
        if sess.user_id == current_user.user_id:
            tg_session = sess
            break

    return {
        "user_id":  current_user.user_id,
        "role":     current_user.role.value,
        "email":    current_user.email,
        "integrations": {
            "gmail": {
                "connected":       gmail_creds is not None,
                "connected_email": prefs.gmail.connected_email,
                "connected_at":    prefs.gmail.connected_at.isoformat() if prefs.gmail.connected_at else None,
                "polling_enabled": prefs.gmail.enabled,
                "poll_interval_minutes": prefs.gmail.poll_interval_minutes,
                "ignored_senders": prefs.gmail.ignored_senders,
                "ignored_domains": prefs.gmail.ignored_domains,
            },
            "telegram": {
                "connected":    tg_session is not None,
                "chat_id":      prefs.telegram.chat_id,
                "connected_at": prefs.telegram.connected_at.isoformat() if prefs.telegram.connected_at else None,
            },
        },
        "preferences": prefs.model_dump(exclude={"pref_id", "created_at"}),
    }

@router.get("/gmail")
async def gmail_oauth_start(
    current_user: UserClaims = Depends(get_current_active_user),
) -> RedirectResponse:
    """
    Step 1: redirect user to Google's OAuth consent screen.
    On return, Google calls /auth/gmail/callback?code=...&state=<user_id>
    """
    if not settings.GMAIL_CLIENT_ID:
        raise HTTPException(501, (
            "Gmail OAuth not configured. "
            "Add GMAIL_CLIENT_ID and GMAIL_CLIENT_SECRET to .env. "
            "Get them from: https://console.cloud.google.com/apis/credentials"
        ))

    redirect_uri = f"{settings.AIDEN_API_URL}/auth/gmail/callback"
    params = {
        "client_id":     settings.GMAIL_CLIENT_ID,
        "redirect_uri":  redirect_uri,
        "response_type": "code",
        "scope":         " ".join(GMAIL_SCOPES),
        "access_type":   "offline",   # get refresh_token
        "prompt":        "consent",   # always show consent to ensure refresh_token
        "state":         current_user.user_id,   # passed back in callback
    }
    from urllib.parse import urlencode
    url = OAUTH_AUTH_URL + "?" + urlencode(params)
    log.info("gmail_oauth_start", user_id=current_user.user_id)
    return RedirectResponse(url)


@router.get("/gmail/callback")
async def gmail_oauth_callback(code: str, state: str, request: Request) -> JSONResponse:
    """
    Step 2: Google returns here with ?code=...&state=<user_id>
    Exchange code for access + refresh tokens, store them, register for polling.
    """
    user_id      = state
    redirect_uri = f"{settings.AIDEN_API_URL}/auth/gmail/callback"

    async with httpx.AsyncClient() as client:
        resp = await client.post(OAUTH_TOKEN_URL, data={
            "code":          code,
            "client_id":     settings.GMAIL_CLIENT_ID,
            "client_secret": settings.GMAIL_CLIENT_SECRET,
            "redirect_uri":  redirect_uri,
            "grant_type":    "authorization_code",
        })
    if resp.status_code != 200:
        raise HTTPException(400, f"Token exchange failed: {resp.text}")

    tokens = resp.json()
    creds  = {
        "access_token":  tokens["access_token"],
        "refresh_token": tokens.get("refresh_token", ""),
        "expires_at":    time.time() + tokens.get("expires_in", 3600),
    }

    # Store credentials
    await cred_store.save(user_id, "gmail", creds)

    # Fetch the connected Gmail address
    gmail_client = GmailDirectClient(**creds, user_id=user_id)
    try:
        async with httpx.AsyncClient() as c:
            profile = await c.get(
                "https://gmail.googleapis.com/gmail/v1/users/me/profile",
                headers={"Authorization": f"Bearer {creds['access_token']}"},
            )
            email_addr = profile.json().get("emailAddress", "")
    except Exception:
        email_addr = ""
    await gmail_client.close()

    # Update user prefs
    await prefs_repo.set_gmail_connected(user_id, email_addr)

    # Register for pipeline polling
    from src.services.gmail_pipeline import register_gmail_user
    register_gmail_user(user_id, tokens["access_token"])   # short-lived; pipeline refreshes

    log.info("gmail_oauth_complete", user_id=user_id, email=email_addr)

    return JSONResponse({
        "status":  "connected",
        "user_id": user_id,
        "email":   email_addr,
        "message": "Gmail connected. Background polling is now active.",
        "next":    "Return to AIDEN and refresh the page.",
    })


@router.delete("/gmail")
async def gmail_disconnect(
    current_user: UserClaims = Depends(get_current_active_user),
) -> dict:
    """Remove stored Gmail credentials and stop polling for this user."""
    await cred_store.delete(current_user.user_id, "gmail")
    from src.services.gmail_pipeline import unregister_gmail_user
    unregister_gmail_user(current_user.user_id)
    await prefs_repo.update(
        current_user.user_id,
        UserPreferencesUpdate.model_validate({
            "gmail": {"connected_email": None, "enabled": False}
        }),
    )
    log.info("gmail_disconnected", user_id=current_user.user_id)
    return {"status": "disconnected", "user_id": current_user.user_id}
