from __future__ import annotations

import dataclasses
from pathlib import Path

import fitz
import pdfplumber

from app.adapters.pdf_scanner_client import PdfScannerClient, PdfScannerClientError, PdfScannerResult


@dataclasses.dataclass(slots=True)
class PdfPageExtraction:
    page_number: int
    parser_name: str
    text: str
    table_count: int
    image_count: int


@dataclasses.dataclass(slots=True)
class PdfPageProfile:
    page_number: int
    text_chars: int
    image_count: int
    drawing_count: int
    block_count: int
    table_candidate: bool
    scanned: bool


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
        pdf_max_pages: int | None = None,
    ) -> None:
        self.pdf_text_threshold = pdf_text_threshold
        self.pdf_image_threshold = pdf_image_threshold
        self.pdf_scanner_client = pdf_scanner_client
        self.pdf_scanner_language = pdf_scanner_language
        self.pdf_max_pages = pdf_max_pages

    def extract(self, pdf_path: Path) -> PdfExtractionResult:
        if not pdf_path.exists():
            raise PdfProcessingError(f"pdf file not found: {pdf_path}")

        page_profiles = self.profile_pdf(pdf_path)
        strategy = self.choose_strategy(page_profiles)
        ocr_pages = [profile.page_number for profile in page_profiles if profile.scanned]
        ocr_result: PdfScannerResult | None = None

        if ocr_pages:
            ocr_result = self._run_ocr(pdf_path, pages=ocr_pages)

        pages, texts = self._extract_pages(
            pdf_path,
            page_profiles=page_profiles,
            strategy=strategy,
            ocr_result=ocr_result,
        )

        parser_name = self._summarize_parser(pages)
        metadata = {
            "parser_name": parser_name,
            "parser_strategy": strategy,
            "page_count": len(pages),
            "ocr_pages": ocr_pages,
            "scanner_duration_ms": ocr_result.duration_ms if ocr_result else None,
            "scanner_warnings": ocr_result.warnings if ocr_result else [],
            "profiles": [dataclasses.asdict(profile) for profile in page_profiles],
            "pages": [dataclasses.asdict(page) for page in pages],
        }
        return PdfExtractionResult(
            content="\n".join(texts).strip(),
            parser_name=parser_name,
            page_count=len(pages),
            pages=pages,
            metadata=metadata,
        )

    def profile_pdf(self, pdf_path: Path) -> list[PdfPageProfile]:
        if not pdf_path.exists():
            raise PdfProcessingError(f"pdf file not found: {pdf_path}")

        profiles: list[PdfPageProfile] = []
        with fitz.open(pdf_path) as doc:
            if self.pdf_max_pages is not None and doc.page_count > self.pdf_max_pages:
                raise PdfProcessingError(
                    f"pdf has {doc.page_count} pages, exceeding {self.pdf_max_pages} page limit"
                )
            for index in range(doc.page_count):
                page = doc.load_page(index)
                profiles.append(self._profile_page(page))
        return profiles

    def _profile_page(self, page: fitz.Page) -> PdfPageProfile:
        text = page.get_text("text").strip()
        image_count = len(page.get_images(full=True))
        drawing_count = len(page.get_drawings())
        block_count = len(page.get_text("blocks"))
        scanned = len(text) < self.pdf_text_threshold and image_count >= self.pdf_image_threshold
        table_candidate = False

        if not scanned:
            table_candidate = drawing_count >= 8 or self._has_table_by_mupdf(page)

        return PdfPageProfile(
            page_number=page.number + 1,
            text_chars=len(text),
            image_count=image_count,
            drawing_count=drawing_count,
            block_count=block_count,
            table_candidate=table_candidate,
            scanned=scanned,
        )

    def _has_table_by_mupdf(self, page: fitz.Page) -> bool:
        try:
            finder = page.find_tables()
        except Exception:
            return False
        return bool(getattr(finder, "tables", []))

    def choose_strategy(self, page_profiles: list[PdfPageProfile]) -> str:
        if not page_profiles:
            return "pymupdf"

        has_scanned = any(profile.scanned for profile in page_profiles)
        has_tables = any(profile.table_candidate for profile in page_profiles)

        if has_scanned and has_tables:
            return "hybrid"
        if has_scanned:
            return "ocr_pages"
        if has_tables:
            return "pdfplumber"
        return "pymupdf"

    def _extract_pages(
        self,
        pdf_path: Path,
        *,
        page_profiles: list[PdfPageProfile],
        strategy: str,
        ocr_result: PdfScannerResult | None,
    ) -> tuple[list[PdfPageExtraction], list[str]]:
        pages: list[PdfPageExtraction] = []
        texts: list[str] = []
        ocr_text_by_page = self._ocr_text_by_page(ocr_result, page_profiles)

        plumber_pdf = None
        try:
            if strategy in {"pdfplumber", "hybrid"}:
                plumber_pdf = pdfplumber.open(pdf_path)

            with fitz.open(pdf_path) as doc:
                for index in range(doc.page_count):
                    profile = page_profiles[index] if index < len(page_profiles) else None
                    page = doc.load_page(index)
                    page_result = self._extract_page(
                        page,
                        pdf_path,
                        profile,
                        plumber_pdf=plumber_pdf,
                        ocr_text=ocr_text_by_page.get(page.number + 1, ""),
                    )
                    pages.append(page_result)
                    if page_result.text.strip():
                        texts.append(f"\n\n--- page {page_result.page_number} ---\n\n{page_result.text.strip()}")
        finally:
            if plumber_pdf is not None:
                plumber_pdf.close()

        return pages, texts

    def _extract_page(
        self,
        page: fitz.Page,
        pdf_path: Path,
        profile: PdfPageProfile | None,
        *,
        plumber_pdf=None,
        ocr_text: str = "",
    ) -> PdfPageExtraction:
        text_chars = profile.text_chars if profile else 0
        image_count = profile.image_count if profile else 0

        if ocr_text.strip():
            text = ocr_text.strip()
            parser_name = "ocr"
            table_text = ""
        else:
            table_text = ""
            if profile and profile.table_candidate and plumber_pdf is not None:
                table_text = self._extract_table_text(page, pdf_path, plumber_pdf=plumber_pdf)

        if not ocr_text.strip() and table_text:
            text = table_text
            parser_name = "pdfplumber"
        elif not ocr_text.strip():
            text = page.get_text("text").strip()
            parser_name = "pymupdf"

            if image_count >= self.pdf_image_threshold and text_chars < self.pdf_text_threshold:
                parser_name = "ocr"

        return PdfPageExtraction(
            page_number=page.number + 1,
            parser_name=parser_name,
            text=text,
            table_count=1 if table_text else 0,
            image_count=image_count,
        )

    def _extract_table_text(self, page: fitz.Page, pdf_path: Path, *, plumber_pdf=None) -> str:
        if not pdf_path.exists():
            return ""

        try:
            close_pdf = False
            if plumber_pdf is None:
                plumber_pdf = pdfplumber.open(pdf_path)
                close_pdf = True
            try:
                plumber_page = plumber_pdf.pages[page.number]
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
            finally:
                if close_pdf:
                    plumber_pdf.close()
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

    def _run_ocr(self, pdf_path: Path, *, pages: list[int]) -> PdfScannerResult:
        if self.pdf_scanner_client is None:
            raise PdfProcessingError("scanned PDF detected but PDF scanner gRPC client is not configured")

        try:
            return self.pdf_scanner_client.ocr_pdf(
                pdf_path,
                language=self.pdf_scanner_language,
                pages=pages,
                mode="text",
            )
        except PdfScannerClientError as exc:
            raise PdfProcessingError(f"PDF scanner OCR failed: {exc}") from exc

    def _ocr_text_by_page(
        self,
        ocr_result: PdfScannerResult | None,
        page_profiles: list[PdfPageProfile],
    ) -> dict[int, str]:
        if ocr_result is None:
            return {}
        if ocr_result.page_texts:
            return dict(ocr_result.page_texts)

        ocr_pages = [profile.page_number for profile in page_profiles if profile.scanned]
        if not ocr_pages:
            return {}

        parts = [part.strip() for part in ocr_result.text.split("\f")]
        parts = [part for part in parts if part]
        if not parts:
            return {}
        if len(parts) == len(ocr_pages):
            return dict(zip(ocr_pages, parts, strict=True))
        return {ocr_pages[0]: ocr_result.text.strip()}

    def _summarize_parser(self, pages: list[PdfPageExtraction]) -> str:
        parser_names = {page.parser_name for page in pages if page.parser_name}
        if "ocr" in parser_names:
            return "ocr"
        if "pdfplumber" in parser_names and "pymupdf" in parser_names:
            return "hybrid"
        if "pdfplumber" in parser_names:
            return "table-aware"
        return "pymupdf"
