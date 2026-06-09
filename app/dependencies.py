from __future__ import annotations

from functools import lru_cache

from qdrant_client import QdrantClient
from sqlalchemy.orm import Session

from app.adapters.qdrant_store import QdrantChunkStore
from app.core.config import Settings
from app.services.chunking import ChunkingService
from app.services.embeddings import FastEmbedEmbeddingService
from app.services.storage import RagStorageService


@lru_cache(maxsize=4)
def get_embedder(model_name: str) -> FastEmbedEmbeddingService:
    return FastEmbedEmbeddingService(model_name)


@lru_cache(maxsize=4)
def get_qdrant_client(qdrant_url: str) -> QdrantClient:
    return QdrantClient(url=qdrant_url)


def build_storage_service(db: Session, settings: Settings) -> RagStorageService:
    chunker = ChunkingService(settings.chunk_size, settings.chunk_overlap)
    embedder = get_embedder(settings.embedding_model)
    qdrant_client = get_qdrant_client(settings.qdrant_url)
    qdrant_store = QdrantChunkStore(qdrant_client, settings.qdrant_collection)
    return RagStorageService(
        db=db,
        chunker=chunker,
        embedder=embedder,
        qdrant_store=qdrant_store,
    )
