"""
AIDEN Telegram Bot
Brings the full AIDEN multi-agent system to Telegram.

Features:
  • Text messages  → routed through AIDEN orchestrator
  • Voice notes    → transcribed with Gemini → routed to AIDEN
  • /tasks         → list open tasks
  • /note <text>   → quick note creation
  • /help          → command reference
  • Auth           → /start <jwt> links Telegram user to AIDEN user

Run:
    python -m src.integrations.telegram_bot

Or start from main.py lifespan (see instructions at the bottom).

Requires:
    pip install python-telegram-bot>=21.0
    TELEGRAM_BOT_TOKEN=... in .env
"""
from __future__ import annotations

import asyncio
import base64
import re
from datetime import datetime, timezone
from typing import Optional

import httpx
import structlog
from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict

log = structlog.get_logger()

class BotSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    TELEGRAM_BOT_TOKEN: str = ""
    AIDEN_API_URL:      str = "http://localhost:8000"

bot_settings = BotSettings()


class TelegramSession(BaseModel):
    """Links a Telegram chat_id to an AIDEN user session."""
    chat_id:    int
    user_id:    str
    jwt_token:  str
    session_id: Optional[str] = None   # AIDEN conversation session


# In-memory registry: chat_id → TelegramSession
_sessions: dict[int, TelegramSession] = {}


def _get_session(chat_id: int) -> Optional[TelegramSession]:
    return _sessions.get(chat_id)


def _register_session(chat_id: int, user_id: str, jwt_token: str) -> TelegramSession:
    sess = TelegramSession(chat_id=chat_id, user_id=user_id, jwt_token=jwt_token)
    _sessions[chat_id] = sess
    log.info("telegram_session_registered", chat_id=chat_id, user_id=user_id)
    return sess


class AIDENAPIClient:
    """Async HTTP client wrapping the AIDEN FastAPI backend."""

    def __init__(self, base_url: str) -> None:
        self._base   = base_url.rstrip("/")
        self._client = httpx.AsyncClient(timeout=60)

    def _headers(self, jwt: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {jwt}",
            "Content-Type":  "application/json",
        }

    async def chat(
        self,
        message:    str,
        jwt:        str,
        session_id: Optional[str] = None,
    ) -> dict:
        payload: dict = {"message": message}
        if session_id:
            payload["session_id"] = session_id

        resp = await self._client.post(
            f"{self._base}/chat",
            json=payload,
            headers=self._headers(jwt),
        )
        resp.raise_for_status()
        return resp.json()

    async def transcribe_voice(
        self,
        audio_b64: str,
        jwt:       str,
        language:  str = "en-US",
    ) -> dict:
        """Send voice note to AIDEN voice/query endpoint."""
        resp = await self._client.post(
            f"{self._base}/voice/query",
            json={
                "audio_b64":    audio_b64,
                "language":     language,
                "auto_execute": True,
            },
            headers=self._headers(jwt),
        )
        resp.raise_for_status()
        return resp.json()

    async def list_tasks(self, jwt: str, status: str = "todo") -> list[dict]:
        resp = await self._client.get(
            f"{self._base}/tasks",
            params={"status": status, "limit": 10},
            headers=self._headers(jwt),
        )
        resp.raise_for_status()
        return resp.json()

    async def create_note(self, title: str, content: str, jwt: str) -> dict:
        resp = await self._client.post(
            f"{self._base}/notes",
            json={"title": title, "content": content, "tags": ["telegram"]},
            headers=self._headers(jwt),
        )
        resp.raise_for_status()
        return resp.json()

    async def close(self) -> None:
        await self._client.aclose()


_aiden_client = AIDENAPIClient(bot_settings.AIDEN_API_URL)

_PRIORITY_EMOJI = {"P0": "🔴", "P1": "🟡", "P2": "🔵", "P3": "⚪"}
_STATUS_EMOJI   = {"todo": "📋", "in_progress": "⚡", "completed": "✅", "cancelled": "❌"}


