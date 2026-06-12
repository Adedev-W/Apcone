from __future__ import annotations

from pathlib import Path

import fitz

from app.adapters.pdf_scanner_client import PdfScannerResult
from app.schemas import DocumentCreate
from app.services.pdf_processing import PdfProcessingService
from app.services.storage import RagStorageService


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
