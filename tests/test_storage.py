from __future__ import annotations

from pathlib import Path
from uuid import UUID

import fitz
import pytest
from qdrant_client import QdrantClient

from app.adapters.qdrant_store import QdrantChunkStore
from app.adapters.pdf_scanner_client import PdfScannerResult
from app.schemas import DocumentCreate
from app.services.file_storage import FileStorageService
from app.services.pdf_processing import PdfProcessingService
from app.services.storage import RagStorageService
from app.workers import pdf_jobs


def _build_service(test_context):
    session = test_context["session_factory"]()
    return RagStorageService(
        db=session,
        chunker=test_context["chunker"],
        embedder=test_context["embedder"],
        qdrant_store=test_context["qdrant_store"],
    )


def test_ingest_and_search_roundtrip(test_context):
    service = _build_service(test_context)
    try:
        result = service.ingest_document(
            DocumentCreate(
                title="FastAPI Guide",
                content="FastAPI async endpoints with PostgreSQL and Qdrant storage.",
                source="guide.md",
                metadata={"topic": "backend"},
            )
        )

        assert result.chunks_created >= 1
        assert result.document.title == "FastAPI Guide"
        assert len(service.list_documents()) == 1

        matches = service.search(query="FastAPI PostgreSQL", top_k=3)
        assert matches
        assert matches[0].document_title == "FastAPI Guide"
        assert "FastAPI" in matches[0].content
    finally:
        service.db.close()


def test_duplicate_ingest_is_idempotent(test_context):
    service = _build_service(test_context)
    try:
        payload = DocumentCreate(
            title="Chunking Notes",
            content="chunk one chunk two chunk three",
            source="notes.txt",
        )

        first = service.ingest_document(payload)
        second = service.ingest_document(payload)

        assert first.document.id == second.document.id
        assert len(service.list_documents()) == 1
    finally:
        service.db.close()


def test_same_payload_isolated_by_tenant_and_scope(test_context):
    service = _build_service(test_context)
    try:
        base_payload = {
            "title": "Shared Handbook",
            "content": "tenant scoped knowledge should not leak across workspaces",
            "source": "handbook.md",
            "metadata": {"kind": "handbook"},
        }

        tenant_a = service.ingest_document(
            DocumentCreate(tenant_id="tenant-a", scope="default", **base_payload)
        )
        tenant_b = service.ingest_document(
            DocumentCreate(tenant_id="tenant-b", scope="default", **base_payload)
        )
        project_scope = service.ingest_document(
            DocumentCreate(tenant_id="tenant-a", scope="project-x", **base_payload)
        )

        assert tenant_a.document.id != tenant_b.document.id
        assert tenant_a.document.id != project_scope.document.id
        assert len(service.list_documents(tenant_id="tenant-a", scope="default")) == 1
        assert len(service.list_documents(tenant_id="tenant-b", scope="default")) == 1
        assert len(service.list_documents(tenant_id="tenant-a", scope="project-x")) == 1

        matches = service.search(
            query="scoped knowledge",
            top_k=5,
            tenant_id="tenant-a",
            scope="default",
        )
        assert {match.document_id for match in matches} == {tenant_a.document.id}
        assert matches[0].tenant_id == "tenant-a"
        assert matches[0].scope == "default"
    finally:
        service.db.close()


def test_document_operations_require_matching_tenant_and_scope(test_context):
    service = _build_service(test_context)
    try:
        created = service.ingest_document(
            DocumentCreate(
                tenant_id="tenant-a",
                scope="project-x",
                title="Private Notes",
                content="private tenant scope content",
                source="private.md",
            )
        )

        assert service.get_document(
            created.document.id,
            tenant_id="tenant-b",
            scope="project-x",
        ) is None
        assert service.get_chunks(
            created.document.id,
            tenant_id="tenant-a",
            scope="default",
        ) == []

        service.delete_document(created.document.id, tenant_id="tenant-b", scope="project-x")
        assert service.get_document(
            created.document.id,
            tenant_id="tenant-a",
            scope="project-x",
        ) is not None

        try:
            service.reindex_document(created.document.id, tenant_id="tenant-a", scope="default")
        except LookupError as exc:
            assert "not found" in str(exc)
        else:  # pragma: no cover - defensive assertion
            raise AssertionError("cross-scope reindex should fail")
    finally:
        service.db.close()


def test_delete_removes_document_and_vectors(test_context):
    service = _build_service(test_context)
    try:
        created = service.ingest_document(
            DocumentCreate(
                title="Delete Me",
                content="vector search cleanup test content",
                source="cleanup.txt",
            )
        )

        service.delete_document(created.document.id)
        assert service.get_document(created.document.id) is None
        assert service.list_documents() == []
        assert service.search(query="cleanup", top_k=3) == []
    finally:
        service.db.close()


