from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
from concurrent import futures
from pathlib import Path

import grpc

from app.proto import pdf_scanner_pb2, pdf_scanner_pb2_grpc


logger = logging.getLogger(__name__)


class PdfScannerService(pdf_scanner_pb2_grpc.PdfScannerServicer):
    def OcrPdf(self, request, context):
        if not request.pdf:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "PDF payload is empty")

        language = request.language or os.getenv("PDF_SCANNER_LANGUAGE", "eng")
        filename = Path(request.filename or "upload.pdf").name

        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                input_path = Path(tmpdir) / filename
                output_path = Path(tmpdir) / f"{input_path.stem}.ocr.pdf"
                input_path.write_bytes(request.pdf)

                completed = subprocess.run(
                    [
                        "ocrmypdf",
                        "--force-ocr",
                        "--quiet",
                        "-l",
                        language,
                        str(input_path),
                        str(output_path),
                    ],
                    check=False,
                    capture_output=True,
                    text=True,
                )
                if completed.returncode != 0:
                    message = completed.stderr.strip() or completed.stdout.strip() or "OCR failed"
                    context.abort(grpc.StatusCode.INTERNAL, message)

                return pdf_scanner_pb2.OcrPdfResponse(
                    pdf=output_path.read_bytes(),
                    parser_name="ocr",
                    message="ok",
                )
        except grpc.RpcError:
            raise
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
