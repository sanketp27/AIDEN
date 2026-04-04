from __future__ import annotations

import asyncio
import structlog
from typing import Optional

import chromadb
import google.generativeai as genai

from src.core.config import settings

log = structlog.get_logger()

_chroma_client: chromadb.PersistentClient | None = None


def _get_client() -> chromadb.PersistentClient:
    global _chroma_client
    if _chroma_client is None:
        _chroma_client = chromadb.PersistentClient(path=settings.CHROMA_PATH)
        log.info("chroma_client_initialised", path=settings.CHROMA_PATH)
    return _chroma_client

def _configure_genai() -> None:
    """Configure google-generativeai SDK with the API key (idempotent)."""
    genai.configure(api_key=settings.GEMINI_API_KEY)


async def _embed_documents(texts: list[str]) -> list[list[float]]:
    """
    Embed one or more document texts using Gemini text-embedding-004.
    Uses RETRIEVAL_DOCUMENT task_type for best indexing recall.
    Returns a list of 768-dimensional float vectors.
    """
    def _sync() -> list[list[float]]:
        _configure_genai()
        result = genai.embed_content(
            model     = "models/text-embedding-004",
            content   = texts,
            task_type = "RETRIEVAL_DOCUMENT",
        )
        emb = result["embedding"]
        if emb and isinstance(emb[0], float):
            return [emb]
        return list(emb)

    return await asyncio.get_event_loop().run_in_executor(None, _sync)


async def _embed_query(query: str) -> list[float]:
    """
    Embed a search query using Gemini text-embedding-004.
    Uses RETRIEVAL_QUERY task_type — optimised for search queries.
    """
    def _sync() -> list[float]:
        _configure_genai()
        result = genai.embed_content(
            model     = "models/text-embedding-004",
            content   = query,
            task_type = "RETRIEVAL_QUERY",
        )
        return result["embedding"]

    return await asyncio.get_event_loop().run_in_executor(None, _sync)


class VectorRepository:
    """
    ChromaDB repository backed by Google Gemini text-embedding-004.

    Each user gets their own isolated collection (notes_{user_id}).
    embedding_function=None is always passed so ChromaDB never calls
    its own model — all vectors come from Gemini.
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
            name               = f"notes_{user_id}",
            metadata           = {"hnsw:space": "cosine", "user_id": user_id},
            embedding_function = None,
        )

    async def add_embedding(
        self,
        user_id:     str,
        document_id: str,
        text:        str,
        metadata:    Optional[dict] = None,
    ) -> None:
        """Generate a Gemini embedding and upsert into ChromaDB."""
        vectors = await _embed_documents([text])
        meta    = {
            **(metadata or {}),
            "user_id": user_id,
            "model":   "text-embedding-004",
        }
        self._collection(user_id).upsert(
            ids        = [document_id],
            documents  = [text],
            embeddings = vectors,
            metadatas  = [meta],
        )
        log.info(
            "gemini_embedding_stored",
            doc_id = document_id,
            dims   = len(vectors[0]),
            model  = "text-embedding-004",
        )

    async def update_embedding(
        self,
        user_id:     str,
        document_id: str,
        text:        str,
        metadata:    Optional[dict] = None,
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
        query:   str,
        top_k:   int = 5,
        filter_metadata: Optional[dict] = None,
    ) -> list[dict]:
        """
        Semantic search using a Gemini RETRIEVAL_QUERY embedding.

        Returns up to top_k results sorted by cosine similarity:
            {"document_id": str, "text": str, "metadata": dict, "score": float}
        score is in [0, 1] — 1.0 = perfect match.
        """
        col       = self._collection(user_id)
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
            query_embeddings = [query_vector],
            n_results        = n_results,
            where            = where,
        )

        formatted: list[dict] = []
        if results["ids"] and results["ids"][0]:
            for i, doc_id in enumerate(results["ids"][0]):
                distance = results["distances"][0][i] if results.get("distances") else 1.0
                formatted.append({
                    "document_id": doc_id,
                    "text":        results["documents"][0][i] if results.get("documents") else "",
                    "metadata":    results["metadatas"][0][i]  if results.get("metadatas")  else {},
                    "score":       round(1.0 - distance, 4),
                })

        log.info(
            "semantic_search_done",
            user_id   = user_id,
            query_len = len(query),
            results   = len(formatted),
            model     = "text-embedding-004",
        )
        return formatted
