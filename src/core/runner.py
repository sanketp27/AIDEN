"""
AIDEN Runner v3.0 — ADK execution engine with full trace emission
=================================================================
Upgraded from v2: supports per-user async orchestrator with MCP tools.

run_with_trace()  — SSE streaming (chat router)
run_agent()       — non-streaming (voice / vision routers)
build_runner()    — async factory that creates a per-session Runner with MCP
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

log = structlog.get_logger()
APP_NAME = "aiden"


class AIDENRunner:
    """
    Wraps ADK Runner with full trace capture and SSE streaming.

    v3.0 upgrade: supports per-user orchestrator (with MCP tools).
    The default self.runner uses the sync aiden_core for backwards compat.
    Use build_runner(user) for MCP-enabled sessions.
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
        """Execute orchestrator and emit SSE-ready dicts."""
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
        """Non-streaming execution for voice / vision routers."""
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


# ── Default singleton (sync fallback — backwards compat) ──────────────────────
aiden_runner = AIDENRunner()


async def build_runner(user: Any) -> AIDENRunner:
    """
    Build a per-session AIDENRunner with the full MCP-enabled orchestrator.
    Use this in the chat router for sessions that need MCP tools.

    Example (chat.py):
        runner = await build_runner(current_user)
        async for event in runner.run_with_trace(user_id, message, session_id):
            yield event
    """
    agent = await build_orchestrator(user=user)
    return AIDENRunner(agent=agent)


async def run_agent(
    user_id: str,
    message: str,
    session_id: str | None = None,
) -> dict:
    """Convenience wrapper — non-streaming (voice / vision routers)."""
    return await aiden_runner.run_agent(user_id, message, session_id)
