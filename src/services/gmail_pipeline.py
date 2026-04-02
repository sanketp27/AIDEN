"""
Gmail → Task Pipeline
Polls Gmail inbox via MCP, extracts action items using Gemini,
and creates AIDEN tasks with full email context.

Architecture:
  GmailPipelineService (APScheduler job, runs every N minutes)
    └─ GmailMCPClient  ──► Gmail MCP SSE server
    └─ ActionExtractor ──► Gemini for NLP extraction
    └─ TaskRepository  ──► MongoDB per-user task collections
    └─ ProcessedEmailRepo ──► tracks already-handled email IDs
"""
from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
import structlog
from pydantic import BaseModel, Field

from src.core.config import settings
from src.models.task import Priority, Task
from src.repositories.task_repo import TaskRepository
from src.services.gmail_direct import (
    GmailDirectClient, get_gmail_client_for_user, extract_email_parts
)
from src.repositories.prefs_repo import prefs_repo

log = structlog.get_logger()


class EmailSummary(BaseModel):
    """Lightweight email record returned by Gmail MCP list."""
    email_id: str
    subject:  str
    sender:   str
    snippet:  str
    date:     str
    thread_id: str = ""


class ExtractedAction(BaseModel):
    """A single action item parsed from an email by Gemini."""
    title:       str
    description: str
    priority:    Priority = Priority.P2
    due_date:    Optional[str] = None 
    tags:        list[str] = Field(default_factory=list)


class EmailProcessingResult(BaseModel):
    """Result for one processed email."""
    email_id:  str
    subject:   str
    sender:    str
    actions:   list[ExtractedAction]
    tasks_created: int = 0
    skipped:   bool = False
    reason:    str = ""


class GmailMCPClient:
    """
    Thin async HTTP client that talks to the Gmail MCP SSE server.
    Calls tools via JSON-RPC over SSE (MCP protocol).
    """

    def __init__(self, mcp_url: str, jwt_token: str) -> None:
        self._base  = mcp_url.rstrip("/")
        self._token = jwt_token
        self._client: Optional[httpx.AsyncClient] = None

    @property
    def headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type":  "application/json",
            "Accept":        "application/json",
        }

    async def _call(self, tool: str, args: dict) -> dict:
        """Send a JSON-RPC tool call to the MCP server."""
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=30)

        payload = {
            "jsonrpc": "2.0",
            "id":      1,
            "method":  "tools/call",
            "params":  {"name": tool, "arguments": args},
        }
        resp = await self._client.post(
            f"{self._base}/mcp",
            headers=self.headers,
            json=payload,
        )
        resp.raise_for_status()
        body = resp.json()

        if "error" in body:
            raise RuntimeError(f"MCP error [{tool}]: {body['error']}")

        # MCP returns result.content as list of {type, text} blocks
        content = body.get("result", {}).get("content", [])
        text    = " ".join(c.get("text", "") for c in content if c.get("type") == "text")
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"raw": text}

    async def list_messages(
        self,
        max_results: int = 20,
        query:       str  = "is:unread",
    ) -> list[EmailSummary]:
        """List inbox messages matching `query`."""
        data = await self._call("gmail_list_messages", {
            "maxResults": max_results,
            "q":          query,
        })
        messages = data.get("messages", [])
        summaries: list[EmailSummary] = []

        for m in messages:
            headers = {h["name"].lower(): h["value"] for h in m.get("payload", {}).get("headers", [])}
            summaries.append(EmailSummary(
                email_id  = m.get("id", ""),
                thread_id = m.get("threadId", ""),
                subject   = headers.get("subject", "(no subject)"),
                sender    = headers.get("from", ""),
                snippet   = m.get("snippet", ""),
                date      = headers.get("date", ""),
            ))

        log.info("gmail_messages_listed", count=len(summaries), query=query)
        return summaries

    async def get_message_body(self, email_id: str) -> str:
        """Fetch the plain-text body of an email."""
        data = await self._call("gmail_get_message", {"messageId": email_id})
        # Walk MIME parts for text/plain
        payload = data.get("payload", {})
        return _extract_plain_text(payload)

    async def mark_as_read(self, email_id: str) -> None:
        """Mark email as read (remove UNREAD label)."""
        await self._call("gmail_modify_message", {
            "messageId":     email_id,
            "removeLabelIds": ["UNREAD"],
        })

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None


def _extract_plain_text(payload: dict) -> str:
    """Recursively walk MIME payload and return first text/plain part."""
    mime = payload.get("mimeType", "")
    if mime == "text/plain":
        import base64
        data = payload.get("body", {}).get("data", "")
        if data:
            return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")

    for part in payload.get("parts", []):
        result = _extract_plain_text(part)
        if result:
            return result

    return payload.get("snippet", "")


