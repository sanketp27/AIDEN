from __future__ import annotations

import asyncio
import os
import time
from typing import Any, Optional

import chromadb
import structlog
from google import genai

from src.core.config import settings

log = structlog.get_logger()

EMBEDDING_MODEL = "text-embedding-004"
_MAX_EMBED_RETRIES = 3
_RETRY_BASE_DELAY_SECONDS = 0.5

_chroma_client: chromadb.PersistentClient | None = None
_genai_client: genai.Client | None = None


def _get_client() -> chromadb.PersistentClient:
    global _chroma_client
    if _chroma_client is None:
        _chroma_client = chromadb.PersistentClient(path=settings.CHROMA_PATH)
        log.info("chroma_client_initialised", path=settings.CHROMA_PATH)
    return _chroma_client


def _get_google_api_key() -> str:
    """Resolve the only supported embedding API key source."""
    api_key = os.getenv("GOOGLE_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("Missing GOOGLE_API_KEY environment variable")
    return api_key


def _get_genai_client() -> genai.Client:
    global _genai_client
    if _genai_client is None:
        _genai_client = genai.Client(api_key=_get_google_api_key())
        log.info("genai_client_initialised", model=EMBEDDING_MODEL)
    return _genai_client


def _validate_text(value: str, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    text = value.strip()
    if not text:
        raise ValueError(f"{field_name} must not be empty")
    return text


def _extract_embeddings(response: Any) -> list[list[float]]:
    embeddings = getattr(response, "embeddings", None)
    if not embeddings:
        raise RuntimeError("Embedding response did not include embeddings")

    vectors: list[list[float]] = []
    for embedding in embeddings:
        values = getattr(embedding, "values", None)
        if not values:
            raise RuntimeError("Embedding response did not include vector values")
        vectors.append([float(v) for v in values])
    return vectors


def _embed_with_retry(contents: list[str], task_type: str) -> list[list[float]]:
    client = _get_genai_client()

    for attempt in range(1, _MAX_EMBED_RETRIES + 1):
        try:
            response = client.models.embed_content(
                model=EMBEDDING_MODEL,
                contents=contents,
                config={"task_type": task_type},
            )
            return _extract_embeddings(response)
        except Exception as exc:
            is_last_attempt = attempt == _MAX_EMBED_RETRIES
            log.warning(
                "embedding_request_failed",
                attempt=attempt,
                max_attempts=_MAX_EMBED_RETRIES,
                task_type=task_type,
                error=str(exc),
                will_retry=not is_last_attempt,
            )
            if is_last_attempt:
                log.error(
                    "embedding_request_exhausted_retries",
                    task_type=task_type,
                    error=str(exc),
                    exc_info=True,
                )
                raise
            time.sleep(_RETRY_BASE_DELAY_SECONDS * attempt)

    raise RuntimeError("Unreachable embedding retry state")


async def _embed_documents(texts: list[str]) -> list[list[float]]:
    """
    Embed one or more document texts using Google GenAI text-embedding-004.
    Uses RETRIEVAL_DOCUMENT task_type for best indexing recall.
    Returns a list of float vectors.
    """
    validated = [_validate_text(text, "document text") for text in texts]

    def _sync() -> list[list[float]]:
        return _embed_with_retry(validated, task_type="RETRIEVAL_DOCUMENT")

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _sync)


async def _embed_query(query: str) -> list[float]:
    """
    Embed a search query using Google GenAI text-embedding-004.
    Uses RETRIEVAL_QUERY task_type — optimised for search queries.
    """
    validated_query = _validate_text(query, "query")

    def _sync() -> list[float]:
        [vector] = _embed_with_retry([validated_query], task_type="RETRIEVAL_QUERY")
        return vector

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _sync)


