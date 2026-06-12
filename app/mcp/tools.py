from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from typing import Annotated, Any
from uuid import UUID

from fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import get_settings
from app.db.models import Document
from app.db.session import SessionLocal
from app.dependencies import build_storage_service
from app.mcp.server import mcp
from app.schemas import DEFAULT_SCOPE, TENANT_SCOPE_PATTERN, DocumentCreate


logger = logging.getLogger(__name__)

TenantId = Annotated[
    str,
    Field(
        min_length=1,
        max_length=80,
        pattern=TENANT_SCOPE_PATTERN,
        description="Required tenant identifier for the knowledge base, such as a team, customer, or workspace.",
    ),
]
KnowledgeScope = Annotated[
    str,
    Field(
        min_length=1,
        max_length=80,
        pattern=TENANT_SCOPE_PATTERN,
        description="Knowledge namespace inside the tenant. Use default unless the caller needs a project or environment namespace.",
    ),
]


@contextmanager
def _storage_service():
    settings = get_settings()
    db = SessionLocal()
    try:
        yield build_storage_service(db, settings)
    finally:
        db.close()


def _document_payload(document: Document) -> dict[str, Any]:
    return {
        "id": str(document.id),
        "tenant_id": document.tenant_id,
        "scope": document.scope,
        "title": document.title,
        "source": document.source,
        "content": document.content,
        "checksum": document.checksum,
        "metadata": document.metadata_json,
        "chunk_count": len(document.chunks),
        "created_at": document.created_at.isoformat(),
        "updated_at": document.updated_at.isoformat(),
    }


def _log_tool_success(
    *,
    tool_name: str,
    started_at: float,
    tenant_id: str | None = None,
    scope: str | None = None,
    result_count: int | None = None,
) -> None:
    logger.info(
        "mcp_tool_success tool=%s tenant_id=%s scope=%s duration_ms=%d result_count=%s",
        tool_name,
        tenant_id,
        scope,
        int((time.perf_counter() - started_at) * 1000),
        result_count,
    )


def _raise_tool_error(
    *,
    tool_name: str,
    started_at: float,
    exc: Exception,
    tenant_id: str | None = None,
    scope: str | None = None,
) -> None:
    if isinstance(exc, LookupError):
        code = "DOCUMENT_NOT_FOUND"
        message = str(exc)
    elif isinstance(exc, ValueError):
        code = "VALIDATION_ERROR"
        message = str(exc)
    elif isinstance(exc, SQLAlchemyError):
        code = "STORAGE_ERROR"
        message = "database operation failed"
    else:
        code = "DEPENDENCY_ERROR"
        message = "knowledge base dependency failed"

    logger.exception(
        "mcp_tool_error tool=%s tenant_id=%s scope=%s duration_ms=%d error_code=%s",
        tool_name,
        tenant_id,
        scope,
        int((time.perf_counter() - started_at) * 1000),
        code,
    )
    raise ToolError(f"{code}: {message}") from exc


@mcp.tool(
    name="search_documents",
    title="Search tenant knowledge base",
    description=(
        "Search already-ingested internal knowledge for one tenant and scope. "
        "Use this tool when an agent needs evidence from the shared knowledge base before answering. "
        "This tool never searches outside the provided tenant_id and scope."
    ),
    tags={"knowledge", "search", "read"},
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
)
def search_documents(
    tenant_id: TenantId,
    query: str,
    scope: KnowledgeScope = DEFAULT_SCOPE,
    top_k: int | None = None,
    source: str | None = None,
    document_id: UUID | None = None,
) -> dict[str, Any]:
    started_at = time.perf_counter()
    try:
        settings = get_settings()
        resolved_top_k = top_k or settings.search_top_k
        with _storage_service() as service:
            results = service.search(
                query=query,
                top_k=resolved_top_k,
                tenant_id=tenant_id,
                scope=scope,
                source=source,
                document_id=document_id,
            )
        payload = {
            "status": "ok",
            "tenant_id": tenant_id,
            "scope": scope,
            "query": query,
            "top_k": resolved_top_k,
            "result_count": len(results),
            "results": [item.model_dump(mode="json") for item in results],
        }
        _log_tool_success(
            tool_name="search_documents",
            tenant_id=tenant_id,
            scope=scope,
            started_at=started_at,
            result_count=len(results),
        )
        return payload
    except Exception as exc:
        _raise_tool_error(
            tool_name="search_documents",
            tenant_id=tenant_id,
            scope=scope,
            started_at=started_at,
            exc=exc,
        )


