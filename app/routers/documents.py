from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.dependencies import build_storage_service
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.schemas import (
    ChunkRead,
    DocumentCreate,
    DocumentRead,
    DocumentSummary,
    IngestionJobRead,
    IngestResponse,
    SearchRequest,
    SearchResultItem,
    UploadAcceptedResponse,
)
from app.services.file_storage import FileStorageService
from app.services.storage import RagStorageService
from app.tasks.rq_queue import get_pdf_profile_queue
from app.workers.pdf_jobs import process_uploaded_document

router = APIRouter(prefix="/documents", tags=["documents"])


def get_storage_service(
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> RagStorageService:
    return build_storage_service(db, settings)


def _to_document_read(document) -> DocumentRead:
    return DocumentRead(
        id=document.id,
        title=document.title,
        source=document.source,
        content=document.content,
        checksum=document.checksum,
        metadata=document.metadata_json,
        chunk_count=len(document.chunks),
        created_at=document.created_at,
        updated_at=document.updated_at,
    )


@router.get("", response_model=list[DocumentSummary])
def list_documents(service: RagStorageService = Depends(get_storage_service)) -> list[DocumentSummary]:
    documents = service.list_documents()
    return [
        DocumentSummary(
            id=document.id,
            title=document.title,
            source=document.source,
            checksum=document.checksum,
            chunk_count=len(document.chunks),
            created_at=document.created_at,
            updated_at=document.updated_at,
        )
        for document in documents
    ]


@router.get("/{document_id}", response_model=DocumentRead)
def get_document(
    document_id: UUID,
    service: RagStorageService = Depends(get_storage_service),
) -> DocumentRead:
    document = service.get_document(document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="document not found")
    return _to_document_read(document)


@router.get("/{document_id}/chunks", response_model=list[ChunkRead])
def get_chunks(
    document_id: UUID,
    service: RagStorageService = Depends(get_storage_service),
) -> list[ChunkRead]:
    chunks = service.get_chunks(document_id)
    return [
        ChunkRead(
            id=chunk.id,
            document_id=chunk.document_id,
            chunk_index=chunk.chunk_index,
            content=chunk.content,
            char_count=chunk.char_count,
            metadata=chunk.metadata_json,
            created_at=chunk.created_at,
        )
        for chunk in chunks
    ]


@router.post("/ingest", response_model=IngestResponse, status_code=201)
def ingest_document(
    payload: DocumentCreate,
    service: RagStorageService = Depends(get_storage_service),
) -> IngestResponse:
    result = service.ingest_document(payload)
    return IngestResponse(
        job_id=result.job.id,
        document=_to_document_read(result.document),
        chunks_created=result.chunks_created,
        status=result.job.status.value,
    )


@router.post("/upload", response_model=IngestResponse, status_code=201)
async def upload_document(
    title: str = Form(...),
    content_file: UploadFile = File(...),
    source: str | None = Form(default=None),
    service: RagStorageService = Depends(get_storage_service),
) -> IngestResponse:
    if (content_file.content_type or "").lower() == "application/pdf" or (content_file.filename or "").lower().endswith(
        ".pdf"
    ):
        raise HTTPException(status_code=400, detail="use /documents/upload-document for PDF uploads")
    raw_content = (await content_file.read()).decode("utf-8")
    result = service.ingest_document(
        DocumentCreate(
            title=title,
            content=raw_content,
            source=source,
            metadata={"filename": content_file.filename},
        )
    )
    return IngestResponse(
        job_id=result.job.id,
        document=_to_document_read(result.document),
        chunks_created=result.chunks_created,
        status=result.job.status.value,
    )


@router.post("/upload-document", response_model=UploadAcceptedResponse, status_code=202)
async def upload_document_background(
    title: str = Form(...),
    content_file: UploadFile = File(...),
    source: str | None = Form(default=None),
    settings: Settings = Depends(get_settings),
    service: RagStorageService = Depends(get_storage_service),
) -> UploadAcceptedResponse:
    file_storage = FileStorageService(settings.upload_storage_dir)
    job = service.create_job(
        source_name=source,
        file_name=content_file.filename,
        mime_type=content_file.content_type,
        storage_path=None,
        parser_name="auto",
        page_count=None,
    )
    stored_path = file_storage.save_upload(job.id, content_file)
    max_bytes = settings.pdf_max_mb * 1024 * 1024
    if stored_path.stat().st_size > max_bytes:
        stored_path.unlink(missing_ok=True)
        service.mark_job_failed(job.id, f"uploaded file exceeds {settings.pdf_max_mb} MiB limit")
        raise HTTPException(status_code=413, detail=f"uploaded file exceeds {settings.pdf_max_mb} MiB limit")

    job.storage_path = str(stored_path)
    job.source_name = source
    job.file_name = content_file.filename
    job.mime_type = content_file.content_type
    job.parser_name = "auto"
    service.db.commit()
    queue = get_pdf_profile_queue(settings)
    try:
        queue.enqueue(
            process_uploaded_document,
            str(job.id),
            job_timeout=settings.pdf_job_timeout_seconds,
            result_ttl=settings.pdf_result_ttl_seconds,
        )
    except Exception as exc:  # pragma: no cover - enqueue failures are operational
        service.mark_job_failed(job.id, f"failed to enqueue background job: {exc}")
        raise HTTPException(status_code=503, detail="failed to enqueue background job") from exc
    return UploadAcceptedResponse(
        job_id=job.id,
        status=job.status.value,
        filename=content_file.filename or stored_path.name,
        mime_type=content_file.content_type,
        parser_hint="auto",
    )


@router.post("/search", response_model=list[SearchResultItem])
def search_documents(
    request: SearchRequest,
    settings: Settings = Depends(get_settings),
    service: RagStorageService = Depends(get_storage_service),
) -> list[SearchResultItem]:
    return service.search(
        query=request.query,
        top_k=request.top_k or settings.search_top_k,
        document_id=request.document_id,
        source=request.source,
    )


@router.get("/jobs/{job_id}", response_model=IngestionJobRead)
def get_job(job_id: UUID, service: RagStorageService = Depends(get_storage_service)) -> IngestionJobRead:
    job = service.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return IngestionJobRead(
        id=job.id,
        document_id=job.document_id,
        source_name=job.source_name,
        file_name=job.file_name,
        mime_type=job.mime_type,
        storage_path=job.storage_path,
        parser_name=job.parser_name,
        page_count=job.page_count,
        progress=job.progress,
        status=job.status.value,
        chunk_count=job.chunk_count,
        error_message=job.error_message,
        started_at=job.started_at,
        finished_at=job.finished_at,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


@router.post("/{document_id}/reindex", response_model=IngestResponse)
def reindex_document(
    document_id: UUID,
    service: RagStorageService = Depends(get_storage_service),
) -> IngestResponse:
    try:
        result = service.reindex_document(document_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return IngestResponse(
        job_id=result.job.id,
        document=_to_document_read(result.document),
        chunks_created=result.chunks_created,
        status=result.job.status.value,
    )


@router.delete("/{document_id}", status_code=204)
def delete_document(
    document_id: UUID,
    service: RagStorageService = Depends(get_storage_service),
) -> None:
    service.delete_document(document_id)
