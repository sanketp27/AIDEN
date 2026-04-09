"""
Auth & OAuth router  —  AIDEN v2.0
====================================
Endpoints:
  POST  /auth/register       — create account (name + email + password → JWT)
  POST  /auth/login          — authenticate   (email + password → JWT)
  POST  /auth/logout         — revoke all tokens for current user
  GET   /auth/me             — current user info + integration status
  GET   /auth/gmail          — start Gmail OAuth2 flow (redirects to Google)
  GET   /auth/gmail/callback — receive code, exchange tokens, redirect back to UI
  DELETE /auth/gmail         — disconnect Gmail

JWT lifecycle
  - Tokens have a TTL (JWT_EXPIRE_MINUTES in .env, default 24 h).
  - Active tokens are stored in the jwt_tokens MongoDB collection.
  - On login/register the repo first checks for a still-valid token;
    if found it is returned as-is (no redundant minting).
  - MongoDB TTL index on expires_at auto-purges expired documents.
  - Logout revokes all tokens in the DB for that user.

Gmail OAuth
  - After successful token exchange the callback redirects the browser back
    to AIDEN_UI_URL/?gmail=connected so the frontend shows a success toast.
    Users never see raw JSON.
"""
from __future__ import annotations

import base64
import secrets
import time
from urllib.parse import urlencode

import httpx
import requests
import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from jose import jwt
from pydantic import BaseModel, EmailStr
from typing import Optional
from datetime import datetime, timezone, timedelta
from cryptography.fernet import Fernet

from src.api.middleware import get_current_active_user
from src.core.config import settings
from src.models.user import UserClaims, UserCreate, UserRole
from src.repositories.user_repo import user_repo
from src.services.gmail_direct import (
    GmailDirectClient,
    GMAIL_SCOPES,
    OAUTH_AUTH_URL,
    OAUTH_TOKEN_URL,
    cred_store,
)
from src.services.google_calendar import CALENDAR_SCOPES
from src.repositories.prefs_repo import prefs_repo
from src.models.user_prefs import UserPreferencesUpdate

log = structlog.get_logger()
router = APIRouter(prefix="/auth", tags=["Auth"])

GOOGLE_WORKSPACE_SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/tasks",
    "openid",
    "email",
    "profile",
]
NOTION_AUTH_URL = "https://api.notion.com/v1/oauth/authorize"
NOTION_TOKEN_URL = "https://api.notion.com/v1/oauth/token"


def _fernet_encrypt(text: str) -> str:
    key = base64.urlsafe_b64encode(settings.JWT_SECRET[:32].ljust(32).encode())
    return Fernet(key).encrypt(text.encode()).decode()

class RegisterRequest(BaseModel):
    name: str
    email: EmailStr
    password: str
    role: str = "user"


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user_id: str
    email: str
    name: str
    role: str

@router.post("/register", response_model=TokenOut)
async def register(body: RegisterRequest) -> TokenOut:
    """
    Create a new user account.
    Returns a JWT that is also persisted in the database with a TTL.
    If an account for that email already exists -> 409.
    """
    try:
        role = UserRole(body.role)
    except ValueError:
        raise HTTPException(400, f"Invalid role. Must be one of: {[r.value for r in UserRole]}")

    user_data = UserCreate(
        email=body.email,
        name=body.name,
        password=body.password,
        role=role,
    )
    try:
        user = await user_repo.create(user_data)
    except ValueError as exc:
        raise HTTPException(409, str(exc))

    token, expires_in = await user_repo.get_or_create_token(user)
    log.info("user_registered", user_id=user.user_id, email=user.email)

    return TokenOut(
        access_token=token,
        expires_in=expires_in,
        user_id=user.user_id,
        email=user.email,
        name=user.name,
        role=user.role.value,
    )


