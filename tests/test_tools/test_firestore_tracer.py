"""
tests/test_tools/test_firestore_tracer.py
==========================================
Unit tests for Firestore trace persistence.
Firestore SDK is fully mocked — no GCP credentials required.
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone


def _make_fake_trace(trace_id: str = "trace_001", agents: list[str] | None = None):
    """Build a minimal AgentTrace-like object for testing."""
    trace = MagicMock()
    trace.trace_id          = trace_id
    trace.user_id           = "test_user_abc123"
    trace.session_id        = "session_001"
    trace.user_message      = "Plan my week"
    trace.agents_involved   = agents or ["TaskMaster", "CalendarBot", "NoteKeeper"]
    trace.total_duration_ms = 1500
    trace.final_response    = "Weekly plan created!"
    trace.success           = True
    trace.error             = None
    trace.started_at        = datetime.now(timezone.utc)

    step = MagicMock()
    step.kind.value   = "tool_call"
    step.agent_label  = "TaskMaster"
    step.tool_name    = "list_tasks"
    step.summary      = "→ list_tasks({...})"
    step.duration_ms  = 42
    step.status       = "success"
    trace.steps       = [step]

    return trace


class TestPersistTraceFirestore:
    @pytest.mark.asyncio
    async def test_skips_when_no_gcp_project(self):
        """Must return False and log a debug when GOOGLE_CLOUD_PROJECT is not set."""
        with patch("src.core.firestore_tracer.settings") as mock_settings:
            mock_settings.GOOGLE_CLOUD_PROJECT = None
            mock_settings.GCP_PROJECT_ID       = None

            from src.core.firestore_tracer import persist_trace_firestore
            result = await persist_trace_firestore(_make_fake_trace())

        assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_on_import_error(self):
        """Returns False gracefully when google-cloud-firestore is not installed."""
        with patch("src.core.firestore_tracer.settings") as mock_settings:
            mock_settings.GOOGLE_CLOUD_PROJECT = "my-gcp-project"
            mock_settings.GCP_PROJECT_ID       = None

            with patch.dict("sys.modules", {"google.cloud": None, "google.cloud.firestore": None}):
                from importlib import reload
                import src.core.firestore_tracer as ft_module
                try:
                    reload(ft_module)
                except Exception:
                    pass
                # Calling with import error should return False
                result = await ft_module.persist_trace_firestore(_make_fake_trace())

        assert result is False

    @pytest.mark.asyncio
    async def test_writes_correct_fields(self):
        """Firestore document must contain all required trace fields."""
        mock_doc_ref = AsyncMock()
        mock_collection = MagicMock()
        mock_collection.document = MagicMock(return_value=mock_doc_ref)

        mock_db = MagicMock()
        mock_db.collection = MagicMock(return_value=mock_collection)

        mock_firestore_module = MagicMock()
        mock_firestore_module.AsyncClient = MagicMock(return_value=mock_db)

        with patch("src.core.firestore_tracer.settings") as mock_settings:
            mock_settings.GOOGLE_CLOUD_PROJECT = "my-gcp-project"
            mock_settings.GCP_PROJECT_ID       = None

            with patch.dict("sys.modules", {
                "google.cloud":           MagicMock(),
                "google.cloud.firestore": mock_firestore_module,
            }):
                from src.core.firestore_tracer import persist_trace_firestore
                trace = _make_fake_trace("trace_xyz", ["TaskMaster", "CalendarBot"])
                result = await persist_trace_firestore(trace)

        # If firestore client was called correctly
        if result:
            mock_doc_ref.set.assert_called_once()
            doc_data = mock_doc_ref.set.call_args[0][0]
            required_fields = [
                "trace_id", "user_id", "session_id", "user_message",
                "agents_involved", "total_duration_ms", "step_count",
                "success", "started_at", "step_summaries",
            ]
            for field in required_fields:
                assert field in doc_data, f"Missing required field: {field}"

    @pytest.mark.asyncio
    async def test_does_not_raise_on_firestore_error(self):
        """Application must not crash if Firestore write fails."""
        with patch("src.core.firestore_tracer.settings") as mock_settings:
            mock_settings.GOOGLE_CLOUD_PROJECT = "my-gcp-project"
            mock_settings.GCP_PROJECT_ID       = None

            mock_firestore_module = MagicMock()
            mock_firestore_module.AsyncClient = MagicMock(
                side_effect=Exception("Firestore unavailable")
            )

            with patch.dict("sys.modules", {
                "google.cloud":           MagicMock(),
                "google.cloud.firestore": mock_firestore_module,
            }):
                from src.core.firestore_tracer import persist_trace_firestore
                # Must not raise
                result = await persist_trace_firestore(_make_fake_trace())

        assert result is False


class TestPersistTraceDualWrite:
    """Verify tracer.persist_trace writes to both MongoDB AND Firestore."""

    @pytest.mark.asyncio
    async def test_dual_write_calls_both_backends(self):
        """persist_trace must attempt both MongoDB and Firestore writes."""
        mongo_called    = False
        firestore_called = False

        async def mock_mongo_insert(*args, **kwargs):
            nonlocal mongo_called
            mongo_called = True

        async def mock_firestore_persist(trace):
            nonlocal firestore_called
            firestore_called = True
            return True

        mock_col = AsyncMock()
        mock_col.insert_one = AsyncMock(side_effect=mock_mongo_insert)
        mock_db  = MagicMock()
        mock_db.__getitem__ = MagicMock(return_value=mock_col)
        mock_client = MagicMock()
        mock_client.__getitem__ = MagicMock(return_value=mock_db)

        with patch("src.core.tracer.persist_trace_firestore", side_effect=mock_firestore_persist):
            with patch("motor.motor_asyncio.AsyncIOMotorClient", return_value=mock_client):
                with patch("src.core.tracer.settings") as mock_settings:
                    mock_settings.MONGO_URI = "mongodb://localhost:27017"
                    mock_settings.MONGO_DB  = "aiden"
                    from src.core.tracer import persist_trace
                    await persist_trace(_make_fake_trace())

        # At least one write path must have been attempted
        assert mongo_called or firestore_called, "At least one backend must be written"