@mcp.tool(
    name="ingest_document",
    title="Ingest text into tenant knowledge base",
    description=(
        "Add plain text knowledge to one tenant and scope. "
        "Use this for small or already-extracted text documents only. "
        "Do not use this tool for PDF uploads, OCR, or large file ingestion."
    ),
    tags={"knowledge", "ingest", "write"},
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
)
def ingest_document(
    tenant_id: TenantId,
    title: str,
    content: str,
    scope: KnowledgeScope = DEFAULT_SCOPE,
    source: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    started_at = time.perf_counter()
    try:
        payload = DocumentCreate(
            tenant_id=tenant_id,
            scope=scope,
            title=title,
            content=content,
            source=source,
            metadata=metadata or {},
        )
        with _storage_service() as service:
            result = service.ingest_document(payload)
        response = {
            "status": result.job.status.value,
            "tenant_id": tenant_id,
            "scope": scope,
            "job_id": str(result.job.id),
            "chunks_created": result.chunks_created,
            "document": _document_payload(result.document),
        }
        _log_tool_success(
            tool_name="ingest_document",
            tenant_id=tenant_id,
            scope=scope,
            started_at=started_at,
            result_count=result.chunks_created,
        )
        return response
    except Exception as exc:
        _raise_tool_error(
            tool_name="ingest_document",
            tenant_id=tenant_id,
            scope=scope,
            started_at=started_at,
            exc=exc,
        )


@mcp.tool(
    name="reindex_document",
    title="Reindex tenant document vectors",
    description=(
        "Rebuild vector embeddings for one existing document inside the provided tenant and scope. "
        "Use this after vector-store repair or embedding configuration changes. "
        "The document is treated as not found when it belongs to another tenant or scope."
    ),
    tags={"knowledge", "reindex", "admin"},
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
)
def reindex_document(
    tenant_id: TenantId,
    document_id: UUID,
    scope: KnowledgeScope = DEFAULT_SCOPE,
) -> dict[str, Any]:
    started_at = time.perf_counter()
    try:
        with _storage_service() as service:
            result = service.reindex_document(document_id, tenant_id=tenant_id, scope=scope)
        response = {
            "status": result.job.status.value,
            "tenant_id": tenant_id,
            "scope": scope,
            "job_id": str(result.job.id),
            "chunks_created": result.chunks_created,
            "document_id": str(result.document.id),
        }
        _log_tool_success(
            tool_name="reindex_document",
            tenant_id=tenant_id,
            scope=scope,
            started_at=started_at,
            result_count=result.chunks_created,
        )
        return response
    except Exception as exc:
        _raise_tool_error(
            tool_name="reindex_document",
            tenant_id=tenant_id,
            scope=scope,
            started_at=started_at,
            exc=exc,
        )


@mcp.tool(
    name="delete_document",
    title="Delete tenant knowledge document",
    description=(
        "Delete one document and its vectors from the provided tenant and scope. "
        "This is a destructive maintenance tool. "
        "Only use it when the caller explicitly wants stale or incorrect knowledge removed."
    ),
    tags={"knowledge", "delete", "admin", "destructive"},
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=True,
        idempotentHint=True,
        openWorldHint=False,
    ),
)
def delete_document(
    tenant_id: TenantId,
    document_id: UUID,
    scope: KnowledgeScope = DEFAULT_SCOPE,
) -> dict[str, str]:
    started_at = time.perf_counter()
    try:
        with _storage_service() as service:
            service.delete_document(document_id, tenant_id=tenant_id, scope=scope)
        _log_tool_success(
            tool_name="delete_document",
            tenant_id=tenant_id,
            scope=scope,
            started_at=started_at,
        )
        return {
            "status": "deleted",
            "tenant_id": tenant_id,
            "scope": scope,
            "document_id": str(document_id),
        }
    except Exception as exc:
        _raise_tool_error(
            tool_name="delete_document",
            tenant_id=tenant_id,
            scope=scope,
            started_at=started_at,
            exc=exc,
        )


@mcp.tool(
    name="health",
    title="Check knowledge base dependencies",
    description=(
        "Check whether the database and vector store used by the MCP knowledge tools are reachable. "
        "Use this before ingest, search, reindex, or delete when an agent or developer needs a readiness check."
    ),
    tags={"health", "read"},
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
)
def health() -> dict[str, Any]:
    started_at = time.perf_counter()
    try:
        settings = get_settings()
        with _storage_service() as service:
            service.db.execute(text("SELECT 1"))
            qdrant_ok = service.qdrant_store.health()
        response = {
            "status": "ok",
            "details": {
                "database": "reachable",
                "qdrant": "reachable" if qdrant_ok else "unreachable",
                "collection": settings.qdrant_collection,
            },
        }
        _log_tool_success(tool_name="health", started_at=started_at)
        return response
    except Exception as exc:
        _raise_tool_error(tool_name="health", started_at=started_at, exc=exc)
