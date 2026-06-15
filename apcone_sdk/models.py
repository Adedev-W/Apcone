from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class SDKModel(BaseModel):
    model_config = ConfigDict(extra="allow")


class Health(SDKModel):
    status: str
    details: dict[str, Any] = Field(default_factory=dict)


class DocumentSummary(SDKModel):
    id: UUID
    tenant_id: str
    scope: str
    title: str
    source: str | None
    checksum: str
    chunk_count: int
    created_at: datetime
    updated_at: datetime


class Document(DocumentSummary):
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class Chunk(SDKModel):
    id: UUID
    document_id: UUID
    tenant_id: str
    scope: str
    chunk_index: int
    content: str
    char_count: int
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class IngestResponse(SDKModel):
    job_id: UUID
    document: Document
    chunks_created: int
    status: str


class UploadAccepted(SDKModel):
    job_id: UUID
    tenant_id: str
    scope: str
    status: str
    title: str
    filename: str
    mime_type: str | None = None
    parser_hint: str | None = None


class IngestionJob(SDKModel):
    id: UUID
    tenant_id: str
    scope: str
    document_id: UUID | None
    title: str | None
    source_name: str | None
    file_name: str | None
    mime_type: str | None
    storage_path: str | None
    page_count: int | None
    progress: int
    status: str
    chunk_count: int
    error_message: str | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    updated_at: datetime


class SearchResult(SDKModel):
    chunk_id: UUID
    document_id: UUID
    tenant_id: str
    scope: str
    document_title: str
    source: str | None
    chunk_index: int
    content: str
    score: float
    metadata: dict[str, Any] = Field(default_factory=dict)


class MCPSearchResponse(SDKModel):
    status: str
    tenant_id: str
    scope: str
    query: str
    top_k: int
    result_count: int
    results: list[SearchResult]


class MCPDeleteResponse(SDKModel):
    status: str
    tenant_id: str
    scope: str
    document_id: UUID


class MCPReindexResponse(SDKModel):
    status: str
    tenant_id: str
    scope: str
    job_id: UUID
    chunks_created: int
    document_id: UUID
