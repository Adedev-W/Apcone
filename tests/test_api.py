from __future__ import annotations

from pathlib import Path

import fitz


class FakeQueue:
    def __init__(self) -> None:
        self.enqueued = []

    def enqueue(self, func, *args, **kwargs):
        self.enqueued.append((func, args, kwargs))
        return object()


def _make_pdf(path: Path, text: str) -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), text)
    pdf_bytes = doc.tobytes()
    path.write_bytes(pdf_bytes)
    return pdf_bytes


def test_api_ingest_search_delete_roundtrip(client):
    ingest_response = client.post(
        "/documents/ingest",
        json={
            "title": "API Notes",
            "content": "RAG storage needs chunks embeddings and Qdrant search.",
            "source": "api.md",
            "metadata": {"kind": "note"},
        },
    )
    assert ingest_response.status_code == 201

    payload = ingest_response.json()
    document_id = payload["document"]["id"]

    search_response = client.post(
        "/documents/search",
        json={"query": "Qdrant search", "top_k": 3},
    )
    assert search_response.status_code == 200
    results = search_response.json()
    assert results
    assert results[0]["document_id"] == document_id

    get_response = client.get(f"/documents/{document_id}")
    assert get_response.status_code == 200
    assert get_response.json()["title"] == "API Notes"

    delete_response = client.delete(f"/documents/{document_id}")
    assert delete_response.status_code == 204

    missing_response = client.get(f"/documents/{document_id}")
    assert missing_response.status_code == 404


def test_api_pdf_upload_enqueues_background_job(client, monkeypatch, tmp_path):
    from app.routers import documents as documents_router

    fake_queue = FakeQueue()
    monkeypatch.setattr(documents_router, "get_pdf_profile_queue", lambda settings: fake_queue)

    pdf_path = tmp_path / "sample.pdf"
    _make_pdf(pdf_path, "PDF upload should be queued")

    with pdf_path.open("rb") as handle:
        response = client.post(
            "/documents/upload-document",
            data={"title": "Sample PDF", "source": "paper.pdf"},
            files={"content_file": ("sample.pdf", handle, "application/pdf")},
        )

    assert response.status_code == 202
    payload = response.json()
    assert payload["status"] == "pending"
    assert payload["parser_hint"] == "auto"
    assert fake_queue.enqueued
    assert fake_queue.enqueued[0][1][0]