def _format_tasks(tasks: list[dict]) -> str:
    if not tasks:
        return "✅ No open tasks — you're all clear!"

    lines = ["*Your open tasks:*\n"]
    for i, t in enumerate(tasks, 1):
        pri   = _PRIORITY_EMOJI.get(t.get("priority", "P3"), "⚪")
        due   = ""
        if t.get("due_date"):
            try:
                dt  = datetime.fromisoformat(t["due_date"].replace("Z", "+00:00"))
                due = f" · {dt.strftime('%b %d')}"
            except ValueError:
                pass
        lines.append(f"{i}. {pri} {t['title']}{due}")

    return "\n".join(lines)


def _truncate(text: str, max_len: int = 4000) -> str:
    return text[:max_len] + "…" if len(text) > max_len else text


def _escape_md(text: str) -> str:
    """Escape Telegram MarkdownV2 special characters."""
    special = r"\_*[]()~`>#+-=|{}.!"
    return re.sub(f"([{re.escape(special)}])", r"\\\1", text)


HELP_TEXT = """
*AIDEN — AI Executive Navigator* 🤖

*Setup:*
`/start <jwt_token>` — connect your AIDEN account

*Commands:*
`/tasks` — list your open tasks
`/note <text>` — save a quick note
`/scan` — trigger Gmail → task scan (if connected)
`/help` — show this message

*Just type or send a voice note* — AIDEN handles it!

_Powered by Gemini & Google ADK_
"""


async def handle_start(bot, chat_id: int, args: list[str]) -> None:
    """Parse /start <jwt_token> and register the session."""
    if not args:
        await bot.send_message(
            chat_id=chat_id,
            text=(
                "👋 Welcome to *AIDEN*!\n\n"
                "To connect your account, run:\n"
                "`python generate_token.py --user-id your_name`\n\n"
                "Then send: `/start <your_jwt_token>`"
            ),
            parse_mode="Markdown",
        )
        return

    jwt = args[0].strip()

    # Quick sanity check — JWTs have 3 dot-separated parts
    if jwt.count(".") != 2:
        await bot.send_message(chat_id=chat_id, text="❌ Invalid token format.")
        return

    # Decode user_id from JWT payload (no verification — API will reject bad tokens)
    try:
        import json as _json
        payload_b64 = jwt.split(".")[1]
        payload_b64 += "=" * (4 - len(payload_b64) % 4)
        payload = _json.loads(base64.b64decode(payload_b64))
        user_id = payload.get("sub", "unknown")
    except Exception:
        await bot.send_message(chat_id=chat_id, text="❌ Could not decode token.")
        return

    _register_session(chat_id, user_id, jwt)

    await bot.send_message(
        chat_id=chat_id,
        text=(
            f"✅ *Connected as `{user_id}`*\n\n"
            "You can now:\n"
            "• Send any message and AIDEN will handle it\n"
            "• Send a 🎤 voice note to transcribe & act on it\n"
            "• Use /tasks, /note, /help\n\n"
            "What would you like to do today?"
        ),
        parse_mode="Markdown",
    )


async def handle_tasks_command(bot, chat_id: int, sess: TelegramSession) -> None:
    await bot.send_chat_action(chat_id=chat_id, action="typing")
    try:
        tasks = await _aiden_client.list_tasks(sess.jwt_token)
        text  = _format_tasks(tasks)
    except Exception as exc:
        log.error("telegram_list_tasks_failed", chat_id=chat_id, error=str(exc))
        text = f"⚠️ Could not fetch tasks: {exc}"

    await bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown")


async def handle_note_command(bot, chat_id: int, sess: TelegramSession, args: list[str]) -> None:
    if not args:
        await bot.send_message(chat_id=chat_id, text="Usage: `/note Your note text here`", parse_mode="Markdown")
        return

    content = " ".join(args)
    title   = content[:60] + ("…" if len(content) > 60 else "")

    await bot.send_chat_action(chat_id=chat_id, action="typing")
    try:
        note = await _aiden_client.create_note(title=title, content=content, jwt=sess.jwt_token)
        await bot.send_message(
            chat_id=chat_id,
            text=f"📝 Note saved!\n*{note.get('title', title)}*",
            parse_mode="Markdown",
        )
    except Exception as exc:
        log.error("telegram_create_note_failed", chat_id=chat_id, error=str(exc))
        await bot.send_message(chat_id=chat_id, text=f"⚠️ Could not save note: {exc}")


