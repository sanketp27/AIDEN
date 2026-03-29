"""
ADK Runner — Main agent execution entry point
Wraps ADK Runner (1.x API) with AIDEN Core orchestrator
"""
from google.adk.runners import Runner
from google.genai.types import Content, Part
from src.agents.orchestrator import aiden_core
from src.core.session import session_service
from src.core.config import settings
from typing import AsyncIterator
import structlog
import uuid

log = structlog.get_logger()

APP_NAME = "aiden"


class AIDENRunner:
    """
    Wrapper around ADK Runner for AIDEN Core orchestrator.
    Provides unified interface for chat API and UI.
    """

    def __init__(self):
        self.runner = Runner(
            agent=aiden_core,
            app_name=APP_NAME,
            session_service=session_service,
        )
        log.info("aiden_runner_initialized")

    async def _ensure_session(self, user_id: str, session_id: str) -> None:
        """Create session if it doesn't exist yet."""
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

    async def run_agent(
        self,
        user_id: str,
        message: str,
        session_id: str | None = None,
    ) -> dict:
        """
        Execute AIDEN Core with user message.

        Args:
            user_id: User identifier for data isolation
            message: User's message/query
            session_id: Optional session ID for conversation continuity

        Returns:
            Dictionary with response, session_id, and metadata
        """
        if not session_id:
            session_id = str(uuid.uuid4())

        log.info("agent_execution_start",
                 user_id=user_id,
                 session_id=session_id,
                 message_length=len(message))

        try:
            # ADK 1.x requires the session to exist before run_async
            await self._ensure_session(user_id, session_id)

            user_message = Content(
                role="user",
                parts=[Part(text=message)]
            )

            response_text = ""
            agent_traces = []

            async for event in self.runner.run_async(
                user_id=user_id,
                session_id=session_id,
                new_message=user_message,
            ):
                if event.is_final_response() and event.content:
                    for part in event.content.parts:
                        if hasattr(part, "text") and part.text:
                            response_text += part.text

                if hasattr(event, "author"):
                    agent_traces.append(event.author)

            log.info("agent_execution_complete",
                     user_id=user_id,
                     session_id=session_id,
                     response_length=len(response_text),
                     agents_used=len(set(agent_traces)))

            return {
                "response": response_text,
                "session_id": session_id,
                "agents_used": list(set(agent_traces)),
                "success": True,
            }

        except Exception as e:
            log.error("agent_execution_failed",
                      user_id=user_id,
                      session_id=session_id,
                      error=str(e))
            return {
                "response": "I encountered an error processing your request. Please try again.",
                "session_id": session_id,
                "error": str(e) if settings.DEBUG else "Internal error",
                "success": False,
            }

    async def run_agent_stream(
        self,
        user_id: str,
        message: str,
        session_id: str | None = None,
    ) -> AsyncIterator[dict]:
        """
        Execute AIDEN Core with streaming response.

        Yields:
            Streaming response chunks
        """
        if not session_id:
            session_id = str(uuid.uuid4())

        log.info("agent_stream_start", user_id=user_id, session_id=session_id)

        try:
            await self._ensure_session(user_id, session_id)

            user_message = Content(
                role="user",
                parts=[Part(text=message)]
            )

            async for event in self.runner.run_async(
                user_id=user_id,
                session_id=session_id,
                new_message=user_message,
            ):
                if event.content:
                    for part in event.content.parts:
                        if hasattr(part, "text") and part.text:
                            yield {
                                "type": "text_chunk",
                                "content": part.text,
                                "session_id": session_id,
                            }

                if hasattr(event, "author"):
                    yield {
                        "type": "agent_event",
                        "agent": event.author,
                        "session_id": session_id,
                    }

            yield {"type": "complete", "session_id": session_id}

        except Exception as e:
            log.error("agent_stream_failed", user_id=user_id, error=str(e))
            yield {
                "type": "error",
                "error": str(e) if settings.DEBUG else "Internal error",
                "session_id": session_id,
            }


# Singleton runner instance
aiden_runner = AIDENRunner()


async def run_agent(user_id: str, message: str, session_id: str | None = None) -> dict:
    """Convenience wrapper for running AIDEN agent."""
    return await aiden_runner.run_agent(user_id, message, session_id)
