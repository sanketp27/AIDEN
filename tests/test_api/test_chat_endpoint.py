from __future__ import annotations

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch



@pytest.fixture
def client(fake_user):
    """FastAPI TestClient with auth bypassed."""
    from src.api.main import app
    from fastapi.testclient import TestClient

    app.dependency_overrides = {}

    with patch("src.api.middleware.get_current_active_user", return_value=fake_user):
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c


@pytest.fixture
def auth_headers():
    return {"Authorization": "Bearer test_token_for_judges"}


@pytest.fixture
def mock_runner():
    """A runner that emits one agent_active + done event."""
    async def _stream(user_id, message, session_id=None):
        yield {"type": "agent_active", "agent": "TaskMaster", "color": "amber", "icon": "✓"}
        yield {
            "type":       "done",
            "response":   "Task created successfully.",
            "session_id": session_id or "sess_new",
            "trace": {
                "trace_id":          "t001",
                "agents_involved":   ["Orchestrator", "TaskMaster"],
                "total_duration_ms": 380,
                "steps":             [],
            },
        }

    runner = MagicMock()
    runner.run_with_trace = _stream
    return runner


class TestChatSync:
    def test_returns_200_with_response(self, client, auth_headers, mock_runner):
        """POST /chat/sync must return 200 with a non-empty response."""
        with patch("src.api.routers.chat.aiden_runner", mock_runner):
            r = client.post(
                "/chat/sync",
                json={"message": "Add a task to prepare the demo"},
                headers=auth_headers,
            )
        assert r.status_code == 200
        data = r.json()
        assert "response" in data
        assert len(data["response"]) > 0
        assert data.get("success") is True

    def test_empty_message_rejected(self, client, auth_headers):
        """POST /chat/sync with empty message must return 422 or 400."""
        with patch("src.api.routers.chat.aiden_runner", MagicMock()):
            r = client.post("/chat/sync", json={"message": ""}, headers=auth_headers)
        assert r.status_code in (400, 422)

    def test_missing_message_field_rejected(self, client, auth_headers):
        """POST /chat/sync without 'message' key must return 422."""
        r = client.post("/chat/sync", json={}, headers=auth_headers)
        assert r.status_code == 422

    def test_session_id_returned(self, client, auth_headers, mock_runner):
        """Response must include a session_id for conversation continuity."""
        with patch("src.api.routers.chat.aiden_runner", mock_runner):
            r = client.post(
                "/chat/sync",
                json={"message": "Hello AIDEN", "session_id": "my-session"},
                headers=auth_headers,
            )
        assert r.status_code == 200
        assert "session_id" in r.json()


class TestChatSSEStream:
    def test_sse_content_type(self, client, auth_headers, mock_runner):
        """POST /chat (SSE) must return text/event-stream content type."""
        with patch("src.api.routers.chat.aiden_runner", mock_runner):
            r = client.post(
                "/chat",
                json={"message": "Plan my week"},
                headers=auth_headers,
            )
        assert "text/event-stream" in r.headers.get("content-type", "")

    def test_sse_stream_contains_done_event(self, client, auth_headers, mock_runner):
        """SSE stream body must contain at least one 'done' event."""
        with patch("src.api.routers.chat.aiden_runner", mock_runner):
            r = client.post(
                "/chat",
                json={"message": "What tasks do I have?"},
                headers=auth_headers,
            )
        body = r.text
        payloads = []
        for line in body.splitlines():
            if line.startswith("data:"):
                try:
                    payloads.append(json.loads(line[5:].strip()))
                except json.JSONDecodeError:
                    pass

        done_events = [p for p in payloads if p.get("type") == "done"]
        assert len(done_events) >= 1

    def test_sse_done_event_has_trace(self, client, auth_headers, mock_runner):
        """'done' SSE event must include the trace object."""
        with patch("src.api.routers.chat.aiden_runner", mock_runner):
            r = client.post(
                "/chat",
                json={"message": "List my notes"},
                headers=auth_headers,
            )
        for line in r.text.splitlines():
            if line.startswith("data:"):
                try:
                    payload = json.loads(line[5:].strip())
                    if payload.get("type") == "done":
                        assert "trace" in payload
                        assert "agents_involved" in payload["trace"]
                        return
                except json.JSONDecodeError:
                    continue
        pytest.fail("No 'done' event with trace found in SSE stream")