def test_ingest_keeps_failed_document_recoverable_when_vector_upsert_fails(test_context, monkeypatch):
    service = _build_service(test_context)
    try:
        original_upsert = service.qdrant_store.upsert_chunks

        def fail_upsert(*, points):
            raise RuntimeError("qdrant unavailable")

        monkeypatch.setattr(service.qdrant_store, "upsert_chunks", fail_upsert)
        with pytest.raises(RuntimeError, match="qdrant unavailable"):
            service.ingest_document(
                DocumentCreate(
                    title="Recoverable",
                    content="recoverable vector failure content",
                    source="recover.md",
                )
            )

        document = service.list_documents()[0]
        job = document.jobs[0]
        assert job.status.value == "failed"
        assert "vector upsert failed" in (job.error_message or "")

        monkeypatch.setattr(service.qdrant_store, "upsert_chunks", original_upsert)
        result = service.reindex_document(document.id)
        assert result.job.status.value == "completed"
        assert service.search(query="recoverable", top_k=3)
    finally:
        service.db.close()


def test_search_uses_lexical_fallback_when_vector_search_misses(test_context, monkeypatch):
    service = _build_service(test_context)
    try:
        created = service.ingest_document(
            DocumentCreate(
                title="Lexical Notes",
                content="needleword appears here even when vector search misses",
                source="lexical.md",
            )
        )
        monkeypatch.setattr(service.qdrant_store, "search", lambda **kwargs: [])

        matches = service.search(query="needleword", top_k=3)

        assert matches
        assert matches[0].document_id == created.document.id
        assert matches[0].score >= 1.0
    finally:
        service.db.close()


def test_qdrant_collection_dimension_mismatch_is_explicit() -> None:
    client = QdrantClient(location=":memory:")
    store = QdrantChunkStore(client, "dimension_test")
    store.ensure_collection(vector_size=8)

    with pytest.raises(ValueError, match="vector size mismatch"):
        store.ensure_collection(vector_size=4)


def test_file_storage_resolve_rejects_paths_outside_base(tmp_path: Path):
    storage = FileStorageService(str(tmp_path / "uploads"))
    allowed = tmp_path / "uploads" / "job" / "file.txt"
    allowed.parent.mkdir(parents=True)
    allowed.write_text("ok")

    assert storage.resolve(str(allowed)) == allowed.resolve()
    with pytest.raises(ValueError, match="outside upload storage"):
        storage.resolve(str(tmp_path / "outside.txt"))


def test_profiled_text_worker_preserves_job_title(test_context, monkeypatch, tmp_path: Path):
    settings = test_context["settings"].model_copy(update={"upload_storage_dir": str(tmp_path)})
    text_path = tmp_path / "upload.txt"
    text_path.write_text("worker title should be preserved", encoding="utf-8")

    def build_test_storage_service(db, settings):
        return RagStorageService(
            db=db,
            chunker=test_context["chunker"],
            embedder=test_context["embedder"],
            qdrant_store=test_context["qdrant_store"],
        )

    monkeypatch.setattr(pdf_jobs, "SessionLocal", test_context["session_factory"])
    monkeypatch.setattr(pdf_jobs, "get_settings", lambda: settings)
    monkeypatch.setattr(pdf_jobs, "build_storage_service", build_test_storage_service)

    session = test_context["session_factory"]()
    try:
        service = build_test_storage_service(session, settings)
        job = service.create_job(
            tenant_id="default",
            scope="default",
            title="Requested Worker Title",
            file_name="upload.txt",
            mime_type="text/plain",
            storage_path=str(text_path),
            parser_name="text",
        )
        job_id = job.id
    finally:
        session.close()

    result = pdf_jobs.process_profiled_document(str(job_id))

    session = test_context["session_factory"]()
    try:
        service = build_test_storage_service(session, settings)
        document = service.get_document(UUID(str(result["document_id"])))
        assert document is not None
        assert document.title == "Requested Worker Title"
    finally:
        session.close()


def test_pdf_processing_extracts_text(tmp_path: Path):
    pdf_path = tmp_path / "text.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Simple PDF text extraction")
    pdf_path.write_bytes(doc.tobytes())

    extractor = PdfProcessingService()
    result = extractor.extract(pdf_path)

    assert result.page_count == 1
    assert "Simple PDF text extraction" in result.content
    assert result.parser_name in {"pymupdf", "table-aware"}


def test_pdf_processing_uses_scanner_client_for_scanned_pdf(tmp_path: Path):
    class FakeScannerClient:
        def __init__(self) -> None:
            self.calls = []

        def ocr_pdf(
            self,
            pdf_path: Path,
            *,
            language: str,
            pages: list[int] | None = None,
            mode: str = "text",
        ) -> PdfScannerResult:
            self.calls.append((pdf_path, language, pages, mode))
            return PdfScannerResult(
                pdf=b"",
                text="OCR fallback test",
                page_texts={1: "OCR fallback test"},
                parser_name="ocr",
                message="ok",
                pages_processed=pages or [],
                duration_ms=10,
                warnings=[],
            )

    pdf_path = tmp_path / "scan.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "OCR fallback test")
    pdf_path.write_bytes(doc.tobytes())

    scanner = FakeScannerClient()
    extractor = PdfProcessingService(
        pdf_text_threshold=10_000,
        pdf_image_threshold=0,
        pdf_scanner_client=scanner,
        pdf_scanner_language="eng",
    )
    result = extractor.extract(pdf_path)

    assert scanner.calls == [(pdf_path, "eng", [1], "text")]
    assert result.parser_name == "ocr"
    assert result.metadata["parser_strategy"] == "ocr_pages"
    assert result.metadata["ocr_pages"] == [1]
