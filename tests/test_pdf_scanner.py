from __future__ import annotations

from pathlib import Path

from scanner_service.server import build_ocrmypdf_command


def test_build_text_only_ocr_command_uses_sidecar(monkeypatch):
    monkeypatch.setenv("PDF_SCANNER_OCR_JOBS", "2")
    monkeypatch.setenv("PDF_SCANNER_TESSERACT_TIMEOUT", "90")

    command = build_ocrmypdf_command(
        input_path=Path("/tmp/input.pdf"),
        output_path=Path("/tmp/output.pdf"),
        sidecar_path=Path("/tmp/output.txt"),
        language="eng",
        pages=[3, 1, 3],
        mode="text",
    )

    assert "--force-ocr" not in command
    assert "--skip-text" in command
    assert command[command.index("--pages") + 1] == "1,3"
    assert command[command.index("--sidecar") + 1] == "/tmp/output.txt"
    assert command[command.index("--output-type") + 1] == "none"
    assert command[-1] == "-"


def test_build_searchable_pdf_command_avoids_pdfa_conversion(monkeypatch):
    monkeypatch.delenv("PDF_SCANNER_OCR_JOBS", raising=False)
    monkeypatch.delenv("PDF_SCANNER_TESSERACT_TIMEOUT", raising=False)

    command = build_ocrmypdf_command(
        input_path=Path("/tmp/input.pdf"),
        output_path=Path("/tmp/output.pdf"),
        sidecar_path=Path("/tmp/output.txt"),
        language="eng",
        pages=[],
        mode="searchable_pdf",
    )

    assert "--force-ocr" not in command
    assert "--skip-text" in command
    assert command[command.index("--output-type") + 1] == "pdf"
    assert command[command.index("--optimize") + 1] == "0"
    assert command[-2:] == ["/tmp/input.pdf", "/tmp/output.pdf"]
