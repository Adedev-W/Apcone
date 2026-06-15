from __future__ import annotations

import hashlib
import re
from collections.abc import Generator
from pathlib import Path
import sys

import pytest
from fastapi.testclient import TestClient
from qdrant_client import QdrantClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.adapters.qdrant_store import QdrantChunkStore
from app.core.config import Settings
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.routers.documents import get_storage_service
from app.routers.health import get_settings
from app.services.chunking import ChunkingService
from app.services.embeddings import EmbeddingService
from app.services.api_keys import ApiKeyService
from app.services.storage import RagStorageService


class FakeEmbeddingService(EmbeddingService):
    def _vectorize(self, text: str) -> list[float]:
        vector = [0.0] * 8
        for token in re.findall(r"\w+", text.lower()):
            slot = int(hashlib.sha256(token.encode("utf-8")).hexdigest()[:8], 16) % len(vector)
            vector[slot] += 1.0
        return vector

    def embed_texts(self, texts):
        return [self._vectorize(text) for text in texts]

    def embed_query(self, query: str):
        return self._vectorize(query)


@pytest.fixture()
def test_context(tmp_path: Path):
    db_path = tmp_path / "test.db"
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
        future=True,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False, future=True)
    settings = Settings(
        database_url=f"sqlite:///{db_path}",
        redis_url="redis://localhost:6379/0",
        qdrant_url="http://localhost:6333",
        qdrant_collection="test_rag_chunks",
    )
    qdrant_client = QdrantClient(location=":memory:")
    chunker = ChunkingService(settings.chunk_size, settings.chunk_overlap)
    embedder = FakeEmbeddingService()
    qdrant_store = QdrantChunkStore(qdrant_client, settings.qdrant_collection)

    def override_get_db() -> Generator:
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    def override_get_settings() -> Settings:
        return settings

    def override_get_storage_service() -> Generator[RagStorageService, None, None]:
        session = session_factory()
        try:
            yield RagStorageService(
                db=session,
                chunker=chunker,
                embedder=embedder,
                qdrant_store=qdrant_store,
            )
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_settings] = override_get_settings
    app.dependency_overrides[get_storage_service] = override_get_storage_service

    try:
        yield {
            "settings": settings,
            "session_factory": session_factory,
            "qdrant_store": qdrant_store,
            "chunker": chunker,
            "embedder": embedder,
        }
    finally:
        app.dependency_overrides.clear()


@pytest.fixture()
def client(test_context):
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def auth_headers(test_context):
    session = test_context["session_factory"]()
    try:
        created = ApiKeyService(session).create_key(
            name="test-admin",
            tenant_id="default",
            role="admin",
        )
        return {"Authorization": f"Bearer {created.secret}"}
    finally:
        session.close()
