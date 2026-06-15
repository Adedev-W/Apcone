# apcone

Minimal FastAPI service with PostgreSQL, Redis, and Qdrant.

## Setup

```bash
uv sync
docker compose up -d 
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

API key auth:

```bash
uv run python -m app.cli api-key create --name local-admin --tenant-id default --role admin
export APCONE_API_KEY=<api_key_from_create_output>
```

Document APIs and MCP require an API key. Use either
`Authorization: Bearer $APCONE_API_KEY` or `X-API-Key: $APCONE_API_KEY`.
The root endpoint and health endpoints stay public for liveness checks.

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

Document APIs and MCP tools support tenant-scoped knowledge namespaces with
`tenant_id` and `scope`. Existing calls default to `tenant_id=default` and
`scope=default`; pass explicit values when multiple teams, projects, or agent
workspaces share the same Apcone service.

Search combines Qdrant vector retrieval with a small PostgreSQL lexical fallback
inside the same tenant and scope. This keeps exact keyword matches discoverable
when vector ranking misses a chunk.

CLI:

```bash
uv run python -m app.cli health
uv run python -m app.cli api-key list
uv run python -m app.cli documents list --tenant-id default --scope default
uv run python -m app.cli jobs list --tenant-id default --scope default
```

Worker:

```bash
uv run python -m app.workers.run_worker
```

The worker uses a short RQ heartbeat/dequeue cycle by default
(`RQ_WORKER_TTL_SECONDS=120`) so an idle queue does not leave a Redis blocking
read open long enough to be closed by the connection path. Redis client
timeouts can be tuned with `REDIS_SOCKET_TIMEOUT_SECONDS`,
`REDIS_SOCKET_CONNECT_TIMEOUT_SECONDS`, and
`REDIS_HEALTH_CHECK_INTERVAL_SECONDS`.

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

The title submitted to `/documents/upload-document` is stored on the ingestion
job and used as the final document title when the worker finishes processing.

For high traffic, run more `app.workers.run_worker` processes for regular parsing, but keep OCR capacity near available CPU with `PDF_SCANNER_WORKERS` and `PDF_SCANNER_OCR_JOBS`. Text-only OCR is the default path for RAG indexing; searchable OCR PDF generation should be treated as a separate heavy operation.
If `PDF_SCANNER_USE_SOURCE_PATH=true`, mount the upload storage into the scanner container and set `PDF_SCANNER_ALLOWED_DIR` to that mounted directory.
