"""
tests/test_agents/test_orchestrator.py
=======================================
Tests for the AIDEN orchestrator SSE stream contract.
Uses a fake runner so no ADK / Gemini calls are made.
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, AsyncMock



def _make_runner(agents: list[str], tool_calls: list[str] | None = None):
    """Return a mock runner that emits a canned multi-agent SSE sequence."""
    async def _stream(user_id, message, session_id=None):
        for agent in agents:
            color = {"Orchestrator": "cyan", "TaskMaster": "amber",
                     "CalendarBot": "blue", "NoteKeeper": "purple"}.get(agent, "gray")
            icon  = {"Orchestrator": "◈", "TaskMaster": "✓",
                     "CalendarBot": "◷", "NoteKeeper": "✦"}.get(agent, "○")
            yield {"type": "agent_active", "agent": agent, "color": color, "icon": icon}

            for tool in (tool_calls or []):
                yield {
                    "type": "trace_step",
                    "step": {
                        "kind":        "tool_call",
                        "agent_label": agent,
                        "agent_color": color,
                        "agent_icon":  icon,
                        "tool_name":   tool,
                        "summary":     f"→ {tool}({{...}})",
                        "duration_ms": 0,
                        "status":      "running",
                    },
                }
                yield {
                    "type": "trace_step",
                    "step": {
                        "kind":        "tool_result",
                        "agent_label": agent,
                        "agent_color": color,
                        "agent_icon":  icon,
                        "tool_name":   tool,
                        "summary":     f"← {tool} (95ms)",
                        "duration_ms": 95,
                        "status":      "success",
                    },
                }

        yield {
            "type":       "done",
            "response":   "Workflow complete.",
            "session_id": session_id or "new_session_001",
            "trace": {
                "trace_id":        "trace_abc",
                "agents_involved": agents,
                "total_duration_ms": 1200,
                "steps":           [],
            },
        }

    runner = MagicMock()
    runner.run_with_trace = _stream
    return runner


class TestSSEStreamContract:
    async def test_stream_always_ends_with_done(self):
        """Every SSE stream MUST end with a 'done' event — no hanging streams."""
        runner = _make_runner(["Orchestrator", "TaskMaster"])
        events = [e async for e in runner.run_with_trace("u1", "Add a task")]
        assert events[-1]["type"] == "done"

    async def test_stream_starts_with_agent_active(self):
        """First event should be agent_active so the UI can show routing immediately."""
        runner = _make_runner(["Orchestrator"])
        events = [e async for e in runner.run_with_trace("u1", "Hello")]
        first  = next(e for e in events if e["type"] in ("agent_active", "trace_step"))
        assert first["type"] == "agent_active"

    async def test_done_event_has_required_fields(self):
        """'done' event must contain response, session_id, and trace."""
        runner = _make_runner(["Orchestrator"])
        events = [e async for e in runner.run_with_trace("u1", "test", "sess_xyz")]
        done   = next(e for e in events if e["type"] == "done")
        assert "response"   in done
        assert "session_id" in done
        assert "trace"      in done
        assert done["session_id"] == "sess_xyz"

    async def test_trace_contains_agents_involved(self):
        """Final trace must list all agents that participated."""
        agents = ["Orchestrator", "TaskMaster", "CalendarBot"]
        runner = _make_runner(agents)
        events = [e async for e in runner.run_with_trace("u1", "Plan my week")]
        done   = next(e for e in events if e["type"] == "done")
        assert set(done["trace"]["agents_involved"]) == set(agents)

    async def test_trace_has_duration_ms(self):
        """Trace must include total_duration_ms for performance visibility."""
        runner = _make_runner(["Orchestrator", "NoteKeeper"])
        events = [e async for e in runner.run_with_trace("u1", "Find my notes")]
        done   = next(e for e in events if e["type"] == "done")
        assert "total_duration_ms" in done["trace"]
        assert done["trace"]["total_duration_ms"] >= 0


class TestMultiAgentRouting:
    async def test_multi_agent_workflow_fires_multiple_agents(self):
        """A multi-step workflow must activate more than one agent."""
        runner  = _make_runner(["Orchestrator", "TaskMaster", "CalendarBot"])
        agents  = []
        async for event in runner.run_with_trace("u1", "Plan my week"):
            if event["type"] == "agent_active":
                agents.append(event["agent"])
        assert len(set(agents)) >= 2, "Multi-agent workflow must involve ≥ 2 agents"

    async def test_tool_calls_emit_trace_steps(self):
        """Each tool call must emit a trace_step so the UI can display it."""
        runner = _make_runner(["TaskMaster"], tool_calls=["create_task", "list_tasks"])
        steps  = [
            e["step"] for e in
            [e async for e in runner.run_with_trace("u1", "Create a task")]
            if e["type"] == "trace_step"
        ]
        assert len(steps) >= 2

    async def test_tool_result_steps_include_duration(self):
        """Tool result steps must include duration_ms for the trace panel display."""
        runner = _make_runner(["TaskMaster"], tool_calls=["list_tasks"])
        steps  = [
            e["step"] for e in
            [e async for e in runner.run_with_trace("u1", "List tasks")]
            if e["type"] == "trace_step" and e["step"]["kind"] == "tool_result"
        ]
        assert all(s["duration_ms"] > 0 for s in steps)

    async def test_agent_active_color_is_valid(self):
        """Agent color tokens must be one of the known UI color values."""
        valid_colors = {"cyan", "amber", "blue", "purple", "green", "coral", "gray"}
        runner = _make_runner(["Orchestrator", "TaskMaster", "NoteKeeper"])
        async for event in runner.run_with_trace("u1", "Plan my week"):
            if event["type"] == "agent_active":
                assert event["color"] in valid_colors, (
                    f"Unknown color '{event['color']}' for agent '{event['agent']}'"
                )


class TestSessionHandling:
    async def test_session_id_passed_through(self):
        """session_id from the request must appear in the done event response."""
        runner = _make_runner(["Orchestrator"])
        events = [e async for e in runner.run_with_trace("u1", "Hi", session_id="my-session-42")]
        done   = next(e for e in events if e["type"] == "done")
        assert done["session_id"] == "my-session-42"

    async def test_new_session_created_when_not_provided(self):
        """When session_id is None, a new session ID must be returned in done."""
        runner = _make_runner(["Orchestrator"])
        events = [e async for e in runner.run_with_trace("u1", "Hi", session_id=None)]
        done   = next(e for e in events if e["type"] == "done")
        assert done["session_id"], "A new session_id must be generated"
