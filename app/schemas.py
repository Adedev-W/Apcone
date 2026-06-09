from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class DocumentCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    content: str = Field(min_length=1)
    source: str | None = Field(default=None, max_length=255)
    metadata: dict[str, Any] = Field(default_factory=dict)


class DocumentRead(BaseModel):
    id: UUID
    title: str
    source: str | None
    content: str
    checksum: str
    metadata: dict[str, Any]
    chunk_count: int
    created_at: datetime
    updated_at: datetime


class DocumentSummary(BaseModel):
    id: UUID
    title: str
    source: str | None
    checksum: str
    chunk_count: int
    created_at: datetime
    updated_at: datetime


class ChunkRead(BaseModel):
    id: UUID
    document_id: UUID
    chunk_index: int
    content: str
    char_count: int
    metadata: dict[str, Any]
    created_at: datetime


class IngestResponse(BaseModel):
    job_id: UUID
    document: DocumentRead
    chunks_created: int
    status: str


class UploadAcceptedResponse(BaseModel):
    job_id: UUID
    status: str
    filename: str
    mime_type: str | None = None
    parser_hint: str | None = None


class IngestionJobRead(BaseModel):
    id: UUID
    document_id: UUID | None
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


class SearchRequest(BaseModel):
    query: str = Field(min_length=1)
    top_k: int | None = Field(default=None, ge=1, le=50)
    source: str | None = Field(default=None, max_length=255)
    document_id: UUID | None = None


class SearchResultItem(BaseModel):
    chunk_id: UUID
    document_id: UUID
    document_title: str
    source: str | None
    chunk_index: int
    content: str
    score: float
    metadata: dict[str, Any]


class HealthResponse(BaseModel):
    status: str
    details: dict[str, Any] = Field(default_factory=dict)

