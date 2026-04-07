"""
AIDEN Telegram Bot — Full Client (Mandatory Registration)
==========================================================
Telegram is a first-class client, equal to the web UI.
Every user MUST register before using any feature.

Registration model
------------------
  NEW user:      /register YourName email@x.com StrongPassword
                 → creates AIDEN account, links this chat_id permanently

  EXISTING user: /login email@x.com YourPassword
  (has web acc)  → validates credentials, links this chat_id to their account
                   → all existing tasks/notes/calendar instantly available

  Any other command before registration → clear error with instructions.

Auth flow (no JWT in bot)
-------------------------
  Bot calls FastAPI with:
    X-Bot-Secret: <BOT_SERVICE_SECRET>   (proves request is from our bot)
    X-Telegram-Chat-Id: <chat_id>        (identifies which user)
  FastAPI middleware resolves chat_id → user_id → UserClaims.
  All existing routers work with zero changes.

Commands
--------
  ACCOUNT
    /start                   — welcome + registration instructions
    /register <n> <e> <p>    — create account (mandatory first step)
    /login <email> <pass>    — link existing web account to this chat
    /unlink                  — detach this chat from AIDEN account
    /me                      — show account and integration status
    /help                    — full command reference

  TASKS
    /tasks                   — list open tasks
    /tasks done              — list completed tasks
    /task <title>            — quick-create task
    /done <task_id>          — mark task complete

  NOTES
    /notes                   — list recent notes
    /note <text>             — quick-create note
    /search <query>          — semantic search across notes

  CALENDAR & GMAIL
    /today                   — today's calendar events
    /scan                    — run Gmail → task scan

  INTELLIGENCE
    /briefing                — morning briefing
    /forecast                — week workload forecast

  MEDIA
    Voice note               — transcribe + route through orchestrator
    Photo / document         — vision analysis
    Plain text               — route through AIDEN orchestrator

BotFather setup (one-time, developer only)
------------------------------------------
  1. Chat with @BotFather → /newbot → follow prompts
  2. Copy the token → add to .env:
       TELEGRAM_BOT_TOKEN=123456:ABC-...
       TELEGRAM_BOT_USERNAME=YourAIDENBot
       BOT_SERVICE_SECRET=<python -c "import secrets;print(secrets.token_hex(32))">
  3. Start the server — the bot launches automatically.
  4. Users find the bot on Telegram and send /start.
"""
from __future__ import annotations

import asyncio
import base64
import textwrap
from typing import Optional

import httpx
import structlog
from pydantic_settings import BaseSettings, SettingsConfigDict

log = structlog.get_logger()


# ── Bot settings (read from .env) ─────────────────────────────────────────────

class BotSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )
    TELEGRAM_BOT_TOKEN:    str = ""
    TELEGRAM_BOT_USERNAME: str = ""
    BOT_SERVICE_SECRET:    str = ""
    AIDEN_API_URL:         str = "http://localhost:8000"


bot_cfg = BotSettings()

# ── Registration guard message — shown for every command before /register ─────

_NOT_REGISTERED = (
    "👋 *Welcome to AIDEN!*\n\n"
    "To get started, please register first:\n"
    "`/register YourName email@example.com StrongPassword`\n\n"
    "Already have an AIDEN account from the web app?\n"
    "`/login email@example.com YourPassword`"
)