class TestNotesSearch:
    def test_search_returns_results_with_score(self, client, auth_headers, fake_vector):
        """GET /notes/search must return results with _score and _model fields."""
        mock_results = [
            {
                "document_id": "note_001",
                "text":        "Board meeting agenda Q2",
                "metadata":    {"title": "Board Meeting", "user_id": "test_user_abc123"},
                "score":       0.92,
            }
        ]
        mock_note = MagicMock()
        mock_note.model_dump = MagicMock(return_value={
            "note_id": "note_001", "title": "Board Meeting",
            "content": "Board meeting agenda Q2", "tags": ["board"],
            "user_id": "test_user_abc123", "project": "Board Prep",
        })

        with patch("src.api.routers.notes.vector_repo.semantic_search",
                   new=AsyncMock(return_value=mock_results)), \
             patch("src.api.routers.notes.notes_repo.get_notes_by_ids",
                   new=AsyncMock(return_value=[mock_note])):
            r = client.get("/notes/search?q=board+meeting", headers=auth_headers)

        assert r.status_code == 200
        data = r.json()
        assert data["count"] == 1
        assert data["model"] == "gemini/text-embedding-004"
        assert "_score" in data["results"][0]
        assert "_model" in data["results"][0]
        assert data["results"][0]["_score"] == 0.92

    def test_search_rejects_short_query(self, client, auth_headers):
        """GET /notes/search?q=x must return 400 (query too short)."""
        r = client.get("/notes/search?q=x", headers=auth_headers)
        assert r.status_code == 400

    def test_search_missing_query_rejected(self, client, auth_headers):
        """GET /notes/search without q param must return 422."""
        r = client.get("/notes/search", headers=auth_headers)
        assert r.status_code == 422


class TestDemoSeed:
    def test_seed_returns_success(self, client, auth_headers):
        """POST /demo/seed must return success with task and note counts."""
        with patch("src.api.routers.demo.TaskRepository") as mock_tr, \
             patch("src.api.routers.demo.NotesRepository") as mock_nr, \
             patch("src.api.routers.demo.VectorRepository") as mock_vr:

            # Configure mocks
            mock_tr.return_value.list_tasks = AsyncMock(return_value=[])
            mock_tr.return_value.create_task = AsyncMock(
                return_value={"task_id": "t1", "title": "demo task"}
            )
            mock_nr.return_value.list_notes = AsyncMock(return_value=[])
            mock_nr.return_value.create_note = AsyncMock(
                return_value={"note_id": "n1", "title": "demo note"}
            )
            mock_vr.return_value.add_embedding = AsyncMock()

            r = client.post("/demo/seed", headers=auth_headers)

        assert r.status_code == 200
        data = r.json()
        assert data["success"] is True
        assert "seeded" in data
        assert data["seeded"]["tasks"] > 0
        assert data["seeded"]["notes"] > 0

    def test_seed_returns_suggested_prompts(self, client, auth_headers):
        """Demo seed response must include suggested_prompts for the judge."""
        with patch("src.api.routers.demo.TaskRepository") as mock_tr, \
             patch("src.api.routers.demo.NotesRepository") as mock_nr, \
             patch("src.api.routers.demo.VectorRepository") as mock_vr:

            mock_tr.return_value.list_tasks   = AsyncMock(return_value=[])
            mock_tr.return_value.create_task  = AsyncMock(return_value={"task_id": "t1", "title": "x"})
            mock_nr.return_value.list_notes   = AsyncMock(return_value=[])
            mock_nr.return_value.create_note  = AsyncMock(return_value={"note_id": "n1", "title": "y"})
            mock_vr.return_value.add_embedding = AsyncMock()

            r = client.post("/demo/seed", headers=auth_headers)

        data = r.json()
        assert "suggested_prompts" in data
        assert len(data["suggested_prompts"]) >= 3