_EXTRACTION_SYSTEM = """
You are an AI assistant that reads emails and extracts explicit action items
that the RECIPIENT (the user reading the email) must do.

Rules:
- Only extract actions the recipient must take, not the sender.
- Look for: "please do X", "can you send", "reply by", "complete by", "I need you to",
  "action required", deadlines, follow-ups, approvals.
- Infer priority: P0=critical/urgent/ASAP, P1=high/important/this week,
  P2=medium/normal, P3=low/FYI/no deadline.
- For due_date output ISO YYYY-MM-DD if a concrete date is mentioned, else null.
- Ignore pure FYI emails with no recipient actions.

Return ONLY valid JSON (no markdown):
{
  "actions": [
    {
      "title":       "<short imperative phrase>",
      "description": "<email context: sender, original request, relevant details>",
      "priority":    "P0|P1|P2|P3",
      "due_date":    "<YYYY-MM-DD or null>",
      "tags":        ["<tag1>", ...]
    }
  ]
}
"""


class ActionExtractor:
    """Uses Gemini to parse action items from email text."""

    def __init__(self) -> None:
        import google.generativeai as genai
        genai.configure(api_key=settings.GEMINI_API_KEY)
        self._model = genai.GenerativeModel(
            model_name=settings.DEFAULT_MODEL,
            system_instruction=_EXTRACTION_SYSTEM,
        )

    async def extract(
        self,
        subject: str,
        sender:  str,
        body:    str,
        date:    str,
    ) -> list[ExtractedAction]:
        prompt = f"""Email details:
From: {sender}
Date: {date}
Subject: {subject}

Body:
{body[:4000]}
"""
        import asyncio
        response = await asyncio.to_thread(self._model.generate_content, prompt)
        raw = response.text.strip()

        # Strip markdown fences
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)

        try:
            data    = json.loads(raw)
            actions = data.get("actions", [])
        except json.JSONDecodeError:
            log.warning("action_extraction_parse_failed", subject=subject, raw=raw[:200])
            return []

        results: list[ExtractedAction] = []
        for a in actions:
            try:
                results.append(ExtractedAction(
                    title       = a.get("title", "Untitled action"),
                    description = a.get("description", ""),
                    priority    = Priority(a.get("priority", "P2")),
                    due_date    = a.get("due_date"),
                    tags        = a.get("tags", []),
                ))
            except Exception as exc:
                log.warning("action_model_parse_error", error=str(exc))

        log.info("actions_extracted", subject=subject, count=len(results))
        return results


class ProcessedEmailRepo:
    """Stores set of processed email IDs per user in MongoDB to ensure idempotency."""

    def __init__(self) -> None:
        from motor.motor_asyncio import AsyncIOMotorClient
        client  = AsyncIOMotorClient(settings.MONGO_URI)
        self._col = client[settings.MONGO_DB]["gmail_processed"]

    async def ensure_index(self) -> None:
        from pymongo import ASCENDING
        await self._col.create_index(
            [("user_id", ASCENDING), ("email_id", ASCENDING)],
            unique=True, background=True,
        )

    async def is_processed(self, user_id: str, email_id: str) -> bool:
        doc = await self._col.find_one({"user_id": user_id, "email_id": email_id})
        return doc is not None

    async def mark_processed(self, user_id: str, email_id: str, subject: str) -> None:
        await self._col.update_one(
            {"user_id": user_id, "email_id": email_id},
            {"$set": {
                "user_id":    user_id,
                "email_id":   email_id,
                "subject":    subject,
                "processed_at": datetime.now(timezone.utc),
            }},
            upsert=True,
        )