class AIDENClient:
    """
    Calls AIDEN FastAPI backend on behalf of a Telegram user.
    Authentication is via internal headers — no JWT stored in the bot.
    """

    def __init__(self) -> None:
        self._base   = bot_cfg.AIDEN_API_URL.rstrip("/")
        self._http   = httpx.AsyncClient(timeout=90)

    def _h(self, chat_id: int) -> dict[str, str]:
        """Internal auth headers that identify the Telegram user."""
        return {
            "X-Bot-Secret":       bot_cfg.BOT_SERVICE_SECRET,
            "X-Telegram-Chat-Id": str(chat_id),
            "Content-Type":       "application/json",
        }

    # ── Orchestrator ──────────────────────────────────────────────────────────
    async def chat(self, chat_id: int, message: str, session_id: Optional[str] = None) -> dict:
        payload: dict = {"message": message}
        if session_id:
            payload["session_id"] = session_id
        r = await self._http.post(f"{self._base}/chat/sync", json=payload, headers=self._h(chat_id))
        r.raise_for_status()
        return r.json()

    async def list_tasks(self, chat_id: int, status: str = "todo", limit: int = 10) -> list:
        r = await self._http.get(f"{self._base}/tasks",
            params={"status": status, "limit": limit}, headers=self._h(chat_id))
        r.raise_for_status()
        return r.json()

    async def create_task(self, chat_id: int, title: str, priority: str = "P2") -> dict:
        r = await self._http.post(f"{self._base}/tasks",
            json={"title": title, "priority": priority}, headers=self._h(chat_id))
        r.raise_for_status()
        return r.json()

    async def complete_task(self, chat_id: int, task_id: str) -> dict:
        r = await self._http.patch(f"{self._base}/tasks/{task_id}",
            json={"status": "completed"}, headers=self._h(chat_id))
        r.raise_for_status()
        return r.json()

    async def list_notes(self, chat_id: int, limit: int = 8) -> list:
        r = await self._http.get(f"{self._base}/notes",
            params={"limit": limit}, headers=self._h(chat_id))
        r.raise_for_status()
        return r.json()

    async def create_note(self, chat_id: int, title: str, content: str) -> dict:
        r = await self._http.post(f"{self._base}/notes",
            json={"title": title, "content": content, "tags": ["telegram"]},
            headers=self._h(chat_id))
        r.raise_for_status()
        return r.json()

    async def search_notes(self, chat_id: int, query: str) -> list:
        r = await self._http.get(f"{self._base}/notes/search",
            params={"q": query, "limit": 5}, headers=self._h(chat_id))
        r.raise_for_status()
        return r.json()

    async def get_today_events(self, chat_id: int) -> list:
        r = await self._http.get(f"{self._base}/calendar/events/today",
            headers=self._h(chat_id))
        r.raise_for_status()
        return r.json()

    async def scan_gmail(self, chat_id: int) -> dict:
        r = await self._http.post(f"{self._base}/gmail/scan",
            json={"max_emails": 20, "mark_emails_read": False},
            headers=self._h(chat_id))
        r.raise_for_status()
        return r.json()

    async def get_briefing(self, chat_id: int) -> dict:
        r = await self._http.post(f"{self._base}/briefing/generate",
            headers=self._h(chat_id))
        r.raise_for_status()
        return r.json()

    async def get_forecast(self, chat_id: int) -> dict:
        r = await self._http.get(f"{self._base}/forecast",
            headers=self._h(chat_id))
        r.raise_for_status()
        return r.json()

    async def get_me(self, chat_id: int) -> dict:
        r = await self._http.get(f"{self._base}/auth/me", headers=self._h(chat_id))
        r.raise_for_status()
        return r.json()
    async def transcribe_and_run(self, chat_id: int, audio_b64: str) -> dict:
        r = await self._http.post(f"{self._base}/voice/query",
            json={"audio_b64": audio_b64, "language": "en-US", "auto_execute": True},
            headers=self._h(chat_id))
        r.raise_for_status()
        return r.json()

    async def analyze_image(self, chat_id: int, image_b64: str, prompt: str = "") -> dict:
        r = await self._http.post(f"{self._base}/vision/analyze",
            json={
                "image_b64": image_b64,
                "prompt": prompt or "Describe this image and extract any actionable information.",
            },
            headers=self._h(chat_id))
        r.raise_for_status()
        return r.json()

    async def close(self) -> None:
        await self._http.aclose()


_api = AIDENClient()


# ── Formatters ────────────────────────────────────────────────────────────────

_PRI = {"P0": "🔴", "P1": "🟡", "P2": "🔵", "P3": "⚪"}


