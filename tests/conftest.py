"""
tests/conftest.py — shared pytest fixtures
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.fixture
def fake_user():
    u = MagicMock()
    u.user_id   = "test_user_abc123"
    u.email     = "judge@hackathon.dev"
    u.name      = "Test Judge"
    u.is_active = True
    return u


@pytest.fixture
def mock_mongo_col():
    """A mock AsyncIOMotorCollection with all async methods pre-wired."""
    col = MagicMock()
    col.insert_one    = AsyncMock(return_value=MagicMock(inserted_id="mock_id_001"))
    col.find_one      = AsyncMock(return_value=None)
    col.update_one    = AsyncMock(return_value=MagicMock(modified_count=1, matched_count=1))
    col.delete_one    = AsyncMock(return_value=MagicMock(deleted_count=1))
    col.count_documents = AsyncMock(return_value=0)
    col.create_index  = AsyncMock(return_value="index_name")

    # find() returns an async cursor mock
    cursor = MagicMock()
    cursor.__aiter__ = MagicMock(return_value=iter([]))
    cursor.sort      = MagicMock(return_value=cursor)
    cursor.skip      = MagicMock(return_value=cursor)
    cursor.limit     = MagicMock(return_value=cursor)
    col.find = MagicMock(return_value=cursor)

    return col


FAKE_VECTOR_768 = [0.01 * (i % 100) for i in range(768)]


@pytest.fixture
def fake_vector():
    return FAKE_VECTOR_768


@pytest.fixture
def mock_chroma_col():
    col = MagicMock()
    col.count  = MagicMock(return_value=3)
    col.upsert = MagicMock()
    col.delete = MagicMock()
    col.query  = MagicMock(return_value={
        "ids":       [["doc_a", "doc_b", "doc_c"]],
        "documents": [["Board meeting notes", "Architecture design", "Hiring negotiation"]],
        "metadatas": [[
            {"user_id": "test_user_abc123", "title": "Board Meeting"},
            {"user_id": "test_user_abc123", "title": "Architecture"},
            {"user_id": "test_user_abc123", "title": "Hiring"},
        ]],
        "distances": [[0.08, 0.25, 0.42]],
    })
    return col
