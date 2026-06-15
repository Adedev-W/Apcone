# PDF and Background Ingestion

Apcone has two ingestion modes:

**Synchronous text ingestion** through `/documents/ingest` and
`/documents/upload`. This is best for small plain-text content.

**Background document ingestion** through `/documents/upload-document`. This is
the path for PDFs and larger uploaded text files. It creates an ingestion job,
stores the file, and uses Redis/RQ workers to profile, parse, OCR if needed, and
index the final text.

## Required Services

Start the core services:

```bash
docker compose up -d postgres redis qdrant
uv run alembic upgrade head
```

Start the API:

```bash
uv run uvicorn app.main:app --reload
```

Start a worker:

```bash
uv run python -m app.workers.run_worker
```

For scanned PDFs, start the scanner service:

```bash
docker compose up -d pdf-scanner
```

## Upload Flow

1. The API receives `/documents/upload-document`.
2. A pending ingestion job is created in PostgreSQL.
3. The uploaded file is saved under `UPLOAD_STORAGE_DIR`.
4. The API enqueues `process_uploaded_document` on the profile queue.
5. The worker profiles the file and routes it to the fast or OCR queue.
6. `process_profiled_document` extracts text, ingests it, updates vectors, and
   marks the job completed or failed.

This keeps expensive parsing and OCR out of the request/response path.

## Upload a PDF

```bash
curl -X POST http://127.0.0.1:8000/documents/upload-document \
  -H "Authorization: Bearer $APCONE_API_KEY" \
  -F title="Vendor Contract" \
  -F tenant_id="default" \
  -F scope="default" \
  -F source="contract.pdf" \
  -F content_file=@contract.pdf
```

The response is immediate:

```json
{
  "job_id": "uuid",
  "tenant_id": "default",
  "scope": "default",
  "status": "pending",
  "title": "Vendor Contract",
  "filename": "contract.pdf",
  "mime_type": "application/pdf",
  "parser_hint": "auto"
}
```

Poll the job:

```bash
curl "http://127.0.0.1:8000/documents/jobs/$JOB_ID?tenant_id=default&scope=default" \
  -H "Authorization: Bearer $APCONE_API_KEY"
```

## Parser Strategy

The worker profiles each PDF page with PyMuPDF:

| Signal | Meaning |
| --- | --- |
| Low text characters and images present | Page may be scanned. |
| Many drawings or detected tables | Page may need table-aware extraction. |
| Page count above `PDF_MAX_PAGES` | Job fails early. |

Strategy selection:

| Strategy | When used |
| --- | --- |
| `pymupdf` | Text PDF without scanned pages or table candidates. |
| `pdfplumber` | Text PDF with table/layout candidates. |
| `ocr_pages` | Scanned pages without table candidates. |
| `hybrid` | Mixed scanned/table candidate content. |
| `text` | Uploaded `.txt`, `.md`, `.rst`, or `text/*` files. |

Only scanned pages are sent to OCR. Text pages are parsed locally.

## OCR Scanner

The scanner runs as a separate gRPC service because OCR can be CPU-heavy and has
different runtime dependencies. The worker calls `PDF_SCANNER_GRPC_URL`.

Default local target:

```text
127.0.0.1:50051
```

The scanner supports two transfer modes:

| Mode | Setting | Behavior |
| --- | --- | --- |
| Bytes mode | `PDF_SCANNER_USE_SOURCE_PATH=false` | Worker reads the PDF and sends bytes over gRPC. |
| Source-path mode | `PDF_SCANNER_USE_SOURCE_PATH=true` | Worker sends a file path; scanner reads from shared mounted storage. |

Use source-path mode only when the scanner container can access the same upload
directory. Docker Compose mounts `./storage/uploads` to `/storage/uploads`.

## Queues

The worker listens to:

```text
pdf_profile
pdf_ingest_fast
pdf_ingest_ocr
pdf_ingest
```

The profile queue decides where work goes. Fast jobs avoid OCR. OCR jobs should
be scaled based on CPU capacity, not HTTP traffic volume.

## Important Limits

| Setting | Default | Why it matters |
| --- | --- | --- |
| `PDF_MAX_MB` | `100` | API rejects uploads above this size. |
| `PDF_MAX_PAGES` | `500` | Profiler rejects very large PDFs. |
| `PDF_JOB_TIMEOUT_SECONDS` | `1800` | RQ job timeout. |
| `PDF_SCANNER_TIMEOUT_SECONDS` | `300` | Worker gRPC call timeout. |
| `PDF_SCANNER_OCR_JOBS` | `1` | OCR parallelism. Increase carefully. |

For RAG, Apcone defaults to text-only OCR extraction. Generating searchable OCR
PDF artifacts should be treated as a separate heavier workflow.

## Common Failures

**Job stays `pending`**: no worker is running, Redis is unreachable, or the
worker is listening to different queue names.

**Job fails with scanner unreachable**: start `pdf-scanner`, verify
`PDF_SCANNER_GRPC_URL`, and check container logs.

**Upload returns `413`**: file exceeds `PDF_MAX_MB`.

**Job fails on page count**: PDF exceeds `PDF_MAX_PAGES`.

**Empty OCR text**: scanned PDF may need a different `PDF_SCANNER_LANGUAGE`, or
the source scan quality may be too low for OCR.

## Verifying the Result

After a job completes, search for content from the uploaded document:

```bash
curl -X POST http://127.0.0.1:8000/documents/search \
  -H "Authorization: Bearer $APCONE_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"query": "a phrase from the PDF", "top_k": 5}'
```

If results are missing, inspect chunks:

```bash
curl "http://127.0.0.1:8000/documents/$DOCUMENT_ID/chunks?tenant_id=default&scope=default" \
  -H "Authorization: Bearer $APCONE_API_KEY"
```