def _fmt_tasks(tasks: list) -> str:
    if not tasks:
        return "✅ No open tasks — you're all clear!"
    lines = ["*Your tasks:*\n"]
    for i, t in enumerate(tasks, 1):
        pri = _PRI.get(t.get("priority", "P3"), "⚪")
        due = ""
        if t.get("due_date"):
            try:
                from datetime import datetime
                dt  = datetime.fromisoformat(t["due_date"].replace("Z", "+00:00"))
                due = f" · {dt.strftime('%b %d')}"
            except Exception:
                pass
        tid = (t.get("task_id") or "")[:8]
        lines.append(f"{i}. {pri} {t['title']}{due}  `{tid}`")
    return "\n".join(lines)


def _fmt_notes(notes: list) -> str:
    if not notes:
        return "📝 No notes yet.\nTry: `/note Your first note`"
    lines = ["*Recent notes:*\n"]
    for n in notes:
        preview = n.get("content", "")[:70].replace("\n", " ")
        if len(n.get("content", "")) > 70:
            preview += "…"
        lines.append(f"📝 *{n['title']}*\n   _{preview}_\n")
    return "\n".join(lines)


def _fmt_events(events: list) -> str:
    if not events:
        return "📅 No events today. Enjoy the free time!"
    from datetime import datetime
    lines = ["*Today's schedule:*\n"]
    for e in events:
        start = e.get("start", {})
        start_str = start.get("dateTime") or start.get("date", "")
        try:
            t = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
            time_str = t.strftime("%H:%M")
        except Exception:
            time_str = start_str
        lines.append(f"⏰ {time_str} — {e.get('summary', 'Untitled')}")
    return "\n".join(lines)


def _trunc(text: str, n: int = 4000) -> str:
    return text[:n] + "…" if len(text) > n else text


HELP_TEXT = textwrap.dedent("""
*AIDEN — AI Intelligent Daily Executive Navigator* 🤖

*Account setup*
`/register <Name> <email> <pass>` — create your account _(required first)_
`/login <email> <pass>`           — link existing web account
`/unlink`                         — detach this chat from AIDEN
`/me`                             — account & integration status

*Tasks*
`/tasks`          — list open tasks
`/tasks done`     — list completed tasks
`/task <title>`   — quick-create a task
`/done <task_id>` — mark task complete

*Notes*
`/notes`          — list recent notes
`/note <text>`    — quick-create a note
`/search <query>` — semantic search across notes

*Calendar & Gmail*
`/today`          — today's calendar events
`/scan`           — Gmail → task scan

*Intelligence*
`/briefing`       — morning briefing
`/forecast`       — week workload forecast

*Just type anything* — AIDEN routes it to the right agent 🧠
Send a 🎤 voice note or 📷 photo too!
""").strip()


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _send(bot, chat_id: int, text: str, pm: str = "Markdown") -> None:
    """Send message with Markdown, fall back to plain text on parse error."""
    try:
        await bot.send_message(chat_id=chat_id, text=_trunc(text), parse_mode=pm)
    except Exception:
        try:
            await bot.send_message(chat_id=chat_id, text=_trunc(text))
        except Exception as exc:
            log.error("send_failed", chat_id=chat_id, error=str(exc))


async def _delete_msg(bot, chat_id: int, msg_id: int) -> None:
    """Delete a message silently (e.g. after reading credentials)."""
    try:
        await bot.delete_message(chat_id=chat_id, message_id=msg_id)
    except Exception:
        pass


async def _get_registered_user(bot, chat_id: int):
    """
    Load the registered user for this chat_id.
    If not registered, send the registration prompt and return None.
    Callers should return immediately when None is returned.
    """
    from src.repositories.user_repo import user_repo
    user = await user_repo.get_by_telegram_chat_id(chat_id)
    if not user:
        await _send(bot, chat_id, _NOT_REGISTERED)
        return None
    return user