@router.post("/login", response_model=TokenOut)
async def login(body: LoginRequest) -> TokenOut:
    """
    Authenticate with email + password.
    Returns an existing live JWT if one is still valid, otherwise mints a new one.
    401 on bad credentials.
    """
    user = await user_repo.authenticate(body.email, body.password)
    if not user:
        raise HTTPException(401, "Invalid email or password")

    token, expires_in = await user_repo.get_or_create_token(user)
    log.info("user_logged_in", user_id=user.user_id, email=user.email)

    return TokenOut(
        access_token=token,
        expires_in=expires_in,
        user_id=user.user_id,
        email=user.email,
        name=user.name,
        role=user.role.value,
    )


_GUEST_EMAIL    = "guest@aiden.demo"
_GUEST_PASSWORD = "AIden@Guest2025"
_GUEST_NAME     = "Evaluator (Guest)"


@router.post("/guest", response_model=TokenOut)
async def guest_login() -> TokenOut:
    """
    Zero-friction guest login for evaluators / demo viewers.

    • Creates the guest account on first call if it does not exist.
    • Returns a standard JWT valid for the same TTL as regular accounts.
    • The guest role is 'guest' — the UI can use this to show an optional
      banner indicating the session is a read-only demo.
    • No email or password required from the client.
    """
    # Try to authenticate with the fixed guest credentials
    user = await user_repo.authenticate(_GUEST_EMAIL, _GUEST_PASSWORD)

    if not user:
        # First boot — create the guest account
        try:
            guest_data = UserCreate(
                email=_GUEST_EMAIL,
                name=_GUEST_NAME,
                password=_GUEST_PASSWORD,
                role=UserRole.GUEST,
            )
            user = await user_repo.create(guest_data)
            log.info("guest_account_created")
        except ValueError:
            # Race condition: account was just created by another request
            user = await user_repo.authenticate(_GUEST_EMAIL, _GUEST_PASSWORD)
            if not user:
                from fastapi import HTTPException
                raise HTTPException(500, "Failed to initialise guest account.")

    token, expires_in = await user_repo.get_or_create_token(user)
    log.info("guest_login", user_id=user.user_id)

    return TokenOut(
        access_token=token,
        expires_in=expires_in,
        user_id=user.user_id,
        email=user.email,
        name=user.name,
        role=user.role.value,
    )


@router.post("/logout")
async def logout(current_user: UserClaims = Depends(get_current_active_user)) -> dict:
    """Revoke all active tokens for the current user."""
    revoked = await user_repo.revoke_all_tokens(current_user.user_id)
    log.info("user_logged_out", user_id=current_user.user_id, tokens_revoked=revoked)
    return {"status": "logged_out", "tokens_revoked": revoked}

