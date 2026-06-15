from __future__ import annotations

from pathlib import Path
from uuid import UUID

from app.adapters.pdf_scanner_client import PdfScannerClient
from app.core.config import get_settings
from app.db.session import SessionLocal
from app.dependencies import build_storage_service
from app.services.file_storage import FileStorageService
from app.services.pdf_processing import PdfProcessingError, PdfProcessingService
from app.tasks.rq_queue import get_pdf_fast_queue, get_pdf_ocr_queue


def process_uploaded_document(job_id: str) -> dict[str, object]:
    """Profile an uploaded file and route expensive work to the right queue."""
    settings = get_settings()
    session = SessionLocal()
    storage = FileStorageService(settings.upload_storage_dir)
    service = build_storage_service(session, settings)
    try:
        job_uuid = UUID(job_id)
        job = service.mark_job_running(job_uuid, parser_name="profiling")
        if not job.storage_path:
            raise PdfProcessingError("job has no stored file path")

        file_path = storage.resolve(job.storage_path)
        suffix = file_path.suffix.lower()
        mime_type = (job.mime_type or "").lower()

        if suffix in {".txt", ".md", ".rst"} or mime_type.startswith("text/"):
            queue = get_pdf_fast_queue(settings)
            service.update_job_progress(job_uuid, progress=10, parser_name="text")
            queue.enqueue(
                process_profiled_document,
                str(job_uuid),
                job_timeout=settings.pdf_job_timeout_seconds,
                result_ttl=settings.pdf_result_ttl_seconds,
            )
            return {"job_id": str(job_uuid), "status": "routed", "parser_strategy": "text"}

        if suffix != ".pdf" and mime_type != "application/pdf":
            raise PdfProcessingError(
                f"unsupported file type for background ingestion: {job.mime_type or file_path.suffix}"
            )

        extractor = PdfProcessingService(
            pdf_text_threshold=settings.pdf_text_threshold,
            pdf_image_threshold=settings.pdf_image_threshold,
            pdf_max_pages=settings.pdf_max_pages,
        )
        profiles = extractor.profile_pdf(file_path)
        strategy = extractor.choose_strategy(profiles)
        ocr_pages = [profile.page_number for profile in profiles if profile.scanned]
        service.update_job_progress(
            job_uuid,
            progress=10,
            parser_name=strategy,
            page_count=len(profiles),
        )

        queue = get_pdf_ocr_queue(settings) if ocr_pages else get_pdf_fast_queue(settings)
        queue.enqueue(
            process_profiled_document,
            str(job_uuid),
            job_timeout=settings.pdf_job_timeout_seconds,
            result_ttl=settings.pdf_result_ttl_seconds,
        )
        return {
            "job_id": str(job_uuid),
            "status": "routed",
            "parser_strategy": strategy,
            "ocr_pages": ocr_pages,
            "page_count": len(profiles),
        }
    except Exception as exc:
        service.mark_job_failed(UUID(job_id), str(exc))
        raise
    finally:
        session.close()


def process_profiled_document(job_id: str) -> dict[str, object]:
    settings = get_settings()
    session = SessionLocal()
    storage = FileStorageService(settings.upload_storage_dir)
    service = build_storage_service(session, settings)
    try:
        job_uuid = UUID(job_id)
        job = service.mark_job_running(job_uuid)
        if not job.storage_path:
            raise PdfProcessingError("job has no stored file path")

        file_path = storage.resolve(job.storage_path)
        suffix = file_path.suffix.lower()
        mime_type = (job.mime_type or "").lower()

        if suffix in {".txt", ".md", ".rst"} or mime_type.startswith("text/"):
            content = file_path.read_text(encoding="utf-8")
            result = service.ingest_extracted_document(
                title=job.title or Path(job.file_name or file_path.name).stem,
                content=content,
                source=job.source_name,
                metadata={
                    "filename": job.file_name,
                    "mime_type": job.mime_type,
                    "source_kind": "text",
                },
                job_id=job_uuid,
                parser_name="text",
                source_name=job.source_name,
            )
            return {
                "job_id": str(result.job.id),
                "document_id": str(result.document.id),
                "status": result.job.status.value,
                "chunks_created": result.chunks_created,
                "parser_name": "text",
            }

        if suffix != ".pdf" and mime_type != "application/pdf":
            raise PdfProcessingError(
                f"unsupported file type for background ingestion: {job.mime_type or file_path.suffix}"
            )

        extractor = PdfProcessingService(
            pdf_text_threshold=settings.pdf_text_threshold,
            pdf_image_threshold=settings.pdf_image_threshold,
            pdf_scanner_client=PdfScannerClient(
                target=settings.pdf_scanner_grpc_url,
                max_message_mb=settings.pdf_scanner_max_mb,
                timeout_seconds=settings.pdf_scanner_timeout_seconds,
                use_source_path=settings.pdf_scanner_use_source_path,
            ),
            pdf_scanner_language=settings.pdf_scanner_language,
            pdf_max_pages=settings.pdf_max_pages,
        )
        extracted = extractor.extract(file_path)
        service.update_job_progress(
            job_uuid,
            progress=15,
            parser_name=extracted.parser_name,
            page_count=extracted.page_count,
        )
        result = service.ingest_extracted_document(
            title=job.title or Path(job.file_name or file_path.name).stem,
            content=extracted.content,
            source=job.source_name,
            metadata={
                "filename": job.file_name,
                "mime_type": job.mime_type,
                "source_kind": "pdf",
                "pdf": extracted.metadata,
            },
            job_id=job_uuid,
            parser_name=extracted.parser_name,
            source_name=job.source_name,
        )
        service.update_job_progress(
            job_uuid,
            progress=100,
            parser_name=extracted.parser_name,
            page_count=extracted.page_count,
        )
        return {
            "job_id": str(result.job.id),
            "document_id": str(result.document.id),
            "status": result.job.status.value,
            "chunks_created": result.chunks_created,
            "parser_name": extracted.parser_name,
        }
    except Exception as exc:
        service.mark_job_failed(UUID(job_id), str(exc))
        raise
    finally:
        session.close()