async def _call(bot, chat_id: int, coro, err: str = "Error"):
    """
    Await an API coroutine and handle errors gracefully.
    Returns the result on success, None on any failure.
    """
    try:
        return await coro
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        if status == 404:
            detail = ""
            try:
                detail = exc.response.json().get("detail", "")
            except Exception:
                pass
            if detail == "NOT_REGISTERED":
                await _send(bot, chat_id, _NOT_REGISTERED)
            else:
                await _send(bot, chat_id, f"⚠️ {err}: resource not found.")
        elif status == 401:
            await _send(bot, chat_id, "❌ Authentication error. Please contact the AIDEN admin.")
        elif status == 422:
            await _send(bot, chat_id, f"⚠️ {err}: invalid input.")
        else:
            await _send(bot, chat_id, f"⚠️ {err} (server error {status}).")
        return None
    except Exception as exc:
        log.error("api_call_failed", chat_id=chat_id, error=str(exc), operation=err)
        await _send(bot, chat_id, f"⚠️ {err}: {exc}")
        return None


# ── In-memory session cache (non-critical; lost on restart is acceptable) ─────
_sessions: dict[int, str] = {}


# ── Command handlers ──────────────────────────────────────────────────────────

async def cmd_start(update, ctx) -> None:
    """/start — always show registration instructions."""
    chat_id = update.effective_chat.id
    first   = update.effective_user.first_name or "there"

    from src.repositories.user_repo import user_repo
    user = await user_repo.get_by_telegram_chat_id(chat_id)

    if user:
        await _send(ctx.bot, chat_id,
            f"👋 Welcome back, *{user.name}*!\n"
            "What can I help you with today?\n\n"
            "Type /help to see all available commands.")
    else:
        await _send(ctx.bot, chat_id,
            f"👋 Hello {first}! Welcome to *AIDEN* — your AI Executive Navigator.\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "To get started, you need to *register*:\n\n"
            "`/register YourName email@example.com Password`\n\n"
            "📌 *Example:*\n"
            "`/register John john@company.com MyPass123`\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "Already have an AIDEN web account?\n"
            "`/login email@example.com Password`\n\n"
            "_Registration is required to keep your data secure and organized._")


async def cmd_register(update, ctx) -> None:
    """/register <Name> <email> <password> — create AIDEN account (mandatory)."""
    chat_id  = update.effective_chat.id
    args     = ctx.args or []
    msg_id   = update.message.message_id

    # Delete message immediately — contains password
    await _delete_msg(ctx.bot, chat_id, msg_id)

    if len(args) < 3:
        await _send(ctx.bot, chat_id,
            "❌ *Usage:* `/register YourName email@example.com Password`\n\n"
            "📌 *Example:*\n"
            "`/register John john@company.com MyPass123`\n\n"
            "_Your message is deleted immediately for security._")
        return

    # Name can be multiple words — everything before the last two args
    password = args[-1]
    email    = args[-2]
    name     = " ".join(args[:-2])

    if not name:
        await _send(ctx.bot, chat_id,
            "❌ Please include your name.\n"
            "`/register John Doe john@example.com Password`")
        return

    tg_username = update.effective_user.username

    from src.repositories.user_repo import user_repo
    try:
        user = await user_repo.register_via_telegram(
            chat_id=chat_id,
            name=name,
            email=email,
            password=password,
            telegram_username=tg_username,
        )
        await _send(ctx.bot, chat_id,
            f"✅ *Account created! Welcome, {user.name}!*\n\n"
            "Your AIDEN account is ready. You can now:\n"
            "• 📋 Manage tasks → /tasks\n"
            "• 📝 Create notes → /note\n"
            "• 📅 Check calendar → /today\n"
            "• ☀️ Get briefing → /briefing\n"
            "• 🧠 Just type anything and I'll figure it out\n\n"
            "🌐 Log in to the web dashboard with the same email & password.\n\n"
            "Type /help to see all commands.")
        log.info("telegram_registered", chat_id=chat_id, user_id=user.user_id)

    except ValueError as exc:
        await _send(ctx.bot, chat_id, f"❌ Registration failed: {exc}")


