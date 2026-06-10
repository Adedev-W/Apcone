# apcone

Minimal FastAPI service with PostgreSQL, Redis, and Qdrant.

## Setup

```bash
uv sync
docker compose up -d postgres redis qdrant
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```

The default host ports are `5433` for PostgreSQL, `6380` for Redis, `6333` for Qdrant HTTP/UI, and `6334` for Qdrant gRPC.

RAG defaults:

- `QDRANT_COLLECTION=rag_chunks`
- `EMBEDDING_MODEL=BAAI/bge-small-en-v1.5`
- `CHUNK_SIZE=1000`
- `CHUNK_OVERLAP=150`
- `SEARCH_TOP_K=5`

Health checks:

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/health/postgres
curl http://127.0.0.1:8000/health/redis
```

Qdrant checks:

```bash
curl http://127.0.0.1:6333/healthz
curl http://127.0.0.1:6333
```

Qdrant dashboard is available at `http://127.0.0.1:6333/dashboard`.

Core endpoints:

- `POST /documents/ingest`
- `POST /documents/upload`
- `POST /documents/upload-document`
- `POST /documents/search`
- `GET /documents/jobs/{job_id}`
- `GET /documents/{document_id}`
- `GET /documents/{document_id}/chunks`
- `POST /documents/{document_id}/reindex`
- `DELETE /documents/{document_id}`

Worker:

```bash
uv run python -m app.workers.run_worker
```

PDF OCR fallback runs through the Alpine-based gRPC scanner service:

```bash
docker compose up -d pdf-scanner
```

The worker calls `PDF_SCANNER_GRPC_URL`, which defaults to `127.0.0.1:50051`.
`PDF_RESULT_TTL_SECONDS` only controls how long Redis keeps a completed job result; it is not scan duration.

PDF ingestion profiles each document before choosing a parser:

- simple text PDF: PyMuPDF
- table/layout candidate: pdfplumber for the candidate pages
- scanned or mixed PDF: OCRmyPDF only for detected scanned pages

For high traffic, run more `app.workers.run_worker` processes for regular parsing, but keep OCR capacity near available CPU with `PDF_SCANNER_WORKERS` and `PDF_SCANNER_OCR_JOBS`. Text-only OCR is the default path for RAG indexing; searchable OCR PDF generation should be treated as a separate heavy operation.
If `PDF_SCANNER_USE_SOURCE_PATH=true`, mount the upload storage into the scanner container and set `PDF_SCANNER_ALLOWED_DIR` to that mounted directory.
