from __future__ import annotations

from pathlib import Path

import grpc

from app.proto import pdf_scanner_pb2, pdf_scanner_pb2_grpc


class PdfScannerClientError(RuntimeError):
    pass


class PdfScannerClient:
    def __init__(
        self,
        *,
        target: str,
        max_message_mb: int,
        timeout_seconds: int = 300,
    ) -> None:
        max_message_bytes = max_message_mb * 1024 * 1024
        options = [
            ("grpc.max_send_message_length", max_message_bytes),
            ("grpc.max_receive_message_length", max_message_bytes),
        ]
        self.target = target
        self.timeout_seconds = timeout_seconds
        self.channel = grpc.insecure_channel(target, options=options)
        self.stub = pdf_scanner_pb2_grpc.PdfScannerStub(self.channel)

    def ocr_pdf(self, pdf_path: Path, *, language: str) -> bytes:
        try:
            response = self.stub.OcrPdf(
                pdf_scanner_pb2.OcrPdfRequest(
                    pdf=pdf_path.read_bytes(),
                    filename=pdf_path.name,
                    language=language,
                ),
                timeout=self.timeout_seconds,
            )
        except OSError as exc:
            raise PdfScannerClientError(f"failed to read PDF for OCR: {pdf_path}") from exc
        except grpc.RpcError as exc:
            details = exc.details() or "PDF scanner service unreachable"
            raise PdfScannerClientError(details) from exc

        if not response.pdf:
            raise PdfScannerClientError(response.message or "PDF scanner returned empty OCR result")
        return bytes(response.pdf)

    def health(self) -> bool:
        try:
            response = self.stub.Health(pdf_scanner_pb2.HealthRequest(), timeout=10)
        except grpc.RpcError as exc:
            raise PdfScannerClientError(exc.details() or "PDF scanner service unreachable") from exc
        return response.status == "ok"
