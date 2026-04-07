"""
AIDEN Runner v3.1 — ADK execution engine with full trace emission
=================================================================
Full merge of:
  - v3.0 merged: run_with_trace, run_agent, build_runner(user) for MCP sessions
  - v4 file-upload: run_with_trace_multimodal, run_agent_multimodal

Streaming protocol (SSE):
  {"type": "trace_step",   "step": {...}}
  {"type": "agent_active", "agent": str, "color": str}
  {"type": "done",         "response": str, "session_id": str, "trace": {...}}
  {"type": "done",         ..., "file_info": {...}}   ← multimodal only
  {"type": "error",        "detail": str, "session_id": str}
"""
from __future__ import annotations

import asyncio
import uuid
from typing import AsyncIterator, Any

import structlog
from google.adk.runners import Runner
from google.genai.types import Content, Part

from src.agents.orchestrator import aiden_core, build_orchestrator
from src.core.config import settings
from src.core.session import session_service
from src.core.tracer import AgentTrace, TraceCollector, persist_trace
from src.core.file_processor import file_to_parts, friendly_file_label

log = structlog.get_logger()
APP_NAME = "aiden"


class AIDENRunner:
    """
    Wraps ADK Runner with full trace capture and SSE streaming.

    Methods:
      run_with_trace()             — SSE streaming, text only
      run_agent()                  — non-streaming, text only (voice/vision routers)
      run_with_trace_multimodal()  — SSE streaming + attached file (v4)
      run_agent_multimodal()       — non-streaming + file (Telegram bot, v4)
    """

    def __init__(self, agent: Any = None) -> None:
        _agent = agent if agent is not None else aiden_core
        self.runner = Runner(
            agent=_agent,
            app_name=APP_NAME,
            session_service=session_service,
        )
        log.info("aiden_runner_initialized")

    async def _ensure_session(self, user_id: str, session_id: str) -> None:
        existing = await session_service.get_session(
            app_name=APP_NAME,
            user_id=user_id,
            session_id=session_id,
        )
        if not existing:
            await session_service.create_session(
                app_name=APP_NAME,
                user_id=user_id,
                session_id=session_id,
            )

    async def run_with_trace(
        self,
        user_id: str,
        message: str,
        session_id: str | None = None,
    ) -> AsyncIterator[dict]:
        """Execute orchestrator and emit SSE-ready dicts (text input only)."""
        if not session_id:
            session_id = str(uuid.uuid4())

        run_log = log.bind(user_id=user_id, session_id=session_id)
        run_log.info("run_with_trace_start", message_length=len(message))

        collector = TraceCollector(
            user_id=user_id,
            session_id=session_id,
            user_message=message,
        )

        try:
            await self._ensure_session(user_id, session_id)
            user_message = Content(role="user", parts=[Part(text=message)])

            response_text    = ""
            last_agent_label = ""

            async for event in self.runner.run_async(
                user_id=user_id,
                session_id=session_id,
                new_message=user_message,
            ):
                steps = collector.process_event(event)
                for step in steps:
                    yield {"type": "trace_step", "step": step.to_dict()}
                    if step.agent_label != last_agent_label:
                        last_agent_label = step.agent_label
                        yield {
                            "type":  "agent_active",
                            "agent": step.agent_label,
                            "color": step.agent_color,
                            "icon":  step.agent_icon,
                        }
                if event.is_final_response() and event.content:
                    for part in event.content.parts:
                        txt = getattr(part, "text", None)
                        if txt:
                            response_text += txt

            trace: AgentTrace = collector.finalise(response_text, success=True)
            asyncio.create_task(persist_trace(trace))
            run_log.info("run_with_trace_complete",
                         agents=trace.agents_involved,
                         steps=len(trace.steps),
                         duration_ms=trace.total_duration_ms)
            yield {
                "type":       "done",
                "response":   response_text,
                "session_id": session_id,
                "trace":      trace.to_dict(),
            }

        except Exception as exc:
            run_log.error("run_with_trace_failed", error=str(exc), exc_info=True)
            trace = collector.finalise("", success=False, error=str(exc))
            asyncio.create_task(persist_trace(trace))
            yield {
                "type":       "error",
                "detail":     str(exc) if settings.DEBUG else "Internal error",
                "session_id": session_id,
            }

    async def run_agent(
        self,
        user_id: str,
        message: str,
        session_id: str | None = None,
    ) -> dict:
        """Non-streaming execution — voice / vision routers."""
        if not session_id:
            session_id = str(uuid.uuid4())

        run_log = log.bind(user_id=user_id, session_id=session_id)
        run_log.info("run_agent_start", message_length=len(message))

        collector = TraceCollector(
            user_id=user_id,
            session_id=session_id,
            user_message=message,
        )

        try:
            await self._ensure_session(user_id, session_id)
            user_message = Content(role="user", parts=[Part(text=message)])
            response_text = ""

            async for event in self.runner.run_async(
                user_id=user_id,
                session_id=session_id,
                new_message=user_message,
            ):
                collector.process_event(event)
                if event.is_final_response() and event.content:
                    for part in event.content.parts:
                        txt = getattr(part, "text", None)
                        if txt:
                            response_text += txt

            trace = collector.finalise(response_text, success=True)
            asyncio.create_task(persist_trace(trace))
            run_log.info("run_agent_complete",
                         agents=trace.agents_involved,
                         duration_ms=trace.total_duration_ms)
            return {
                "response":    response_text,
                "session_id":  session_id,
                "agents_used": trace.agents_involved,
                "trace":       trace.to_dict(),
                "success":     True,
            }

        except Exception as exc:
            run_log.error("run_agent_failed", error=str(exc), exc_info=True)
            return {
                "response":   "I encountered an error. Please try again.",
                "session_id": session_id,
                "error":      str(exc) if settings.DEBUG else "Internal error",
                "success":    False,
            }

    async def run_with_trace_multimodal(
        self,
        user_id:    str,
        message:    str,
        file_bytes: bytes,
        mime_type:  str,
        filename:   str,
        session_id: str | None = None,
    ) -> AsyncIterator[dict]:
        """
        SSE-streaming execution with an attached file.
        Supports: images, audio, PDF, plain text, DOCX, XLSX.
        File is converted to Gemini-compatible Parts by FileProcessor.
        """
        if not session_id:
            session_id = str(uuid.uuid4())

        run_log = log.bind(user_id=user_id, session_id=session_id)
        label   = friendly_file_label(mime_type, filename)
        run_log.info("run_with_trace_multimodal_start",
                     filename=filename, mime=mime_type, size=len(file_bytes))

        collector = TraceCollector(
            user_id=user_id,
            session_id=session_id,
            user_message=f"[{label}: {filename}] {message}",
        )

        try:
            await self._ensure_session(user_id, session_id)

            file_parts = await file_to_parts(file_bytes, mime_type, filename, caption=message)
            if message and not any(getattr(p, "text", None) == message for p in file_parts):
                file_parts.append(Part(text=message))

            user_message = Content(role="user", parts=file_parts)

            response_text    = ""
            last_agent_label = ""

            async for event in self.runner.run_async(
                user_id=user_id,
                session_id=session_id,
                new_message=user_message,
            ):
                steps = collector.process_event(event)
                for step in steps:
                    yield {"type": "trace_step", "step": step.to_dict()}
                    if step.agent_label != last_agent_label:
                        last_agent_label = step.agent_label
                        yield {
                            "type":  "agent_active",
                            "agent": step.agent_label,
                            "color": step.agent_color,
                            "icon":  step.agent_icon,
                        }
                if event.is_final_response() and event.content:
                    for part in event.content.parts:
                        txt = getattr(part, "text", None)
                        if txt:
                            response_text += txt

            trace = collector.finalise(response_text, success=True)
            asyncio.create_task(persist_trace(trace))
            run_log.info("run_with_trace_multimodal_complete",
                         agents=trace.agents_involved,
                         duration_ms=trace.total_duration_ms)
            yield {
                "type":       "done",
                "response":   response_text,
                "session_id": session_id,
                "trace":      trace.to_dict(),
                "file_info":  {"filename": filename, "mime_type": mime_type, "label": label},
            }

        except Exception as exc:
            run_log.error("run_with_trace_multimodal_failed", error=str(exc), exc_info=True)
            trace = collector.finalise("", success=False, error=str(exc))
            asyncio.create_task(persist_trace(trace))
            yield {
                "type":       "error",
                "detail":     str(exc) if settings.DEBUG else "Internal error",
                "session_id": session_id,
            }

    async def run_agent_multimodal(
        self,
        user_id:    str,
        message:    str,
        file_bytes: bytes,
        mime_type:  str,
        filename:   str,
        session_id: str | None = None,
    ) -> dict:
        """Non-streaming multimodal execution — Telegram bot and API clients."""
        if not session_id:
            session_id = str(uuid.uuid4())

        run_log = log.bind(user_id=user_id, session_id=session_id)
        label   = friendly_file_label(mime_type, filename)
        run_log.info("run_agent_multimodal_start", filename=filename, mime=mime_type)

        collector = TraceCollector(
            user_id=user_id,
            session_id=session_id,
            user_message=f"[{label}: {filename}] {message}",
        )

        try:
            await self._ensure_session(user_id, session_id)

            file_parts = await file_to_parts(file_bytes, mime_type, filename, caption=message)
            if message and not any(getattr(p, "text", None) == message for p in file_parts):
                file_parts.append(Part(text=message))

            user_message = Content(role="user", parts=file_parts)
            response_text = ""

            async for event in self.runner.run_async(
                user_id=user_id,
                session_id=session_id,
                new_message=user_message,
            ):
                collector.process_event(event)
                if event.is_final_response() and event.content:
                    for part in event.content.parts:
                        txt = getattr(part, "text", None)
                        if txt:
                            response_text += txt

            trace = collector.finalise(response_text, success=True)
            asyncio.create_task(persist_trace(trace))
            run_log.info("run_agent_multimodal_complete",
                         agents=trace.agents_involved,
                         duration_ms=trace.total_duration_ms)
            return {
                "response":    response_text,
                "session_id":  session_id,
                "agents_used": trace.agents_involved,
                "file_info":   {"filename": filename, "mime_type": mime_type, "label": label},
                "trace":       trace.to_dict(),
                "success":     True,
            }

        except Exception as exc:
            run_log.error("run_agent_multimodal_failed", error=str(exc), exc_info=True)
            return {
                "response":   "I encountered an error processing your file. Please try again.",
                "session_id": session_id,
                "error":      str(exc) if settings.DEBUG else "Internal error",
                "success":    False,
            }


# Default sync runner — backwards compat with voice/vision/telegram routers
aiden_runner = AIDENRunner()


async def build_runner(user: Any) -> "AIDENRunner":
    """
    Build a per-session AIDENRunner with MCP-enabled orchestrator (v3.0+).
    Use this in chat router for sessions needing MCP tools.
    Multimodal methods are available on the returned runner too.
    """
    agent = await build_orchestrator(user=user)
    return AIDENRunner(agent=agent)


async def run_agent(
    user_id: str,
    message: str,
    session_id: str | None = None,
) -> dict:
    """Convenience wrapper — non-streaming text (voice / vision routers)."""
    return await aiden_runner.run_agent(user_id, message, session_id)
