# Configuration

Apcone loads configuration with Pydantic Settings from environment variables and
the repository `.env` file. The defaults are designed for local development, but
production deployments should set explicit values instead of relying on checked
examples.

## Files and Loading Order

`app.core.config.Settings` reads `.env` from the repository root and ignores
unknown keys. A typical setup is:

```bash
cp .env.example .env
```

Then edit `.env` for your local ports, credentials, model choice, storage path,
and scanner settings.

## Core Settings

| Variable | Default | Purpose |
| --- | --- | --- |
| `APP_NAME` | `apcone` | FastAPI application name and root service label. |
| `DATABASE_URL` | `postgresql+psycopg://apcone:apcone_password@localhost:5433/apcone` | SQLAlchemy database URL for documents, chunks, jobs, and API keys. |
| `REDIS_URL` | `redis://localhost:6380/0` | Redis connection used by RQ queues. |
| `UPLOAD_STORAGE_DIR` | `storage/uploads` | Local directory where uploaded files are stored before worker processing. |

The Docker Compose file binds services to `127.0.0.1` so they are reachable
from the host but not exposed publicly by default.

## PostgreSQL

| Variable | Example | Notes |
| --- | --- | --- |
| `POSTGRES_USER` | `apcone` | Used by the Docker container. |
| `POSTGRES_PASSWORD` | `apcone_password` | Local development password. Replace outside dev. |
| `POSTGRES_DB` | `apcone` | Database name. |
| `POSTGRES_PORT` | `5433` | Host port from `.env.example`; Docker's fallback is `5432` if no `.env` exists. |

After changing database settings, rerun migrations:

```bash
uv run alembic upgrade head
```

## Redis and Queues

| Variable | Default | Purpose |
| --- | --- | --- |
| `REDIS_SOCKET_TIMEOUT_SECONDS` | `5` | Socket read timeout. |
| `REDIS_SOCKET_CONNECT_TIMEOUT_SECONDS` | `5` | Socket connect timeout. |
| `REDIS_HEALTH_CHECK_INTERVAL_SECONDS` | `30` | Redis keepalive health check interval. |
| `PDF_QUEUE_NAME` | `pdf_ingest` | Legacy/general PDF queue name included in worker queue list. |
| `PDF_PROFILE_QUEUE_NAME` | `pdf_profile` | Queue that profiles uploads and routes work. |
| `PDF_FAST_QUEUE_NAME` | `pdf_ingest_fast` | Queue for text PDFs and non-OCR extraction. |
| `PDF_OCR_QUEUE_NAME` | `pdf_ingest_ocr` | Queue for scanned or OCR-required documents. |
| `RQ_WORKER_TTL_SECONDS` | `120` | Worker heartbeat/dequeue TTL. |

`app.workers.run_worker` listens to the configured queues in this order:
profile, fast, OCR, and general. Duplicate queue names are removed while keeping
the first occurrence.

## Qdrant and Embeddings

| Variable | Default | Purpose |
| --- | --- | --- |
| `QDRANT_URL` | `http://localhost:6333` | Qdrant HTTP endpoint used by the Python client. |
| `QDRANT_HTTP_PORT` | `6333` | Host HTTP/UI port for Docker Compose. |
| `QDRANT_GRPC_PORT` | `6334` | Host gRPC port for Docker Compose. |
| `QDRANT_COLLECTION` | `rag_chunks` | Collection where chunk vectors are stored. |
| `EMBEDDING_MODEL` | `BAAI/bge-small-en-v1.5` | FastEmbed model used for chunk and query embeddings. |
| `CHUNK_SIZE` | `1000` | Target maximum text size per chunk. Minimum is `200`. |
| `CHUNK_OVERLAP` | `150` | Character overlap between neighboring chunks. |
| `SEARCH_TOP_K` | `5` | Default search limit when clients omit `top_k`. Maximum request value is `50`. |

If you change the embedding model and its vector dimension changes, reindex
documents so Qdrant contains vectors built with the current model.

## PDF Upload Limits

| Variable | Default | Purpose |
| --- | --- | --- |
| `PDF_JOB_TIMEOUT_SECONDS` | `1800` | RQ timeout for PDF jobs. |
| `PDF_RESULT_TTL_SECONDS` | `3600` | How long Redis keeps completed job results. |
| `PDF_MAX_MB` | `100` | HTTP upload size limit for background document upload. |
| `PDF_MAX_PAGES` | `500` | Maximum PDF page count accepted by the profiler. |
| `PDF_TEXT_THRESHOLD` | `80` | Page text threshold below which image-heavy pages may be treated as scanned. |
| `PDF_IMAGE_THRESHOLD` | `1` | Minimum image count used in scanned-page detection. |

These settings protect the API and worker from unexpectedly large documents.
For production, tune them based on CPU, memory, OCR throughput, and user needs.

## PDF Scanner

| Variable | Default | Purpose |
| --- | --- | --- |
| `PDF_SCANNER_GRPC_URL` | `127.0.0.1:50051` | gRPC target used by the worker. |
| `PDF_SCANNER_LANGUAGE` | `eng` | OCR language passed to the scanner. |
| `PDF_SCANNER_MAX_MB` | `100` | Max scanner gRPC message size. |
| `PDF_SCANNER_TIMEOUT_SECONDS` | `300` | Worker-side scanner call timeout. |
| `PDF_SCANNER_USE_SOURCE_PATH` | `false` | Send a source path instead of PDF bytes when scanner shares storage. |
| `PDF_SCANNER_ALLOWED_DIR` | `/storage/uploads` | Directory mounted into scanner for source-path mode. |
| `PDF_SCANNER_WORKERS` | `2` | Scanner service worker count. |
| `PDF_SCANNER_OCR_JOBS` | `1` | OCR parallelism inside scanner. |
| `PDF_SCANNER_TESSERACT_TIMEOUT` | `180` | Scanner-side OCR timeout. |

Use source-path mode only when both the API/worker and scanner can see the same
upload storage path. The Docker Compose scanner mounts `./storage/uploads` to
`/storage/uploads`.

## Tenant and Scope Rules

`tenant_id` and `scope` are validated with this pattern:

```text
^[A-Za-z0-9_.:-]+$
```

Both values must be 1 to 80 characters. Use one stable `tenant_id` per customer,
team, or workspace. Use `scope` for a namespace inside that tenant, such as
`default`, `project-x`, or `prod`.