async def cmd_login(update, ctx) -> None:
    """/login <email> <password> — link existing web account to this chat."""
    chat_id = update.effective_chat.id
    args    = ctx.args or []
    msg_id  = update.message.message_id

    # Delete message immediately — contains password
    await _delete_msg(ctx.bot, chat_id, msg_id)

    if len(args) != 2:
        await _send(ctx.bot, chat_id,
            "❌ *Usage:* `/login email@example.com Password`\n\n"
            "_Your message is deleted immediately for security._")
        return

    email, password = args[0], args[1]
    tg_username = update.effective_user.username

    from src.repositories.user_repo import user_repo
    try:
        user = await user_repo.login_via_telegram(
            chat_id=chat_id,
            email=email,
            password=password,
            telegram_username=tg_username,
        )
        if not user:
            await _send(ctx.bot, chat_id,
                "❌ *Invalid email or password.*\n\n"
                "Please check your credentials and try again.\n"
                "If you don't have an account yet, use:\n"
                "`/register YourName email@example.com Password`")
            return

        await _send(ctx.bot, chat_id,
            f"✅ *Logged in as {user.name}!*\n\n"
            "Your existing tasks, notes, calendar, and Gmail from the web app "
            "are all available here now.\n\n"
            "Type /help to see all commands.")
        log.info("telegram_login", chat_id=chat_id, user_id=user.user_id)

    except ValueError as exc:
        await _send(ctx.bot, chat_id, f"❌ {exc}")


async def cmd_unlink(update, ctx) -> None:
    """/unlink — detach this Telegram chat from AIDEN account."""
    chat_id = update.effective_chat.id
    user = await _get_registered_user(ctx.bot, chat_id)
    if not user:
        return

    from src.repositories.user_repo import user_repo
    await user_repo.unlink_telegram(user.user_id)
    await _send(ctx.bot, chat_id,
        "✅ *Telegram unlinked* from your AIDEN account.\n\n"
        "Your account and data are still safe in AIDEN.\n"
        "To reconnect: `/login email@example.com Password`")


async def cmd_me(update, ctx) -> None:
    """/me — account and integration status."""
    chat_id = update.effective_chat.id
    user = await _get_registered_user(ctx.bot, chat_id)
    if not user:
        return

    await ctx.bot.send_chat_action(chat_id=chat_id, action="typing")
    me = await _call(ctx.bot, chat_id, _api.get_me(chat_id), "Could not fetch account")
    if not me:
        return

    intg     = me.get("integrations", {})
    gmail    = intg.get("gmail", {})
    cal      = intg.get("calendar", {})
    gmail_ic = "✅" if gmail.get("connected") else "❌"
    cal_ic   = "✅" if cal.get("connected") else "❌"
    gmail_em = gmail.get("connected_email", "not connected")

    await _send(ctx.bot, chat_id,
        f"👤 *{me.get('name')}*\n"
        f"📧 {me.get('email')}\n"
        f"Role: `{me.get('role')}`\n\n"
        f"*Integrations*\n"
        f"{gmail_ic} Gmail: {gmail_em}\n"
        f"{cal_ic} Google Calendar\n\n"
        f"🌐 Web dashboard: same email & password")


async def cmd_help(update, ctx) -> None:
    await _send(ctx.bot, update.effective_chat.id, HELP_TEXT)


# ── Task commands ─────────────────────────────────────────────────────────────

async def cmd_tasks(update, ctx) -> None:
    chat_id = update.effective_chat.id
    if not await _get_registered_user(ctx.bot, chat_id):
        return
    status = "completed" if ctx.args and ctx.args[0].lower() == "done" else "todo"
    await ctx.bot.send_chat_action(chat_id=chat_id, action="typing")
    tasks = await _call(ctx.bot, chat_id, _api.list_tasks(chat_id, status=status), "Could not fetch tasks")
    if tasks is not None:
        await _send(ctx.bot, chat_id, _fmt_tasks(tasks))


