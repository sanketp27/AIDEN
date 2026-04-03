from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

import structlog

log = structlog.get_logger()

class AgentKind(str, Enum):
    ORCHESTRATOR = "orchestrator"
    TASK_MASTER  = "task_master"
    CALENDAR_BOT = "calendar_bot"
    NOTE_KEEPER  = "note_keeper"
    VOICE_AGENT  = "voice_agent"
    VISION_AGENT = "vision_agent"
    UNKNOWN      = "unknown"


# Maps ADK agent `author` field → display name + colour token
AGENT_META: dict[str, dict] = {
    "aiden_core":       {"label": "Orchestrator",  "color": "cyan",   "icon": "◈"},
    "task_master":      {"label": "TaskMaster",    "color": "amber",  "icon": "✓"},
    "calendar_bot":     {"label": "CalendarBot",   "color": "blue",   "icon": "◷"},
    "note_keeper":      {"label": "NoteKeeper",    "color": "purple", "icon": "✦"},
    "voice_agent":      {"label": "VoiceAgent",    "color": "green",  "icon": "◎"},
    "vision_agent":     {"label": "VisionAgent",   "color": "coral",  "icon": "◉"},
}


def _agent_meta(author: str) -> dict:
    # Normalise: ADK sometimes sends class names or display names
    key = author.lower().replace(" ", "_").replace("-", "_")
    for k, v in AGENT_META.items():
        if k in key or key in k:
            return {"author": key, **v}
    return {"author": key, "label": author.upper(), "color": "gray", "icon": "○"}


class StepKind(str, Enum):
    ROUTING    = "routing"      # orchestrator decided to call a sub-agent
    TOOL_CALL  = "tool_call"    # agent invoked an @tool function
    TOOL_RESULT = "tool_result" # @tool returned a result
    THINKING   = "thinking"     # agent is generating (no tool, not final)
    RESPONSE   = "response"     # final text response produced


@dataclass
class TraceStep:
    """A single observable event in the agent execution chain."""
    step_id:      str          = field(default_factory=lambda: str(uuid.uuid4())[:8])
    kind:         StepKind     = StepKind.THINKING
    agent:        str          = ""            # raw ADK author string
    agent_label:  str          = ""            # human display name
    agent_color:  str          = "gray"
    agent_icon:   str          = "○"
    tool_name:    Optional[str] = None
    summary:      str          = ""            # one-line human description
    detail:       Optional[str] = None         # serialised input/output (truncated)
    duration_ms:  int          = 0
    started_at:   float        = field(default_factory=time.monotonic)
    status:       str          = "success"     # success | error

    def to_dict(self) -> dict:
        return {
            "step_id":     self.step_id,
            "kind":        self.kind.value,
            "agent":       self.agent,
            "agent_label": self.agent_label,
            "agent_color": self.agent_color,
            "agent_icon":  self.agent_icon,
            "tool_name":   self.tool_name,
            "summary":     self.summary,
            "detail":      self.detail,
            "duration_ms": self.duration_ms,
            "status":      self.status,
        }


@dataclass
class AgentTrace:
    """Complete execution trace for a single chat turn."""
    trace_id:         str       = field(default_factory=lambda: str(uuid.uuid4()))
    user_id:          str       = ""
    session_id:       str       = ""
    user_message:     str       = ""
    steps:            list[TraceStep] = field(default_factory=list)
    agents_involved:  list[str] = field(default_factory=list)
    total_duration_ms: int      = 0
    started_at:       datetime  = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    final_response:   str       = ""
    success:          bool      = True
    error:            Optional[str] = None

    def add_step(self, step: TraceStep) -> None:
        self.steps.append(step)
        if step.agent and step.agent not in self.agents_involved:
            self.agents_involved.append(step.agent)

    def to_dict(self) -> dict:
        return {
            "trace_id":         self.trace_id,
            "user_id":          self.user_id,
            "session_id":       self.session_id,
            "user_message":     self.user_message,
            "steps":            [s.to_dict() for s in self.steps],
            "agents_involved":  self.agents_involved,
            "total_duration_ms": self.total_duration_ms,
            "final_response":   self.final_response,
            "success":          self.success,
            "error":            self.error,
        }

    def to_mongo(self) -> dict:
        d = self.to_dict()
        d["started_at"] = self.started_at
        return d