class VectorRepository:
    """
    ChromaDB repository backed by Google GenAI text-embedding-004.

    Each user gets their own isolated collection (notes_{user_id}).
    embedding_function=None is always passed so ChromaDB never calls
    its own model — all vectors come from Google GenAI.
    """

    def __init__(self) -> None:
        self._client: chromadb.PersistentClient | None = None

    @property
    def client(self) -> chromadb.PersistentClient:
        if self._client is None:
            self._client = _get_client()
        return self._client

    def _collection(self, user_id: str) -> chromadb.Collection:
        """
        Get or create the user-specific ChromaDB collection.
        embedding_function=None tells ChromaDB we supply vectors ourselves.
        """
        return self.client.get_or_create_collection(
            name=f"notes_{user_id}",
            metadata={"hnsw:space": "cosine", "user_id": user_id},
            embedding_function=None,
        )

    async def add_embedding(
        self,
        user_id: str,
        document_id: str,
        text: str,
        metadata: Optional[dict] = None,
    ) -> None:
        """Generate an embedding and upsert into ChromaDB."""
        validated_text = _validate_text(text, "text")
        vectors = await _embed_documents([validated_text])
        meta = {
            **(metadata or {}),
            "user_id": user_id,
            "model": EMBEDDING_MODEL,
        }
        self._collection(user_id).upsert(
            ids=[document_id],
            documents=[validated_text],
            embeddings=vectors,
            metadatas=[meta],
        )
        log.info(
            "embedding_stored",
            doc_id=document_id,
            dims=len(vectors[0]),
            model=EMBEDDING_MODEL,
        )

    async def update_embedding(
        self,
        user_id: str,
        document_id: str,
        text: str,
        metadata: Optional[dict] = None,
    ) -> None:
        """Update an existing embedding (re-embeds and upserts)."""
        await self.add_embedding(user_id, document_id, text, metadata)

    async def delete_embedding(self, user_id: str, document_id: str) -> None:
        """Delete a single document embedding by ID."""
        self._collection(user_id).delete(ids=[document_id])
        log.info("embedding_deleted", doc_id=document_id)

    async def delete_user_collection(self, user_id: str) -> None:
        """Delete the entire user collection (e.g. on account deletion)."""
        name = f"notes_{user_id}"
        try:
            self.client.delete_collection(name=name)
            log.info("chroma_collection_deleted", collection=name)
        except Exception as exc:
            log.warning("collection_deletion_failed", collection=name, error=str(exc))

    async def semantic_search(
        self,
        user_id: str,
        query: str,
        top_k: int = 5,
        filter_metadata: Optional[dict] = None,
    ) -> list[dict]:
        """
        Semantic search using a Google GenAI RETRIEVAL_QUERY embedding.

        Returns up to top_k results sorted by cosine similarity:
            {"document_id": str, "text": str, "metadata": dict, "score": float}
        score is in [0, 1] — 1.0 = perfect match.
        """
        col = self._collection(user_id)
        doc_count = col.count()
        n_results = min(top_k, doc_count) if doc_count > 0 else 0

        if n_results == 0:
            log.info("semantic_search_empty_collection", user_id=user_id)
            return []

        where: dict = {"user_id": {"$eq": user_id}}
        if filter_metadata:
            where = {"$and": [{"user_id": {"$eq": user_id}}, filter_metadata]}

        query_vector = await _embed_query(query)

        results = col.query(
            query_embeddings=[query_vector],
            n_results=n_results,
            where=where,
        )

        formatted: list[dict] = []
        if results["ids"] and results["ids"][0]:
            for i, doc_id in enumerate(results["ids"][0]):
                distance = results["distances"][0][i] if results.get("distances") else 1.0
                formatted.append(
                    {
                        "document_id": doc_id,
                        "text": results["documents"][0][i] if results.get("documents") else "",
                        "metadata": results["metadatas"][0][i] if results.get("metadatas") else {},
                        "score": round(1.0 - distance, 4),
                    }
                )

        log.info(
            "semantic_search_done",
            user_id=user_id,
            query_len=len(query),
            results=len(formatted),
            model=EMBEDDING_MODEL,
        )
        return formatted
