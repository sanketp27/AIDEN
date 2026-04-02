"""
Gmail Pipeline API endpoints
Connects a user's Gmail account to AIDEN's task extraction pipeline.

Endpoints:
  POST /gmail/connect      — register user for scheduled polling
  POST /gmail/scan         — manually trigger one pipeline run
  GET  /gmail/status       — check connection & processed stats
  DELETE /gmail/disconnect — stop polling for this user
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from src.api.middleware import get_current_active_user
from src.models.user import UserClaims
from src.services.gmail_pipeline import (
    EmailProcessingResult,
    GmailPipelineService,
    _pipeline_registry,
    register_gmail_user,
    unregister_gmail_user,
)

log = structlog.get_logger()
router = APIRouter(prefix="/gmail", tags=["Gmail Pipeline"])


class GmailConnectRequest(BaseModel):
    """Body for POST /gmail/connect."""
    gmail_jwt: str          # Gmail MCP OAuth JWT (from Google sign-in flow)
    poll_interval_minutes: int = 15   # how often the scheduler runs
    mark_emails_read: bool = True     # mark emails read after extracting tasks


class GmailScanRequest(BaseModel):
    max_emails: int = 20
    query: str = "is:unread -from:noreply -from:no-reply"
    mark_emails_read: bool = False


class ActionSummary(BaseModel):
    title:      str
    priority:   str
    due_date:   Optional[str]
    tags:       list[str]


class EmailResult(BaseModel):
    email_id:     str
    subject:      str
    sender:       str
    tasks_created: int
    skipped:      bool
    actions:      list[ActionSummary]


class ScanResponse(BaseModel):
    user_id:       str
    emails_scanned: int
    tasks_created: int
    results:       list[EmailResult]
    triggered_at:  str


class StatusResponse(BaseModel):
    user_id:     str
    connected:   bool
    polling:     bool
    message:     str


def _fmt_results(raw: list[EmailProcessingResult]) -> list[EmailResult]:
    return [
        EmailResult(
            email_id      = r.email_id,
            subject       = r.subject,
            sender        = r.sender,
            tasks_created = r.tasks_created,
            skipped       = r.skipped,
            actions=[
                ActionSummary(
                    title     = a.title,
                    priority  = a.priority.value,
                    due_date  = a.due_date,
                    tags      = a.tags,
                )
                for a in r.actions
            ],
        )
        for r in raw
    ]


@router.post("/connect", response_model=StatusResponse)
async def connect_gmail(
    body: GmailConnectRequest,
    current_user: UserClaims = Depends(get_current_active_user),
) -> StatusResponse:
    """
    Register user's Gmail for periodic task extraction.

    The `gmail_jwt` is the OAuth token obtained from the Gmail MCP
    Google sign-in flow. Once registered, the APScheduler job polls
    Gmail every `poll_interval_minutes` and auto-creates tasks.
    """
    register_gmail_user(current_user.user_id, body.gmail_jwt)

    # Reschedule with user-specified interval (APScheduler modification)
    try:
        from src.core.scheduler import scheduler
        from apscheduler.triggers.interval import IntervalTrigger
        from src.services.gmail_pipeline import run_gmail_pipeline_for_all_users

        job_id = "gmail_pipeline"
        if scheduler.get_job(job_id):
            scheduler.reschedule_job(
                job_id,
                trigger=IntervalTrigger(minutes=body.poll_interval_minutes),
            )
        else:
            scheduler.add_job(
                run_gmail_pipeline_for_all_users,
                trigger=IntervalTrigger(minutes=body.poll_interval_minutes),
                id=job_id,
                replace_existing=True,
                misfire_grace_time=120,
            )
    except Exception as exc:
        log.warning("gmail_scheduler_setup_failed", error=str(exc))

    log.info("gmail_connected", user_id=current_user.user_id,
             interval=body.poll_interval_minutes)

    return StatusResponse(
        user_id=current_user.user_id,
        connected=True,
        polling=True,
        message=(
            f"Gmail pipeline connected. "
            f"Polling every {body.poll_interval_minutes} minutes. "
            f"Emails {'will' if body.mark_emails_read else 'will not'} be marked as read."
        ),
    )


@router.post("/scan", response_model=ScanResponse)
async def scan_gmail(
    body: GmailScanRequest,
    current_user: UserClaims = Depends(get_current_active_user),
) -> ScanResponse:
    """
    Manually trigger one Gmail scan for the current user.

    Useful for on-demand task extraction without waiting for the
    scheduled poll. Returns full breakdown of emails processed and
    tasks created.
    """
    # Use the stored JWT if available, otherwise 401
    jwt_token = _pipeline_registry.get(current_user.user_id)
    if not jwt_token:
        raise HTTPException(
            status_code=400,
            detail=(
                "Gmail not connected. "
                "Call POST /gmail/connect first with your Gmail OAuth token."
            ),
        )

    log.info("gmail_manual_scan", user_id=current_user.user_id,
             max_emails=body.max_emails, query=body.query)

    service = GmailPipelineService(
        user_id=current_user.user_id,
        jwt_token=jwt_token,
    )
    try:
        raw_results = await service.run_once(
            max_emails=body.max_emails,
            mark_as_read=body.mark_emails_read,
            query=body.query,
        )
    finally:
        await service.close()

    results      = _fmt_results(raw_results)
    total_tasks  = sum(r.tasks_created for r in results)
    scanned      = sum(1 for r in results if not r.skipped)

    return ScanResponse(
        user_id=current_user.user_id,
        emails_scanned=scanned,
        tasks_created=total_tasks,
        results=results,
        triggered_at=datetime.now(timezone.utc).isoformat(),
    )


@router.get("/status", response_model=StatusResponse)
async def gmail_status(
    current_user: UserClaims = Depends(get_current_active_user),
) -> StatusResponse:
    """Check whether Gmail pipeline is connected and polling for this user."""
    connected = current_user.user_id in _pipeline_registry

    if connected:
        return StatusResponse(
            user_id=current_user.user_id,
            connected=True,
            polling=True,
            message="Gmail pipeline is active and polling for new emails.",
        )
    return StatusResponse(
        user_id=current_user.user_id,
        connected=False,
        polling=False,
        message="Gmail not connected. Call POST /gmail/connect to enable.",
    )


@router.delete("/disconnect", status_code=204)
async def disconnect_gmail(
    current_user: UserClaims = Depends(get_current_active_user),
) -> None:
    """Stop Gmail polling for this user and remove stored credentials."""
    unregister_gmail_user(current_user.user_id)
    log.info("gmail_disconnected", user_id=current_user.user_id)
    return None