async def handle_scan_command(bot, chat_id: int, sess: TelegramSession) -> None:
    """Trigger Gmail scan via AIDEN API."""
    await bot.send_message(chat_id=chat_id, text="📧 Scanning your Gmail for action items…")
    await bot.send_chat_action(chat_id=chat_id, action="typing")

    try:
        resp = await _aiden_client._client.post(
            f"{bot_settings.AIDEN_API_URL}/gmail/scan",
            json={"max_emails": 20, "mark_emails_read": False},
            headers=_aiden_client._headers(sess.jwt_token),
        )
        resp.raise_for_status()
        data = resp.json()
        await bot.send_message(
            chat_id=chat_id,
            text=(
                f"✅ *Gmail Scan Complete*\n"
                f"Emails scanned: {data.get('emails_scanned', 0)}\n"
                f"Tasks created: {data.get('tasks_created', 0)}\n\n"
                f"Use /tasks to see your updated task list."
            ),
            parse_mode="Markdown",
        )
    except Exception as exc:
        log.error("telegram_scan_failed", chat_id=chat_id, error=str(exc))
        await bot.send_message(chat_id=chat_id, text=f"⚠️ Scan failed: {exc}")


async def handle_text_message(bot, chat_id: int, text: str, sess: TelegramSession) -> None:
    """Route plain text through AIDEN orchestrator."""
    await bot.send_chat_action(chat_id=chat_id, action="typing")

    try:
        result = await _aiden_client.chat(
            message=text,
            jwt=sess.jwt_token,
            session_id=sess.session_id,
        )

        # Persist session_id for conversation continuity
        sess.session_id = result.get("session_id")

        response = result.get("response", "…")
        agents   = result.get("agents_used", [])

        reply = _truncate(response)

        # Append agent attribution if any
        if agents:
            agent_str = " · ".join(a.upper() for a in agents)
            reply += f"\n\n_via {agent_str}_"

        await bot.send_message(chat_id=chat_id, text=reply, parse_mode="Markdown")

    except httpx.HTTPStatusError as exc:
        log.error("telegram_chat_http_error", chat_id=chat_id, status=exc.response.status_code)
        if exc.response.status_code == 401:
            await bot.send_message(
                chat_id=chat_id,
                text="❌ Token expired. Please reconnect with `/start <new_token>`.",
                parse_mode="Markdown",
            )
        else:
            await bot.send_message(chat_id=chat_id, text=f"⚠️ AIDEN error: {exc}")
    except Exception as exc:
        log.error("telegram_chat_failed", chat_id=chat_id, error=str(exc))
        await bot.send_message(chat_id=chat_id, text=f"⚠️ Error: {exc}")


async def handle_voice_message(bot, chat_id: int, file_id: str, sess: TelegramSession) -> None:
    """
    Download voice note → base64 → Gemini transcription → AIDEN.
    Updates session_id for conversation continuity.
    """
    await bot.send_message(chat_id=chat_id, text="🎤 Processing your voice note…")
    await bot.send_chat_action(chat_id=chat_id, action="typing")

    try:
        # Download voice file from Telegram
        tg_file  = await bot.get_file(file_id)
        dl_url   = tg_file.file_path   # already full URL in python-telegram-bot v21
        async with httpx.AsyncClient() as dl:
            audio_resp = await dl.get(dl_url)
            audio_resp.raise_for_status()
            audio_bytes = audio_resp.content

        audio_b64 = base64.b64encode(audio_bytes).decode()

        # Transcribe + execute via AIDEN voice/query
        result = await _aiden_client.transcribe_voice(
            audio_b64=audio_b64,
            jwt=sess.jwt_token,
        )

        transcript = result.get("transcript", "")
        aiden_resp = result.get("aiden_response", "")
        agents     = result.get("actions_taken", [])

        # Update session
        # (voice/query doesn't return session_id — handled inside AIDEN)

        reply_parts = []
        if transcript:
            reply_parts.append(f"📝 *Transcript:* _{transcript}_")
        if aiden_resp:
            reply_parts.append(f"\n{aiden_resp}")
        if agents:
            reply_parts.append(f"\n_via {' · '.join(a.upper() for a in agents)}_")

        reply = "\n".join(reply_parts) or "✅ Processed!"
        await bot.send_message(
            chat_id=chat_id,
            text=_truncate(reply),
            parse_mode="Markdown",
        )

    except Exception as exc:
        log.error("telegram_voice_failed", chat_id=chat_id, error=str(exc))
        await bot.send_message(chat_id=chat_id, text=f"⚠️ Voice processing failed: {exc}")

