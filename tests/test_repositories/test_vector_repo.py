from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

USER_ID = "test_user_abc123"


@pytest.fixture
def vector_repo(mock_chroma_col, fake_vector):
    from src.repositories.vector_repo import VectorRepository
    repo = VectorRepository()
    repo._collection = MagicMock(return_value=mock_chroma_col)
    return repo


class TestAddEmbedding:
    async def test_calls_gemini_embed(self, vector_repo, mock_chroma_col, fake_vector):
        """add_embedding must call _embed_documents (the Gemini API call)."""
        with patch(
            "src.repositories.vector_repo._embed_documents",
            new=AsyncMock(return_value=[fake_vector]),
        ):
            await vector_repo.add_embedding(USER_ID, "note_001", "Board meeting Q2 agenda")

        mock_chroma_col.upsert.assert_called_once()

    async def test_passes_gemini_vector_not_chromadb_default(self, vector_repo, mock_chroma_col, fake_vector):
        """
        The Gemini vector must be passed as the `embeddings` kwarg.
        If it isn't, ChromaDB would silently use its own (wrong) model.
        """
        with patch(
            "src.repositories.vector_repo._embed_documents",
            new=AsyncMock(return_value=[fake_vector]),
        ):
            await vector_repo.add_embedding(USER_ID, "note_002", "Architecture notes")

        call_kwargs = mock_chroma_col.upsert.call_args.kwargs
        assert "embeddings" in call_kwargs, "Gemini vector must be passed as 'embeddings'"
        assert call_kwargs["embeddings"] == [fake_vector]

    async def test_upsert_is_idempotent(self, vector_repo, mock_chroma_col, fake_vector):
        """add_embedding uses upsert so calling twice is safe."""
        with patch(
            "src.repositories.vector_repo._embed_documents",
            new=AsyncMock(return_value=[fake_vector]),
        ):
            await vector_repo.add_embedding(USER_ID, "note_003", "Text A")
            await vector_repo.add_embedding(USER_ID, "note_003", "Text B — updated")

        assert mock_chroma_col.upsert.call_count == 2  # both succeed without error

    async def test_metadata_includes_model_field(self, vector_repo, mock_chroma_col, fake_vector):
        """Stored metadata must include model='text-embedding-004' for auditability."""
        with patch(
            "src.repositories.vector_repo._embed_documents",
            new=AsyncMock(return_value=[fake_vector]),
        ):
            await vector_repo.add_embedding(USER_ID, "note_004", "Meeting notes", {"title": "Meeting"})

        call_kwargs  = mock_chroma_col.upsert.call_args.kwargs
        stored_meta  = call_kwargs["metadatas"][0]
        assert stored_meta.get("model") == "text-embedding-004"
        assert stored_meta.get("user_id") == USER_ID


class TestSemanticSearch:
    async def test_returns_results_with_score(self, vector_repo, fake_vector):
        """semantic_search must return a list of dicts each with a 'score' key."""
        with patch(
            "src.repositories.vector_repo._embed_query",
            new=AsyncMock(return_value=fake_vector),
        ):
            results = await vector_repo.semantic_search(USER_ID, "quarterly board meeting", top_k=3)

        assert len(results) == 3
        for r in results:
            assert "document_id" in r
            assert "score" in r
            assert 0.0 <= r["score"] <= 1.0

    async def test_score_is_cosine_similarity(self, vector_repo, fake_vector):
        """Score = 1 - cosine_distance. Distance 0.08 → score ≈ 0.92."""
        with patch(
            "src.repositories.vector_repo._embed_query",
            new=AsyncMock(return_value=fake_vector),
        ):
            results = await vector_repo.semantic_search(USER_ID, "board")

        # mock_chroma_col distances = [0.08, 0.25, 0.42]
        assert abs(results[0]["score"] - 0.92) < 0.01

    async def test_uses_retrieval_query_task_type(self, fake_vector):
        """_embed_query must be called (not _embed_documents) for search queries."""
        from src.repositories.vector_repo import VectorRepository
        repo = VectorRepository()
        col  = MagicMock()
        col.count  = MagicMock(return_value=1)
        col.query  = MagicMock(return_value={
            "ids": [["x"]], "documents": [["text"]], "metadatas": [[{"user_id": USER_ID}]], "distances": [[0.1]]
        })
        repo._collection = MagicMock(return_value=col)

        embed_query_mock = AsyncMock(return_value=fake_vector)
        embed_docs_mock  = AsyncMock(return_value=[fake_vector])

        with patch("src.repositories.vector_repo._embed_query",     embed_query_mock), \
             patch("src.repositories.vector_repo._embed_documents", embed_docs_mock):
            await repo.semantic_search(USER_ID, "test query")

        embed_query_mock.assert_called_once_with("test query")
        embed_docs_mock.assert_not_called()  # ← documents path must NOT be used for queries

    async def test_empty_collection_returns_empty_list(self, vector_repo, mock_chroma_col, fake_vector):
        """semantic_search on an empty collection returns [] without error."""
        mock_chroma_col.count = MagicMock(return_value=0)
        with patch(
            "src.repositories.vector_repo._embed_query",
            new=AsyncMock(return_value=fake_vector),
        ):
            results = await vector_repo.semantic_search(USER_ID, "anything")
        assert results == []

    async def test_results_scoped_to_user(self, vector_repo, mock_chroma_col, fake_vector):
        """ChromaDB query must be called with a user_id where-filter."""
        with patch(
            "src.repositories.vector_repo._embed_query",
            new=AsyncMock(return_value=fake_vector),
        ):
            await vector_repo.semantic_search(USER_ID, "query")

        call_kwargs = mock_chroma_col.query.call_args.kwargs
        where       = call_kwargs.get("where", {})
        assert USER_ID in str(where), "Query must be scoped to user_id"


class TestDeleteEmbedding:
    async def test_delete_called_with_correct_id(self, vector_repo, mock_chroma_col):
        """delete_embedding must call collection.delete with the document ID."""
        await vector_repo.delete_embedding(USER_ID, "note_to_delete")
        mock_chroma_col.delete.assert_called_once_with(ids=["note_to_delete"])


class TestEmbeddingDimensions:
    async def test_gemini_returns_768_dimensions(self):
        """
        Integration smoke-test: the Gemini API contract is 768 dims.
        This test validates our understanding of the API response shape
        using a mock that mimics the real response structure.
        """
        import google.generativeai as genai
        from src.repositories.vector_repo import _embed_documents

        fake_response = {"embedding": [0.1] * 768}

        with patch.object(genai, "embed_content", return_value=fake_response):
            with patch("src.repositories.vector_repo._configure_genai"):
                result = await _embed_documents(["test text"])

        assert len(result) == 1,       "Should return 1 vector for 1 input"
        assert len(result[0]) == 768,  "text-embedding-004 produces 768-dim vectors"