async def cmd_task(update, ctx) -> None:
    chat_id = update.effective_chat.id
    if not await _get_registered_user(ctx.bot, chat_id):
        return
    args = ctx.args or []
    if not args:
        await _send(ctx.bot, chat_id, "Usage: `/task Review the proposal`")
        return
    title = " ".join(args)
    await ctx.bot.send_chat_action(chat_id=chat_id, action="typing")
    task = await _call(ctx.bot, chat_id, _api.create_task(chat_id, title), "Could not create task")
    if task:
        pri = _PRI.get(task.get("priority", "P2"), "🔵")
        tid = (task.get("task_id") or "")[:8]
        await _send(ctx.bot, chat_id,
            f"✅ Task created!\n{pri} *{task['title']}*\n`{tid}`")


async def cmd_done(update, ctx) -> None:
    chat_id = update.effective_chat.id
    if not await _get_registered_user(ctx.bot, chat_id):
        return
    args = ctx.args or []
    if not args:
        await _send(ctx.bot, chat_id, "Usage: `/done <task_id>`\nGet the ID from /tasks")
        return
    await ctx.bot.send_chat_action(chat_id=chat_id, action="typing")
    task = await _call(ctx.bot, chat_id, _api.complete_task(chat_id, args[0]), "Could not update task")
    if task:
        await _send(ctx.bot, chat_id, f"✅ Marked complete: *{task.get('title', args[0])}*")


# ── Note commands ─────────────────────────────────────────────────────────────

async def cmd_notes(update, ctx) -> None:
    chat_id = update.effective_chat.id
    if not await _get_registered_user(ctx.bot, chat_id):
        return
    await ctx.bot.send_chat_action(chat_id=chat_id, action="typing")
    notes = await _call(ctx.bot, chat_id, _api.list_notes(chat_id), "Could not fetch notes")
    if notes is not None:
        await _send(ctx.bot, chat_id, _fmt_notes(notes))


async def cmd_note(update, ctx) -> None:
    chat_id = update.effective_chat.id
    if not await _get_registered_user(ctx.bot, chat_id):
        return
    args = ctx.args or []
    if not args:
        await _send(ctx.bot, chat_id, "Usage: `/note Meeting recap: decided to launch in Q3`")
        return
    content = " ".join(args)
    title   = content[:60] + ("…" if len(content) > 60 else "")
    await ctx.bot.send_chat_action(chat_id=chat_id, action="typing")
    note = await _call(ctx.bot, chat_id, _api.create_note(chat_id, title, content), "Could not save note")
    if note:
        await _send(ctx.bot, chat_id, f"📝 Note saved!\n*{note.get('title', title)}*")


async def cmd_search(update, ctx) -> None:
    chat_id = update.effective_chat.id
    if not await _get_registered_user(ctx.bot, chat_id):
        return
    args = ctx.args or []
    if not args:
        await _send(ctx.bot, chat_id, "Usage: `/search Q3 budget`")
        return
    query = " ".join(args)
    await ctx.bot.send_chat_action(chat_id=chat_id, action="typing")
    results = await _call(ctx.bot, chat_id, _api.search_notes(chat_id, query), "Search failed")
    if results is not None:
        if not results:
            await _send(ctx.bot, chat_id, f"🔍 No results for: _{query}_")
        else:
            lines = [f"🔍 *Results for \"{query}\":*\n"]
            for r in results:
                preview = r.get("content", "")[:80].replace("\n", " ")
                lines.append(f"📝 *{r['title']}*\n   _{preview}_\n")
            await _send(ctx.bot, chat_id, "\n".join(lines))


# ── Calendar, Gmail, Intelligence ─────────────────────────────────────────────

async def cmd_today(update, ctx) -> None:
    chat_id = update.effective_chat.id
    if not await _get_registered_user(ctx.bot, chat_id):
        return
    await ctx.bot.send_chat_action(chat_id=chat_id, action="typing")
    events = await _call(ctx.bot, chat_id, _api.get_today_events(chat_id), "Could not fetch calendar")
    if events is not None:
        await _send(ctx.bot, chat_id, _fmt_events(events))


