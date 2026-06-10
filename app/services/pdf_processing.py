from __future__ import annotations

import dataclasses
import tempfile
from pathlib import Path

import fitz
import pdfplumber

from app.adapters.pdf_scanner_client import PdfScannerClient, PdfScannerClientError


@dataclasses.dataclass(slots=True)
class PdfPageExtraction:
    page_number: int
    parser_name: str
    text: str
    table_count: int
    image_count: int


@dataclasses.dataclass(slots=True)
class PdfExtractionResult:
    content: str
    parser_name: str
    page_count: int
    pages: list[PdfPageExtraction]
    metadata: dict[str, object]


class PdfProcessingError(RuntimeError):
    pass


class PdfProcessingService:
    def __init__(
        self,
        *,
        pdf_text_threshold: int = 80,
        pdf_image_threshold: int = 1,
        pdf_scanner_client: PdfScannerClient | None = None,
        pdf_scanner_language: str = "eng",
    ) -> None:
        self.pdf_text_threshold = pdf_text_threshold
        self.pdf_image_threshold = pdf_image_threshold
        self.pdf_scanner_client = pdf_scanner_client
        self.pdf_scanner_language = pdf_scanner_language

    def extract(self, pdf_path: Path) -> PdfExtractionResult:
        if not pdf_path.exists():
            raise PdfProcessingError(f"pdf file not found: {pdf_path}")

        used_ocr = False
        cleanup_path: Path | None = None
        with fitz.open(pdf_path) as doc:
            page_count = doc.page_count
            page_profiles = [self._profile_page(doc.load_page(index)) for index in range(page_count)]

        if self._needs_ocr(page_profiles):
            ocr_path = self._run_ocr(pdf_path)
            pdf_path = ocr_path
            cleanup_path = ocr_path
            used_ocr = True

        pages: list[PdfPageExtraction] = []
        texts: list[str] = []
        try:
            with fitz.open(pdf_path) as doc:
                for index in range(doc.page_count):
                    profile = page_profiles[index] if index < len(page_profiles) else None
                    page = doc.load_page(index)
                    page_result = self._extract_page(page, pdf_path, profile, used_ocr=used_ocr)
                    pages.append(page_result)
                    if page_result.text.strip():
                        texts.append(f"\n\n--- page {page_result.page_number} ---\n\n{page_result.text.strip()}")
        finally:
            if cleanup_path is not None:
                cleanup_path.unlink(missing_ok=True)

        parser_name = self._summarize_parser(pages)
        metadata = {
            "parser_name": parser_name,
            "page_count": len(pages),
            "pages": [dataclasses.asdict(page) for page in pages],
        }
        return PdfExtractionResult(
            content="\n".join(texts).strip(),
            parser_name=parser_name,
            page_count=len(pages),
            pages=pages,
            metadata=metadata,
        )

    def _profile_page(self, page: fitz.Page) -> dict[str, int]:
        text = page.get_text("text").strip()
        return {
            "text_chars": len(text),
            "image_count": len(page.get_images(full=True)),
        }

    def _needs_ocr(self, page_profiles: list[dict[str, int]]) -> bool:
        if not page_profiles:
            return False
        scanned_pages = 0
        for profile in page_profiles:
            if profile["text_chars"] < self.pdf_text_threshold and profile["image_count"] >= self.pdf_image_threshold:
                scanned_pages += 1
        return scanned_pages > 0

    def _extract_page(
        self,
        page: fitz.Page,
        pdf_path: Path,
        profile: dict[str, int] | None,
        *,
        used_ocr: bool = False,
    ) -> PdfPageExtraction:
        text_chars = profile["text_chars"] if profile else 0
        image_count = profile["image_count"] if profile else 0

        table_text = self._extract_table_text(page, pdf_path)
        if table_text:
            text = table_text
            parser_name = "pdfplumber"
        else:
            text = page.get_text("text").strip()
            parser_name = "pymupdf"

        if image_count >= self.pdf_image_threshold and text_chars < self.pdf_text_threshold:
            parser_name = "ocr" if used_ocr else parser_name

        return PdfPageExtraction(
            page_number=page.number + 1,
            parser_name=parser_name,
            text=text,
            table_count=1 if table_text else 0,
            image_count=image_count,
        )

    def _extract_table_text(self, page: fitz.Page, pdf_path: Path) -> str:
        if not pdf_path.exists():
            return ""

        try:
            with pdfplumber.open(pdf_path) as pdf:
                plumber_page = pdf.pages[page.number]
                tables = plumber_page.extract_tables()
                if not tables:
                    return ""
                sections: list[str] = []
                text = plumber_page.extract_text(layout=True) or ""
                if text.strip():
                    sections.append(text.strip())
                for table in tables:
                    markdown_table = self._table_to_markdown(table)
                    if markdown_table:
                        sections.append(markdown_table)
                return "\n\n".join(sections).strip()
        except Exception:
            return ""

    def _table_to_markdown(self, table: list[list[str | None]]) -> str:
        normalized = [[(cell or "").strip() for cell in row] for row in table if any(cell and str(cell).strip() for cell in row)]
        if not normalized:
            return ""
        width = max(len(row) for row in normalized)
        rows: list[str] = []
        header = normalized[0] + [""] * (width - len(normalized[0]))
        rows.append("| " + " | ".join(header) + " |")
        rows.append("| " + " | ".join(["---"] * width) + " |")
        for row in normalized[1:]:
            padded = row + [""] * (width - len(row))
            rows.append("| " + " | ".join(padded) + " |")
        return "\n".join(rows)

    def _run_ocr(self, pdf_path: Path) -> Path:
        if self.pdf_scanner_client is None:
            raise PdfProcessingError("scanned PDF detected but PDF scanner gRPC client is not configured")

        try:
            ocr_pdf = self.pdf_scanner_client.ocr_pdf(pdf_path, language=self.pdf_scanner_language)
        except PdfScannerClientError as exc:
            raise PdfProcessingError(f"PDF scanner OCR failed: {exc}") from exc

        with tempfile.NamedTemporaryFile(
            prefix=f"{pdf_path.stem}.",
            suffix=".ocr.pdf",
            delete=False,
        ) as output:
            output.write(ocr_pdf)
            return Path(output.name)

    def _summarize_parser(self, pages: list[PdfPageExtraction]) -> str:
        parser_names = {page.parser_name for page in pages if page.parser_name}
        if "ocr" in parser_names:
            return "ocr"
        if "pdfplumber" in parser_names and "pymupdf" in parser_names:
            return "hybrid"
        if "pdfplumber" in parser_names:
            return "table-aware"
        return "pymupdf"
