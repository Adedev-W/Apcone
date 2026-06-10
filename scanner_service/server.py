from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
import time
from concurrent import futures
from pathlib import Path

import grpc

from app.proto import pdf_scanner_pb2, pdf_scanner_pb2_grpc


logger = logging.getLogger(__name__)


class ScannerRequestError(RuntimeError):
    def __init__(self, status_code: grpc.StatusCode, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


def _parse_pages(pages: list[int]) -> list[int]:
    return sorted({page for page in pages if page > 0})


def _format_pages(pages: list[int]) -> str:
    return ",".join(str(page) for page in _parse_pages(pages))


def _split_sidecar_text(text: str, pages: list[int]) -> list[tuple[int, str]]:
    normalized_pages = _parse_pages(pages)
    parts = [part.strip() for part in text.split("\f")]
    parts = [part for part in parts if part]
    if normalized_pages and len(parts) == len(normalized_pages):
        return list(zip(normalized_pages, parts, strict=True))
    if normalized_pages and len(parts) == 1:
        return [(normalized_pages[0], parts[0])]
    if normalized_pages:
        return [(page, parts[index] if index < len(parts) else "") for index, page in enumerate(normalized_pages)]
    return [(index + 1, part) for index, part in enumerate(parts)]


def build_ocrmypdf_command(
    *,
    input_path: Path,
    output_path: Path,
    sidecar_path: Path,
    language: str,
    pages: list[int],
    mode: str,
) -> list[str]:
    jobs = int(os.getenv("PDF_SCANNER_OCR_JOBS", "1"))
    timeout = int(os.getenv("PDF_SCANNER_TESSERACT_TIMEOUT", "180"))
    command = [
        "ocrmypdf",
        "--quiet",
        "-l",
        language,
        "--jobs",
        str(max(1, jobs)),
        "--tesseract-timeout",
        str(max(1, timeout)),
    ]
    if pages:
        command.extend(["--pages", _format_pages(pages)])

    if mode == "searchable_pdf":
        command.extend(["--skip-text", "--output-type", "pdf", "--optimize", "0"])
        command.extend([str(input_path), str(output_path)])
        return command

    if mode == "force_ocr_pdf":
        command.extend(["--force-ocr", "--output-type", "pdf", "--optimize", "0"])
        command.extend([str(input_path), str(output_path)])
        return command

    command.extend(["--skip-text", "--sidecar", str(sidecar_path), "--output-type", "none"])
    command.extend([str(input_path), "-"])
    return command


def _resolve_source_path(source_path: str) -> Path:
    allowed_dir = os.getenv("PDF_SCANNER_ALLOWED_DIR")
    if not allowed_dir:
        raise PermissionError("source_path OCR is disabled because PDF_SCANNER_ALLOWED_DIR is not configured")

    allowed_root = Path(allowed_dir).resolve()
    candidate = Path(source_path).resolve(strict=True)
    if allowed_root != candidate and allowed_root not in candidate.parents:
        raise PermissionError("source_path is outside PDF_SCANNER_ALLOWED_DIR")
    if not candidate.is_file():
        raise FileNotFoundError("source_path is not a file")
    return candidate


class PdfScannerService(pdf_scanner_pb2_grpc.PdfScannerServicer):
    def OcrPdf(self, request, context):
        try:
            if not request.pdf and not request.source_path:
                raise ScannerRequestError(grpc.StatusCode.INVALID_ARGUMENT, "PDF payload or source_path is required")

            language = request.language or os.getenv("PDF_SCANNER_LANGUAGE", "eng")
            filename = Path(request.filename or "upload.pdf").name
            pages = _parse_pages(list(request.pages))
            mode = request.mode or "text"
            if mode not in {"text", "searchable_pdf", "force_ocr_pdf"}:
                raise ScannerRequestError(grpc.StatusCode.INVALID_ARGUMENT, f"unsupported OCR mode: {mode}")

            with tempfile.TemporaryDirectory() as tmpdir:
                start = time.monotonic()
                if request.source_path:
                    try:
                        input_path = _resolve_source_path(request.source_path)
                    except PermissionError as exc:
                        raise ScannerRequestError(grpc.StatusCode.PERMISSION_DENIED, str(exc)) from exc
                    except FileNotFoundError as exc:
                        raise ScannerRequestError(grpc.StatusCode.INVALID_ARGUMENT, str(exc)) from exc
                else:
                    input_path = Path(tmpdir) / filename
                    input_path.write_bytes(request.pdf)

                output_path = Path(tmpdir) / f"{input_path.stem}.ocr.pdf"
                sidecar_path = Path(tmpdir) / f"{input_path.stem}.txt"

                completed = subprocess.run(
                    build_ocrmypdf_command(
                        input_path=input_path,
                        output_path=output_path,
                        sidecar_path=sidecar_path,
                        language=language,
                        pages=pages,
                        mode=mode,
                    ),
                    check=False,
                    capture_output=True,
                    text=True,
                )
                if completed.returncode != 0:
                    message = completed.stderr.strip() or completed.stdout.strip() or "OCR failed"
                    raise ScannerRequestError(grpc.StatusCode.INTERNAL, message)

                duration_ms = int((time.monotonic() - start) * 1000)
                text = sidecar_path.read_text(encoding="utf-8") if sidecar_path.exists() else ""
                page_texts = [
                    pdf_scanner_pb2.OcrPageText(page=page, text=page_text)
                    for page, page_text in _split_sidecar_text(text, pages)
                ]
                return pdf_scanner_pb2.OcrPdfResponse(
                    pdf=output_path.read_bytes() if output_path.exists() else b"",
                    parser_name="ocr",
                    message="ok",
                    text=text,
                    pages_processed=pages,
                    duration_ms=duration_ms,
                    warnings=[],
                    page_texts=page_texts,
                )
        except ScannerRequestError as exc:
            context.abort(exc.status_code, exc.message)
        except Exception as exc:
            logger.exception("PDF OCR failed")
            context.abort(grpc.StatusCode.INTERNAL, str(exc))

    def Health(self, request, context):
        missing = [
            binary
            for binary in ("ocrmypdf", "tesseract", "gs", "qpdf")
            if shutil.which(binary) is None
        ]
        if missing:
            return pdf_scanner_pb2.HealthResponse(
                status="error",
                message=f"missing binaries: {', '.join(missing)}",
            )
        return pdf_scanner_pb2.HealthResponse(status="ok", message="ready")


def main() -> None:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
    port = int(os.getenv("PDF_SCANNER_GRPC_PORT", "50051"))
    max_mb = int(os.getenv("PDF_SCANNER_MAX_MB", "100"))
    max_bytes = max_mb * 1024 * 1024
    server = grpc.server(
        futures.ThreadPoolExecutor(max_workers=int(os.getenv("PDF_SCANNER_WORKERS", "2"))),
        options=[
            ("grpc.max_send_message_length", max_bytes),
            ("grpc.max_receive_message_length", max_bytes),
        ],
    )
    pdf_scanner_pb2_grpc.add_PdfScannerServicer_to_server(PdfScannerService(), server)
    server.add_insecure_port(f"0.0.0.0:{port}")
    server.start()
    logger.info("PDF scanner gRPC service listening on %s", port)
    server.wait_for_termination()


if __name__ == "__main__":
    main()
