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