@router.get("/me")
async def get_me(current_user: UserClaims = Depends(get_current_active_user)) -> dict:
    """Returns current user info + integration connection status."""
    prefs       = await prefs_repo.get_or_create(current_user.user_id)
    gmail_creds = await cred_store.load(current_user.user_id, "gmail")
    cal_creds   = await cred_store.load(current_user.user_id, "calendar")

    from src.integrations.telegram_bot import _sessions
    tg_session = None
    for sess in _sessions.values():
        if sess.user_id == current_user.user_id:
            tg_session = sess
            break

    return {
        "user_id": current_user.user_id,
        "role":    current_user.role.value,
        "email":   current_user.email,
        "name":    current_user.name,
        "integrations": {
            "gmail": {
                "connected":             gmail_creds is not None,
                "connected_email":       prefs.gmail.connected_email,
                "connected_at":          prefs.gmail.connected_at.isoformat() if prefs.gmail.connected_at else None,
                "polling_enabled":       prefs.gmail.enabled,
                "poll_interval_minutes": prefs.gmail.poll_interval_minutes,
                "ignored_senders":       prefs.gmail.ignored_senders,
                "ignored_domains":       prefs.gmail.ignored_domains,
            },
            "calendar": {
                "connected":    cal_creds is not None,
                "connected_at": None,
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
    request: Request,
    bearer: Optional[str] = None,
    current_user: Optional[UserClaims] = None,
) -> RedirectResponse:
    """
    Step 1: redirect the browser to Google's OAuth consent screen.

    Accepts authentication via:
      - Standard Authorization: Bearer <token> header  (API clients)
      - ?bearer=<token> query param                    (browser redirects from UI)
    """
    # Resolve user from bearer query param when the Authorization header isn't available
    # (e.g. when the user clicks "Connect Gmail" and the browser navigates directly here)
    if current_user is None:
        if not bearer:
            raise HTTPException(401, "Authentication required. Provide Authorization header or ?bearer= param.")
        from jose import JWTError, jwt as jose_jwt
        from src.models.user import UserRole
        try:
            payload = jose_jwt.decode(bearer, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
            current_user = UserClaims(
                user_id=payload["sub"],
                role=UserRole(payload.get("role", "user")),
                email=payload.get("email"),
                name=payload.get("name"),
            )
        except Exception:
            raise HTTPException(401, "Invalid or expired token.")

    if not settings.GMAIL_CLIENT_ID:
        raise HTTPException(501, (
            "Gmail OAuth not configured. "
            "Add GMAIL_CLIENT_ID and GMAIL_CLIENT_SECRET to .env. "
            "See: https://console.cloud.google.com/apis/credentials"
        ))

    redirect_uri = f"{settings.AIDEN_API_URL}/auth/gmail/callback"
    params = {
        "client_id":     settings.GMAIL_CLIENT_ID,
        "redirect_uri":  redirect_uri,
        "response_type": "code",
        "scope":         " ".join(GMAIL_SCOPES),
        "access_type":   "offline",
        "prompt":        "consent",
        "state":         current_user.user_id,
    }
    url = OAUTH_AUTH_URL + "?" + urlencode(params)
    log.info("gmail_oauth_start", user_id=current_user.user_id)
    return RedirectResponse(url)


@router.get("/gmail/callback")
async def gmail_oauth_callback(code: str, state: str, request: Request) -> RedirectResponse:
    """
    Step 2: Google redirects here with ?code=...&state=<user_id>

    After token exchange, redirects the browser back to the UI:
      Success: {AIDEN_UI_URL}/?gmail=connected&email=<addr>
      Failure: {AIDEN_UI_URL}/?gmail=error&reason=<msg>

    The user never sees raw JSON.
    """
    user_id      = state
    redirect_uri = f"{settings.AIDEN_API_URL}/auth/gmail/callback"
    ui_base      = settings.AIDEN_UI_URL.rstrip("/")

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(OAUTH_TOKEN_URL, data={
                "code":          code,
                "client_id":     settings.GMAIL_CLIENT_ID,
                "client_secret": settings.GMAIL_CLIENT_SECRET,
                "redirect_uri":  redirect_uri,
                "grant_type":    "authorization_code",
            })

        if resp.status_code != 200:
            log.error("gmail_token_exchange_failed", status=resp.status_code)
            return RedirectResponse(f"{ui_base}/?gmail=error&reason=token_exchange_failed")

        tokens = resp.json()
        creds = {
            "access_token":  tokens["access_token"],
            "refresh_token": tokens.get("refresh_token", ""),
            "expires_at":    time.time() + tokens.get("expires_in", 3600),
        }

        await cred_store.save(user_id, "gmail", creds)

        # Fetch the connected Gmail address
        email_addr = ""
        try:
            async with httpx.AsyncClient() as c:
                profile = await c.get(
                    "https://gmail.googleapis.com/gmail/v1/users/me/profile",
                    headers={"Authorization": f"Bearer {creds['access_token']}"},
                )
                email_addr = profile.json().get("emailAddress", "")
        except Exception:
            pass

        gmail_client = GmailDirectClient(**creds, user_id=user_id)
        await gmail_client.close()

        await prefs_repo.set_gmail_connected(user_id, email_addr)

        from src.services.gmail_pipeline import register_gmail_user
        register_gmail_user(user_id, tokens["access_token"])

        log.info("gmail_oauth_complete", user_id=user_id, email=email_addr)

        # Redirect back to UI — browser lands on the app, not a JSON page
        qs = urlencode({"gmail": "connected", "email": email_addr})
        return RedirectResponse(f"{ui_base}/?{qs}")

    except Exception as exc:
        log.error("gmail_oauth_callback_error", error=str(exc), user_id=user_id)
        return RedirectResponse(f"{ui_base}/?gmail=error&reason=internal_error")


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
        UserPreferencesUpdate.model_validate({"gmail": {"connected_email": None, "enabled": False}}),
    )
    log.info("gmail_disconnected", user_id=current_user.user_id)
    return {"status": "disconnected", "user_id": current_user.user_id}


@router.get("/calendar")
async def calendar_oauth_start(
    request: Request,
    bearer: Optional[str] = None,
    current_user: Optional[UserClaims] = None,
) -> RedirectResponse:
    """
    Step 1: redirect browser to Google consent screen for Calendar access.
    Accepts ?bearer=<token> for browser-redirect flow (same pattern as Gmail).
    """
    if current_user is None:
        if not bearer:
            raise HTTPException(401, "Authentication required.")
        from jose import jwt as jose_jwt
        from src.models.user import UserRole
        try:
            payload = jose_jwt.decode(bearer, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
            current_user = UserClaims(
                user_id=payload["sub"],
                role=UserRole(payload.get("role", "user")),
                email=payload.get("email"),
                name=payload.get("name"),
            )
        except Exception:
            raise HTTPException(401, "Invalid or expired token.")

    if not settings.GMAIL_CLIENT_ID:
        raise HTTPException(501, "Google OAuth not configured. Add GMAIL_CLIENT_ID and GMAIL_CLIENT_SECRET to .env.")

    redirect_uri = f"{settings.AIDEN_API_URL}/auth/calendar/callback"
    # Request both Gmail + Calendar scopes together for a unified consent screen
    all_scopes = GMAIL_SCOPES + CALENDAR_SCOPES
    params = {
        "client_id":     settings.GMAIL_CLIENT_ID,
        "redirect_uri":  redirect_uri,
        "response_type": "code",
        "scope":         " ".join(all_scopes),
        "access_type":   "offline",
        "prompt":        "consent",
        "state":         current_user.user_id,
    }
    url = OAUTH_AUTH_URL + "?" + urlencode(params)
    log.info("calendar_oauth_start", user_id=current_user.user_id)
    return RedirectResponse(url)


@router.get("/calendar/callback")
async def calendar_oauth_callback(code: str, state: str, request: Request) -> RedirectResponse:
    """
    Step 2: Google redirects here. Exchange code → tokens → persist → redirect to UI.
    """
    user_id      = state
    redirect_uri = f"{settings.AIDEN_API_URL}/auth/calendar/callback"
    ui_base      = settings.AIDEN_UI_URL.rstrip("/")

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(OAUTH_TOKEN_URL, data={
                "code":          code,
                "client_id":     settings.GMAIL_CLIENT_ID,
                "client_secret": settings.GMAIL_CLIENT_SECRET,
                "redirect_uri":  redirect_uri,
                "grant_type":    "authorization_code",
            })

        if resp.status_code != 200:
            log.error("calendar_token_exchange_failed", status=resp.status_code)
            return RedirectResponse(f"{ui_base}/?calendar=error&reason=token_exchange_failed")

        tokens = resp.json()
        creds = {
            "access_token":  tokens["access_token"],
            "refresh_token": tokens.get("refresh_token", ""),
            "expires_at":    time.time() + tokens.get("expires_in", 3600),
        }

        await cred_store.save(user_id, "calendar", creds)
        log.info("calendar_oauth_complete", user_id=user_id)

        return RedirectResponse(f"{ui_base}/?calendar=connected")

    except Exception as exc:
        log.error("calendar_oauth_callback_error", error=str(exc))
        return RedirectResponse(f"{ui_base}/?calendar=error&reason=internal_error")


@router.delete("/calendar")
async def calendar_disconnect(
    current_user: UserClaims = Depends(get_current_active_user),
) -> dict:
    """Remove stored Calendar credentials."""
    await cred_store.delete(current_user.user_id, "calendar")
    log.info("calendar_disconnected", user_id=current_user.user_id)
    return {"status": "disconnected", "user_id": current_user.user_id}


@router.get("/google/start")
async def google_oauth_start(current_user: UserClaims = Depends(get_current_active_user)):
    """Initiate unified Google Workspace OAuth flow."""
    state = jwt.encode(
        {
            "user_id": current_user.user_id,
            "exp": datetime.utcnow() + timedelta(minutes=10),
            "nonce": secrets.token_urlsafe(8),
        },
        settings.JWT_SECRET,
        algorithm="HS256",
    )
    params = urlencode(
        {
            "client_id": settings.GMAIL_CLIENT_ID,
            "redirect_uri": settings.GOOGLE_REDIRECT_URI,
            "response_type": "code",
            "scope": " ".join(GOOGLE_WORKSPACE_SCOPES),
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
        }
    )
    return RedirectResponse(url=f"https://accounts.google.com/o/oauth2/auth?{params}")


@router.get("/google/callback")
async def google_oauth_callback(code: str, state: str):
    """Handle Google OAuth callback and persist per-user tokens."""
    try:
        payload = jwt.decode(state, settings.JWT_SECRET, algorithms=["HS256"])
        user_id = payload["user_id"]
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid OAuth state — please try again")

    token_resp = requests.post(
        "https://oauth2.googleapis.com/token",
        data={
            "code": code,
            "client_id": settings.GMAIL_CLIENT_ID,
            "client_secret": settings.GMAIL_CLIENT_SECRET,
            "redirect_uri": settings.GOOGLE_REDIRECT_URI,
            "grant_type": "authorization_code",
        },
        timeout=20,
    )
    if not token_resp.ok:
        raise HTTPException(status_code=400, detail="Token exchange failed")
    tokens = token_resp.json()

    userinfo_resp = requests.get(
        "https://www.googleapis.com/oauth2/v3/userinfo",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
        timeout=20,
    )
    userinfo = userinfo_resp.json() if userinfo_resp.ok else {}

    await user_repo.update_user(
        user_id,
        {
            "google_access_token": tokens["access_token"],
            "google_refresh_token": tokens.get("refresh_token"),
            "google_email": userinfo.get("email", ""),
            "calendar_connected": True,
            "gmail_connected": True,
            "google_connected_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    ui_base = settings.AIDEN_UI_URL.rstrip("/")
    return RedirectResponse(url=f"{ui_base}/?connected=google_workspace")


@router.get("/notion/start")
async def notion_oauth_start(current_user: UserClaims = Depends(get_current_active_user)):
    """Initiate Notion OAuth2 flow."""
    state = jwt.encode(
        {
            "user_id": current_user.user_id,
            "exp": datetime.utcnow() + timedelta(minutes=10),
        },
        settings.JWT_SECRET,
        algorithm="HS256",
    )
    params = urlencode(
        {
            "client_id": settings.NOTION_CLIENT_ID,
            "response_type": "code",
            "owner": "user",
            "redirect_uri": settings.NOTION_REDIRECT_URI,
            "state": state,
        }
    )
    return RedirectResponse(url=f"{NOTION_AUTH_URL}?{params}")


@router.get("/notion/callback")
async def notion_oauth_callback(code: str, state: str):
    """Exchange Notion code for a token and store it per user."""
    try:
        payload = jwt.decode(state, settings.JWT_SECRET, algorithms=["HS256"])
        user_id = payload["user_id"]
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid state")

    resp = requests.post(
        NOTION_TOKEN_URL,
        auth=(settings.NOTION_CLIENT_ID, settings.NOTION_CLIENT_SECRET),
        json={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": settings.NOTION_REDIRECT_URI,
        },
        timeout=20,
    )
    if not resp.ok:
        raise HTTPException(status_code=400, detail="Notion token exchange failed")
    data = resp.json()
    access_token = data.get("access_token")
    if not access_token:
        raise HTTPException(status_code=400, detail="Notion access token missing")

    encrypted = _fernet_encrypt(access_token)
    await user_repo.update_user(
        user_id,
        {
            "notion_token_encrypted": encrypted,
            "notion_workspace_name": data.get("workspace_name", ""),
            "notion_workspace_id": data.get("workspace_id", ""),
            "notion_connected": True,
            "notion_connected_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    ui_base = settings.AIDEN_UI_URL.rstrip("/")
    return RedirectResponse(url=f"{ui_base}/?connected=notion")