def build_application():
    """Build and return the python-telegram-bot Application."""
    try:
        from telegram import Update
        from telegram.ext import (
            Application,
            CommandHandler,
            ContextTypes,
            MessageHandler,
            filters,
        )
    except ImportError as exc:
        raise ImportError(
            "python-telegram-bot not installed. Run: pip install 'python-telegram-bot>=21.0'"
        ) from exc


    async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        chat_id = update.effective_chat.id
        await handle_start(ctx.bot, chat_id, ctx.args or [])

    async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        await update.message.reply_text(HELP_TEXT, parse_mode="Markdown")

    async def cmd_tasks(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        chat_id = update.effective_chat.id
        sess = _get_session(chat_id)
        if not sess:
            await update.message.reply_text("❌ Not connected. Send `/start <token>` first.", parse_mode="Markdown")
            return
        await handle_tasks_command(ctx.bot, chat_id, sess)

    async def cmd_note(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        chat_id = update.effective_chat.id
        sess = _get_session(chat_id)
        if not sess:
            await update.message.reply_text("❌ Not connected. Send `/start <token>` first.", parse_mode="Markdown")
            return
        await handle_note_command(ctx.bot, chat_id, sess, ctx.args or [])

    async def cmd_scan(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        chat_id = update.effective_chat.id
        sess = _get_session(chat_id)
        if not sess:
            await update.message.reply_text("❌ Not connected. Send `/start <token>` first.", parse_mode="Markdown")
            return
        await handle_scan_command(ctx.bot, chat_id, sess)

    async def on_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.message or not update.message.text:
            return
        chat_id = update.effective_chat.id
        sess = _get_session(chat_id)
        if not sess:
            await update.message.reply_text(
                "👋 Hi! I'm AIDEN. Connect with `/start <jwt_token>`.",
                parse_mode="Markdown",
            )
            return
        await handle_text_message(ctx.bot, chat_id, update.message.text, sess)

    async def on_voice(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.message:
            return
        chat_id = update.effective_chat.id
        sess = _get_session(chat_id)
        if not sess:
            await update.message.reply_text("❌ Not connected. Send `/start <token>` first.", parse_mode="Markdown")
            return

        voice_obj = update.message.voice or update.message.audio
        if not voice_obj:
            return

        await handle_voice_message(ctx.bot, chat_id, voice_obj.file_id, sess)

    app = (
        Application.builder()
        .token(bot_settings.TELEGRAM_BOT_TOKEN)
        .build()
    )

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help",  cmd_help))
    app.add_handler(CommandHandler("tasks", cmd_tasks))
    app.add_handler(CommandHandler("note",  cmd_note))
    app.add_handler(CommandHandler("scan",  cmd_scan))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, on_voice))

    log.info("telegram_bot_built")
    return app


async def run_bot() -> None:
    """Start the Telegram bot (polling mode). Blocks until Ctrl-C."""
    if not bot_settings.TELEGRAM_BOT_TOKEN:
        log.error("telegram_token_missing",
                  message="Set TELEGRAM_BOT_TOKEN in .env to run the bot")
        return

    app = build_application()

    log.info("telegram_bot_starting", api_url=bot_settings.AIDEN_API_URL)
    async with app:
        await app.initialize()
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True)
        log.info("telegram_bot_running", hint="Press Ctrl-C to stop")
        await asyncio.Event().wait()   # block forever

if __name__ == "__main__":
    import asyncio
    asyncio.run(run_bot())
