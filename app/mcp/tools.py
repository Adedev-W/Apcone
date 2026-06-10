from __future__ import annotations

from contextlib import contextmanager
from typing import Any
from uuid import UUID

from sqlalchemy import text

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.dependencies import build_storage_service
from app.mcp.server import mcp
from app.schemas import DocumentCreate, DocumentRead


@contextmanager
def _storage_service():
    settings = get_settings()
    db = SessionLocal()
    try:
        yield build_storage_service(db, settings)
    finally:
        db.close()


@mcp.tool(name="search_documents")
def search_documents(
    query: str,
    top_k: int | None = None,
    source: str | None = None,
    document_id: UUID | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    resolved_top_k = top_k or settings.search_top_k
    with _storage_service() as service:
        results = service.search(
            query=query,
            top_k=resolved_top_k,
            source=source,
            document_id=document_id,
        )
    return {
        "query": query,
        "top_k": resolved_top_k,
        "results": [item.model_dump(mode="json") for item in results],
    }


@mcp.tool(name="ingest_document")
def ingest_document(
    title: str,
    content: str,
    source: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = DocumentCreate(
        title=title,
        content=content,
        source=source,
        metadata=metadata or {},
    )
    with _storage_service() as service:
        result = service.ingest_document(payload)
    return {
        "job_id": str(result.job.id),
        "status": result.job.status.value,
        "chunks_created": result.chunks_created,
        "document": DocumentRead.model_validate(result.document, from_attributes=True).model_dump(
            mode="json"
        ),
    }


@mcp.tool(name="reindex_document")
def reindex_document(document_id: UUID) -> dict[str, Any]:
    with _storage_service() as service:
        result = service.reindex_document(document_id)
    return {
        "job_id": str(result.job.id),
        "status": result.job.status.value,
        "chunks_created": result.chunks_created,
        "document_id": str(result.document.id),
    }


@mcp.tool(name="delete_document")
def delete_document(document_id: UUID) -> dict[str, str]:
    with _storage_service() as service:
        service.delete_document(document_id)
    return {"status": "deleted", "document_id": str(document_id)}




@mcp.tool(name="health")
def health() -> dict[str, Any]:
    settings = get_settings()
    with _storage_service() as service:
        service.db.execute(text("SELECT 1"))
        qdrant_ok = service.qdrant_store.health()
    return {
        "status": "ok",
        "details": {
            "database": "reachable",
            "qdrant": "reachable" if qdrant_ok else "unreachable",
            "collection": settings.qdrant_collection,
        },
    }
