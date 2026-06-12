from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from qdrant_client import models
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.qdrant_store import QdrantChunkStore
from app.db.models import Document, DocumentChunk, IngestionJob, JobStatus
from app.schemas import DEFAULT_SCOPE, DEFAULT_TENANT_ID, DocumentCreate, SearchResultItem
from app.services.chunking import ChunkingService
from app.services.embeddings import EmbeddingService


@dataclass(slots=True)
class IngestResult:
    job: IngestionJob
    document: Document
    chunks_created: int


class RagStorageService:
    def __init__(
        self,
        *,
        db: Session,
        chunker: ChunkingService,
        embedder: EmbeddingService,
        qdrant_store: QdrantChunkStore,
    ) -> None:
        self.db = db
        self.chunker = chunker
        self.embedder = embedder
        self.qdrant_store = qdrant_store

    def create_job(
        self,
        *,
        tenant_id: str = DEFAULT_TENANT_ID,
        scope: str = DEFAULT_SCOPE,
        source_name: str | None = None,
        file_name: str | None = None,
        mime_type: str | None = None,
        storage_path: str | None = None,
        parser_name: str | None = None,
        page_count: int | None = None,
        source_kind: str | None = None,
    ) -> IngestionJob:
        job = IngestionJob(
            tenant_id=tenant_id,
            scope=scope,
            source_name=source_name,
            file_name=file_name,
            mime_type=mime_type,
            storage_path=storage_path,
            parser_name=parser_name,
            page_count=page_count,
            status=JobStatus.pending,
            progress=0,
            started_at=None,
            finished_at=None,
        )
        self.db.add(job)
        self.db.commit()
        self.db.refresh(job)
        return job

    def get_job(
        self,
        job_id: UUID,
        *,
        tenant_id: str | None = None,
        scope: str | None = None,
    ) -> IngestionJob | None:
        statement = select(IngestionJob).where(IngestionJob.id == job_id)
        if tenant_id is not None:
            statement = statement.where(IngestionJob.tenant_id == tenant_id)
        if scope is not None:
            statement = statement.where(IngestionJob.scope == scope)
        return self.db.scalar(statement)

    def mark_job_running(self, job_id: UUID, parser_name: str | None = None) -> IngestionJob:
        job = self.get_job(job_id)
        if job is None:
            raise LookupError(f"job {job_id} not found")
        job.status = JobStatus.running
        job.started_at = datetime.now(timezone.utc)
        if parser_name is not None:
            job.parser_name = parser_name
        job.progress = max(job.progress, 5)
        self.db.commit()
        self.db.refresh(job)
        return job

    def update_job_progress(
        self,
        job_id: UUID,
        *,
        progress: int,
        parser_name: str | None = None,
        page_count: int | None = None,
    ) -> IngestionJob:
        job = self.get_job(job_id)
        if job is None:
            raise LookupError(f"job {job_id} not found")
        job.progress = max(0, min(progress, 100))
        if parser_name is not None:
            job.parser_name = parser_name
        if page_count is not None:
            job.page_count = page_count
        self.db.commit()
        self.db.refresh(job)
        return job

    def mark_job_failed(self, job_id: UUID, error_message: str) -> IngestionJob:
        job = self.get_job(job_id)
        if job is None:
            raise LookupError(f"job {job_id} not found")
        job.status = JobStatus.failed
        job.error_message = error_message
        job.finished_at = datetime.now(timezone.utc)
        job.progress = 100
        self.db.commit()
        self.db.refresh(job)
        return job

    def mark_job_completed(self, job_id: UUID, chunk_count: int) -> IngestionJob:
        job = self.get_job(job_id)
        if job is None:
            raise LookupError(f"job {job_id} not found")
        job.status = JobStatus.completed
        job.chunk_count = chunk_count
        job.progress = 100
        job.finished_at = datetime.now(timezone.utc)
        self.db.commit()
        self.db.refresh(job)
        return job

    def ingest_extracted_document(
        self,
        *,
        tenant_id: str = DEFAULT_TENANT_ID,
        scope: str = DEFAULT_SCOPE,
        title: str,
        content: str,
        source: str | None,
        metadata: dict,
        job_id: UUID | None = None,
        parser_name: str | None = None,
        source_name: str | None = None,
    ) -> IngestResult:
        payload = DocumentCreate(
            tenant_id=tenant_id,
            scope=scope,
            title=title,
            content=content,
            source=source,
            metadata=metadata,
        )
        return self._ingest_payload(
            payload=payload,
            source_name=source_name,
            job_id=job_id,
            parser_name=parser_name,
        )

    def ingest_document(self, payload: DocumentCreate, source_name: str | None = None) -> IngestResult:
        return self._ingest_payload(payload=payload, source_name=source_name)

    def _ingest_payload(
        self,
        *,
        payload: DocumentCreate,
        source_name: str | None,
        job_id: UUID | None = None,
        parser_name: str | None = None,
    ) -> IngestResult:
        job = self.get_job(job_id) if job_id is not None else None
        if job_id is not None and job is None:
            raise LookupError(f"job {job_id} not found")

        tenant_id = job.tenant_id if job is not None else payload.tenant_id
        scope = job.scope if job is not None else payload.scope

        checksum = self._checksum(payload)
        existing = self.db.scalar(
            select(Document).where(
                Document.tenant_id == tenant_id,
                Document.scope == scope,
                Document.checksum == checksum,
            )
        )
        if existing is not None:
            if job_id is None:
                job = self._create_job(document=existing, source_name=source_name, status=JobStatus.completed)
            else:
                assert job is not None
                job.document_id = existing.id
                job.status = JobStatus.completed
                job.chunk_count = len(existing.chunks)
                job.progress = 100
                job.finished_at = datetime.now(timezone.utc)
                if parser_name is not None:
                    job.parser_name = parser_name
                self.db.commit()
                self.db.refresh(job)
            return IngestResult(job=job, document=existing, chunks_created=len(existing.chunks))

        if job_id is None:
            job = IngestionJob(
                tenant_id=tenant_id,
                scope=scope,
                source_name=source_name or payload.source,
                status=JobStatus.running,
                started_at=datetime.now(timezone.utc),
                progress=5,
                parser_name=parser_name,
            )
            self.db.add(job)
            self.db.flush()
        else:
            assert job is not None
            job.status = JobStatus.running
            job.started_at = datetime.now(timezone.utc)
            job.progress = max(job.progress, 5)
            if parser_name is not None:
                job.parser_name = parser_name

        document = Document(
            tenant_id=tenant_id,
            scope=scope,
            title=payload.title,
            source=payload.source,
            content=payload.content,
            checksum=checksum,
            metadata_json=payload.metadata,
        )
        self.db.add(document)
        self.db.flush()
        job.document_id = document.id

        chunks = self.chunker.chunk(payload.content)
        if not chunks:
            raise ValueError("document content produced no chunks")

        embeddings = self.embedder.embed_texts([chunk.content for chunk in chunks])
        self.qdrant_store.ensure_collection(vector_size=len(embeddings[0]))

        qdrant_points: list[models.PointStruct] = []
        total = len(chunks)
        for chunk, embedding in zip(chunks, embeddings, strict=True):
            chunk_row = DocumentChunk(
                document_id=document.id,
                chunk_index=chunk.index,
                content=chunk.content,
                char_count=chunk.char_count,
                metadata_json={
                    "tenant_id": tenant_id,
                    "scope": scope,
                    "title": payload.title,
                    "source": payload.source,
                    **payload.metadata,
                },
            )
            self.db.add(chunk_row)
            self.db.flush()

            qdrant_points.append(
                models.PointStruct(
                    id=str(chunk_row.id),
                    vector=embedding,
                    payload={
                        "chunk_id": str(chunk_row.id),
                        "document_id": str(document.id),
                        "tenant_id": tenant_id,
                        "scope": scope,
                        "document_title": document.title,
                        "source": document.source,
                        "chunk_index": chunk_row.chunk_index,
                        "content": chunk_row.content,
                        "char_count": chunk_row.char_count,
                        "metadata": document.metadata_json,
                        "checksum": document.checksum,
                    },
                )
            )
            if job_id is not None:
                job.progress = min(95, 5 + int(((chunk.index + 1) / total) * 90))

        self.qdrant_store.upsert_chunks(points=qdrant_points)
        job.status = JobStatus.completed
        job.chunk_count = len(qdrant_points)
        job.progress = 100
        job.finished_at = datetime.now(timezone.utc)
        self.db.commit()
        self.db.refresh(document)
        self.db.refresh(job)
        return IngestResult(job=job, document=document, chunks_created=len(qdrant_points))

    def reindex_document(
        self,
        document_id: UUID,
        *,
        tenant_id: str = DEFAULT_TENANT_ID,
        scope: str = DEFAULT_SCOPE,
    ) -> IngestResult:
        document = self._get_document_for_context(document_id, tenant_id=tenant_id, scope=scope)
        if document is None:
            raise LookupError(f"document {document_id} not found")

        job = self._create_job(document=document, source_name=document.source, status=JobStatus.running)
        chunks = sorted(document.chunks, key=lambda row: row.chunk_index)
        if not chunks:
            raise ValueError("document has no chunks to reindex")

        embeddings = self.embedder.embed_texts([chunk.content for chunk in chunks])
        self.qdrant_store.delete_document(
            document_id=document.id,
            tenant_id=document.tenant_id,
            scope=document.scope,
        )

        points = []
        for chunk, embedding in zip(chunks, embeddings, strict=True):
            points.append(
                models.PointStruct(
                    id=str(chunk.id),
                    vector=embedding,
                    payload={
                        "chunk_id": str(chunk.id),
                        "document_id": str(document.id),
                        "tenant_id": document.tenant_id,
                        "scope": document.scope,
                        "document_title": document.title,
                        "source": document.source,
                        "chunk_index": chunk.chunk_index,
                        "content": chunk.content,
                        "char_count": chunk.char_count,
                        "metadata": document.metadata_json,
                        "checksum": document.checksum,
                    },
                )
            )

        self.qdrant_store.ensure_collection(vector_size=len(embeddings[0]))
        self.qdrant_store.upsert_chunks(points=points)
        job.status = JobStatus.completed
        job.chunk_count = len(points)
        job.finished_at = datetime.now(timezone.utc)
        self.db.commit()
        self.db.refresh(job)
        return IngestResult(job=job, document=document, chunks_created=len(points))

    def delete_document(
        self,
        document_id: UUID,
        *,
        tenant_id: str = DEFAULT_TENANT_ID,
        scope: str = DEFAULT_SCOPE,
    ) -> None:
        document = self._get_document_for_context(document_id, tenant_id=tenant_id, scope=scope)
        if document is None:
            return
        self.qdrant_store.delete_document(
            document_id=document.id,
            tenant_id=document.tenant_id,
            scope=document.scope,
        )
        self.db.delete(document)
        self.db.commit()

    def search(
        self,
        *,
        query: str,
        top_k: int,
        tenant_id: str = DEFAULT_TENANT_ID,
        scope: str = DEFAULT_SCOPE,
        document_id: UUID | None = None,
        source: str | None = None,
    ) -> list[SearchResultItem]:
        query_vector = self.embedder.embed_query(query)
        points = self.qdrant_store.search(
            query_vector=query_vector,
            limit=top_k,
            tenant_id=tenant_id,
            scope=scope,
            document_id=document_id,
            source=source,
        )

        results: list[SearchResultItem] = []
        for point in points:
            payload = point.payload or {}
            results.append(
                SearchResultItem(
                    chunk_id=UUID(payload["chunk_id"]),
                    document_id=UUID(payload["document_id"]),
                    tenant_id=str(payload.get("tenant_id", tenant_id)),
                    scope=str(payload.get("scope", scope)),
                    document_title=str(payload.get("document_title", "")),
                    source=payload.get("source"),
                    chunk_index=int(payload.get("chunk_index", 0)),
                    content=str(payload.get("content", "")),
                    score=float(point.score),
                    metadata=dict(payload.get("metadata") or {}),
                )
            )
        return results

    def list_documents(
        self,
        *,
        tenant_id: str = DEFAULT_TENANT_ID,
        scope: str = DEFAULT_SCOPE,
        limit: int = 100,
    ) -> list[Document]:
        statement = (
            select(Document)
            .where(Document.tenant_id == tenant_id, Document.scope == scope)
            .order_by(Document.created_at.desc())
            .limit(limit)
        )
        return list(self.db.scalars(statement))

    def get_document(
        self,
        document_id: UUID,
        *,
        tenant_id: str = DEFAULT_TENANT_ID,
        scope: str = DEFAULT_SCOPE,
    ) -> Document | None:
        return self._get_document_for_context(document_id, tenant_id=tenant_id, scope=scope)

    def get_chunks(
        self,
        document_id: UUID,
        *,
        tenant_id: str = DEFAULT_TENANT_ID,
        scope: str = DEFAULT_SCOPE,
    ) -> list[DocumentChunk]:
        statement = (
            select(DocumentChunk)
            .join(Document)
            .where(DocumentChunk.document_id == document_id)
            .where(Document.tenant_id == tenant_id, Document.scope == scope)
            .order_by(DocumentChunk.chunk_index.asc())
        )
        return list(self.db.scalars(statement))

    def _create_job(
        self,
        *,
        document: Document,
        source_name: str | None,
        status: JobStatus,
    ) -> IngestionJob:
        job = IngestionJob(
            tenant_id=document.tenant_id,
            scope=document.scope,
            document_id=document.id,
            source_name=source_name,
            status=status,
            started_at=datetime.now(timezone.utc) if status == JobStatus.running else None,
            finished_at=datetime.now(timezone.utc) if status == JobStatus.completed else None,
            chunk_count=len(document.chunks),
        )
        self.db.add(job)
        self.db.commit()
        self.db.refresh(job)
        return job

    def _get_document_for_context(
        self,
        document_id: UUID,
        *,
        tenant_id: str,
        scope: str,
    ) -> Document | None:
        return self.db.scalar(
            select(Document).where(
                Document.id == document_id,
                Document.tenant_id == tenant_id,
                Document.scope == scope,
            )
        )

    @staticmethod
    def _checksum(payload: DocumentCreate) -> str:
        digest = hashlib.sha256()
        digest.update(payload.title.encode("utf-8"))
        digest.update(b"\0")
        digest.update((payload.source or "").encode("utf-8"))
        digest.update(b"\0")
        digest.update(payload.content.encode("utf-8"))
        digest.update(b"\0")
        digest.update(json.dumps(payload.metadata, sort_keys=True, separators=(",", ":")).encode("utf-8"))
        return digest.hexdigest()