class GmailPipelineService:
    """
    Orchestrates the full Gmail → Task pipeline for one user.
    Credentials are loaded from MongoDB (set via GET /auth/gmail OAuth flow).

    Typical call:
        service = GmailPipelineService(user_id="alice")
        results = await service.run_once()
    """

    def __init__(self, user_id: str, jwt_token: str = "") -> None:
        self.user_id   = user_id
        self._gmail    = None
        self._extractor = ActionExtractor()
        self._task_repo  = TaskRepository()
        self._processed  = ProcessedEmailRepo()

    async def run_once(
        self,
        max_emails:   int  = 20,
        mark_as_read: bool = False,
        query:        str  = "",
    ) -> list[EmailProcessingResult]:
        """
        Run one pipeline cycle using GmailDirectClient (no MCP required):
          1. Load user credentials + preferences from MongoDB
          2. Apply per-user filter (ignored senders, domains, keywords)
          3. Fetch body, extract actions with Gemini
          4. Create tasks with email context
          5. Optionally mark email as read
        """
        await self._processed.ensure_index()

        # Load Gmail client from stored OAuth credentials
        gmail_client = await get_gmail_client_for_user(self.user_id)
        if not gmail_client:
            log.warning("gmail_no_credentials", user_id=self.user_id,
                        hint="User must complete OAuth at GET /auth/gmail")
            return []
        self._gmail = gmail_client

        # Load user preferences for filtering
        prefs = await prefs_repo.get_or_create(self.user_id)
        gp    = prefs.gmail
        if not gp.enabled:
            log.info("gmail_pipeline_disabled", user_id=self.user_id)
            await self._gmail.close()
            return []

        # Build query string from preferences
        effective_query = query or gp.custom_query or "is:unread -from:noreply -from:no-reply"

        log.info("gmail_pipeline_start", user_id=self.user_id,
                 max_emails=max_emails, query=effective_query)

        try:
            raw_msgs = await self._gmail.list_messages(
                max_results=max_emails, query=effective_query
            )
        except Exception as exc:
            log.error("gmail_list_failed", user_id=self.user_id, error=str(exc))
            await self._gmail.close()
            return []

        results: list[EmailProcessingResult] = []
        ignored_senders  = {s.lower() for s in gp.ignored_senders}
        ignored_domains  = {d.lower() for d in gp.ignored_domains}
        ignored_keywords = [k.lower() for k in gp.ignored_subject_keywords]

        for msg_stub in raw_msgs:
            try:
                msg = await self._gmail.get_message(msg_stub["id"])
                subject, sender, date, body, snippet = extract_email_parts(msg)
            except Exception as exc:
                log.warning("gmail_fetch_failed", msg_id=msg_stub["id"], error=str(exc))
                continue

            email = EmailSummary(
                email_id=msg_stub["id"],
                thread_id=msg_stub.get("threadId", ""),
                subject=subject, sender=sender, snippet=snippet, date=date,
            )

            # Per-user ignore rules (no LLM — pure string matching)
            sender_lower  = sender.lower()
            subject_lower = subject.lower()
            sender_domain = sender_lower.split("@")[-1].rstrip(">")

            if any(s in sender_lower for s in ignored_senders):
                results.append(EmailProcessingResult(
                    email_id=email.email_id, subject=subject, sender=sender,
                    actions=[], skipped=True, reason=f"sender in ignore list"
                ))
                continue

            if any(d in sender_domain for d in ignored_domains):
                results.append(EmailProcessingResult(
                    email_id=email.email_id, subject=subject, sender=sender,
                    actions=[], skipped=True, reason=f"domain in ignore list"
                ))
                continue

            if any(k in subject_lower for k in ignored_keywords):
                results.append(EmailProcessingResult(
                    email_id=email.email_id, subject=subject, sender=sender,
                    actions=[], skipped=True, reason="subject keyword filtered"
                ))
                continue

            result = await self._process_email_direct(
                email, body, mark_as_read=mark_as_read or gp.mark_read_after_task
            )
            results.append(result)

        await self._gmail.close()

        total_tasks = sum(r.tasks_created for r in results)
        log.info("gmail_pipeline_complete", user_id=self.user_id,
                 emails_processed=len(results), tasks_created=total_tasks)
        return results

    async def _process_email_direct(
        self,
        email: EmailSummary,
        body: str,
        mark_as_read: bool,
    ) -> EmailProcessingResult:
        """Process a single email using pre-fetched body."""
        if await self._processed.is_processed(self.user_id, email.email_id):
            return EmailProcessingResult(
                email_id=email.email_id, subject=email.subject, sender=email.sender,
                actions=[], skipped=True, reason="already processed",
            )

        try:
            actions = await self._extractor.extract(
                subject=email.subject, sender=email.sender,
                body=body, date=email.date,
            )
        except Exception as exc:
            log.error("action_extraction_failed", email_id=email.email_id, error=str(exc))
            actions = []

        tasks_created = 0
        for action in actions:
            await self._create_task_from_action(action, email)
            tasks_created += 1

        await self._processed.mark_processed(self.user_id, email.email_id, email.subject)

        if mark_as_read and self._gmail and tasks_created > 0:
            try:
                await self._gmail.mark_as_read(email.email_id)
            except Exception as exc:
                log.warning("gmail_mark_read_failed", email_id=email.email_id, error=str(exc))

        return EmailProcessingResult(
            email_id=email.email_id, subject=email.subject, sender=email.sender,
            actions=actions, tasks_created=tasks_created,
        )

    async def _process_email(
        self,
        email: EmailSummary,
        mark_as_read: bool,
    ) -> EmailProcessingResult:
        """Process a single email: extract actions → create tasks."""

        # Idempotency check
        if await self._processed.is_processed(self.user_id, email.email_id):
            return EmailProcessingResult(
                email_id=email.email_id,
                subject=email.subject,
                sender=email.sender,
                actions=[],
                skipped=True,
                reason="already processed",
            )

        log.info("gmail_email_processing", user_id=self.user_id,
                 email_id=email.email_id, subject=email.subject)

        # Fetch full body
        try:
            body = await self._gmail.get_message_body(email.email_id)
        except Exception as exc:
            log.warning("gmail_body_fetch_failed", email_id=email.email_id, error=str(exc))
            body = email.snippet   # fallback to snippet

        # Extract actions with Gemini
        try:
            actions = await self._extractor.extract(
                subject=email.subject,
                sender=email.sender,
                body=body,
                date=email.date,
            )
        except Exception as exc:
            log.error("action_extraction_failed", email_id=email.email_id, error=str(exc))
            actions = []

        tasks_created = 0
        for action in actions:
            await self._create_task_from_action(action, email)
            tasks_created += 1

        # Mark processed (even if no tasks — avoids re-processing FYI emails)
        await self._processed.mark_processed(self.user_id, email.email_id, email.subject)

        # Optionally mark email as read in Gmail
        if mark_as_read and tasks_created > 0:
            try:
                await self._gmail.mark_as_read(email.email_id)
            except Exception as exc:
                log.warning("gmail_mark_read_failed", email_id=email.email_id, error=str(exc))

        return EmailProcessingResult(
            email_id=email.email_id,
            subject=email.subject,
            sender=email.sender,
            actions=actions,
            tasks_created=tasks_created,
        )

    async def _create_task_from_action(
        self,
        action: ExtractedAction,
        email:  EmailSummary,
    ) -> Task:
        """Persist one extracted action as an AIDEN task."""
        due_dt: Optional[datetime] = None
        if action.due_date:
            try:
                due_dt = datetime.fromisoformat(action.due_date).replace(tzinfo=timezone.utc)
            except ValueError:
                pass

        # Enrich description with email provenance
        full_desc = (
            f"{action.description}\n\n"
            f"── Email Context ──\n"
            f"From: {email.sender}\n"
            f"Subject: {email.subject}\n"
            f"Date: {email.date}\n"
            f"Email ID: {email.email_id}"
        )

        tags = list(set(action.tags + ["from-email", "gmail"]))

        task = Task(
            user_id     = self.user_id,
            title       = action.title,
            description = full_desc,
            priority    = action.priority,
            due_date    = due_dt,
            tags        = tags,
        )
        await self._task_repo.create_task(task)

        log.info(
            "task_created_from_email",
            user_id=self.user_id,
            task_id=task.task_id,
            title=task.title,
            priority=task.priority,
        )
        return task

    async def close(self) -> None:
        await self._gmail.close()


