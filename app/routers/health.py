from __future__ import annotations

from fastapi import APIRouter, Depends
from qdrant_client import QdrantClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.adapters.qdrant_store import QdrantChunkStore
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.schemas import HealthResponse
from app.tasks.rq_queue import get_redis_connection

router = APIRouter(prefix="/health", tags=["health"])


@router.get("", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok", details={"service": "apcone-rag-storage"})


@router.get("/postgres", response_model=HealthResponse)
def health_postgres(db: Session = Depends(get_db)) -> HealthResponse:
    db.execute(text("SELECT 1"))
    return HealthResponse(status="ok", details={"database": "reachable"})


@router.get("/redis", response_model=HealthResponse)
def health_redis(settings: Settings = Depends(get_settings)) -> HealthResponse:
    client = get_redis_connection(settings)
    client.ping()
    return HealthResponse(status="ok", details={"redis": "reachable"})


@router.get("/qdrant", response_model=HealthResponse)
def health_qdrant(settings: Settings = Depends(get_settings)) -> HealthResponse:
    client = QdrantClient(url=settings.qdrant_url)
    store = QdrantChunkStore(client=client, collection_name=settings.qdrant_collection)
    store.health()
    return HealthResponse(
        status="ok",
        details={"qdrant": "reachable", "collection": settings.qdrant_collection},
    )
