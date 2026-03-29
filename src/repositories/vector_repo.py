"""
Vector repository for ChromaDB semantic search
Per-user collection namespacing for data isolation
"""
import chromadb
from src.core.config import settings
from typing import Optional
import structlog

log = structlog.get_logger()

_chroma_client = None


def _get_client() -> chromadb.PersistentClient:
    """Return (or lazily create) the shared PersistentClient instance."""
    global _chroma_client
    if _chroma_client is None:
        _chroma_client = chromadb.PersistentClient(path=settings.CHROMA_PATH)
        log.info("chroma_persistent_client_initialized", path=settings.CHROMA_PATH)
    return _chroma_client


class VectorRepository:
    """Repository for vector embeddings and semantic search"""

    def __init__(self):
        self._client = None

    @property
    def client(self) -> chromadb.PersistentClient:
        if self._client is None:
            self._client = _get_client()
        return self._client

    def _get_collection_name(self, user_id: str) -> str:
        """Get user-specific collection name"""
        return f"notes_{user_id}"

    def _get_or_create_collection(self, user_id: str):
        """
        Get or create user-specific ChromaDB collection.
        Uses get_or_create_collection (idiomatic Chroma API) to avoid
        the try/except create dance that could hide real errors.
        """
        collection_name = self._get_collection_name(user_id)
        collection = self.client.get_or_create_collection(
            name=collection_name,
            metadata={"user_id": user_id, "hnsw:space": "cosine"}
        )
        return collection

    async def add_embedding(
        self,
        user_id: str,
        document_id: str,
        text: str,
        metadata: Optional[dict] = None
    ) -> None:
        """
        Add document embedding to ChromaDB.
        Uses upsert so calling this twice for the same ID is safe (idempotent).
        """
        collection = self._get_or_create_collection(user_id)
        meta = {**(metadata or {}), "user_id": user_id}

        # upsert = insert or update — avoids duplicate-ID errors on retries
        collection.upsert(
            documents=[text],
            metadatas=[meta],
            ids=[document_id]
        )
        log.info("embedding_added", user_id=user_id, document_id=document_id)

    async def semantic_search(
        self,
        user_id: str,
        query: str,
        top_k: int = 5,
        filter_metadata: Optional[dict] = None
    ) -> list[dict]:
        """
        Perform semantic search in user's documents.
        ChromaDB embeds the query text automatically using its default model.
        """
        collection = self._get_or_create_collection(user_id)

        # Build where filter — always scope to this user
        where = {"user_id": {"$eq": user_id}}
        if filter_metadata:
            # Merge extra filters with $and so both conditions apply
            where = {"$and": [{"user_id": {"$eq": user_id}}, filter_metadata]}

        # Guard: n_results cannot exceed documents in the collection
        doc_count = collection.count()
        n_results = min(top_k, doc_count) if doc_count > 0 else 0

        if n_results == 0:
            log.info("semantic_search_empty_collection", user_id=user_id)
            return []

        results = collection.query(
            query_texts=[query],
            n_results=n_results,
            where=where
        )

        # Format results into a consistent structure
        formatted = []
        if results["ids"] and results["ids"][0]:
            for i, doc_id in enumerate(results["ids"][0]):
                formatted.append({
                    "document_id": doc_id,
                    "text": results["documents"][0][i] if results["documents"] else "",
                    "metadata": results["metadatas"][0][i] if results["metadatas"] else {},
                    "distance": results["distances"][0][i] if results.get("distances") else 0.0
                })

        log.info(
            "semantic_search_completed",
            user_id=user_id,
            query_length=len(query),
            results=len(formatted)
        )
        return formatted

    async def update_embedding(
        self,
        user_id: str,
        document_id: str,
        text: str,
        metadata: Optional[dict] = None
    ) -> None:
        """Update an existing embedding (or create it if missing via upsert)."""
        collection = self._get_or_create_collection(user_id)
        meta = {**(metadata or {}), "user_id": user_id}
        collection.upsert(
            documents=[text],
            metadatas=[meta],
            ids=[document_id]
        )
        log.info("embedding_updated", user_id=user_id, document_id=document_id)

    async def delete_embedding(self, user_id: str, document_id: str) -> None:
        """Delete a single embedding by ID."""
        collection = self._get_or_create_collection(user_id)
        collection.delete(ids=[document_id])
        log.info("embedding_deleted", user_id=user_id, document_id=document_id)

    async def delete_user_collection(self, user_id: str) -> None:
        """Delete the entire user collection (e.g. on account deletion)."""
        collection_name = self._get_collection_name(user_id)
        try:
            self.client.delete_collection(name=collection_name)
            log.info("chroma_collection_deleted", collection=collection_name)
        except Exception as e:
            log.warning(
                "collection_deletion_failed",
                collection=collection_name,
                error=str(e)
            )