# ── Multi-user scheduler job ─────────────────────────────────────────────────

# Registry: user_id → JWT token (populated at runtime via POST /gmail/connect)
_pipeline_registry: dict[str, str] = {}


def register_gmail_user(user_id: str, jwt_token: str) -> None:
    """Register a user for scheduled Gmail polling."""
    _pipeline_registry[user_id] = jwt_token
    log.info("gmail_pipeline_registered", user_id=user_id)


def unregister_gmail_user(user_id: str) -> None:
    _pipeline_registry.pop(user_id, None)
    log.info("gmail_pipeline_unregistered", user_id=user_id)


async def run_gmail_pipeline_for_all_users() -> None:
    """
    Called by APScheduler every N minutes.
    Loads all users with stored Gmail credentials from MongoDB.
    Credentials are set via GET /auth/gmail OAuth flow — no in-memory registry needed.
    _pipeline_registry still works as an opt-in override (legacy POST /gmail/connect).
    """
    from src.services.gmail_direct import cred_store

    # Get users from credential store (persistent across restarts)
    db_users = await cred_store.list_connected_users("gmail")
    # Merge with in-memory registry (legacy connect flow)
    all_users = set(db_users) | set(_pipeline_registry.keys())

    if not all_users:
        return

    log.info("gmail_pipeline_scheduler_run", users=len(all_users))
    tasks = [_run_for_user(uid) for uid in all_users]
    await asyncio.gather(*tasks, return_exceptions=True)


async def _run_for_user(user_id: str, jwt_token: str = "") -> None:
    service = GmailPipelineService(user_id=user_id)
    try:
        await service.run_once(max_emails=30, mark_as_read=True)
    except Exception as exc:
        log.error("gmail_pipeline_user_failed", user_id=user_id, error=str(exc))
    finally:
        await service.close()