class TraceCollector:
    """
    Stateful collector that parses raw ADK events and emits structured
    TraceStep objects.

    Usage (inside AIDENRunner):
        collector = TraceCollector(user_id, session_id, message)
        async for event in adk_runner.run_async(...):
            step = collector.process_event(event)  # may return None
            if step:
                yield {"type": "trace_step", "step": step.to_dict()}
        trace = collector.finalise(response_text)
    """

    def __init__(self, user_id: str, session_id: str, user_message: str) -> None:
        self.trace = AgentTrace(
            user_id=user_id,
            session_id=session_id,
            user_message=user_message,
        )
        self._wall_start       = time.monotonic()
        self._last_author: str = ""
        self._open_tool_steps: dict[str, TraceStep] = {}  # call_id → step

    def process_event(self, event) -> list[TraceStep]:  # noqa: ANN001
        """
        Parse an ADK runner event and return 0-N completed TraceStep objects.
        Caller should yield each as an SSE event.
        """
        completed: list[TraceStep] = []
        author = getattr(event, "author", "") or ""
        content = getattr(event, "content", None)
        meta = _agent_meta(author) if author else {}

        if author and author != self._last_author and self._last_author:
            step = self._make_routing_step(
                from_agent=self._last_author,
                to_agent=author,
                meta=meta,
            )
            self.trace.add_step(step)
            completed.append(step)

        if author:
            self._last_author = author

        if content and hasattr(content, "parts"):
            for part in content.parts:
                # Tool / function CALL
                fc = getattr(part, "function_call", None)
                if fc:
                    step = self._start_tool_step(fc, meta)
                    self.trace.add_step(step)
                    completed.append(step)

                # Tool / function RESPONSE
                fr = getattr(part, "function_response", None)
                if fr:
                    step = self._close_tool_step(fr, meta)
                    if step:
                        self.trace.add_step(step)
                        completed.append(step)

                # Plain thinking text (non-final intermediate text)
                text = getattr(part, "text", None)
                if text and not event.is_final_response():
                    step = self._make_thinking_step(author, meta, text)
                    self.trace.add_step(step)
                    completed.append(step)

        return completed

    def finalise(self, response_text: str, success: bool = True, error: str | None = None) -> AgentTrace:
        """Call once the ADK runner loop exits. Returns the complete trace."""
        elapsed_ms = int((time.monotonic() - self._wall_start) * 1000)
        self.trace.total_duration_ms = elapsed_ms
        self.trace.final_response    = response_text
        self.trace.success           = success
        self.trace.error             = error

        # Add final response step
        if response_text:
            meta = _agent_meta(self._last_author) if self._last_author else {"label": "AIDEN", "color": "cyan", "icon": "◈"}
            step = TraceStep(
                kind        = StepKind.RESPONSE,
                agent       = self._last_author,
                agent_label = meta.get("label", "AIDEN"),
                agent_color = meta.get("color", "cyan"),
                agent_icon  = meta.get("icon", "◈"),
                summary     = f"Response generated ({len(response_text)} chars)",
                duration_ms = elapsed_ms,
                status      = "success" if success else "error",
            )
            self.trace.add_step(step)

        log.info(
            "trace_finalised",
            trace_id=self.trace.trace_id,
            steps=len(self.trace.steps),
            agents=self.trace.agents_involved,
            duration_ms=elapsed_ms,
        )
        return self.trace


    def _make_routing_step(
        self,
        from_agent: str,
        to_agent: str,
        meta: dict,
    ) -> TraceStep:
        from_meta = _agent_meta(from_agent)
        return TraceStep(
            kind        = StepKind.ROUTING,
            agent       = from_agent,
            agent_label = from_meta.get("label", from_agent),
            agent_color = from_meta.get("color", "gray"),
            agent_icon  = from_meta.get("icon", "○"),
            summary     = f"Routed to {meta.get('label', to_agent)}",
            detail      = f"{from_meta.get('label', from_agent)} → {meta.get('label', to_agent)}",
            duration_ms = 0,
            status      = "success",
        )

    def _start_tool_step(self, fc, meta: dict) -> TraceStep:  # noqa: ANN001
        """Create and register an in-flight tool call step."""
        name  = getattr(fc, "name", "unknown_tool")
        args  = getattr(fc, "args", {})
        # Truncate args for display
        args_str = _truncate(str(args), 120)
        step = TraceStep(
            kind        = StepKind.TOOL_CALL,
            agent       = self._last_author,
            agent_label = meta.get("label", self._last_author),
            agent_color = meta.get("color", "gray"),
            agent_icon  = meta.get("icon", "○"),
            tool_name   = name,
            summary     = f"→ {name}({args_str})",
            detail      = str(args),
            duration_ms = 0,
            status      = "running",
        )
        # Use name as key (ADK doesn't always give call IDs)
        self._open_tool_steps[name] = step
        return step

    def _close_tool_step(self, fr, meta: dict) -> TraceStep | None:  # noqa: ANN001
        """Complete an in-flight tool step with its result."""
        name     = getattr(fr, "name", "")
        response = getattr(fr, "response", {})
        resp_str = _truncate(str(response), 120)

        open_step = self._open_tool_steps.pop(name, None)
        if open_step is None:
            # No matching call — emit a standalone result step
            return TraceStep(
                kind        = StepKind.TOOL_RESULT,
                agent       = self._last_author,
                agent_label = meta.get("label", self._last_author),
                agent_color = meta.get("color", "gray"),
                agent_icon  = meta.get("icon", "○"),
                tool_name   = name,
                summary     = f"← {name}: {resp_str}",
                detail      = str(response),
                duration_ms = 0,
                status      = "success",
            )

        elapsed = int((time.monotonic() - open_step.started_at) * 1000)
        open_step.duration_ms = elapsed
        open_step.status      = "success"
        open_step.detail      = f"args: {open_step.detail}\nresult: {resp_str}"
        open_step.summary     = f"← {name} ({elapsed}ms)"
        return open_step

    def _make_thinking_step(self, author: str, meta: dict, text: str) -> TraceStep:
        return TraceStep(
            kind        = StepKind.THINKING,
            agent       = author,
            agent_label = meta.get("label", author),
            agent_color = meta.get("color", "gray"),
            agent_icon  = meta.get("icon", "○"),
            summary     = _truncate(text.strip().replace("\n", " "), 80),
            duration_ms = 0,
            status      = "success",
        )


def _truncate(s: str, max_len: int) -> str:
    return s if len(s) <= max_len else s[:max_len - 1] + "…"

COLL_TRACES = "agent_traces"


async def persist_trace(trace: AgentTrace) -> None:
    """
    Fire-and-forget: save the completed trace to MongoDB.
    Called from the chat router after the SSE stream closes.
    """
    try:
        from motor.motor_asyncio import AsyncIOMotorClient
        from src.core.config import settings

        col = AsyncIOMotorClient(settings.MONGO_URI)[settings.MONGO_DB][COLL_TRACES]
        await col.insert_one(trace.to_mongo())
        log.info("trace_persisted", trace_id=trace.trace_id, steps=len(trace.steps))
    except Exception as exc:
        log.warning("trace_persist_failed", error=str(exc))