async def cmd_scan(update, ctx) -> None:
    chat_id = update.effective_chat.id
    if not await _get_registered_user(ctx.bot, chat_id):
        return
    await _send(ctx.bot, chat_id, "📧 Scanning your Gmail for action items…")
    await ctx.bot.send_chat_action(chat_id=chat_id, action="typing")
    result = await _call(ctx.bot, chat_id, _api.scan_gmail(chat_id), "Gmail scan failed")
    if result:
        await _send(ctx.bot, chat_id,
            f"✅ *Gmail Scan Complete*\n"
            f"Emails scanned: {result.get('emails_scanned', 0)}\n"
            f"Tasks created:  {result.get('tasks_created', 0)}\n\n"
            "Use /tasks to see your updated list.")


async def cmd_briefing(update, ctx) -> None:
    chat_id = update.effective_chat.id
    if not await _get_registered_user(ctx.bot, chat_id):
        return
    await _send(ctx.bot, chat_id, "☀️ Generating your briefing…")
    await ctx.bot.send_chat_action(chat_id=chat_id, action="typing")
    result = await _call(ctx.bot, chat_id, _api.get_briefing(chat_id), "Briefing failed")
    if result:
        text = result.get("briefing") or result.get("content") or str(result)
        await _send(ctx.bot, chat_id, f"☀️ *Your Morning Briefing*\n\n{text}")


async def cmd_forecast(update, ctx) -> None:
    chat_id = update.effective_chat.id
    if not await _get_registered_user(ctx.bot, chat_id):
        return
    await ctx.bot.send_chat_action(chat_id=chat_id, action="typing")
    result = await _call(ctx.bot, chat_id, _api.get_forecast(chat_id), "Forecast failed")
    if result:
        text = result.get("forecast") or result.get("summary") or str(result)
        await _send(ctx.bot, chat_id, f"📊 *Workload Forecast*\n\n{text}")


# ── Message handlers ──────────────────────────────────────────────────────────

async def on_text(update, ctx) -> None:
    """Route all plain-text messages through AIDEN orchestrator."""
    if not update.message or not update.message.text:
        return
    chat_id = update.effective_chat.id
    text    = update.message.text

    user = await _get_registered_user(ctx.bot, chat_id)
    if not user:
        return

    await ctx.bot.send_chat_action(chat_id=chat_id, action="typing")
    result = await _call(
        ctx.bot, chat_id,
        _api.chat(chat_id, f"[TELEGRAM] {text}", _sessions.get(chat_id)),
        "Something went wrong",
    )
    if not result:
        return

    _sessions[chat_id] = result.get("session_id") or _sessions.get(chat_id, "")
    response = result.get("response", "…")
    agents   = result.get("agents_used", [])
    reply    = _trunc(response)
    if agents:
        reply += f"\n\n_via {' · '.join(a.upper() for a in agents)}_"
    await _send(ctx.bot, chat_id, reply)


async def on_voice(update, ctx) -> None:
    """Transcribe voice note and route through orchestrator."""
    if not update.message:
        return
    chat_id   = update.effective_chat.id
    voice_obj = update.message.voice or update.message.audio
    if not voice_obj:
        return

    if not await _get_registered_user(ctx.bot, chat_id):
        return

    await _send(ctx.bot, chat_id, "🎤 Processing your voice note…")
    await ctx.bot.send_chat_action(chat_id=chat_id, action="typing")

    try:
        tg_file = await ctx.bot.get_file(voice_obj.file_id)
        async with httpx.AsyncClient() as dl:
            resp = await dl.get(tg_file.file_path)
        audio_b64 = base64.b64encode(resp.content).decode()
    except Exception as exc:
        await _send(ctx.bot, chat_id, f"⚠️ Could not download voice note: {exc}")
        return

    result = await _call(ctx.bot, chat_id,
        _api.transcribe_and_run(chat_id, audio_b64), "Voice processing failed")
    if not result:
        return

    parts = []
    if result.get("transcript"):
        parts.append(f"📝 *Transcript:* _{result['transcript']}_")
    if result.get("aiden_response"):
        parts.append(result["aiden_response"])
    if result.get("actions_taken"):
        parts.append(f"_via {' · '.join(a.upper() for a in result['actions_taken'])}_")
    await _send(ctx.bot, chat_id, "\n\n".join(parts) or "✅ Processed!")


