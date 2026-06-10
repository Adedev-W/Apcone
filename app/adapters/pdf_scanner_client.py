from __future__ import annotations

import dataclasses
from pathlib import Path

import grpc

from app.proto import pdf_scanner_pb2, pdf_scanner_pb2_grpc


class PdfScannerClientError(RuntimeError):
    pass


@dataclasses.dataclass(slots=True)
class PdfScannerResult:
    pdf: bytes
    text: str
    page_texts: dict[int, str]
    parser_name: str
    message: str
    pages_processed: list[int]
    duration_ms: int
    warnings: list[str]


class PdfScannerClient:
    def __init__(
        self,
        *,
        target: str,
        max_message_mb: int,
        timeout_seconds: int = 300,
        use_source_path: bool = False,
    ) -> None:
        max_message_bytes = max_message_mb * 1024 * 1024
        options = [
            ("grpc.max_send_message_length", max_message_bytes),
            ("grpc.max_receive_message_length", max_message_bytes),
        ]
        self.target = target
        self.timeout_seconds = timeout_seconds
        self.use_source_path = use_source_path
        self.channel = grpc.insecure_channel(target, options=options)
        self.stub = pdf_scanner_pb2_grpc.PdfScannerStub(self.channel)

    def ocr_pdf(
        self,
        pdf_path: Path,
        *,
        language: str,
        pages: list[int] | None = None,
        mode: str = "text",
    ) -> PdfScannerResult:
        try:
            pdf_bytes = b"" if self.use_source_path else pdf_path.read_bytes()
            response = self.stub.OcrPdf(
                pdf_scanner_pb2.OcrPdfRequest(
                    pdf=pdf_bytes,
                    filename=pdf_path.name,
                    language=language,
                    source_path=str(pdf_path) if self.use_source_path else "",
                    pages=pages or [],
                    mode=mode,
                ),
                timeout=self.timeout_seconds,
            )
        except OSError as exc:
            raise PdfScannerClientError(f"failed to read PDF for OCR: {pdf_path}") from exc
        except grpc.RpcError as exc:
            details = exc.details() or "PDF scanner service unreachable"
            raise PdfScannerClientError(details) from exc

        if mode != "text" and not response.pdf:
            raise PdfScannerClientError(response.message or "PDF scanner returned empty OCR result")
        if mode == "text" and not response.text and not response.page_texts:
            raise PdfScannerClientError(response.message or "PDF scanner returned empty OCR text")

        return PdfScannerResult(
            pdf=bytes(response.pdf),
            text=response.text,
            page_texts={page_text.page: page_text.text for page_text in response.page_texts},
            parser_name=response.parser_name,
            message=response.message,
            pages_processed=list(response.pages_processed),
            duration_ms=response.duration_ms,
            warnings=list(response.warnings),
        )

    def health(self) -> bool:
        try:
            response = self.stub.Health(pdf_scanner_pb2.HealthRequest(), timeout=10)
        except grpc.RpcError as exc:
            raise PdfScannerClientError(exc.details() or "PDF scanner service unreachable") from exc
        return response.status == "ok"
