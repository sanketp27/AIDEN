"""
Vector repository for ChromaDB semantic search
Per-user collection namespacing for data isolation
"""
import chromadb
from chromadb.config import Settings as ChromaSettings
from src.core.config import settings
from typing import Optional
import structlog

log = structlog.get_logger()


class VectorRepository:
    """Repository for vector embeddings and semantic search"""

    def __init__(self):
        self.client = chromadb.HttpClient(
            host=settings.CHROMA_HOST,
            port=settings.CHROMA_PORT,
            settings=ChromaSettings(
                anonymized_telemetry=False
            )
        )

    def _get_collection_name(self, user_id: str) -> str:
        """Get user-specific collection name"""
        return f"notes_{user_id}"

    def _get_or_create_collection(self, user_id: str):
        """Get or create user-specific ChromaDB collection"""
        collection_name = self._get_collection_name(user_id)

        try:
            collection = self.client.get_collection(name=collection_name)
        except Exception:
            # Collection doesn't exist, create it
            collection = self.client.create_collection(
                name=collection_name,
                metadata={"user_id": user_id}
            )
            log.info("chroma_collection_created", collection=collection_name)

        return collection

    async def add_embedding(
        self,
        user_id: str,
        document_id: str,
        text: str,
        metadata: Optional[dict] = None
    ) -> None:
        """Add document embedding to ChromaDB"""
        collection = self._get_or_create_collection(user_id)

        metadata = metadata or {}
        metadata["user_id"] = user_id

        collection.add(
            documents=[text],
            metadatas=[metadata],
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
        """Perform semantic search in user's documents"""
        collection = self._get_or_create_collection(user_id)

        where_filter = filter_metadata or {}
        where_filter["user_id"] = user_id

        results = collection.query(
            query_texts=[query],
            n_results=top_k,
            where=where_filter if where_filter != {"user_id": user_id} else None
        )

        # Format results
        formatted_results = []
        if results["ids"] and len(results["ids"]) > 0:
            for i, doc_id in enumerate(results["ids"][0]):
                formatted_results.append({
                    "document_id": doc_id,
                    "text": results["documents"][0][i] if results["documents"] else "",
                    "metadata": results["metadatas"][0][i] if results["metadatas"] else {},
                    "distance": results["distances"][0][i] if results.get("distances") else 0.0
                })

        log.info("semantic_search_completed", user_id=user_id, query_length=len(query), results=len(formatted_results))
        return formatted_results

    async def update_embedding(
        self,
        user_id: str,
        document_id: str,
        text: str,
        metadata: Optional[dict] = None
    ) -> None:
        """Update an existing embedding"""
        collection = self._get_or_create_collection(user_id)

        metadata = metadata or {}
        metadata["user_id"] = user_id

        collection.update(
            documents=[text],
            metadatas=[metadata],
            ids=[document_id]
        )

        log.info("embedding_updated", user_id=user_id, document_id=document_id)

    async def delete_embedding(self, user_id: str, document_id: str) -> None:
        """Delete an embedding"""
        collection = self._get_or_create_collection(user_id)

        collection.delete(ids=[document_id])

        log.info("embedding_deleted", user_id=user_id, document_id=document_id)

    async def delete_user_collection(self, user_id: str) -> None:
        """Delete entire user collection (for account deletion)"""
        collection_name = self._get_collection_name(user_id)

        try:
            self.client.delete_collection(name=collection_name)
            log.info("chroma_collection_deleted", collection=collection_name)
        except Exception as e:
            log.warning("collection_deletion_failed", collection=collection_name, error=str(e))