async def on_photo(update, ctx) -> None:
    """Analyze photo/document with vision agent."""
    if not update.message:
        return
    chat_id = update.effective_chat.id

    if not await _get_registered_user(ctx.bot, chat_id):
        return

    photo  = update.message.photo[-1] if update.message.photo else None
    doc    = update.message.document
    target = photo or doc
    if not target:
        return

    caption = update.message.caption or ""
    await ctx.bot.send_chat_action(chat_id=chat_id, action="typing")

    try:
        tg_file = await ctx.bot.get_file(target.file_id)
        async with httpx.AsyncClient() as dl:
            resp = await dl.get(tg_file.file_path)
        image_b64 = base64.b64encode(resp.content).decode()
    except Exception as exc:
        await _send(ctx.bot, chat_id, f"⚠️ Could not download image: {exc}")
        return

    result = await _call(ctx.bot, chat_id,
        _api.analyze_image(chat_id, image_b64, caption), "Vision analysis failed")
    if result:
        text = result.get("analysis") or result.get("response") or str(result)
        await _send(ctx.bot, chat_id, f"👁️ *Vision Analysis*\n\n{text}")


# ── Build and run ─────────────────────────────────────────────────────────────

def build_application():
    try:
        from telegram.ext import Application, CommandHandler, MessageHandler, filters
    except ImportError as exc:
        raise ImportError(
            "python-telegram-bot not installed.\n"
            "Run: pip install 'python-telegram-bot>=21.0'"
        ) from exc

    app = Application.builder().token(bot_cfg.TELEGRAM_BOT_TOKEN).build()

    # Account (open to all — no registration check)
    app.add_handler(CommandHandler("start",    cmd_start))
    app.add_handler(CommandHandler("register", cmd_register))
    app.add_handler(CommandHandler("login",    cmd_login))
    app.add_handler(CommandHandler("help",     cmd_help))

    # Account (requires registration)
    app.add_handler(CommandHandler("unlink",   cmd_unlink))
    app.add_handler(CommandHandler("me",       cmd_me))

    # Tasks
    app.add_handler(CommandHandler("tasks",    cmd_tasks))
    app.add_handler(CommandHandler("task",     cmd_task))
    app.add_handler(CommandHandler("done",     cmd_done))

    # Notes
    app.add_handler(CommandHandler("notes",    cmd_notes))
    app.add_handler(CommandHandler("note",     cmd_note))
    app.add_handler(CommandHandler("search",   cmd_search))

    # Calendar & Gmail
    app.add_handler(CommandHandler("today",    cmd_today))
    app.add_handler(CommandHandler("scan",     cmd_scan))

    # Intelligence
    app.add_handler(CommandHandler("briefing", cmd_briefing))
    app.add_handler(CommandHandler("forecast", cmd_forecast))

    # Media
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, on_voice))
    app.add_handler(MessageHandler(filters.PHOTO | filters.Document.ALL, on_photo))

    log.info("telegram_bot_built")
    return app


async def run_bot() -> None:
    """Entry point — called from main.py lifespan as a background task."""
    if not bot_cfg.TELEGRAM_BOT_TOKEN:
        log.warning("telegram_bot_disabled", reason="TELEGRAM_BOT_TOKEN not set in .env")
        return
    if not bot_cfg.BOT_SERVICE_SECRET:
        log.warning("telegram_bot_disabled", reason="BOT_SERVICE_SECRET not set in .env")
        return

    app = build_application()
    log.info("telegram_bot_starting", api=bot_cfg.AIDEN_API_URL)
    async with app:
        await app.initialize()
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True)
        log.info("telegram_bot_running")
        await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(run_bot())
