from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from qdrant_client import QdrantClient, models


class QdrantChunkStore:
    def __init__(self, client: QdrantClient, collection_name: str) -> None:
        self.client = client
        self.collection_name = collection_name

    def ensure_collection(self, vector_size: int) -> None:
        if self.client.collection_exists(self.collection_name):
            self._validate_vector_size(vector_size)
            return
        self.client.create_collection(
            collection_name=self.collection_name,
            vectors_config=models.VectorParams(size=vector_size, distance=models.Distance.COSINE),
        )

    def upsert_chunks(self, *, points: Sequence[models.PointStruct]) -> None:
        self.client.upsert(collection_name=self.collection_name, points=list(points), wait=True)

    def search(
        self,
        *,
        query_vector: Sequence[float],
        limit: int,
        tenant_id: str,
        scope: str,
        document_id: UUID | None = None,
        source: str | None = None,
    ) -> list[models.ScoredPoint]:
        query_filter = self._build_filter(
            tenant_id=tenant_id,
            scope=scope,
            document_id=document_id,
            source=source,
        )
        response = self.client.query_points(
            collection_name=self.collection_name,
            query=list(query_vector),
            query_filter=query_filter,
            limit=limit,
            with_payload=True,
            with_vectors=False,
        )
        return response.points

    def delete_document(self, *, document_id: UUID, tenant_id: str, scope: str) -> None:
        self.client.delete(
            collection_name=self.collection_name,
            points_selector=self._build_filter(
                tenant_id=tenant_id,
                scope=scope,
                document_id=document_id,
            ),
            wait=True,
        )

    def health(self) -> bool:
        self.client.get_collections()
        return True

    def _validate_vector_size(self, vector_size: int) -> None:
        collection = self.client.get_collection(self.collection_name)
        vectors = collection.config.params.vectors
        configured_size = getattr(vectors, "size", None)
        if configured_size is None and isinstance(vectors, dict):
            default_vector = vectors.get("")
            configured_size = getattr(default_vector, "size", None)
        if configured_size is not None and configured_size != vector_size:
            raise ValueError(
                f"qdrant collection vector size mismatch: expected {configured_size}, got {vector_size}"
            )

    def _build_filter(
        self,
        *,
        tenant_id: str,
        scope: str,
        document_id: UUID | None = None,
        source: str | None = None,
    ) -> models.Filter:
        must: list[models.FieldCondition] = [
            models.FieldCondition(
                key="tenant_id",
                match=models.MatchValue(value=tenant_id),
            ),
            models.FieldCondition(
                key="scope",
                match=models.MatchValue(value=scope),
            ),
        ]
        if document_id is not None:
            must.append(
                models.FieldCondition(
                    key="document_id",
                    match=models.MatchValue(value=str(document_id)),
                )
            )
        if source is not None:
            must.append(
                models.FieldCondition(
                    key="source",
                    match=models.MatchValue(value=source),
                )
            )
        return models.Filter(must=must)
