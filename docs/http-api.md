# HTTP API

Apcone exposes a small FastAPI surface for document storage, search, uploads,
jobs, and health checks. Document endpoints require an API key. Health endpoints
are public so load balancers and local scripts can check liveness.

Base URL in local development:

```text
http://127.0.0.1:8000
```

## Authentication

Use either bearer auth or `X-API-Key`:

```http
Authorization: Bearer <apcone_api_key>
X-API-Key: <apcone_api_key>
```

Create a key locally:

```bash
uv run python -m app.cli api-key create --name local-admin --tenant-id default --role admin
export APCONE_API_KEY=<api_key_from_create_output>
```

Roles:

| Role | Can do |
| --- | --- |
| `read` | List, get, chunk-read, search, and job-read. |
| `write` | Everything `read` can do, plus ingest, upload, and reindex. |
| `admin` | Everything `write` can do, plus delete. |

API keys are tenant-bound and can optionally be scope-bound. If a key has
`scope="project-x"`, requests for `scope="default"` are rejected.

## Tenant and Scope

Most endpoints accept or include:

```json
{
  "tenant_id": "default",
  "scope": "default"
}
```

The defaults are `default/default`. In multi-team deployments, always pass both
values explicitly so callers do not accidentally write to the default namespace.

## Health

### `GET /`

Returns the service name and a ready status.

```bash
curl http://127.0.0.1:8000/
```

### `GET /health`

Checks API process liveness.

```bash
curl http://127.0.0.1:8000/health
```

### `GET /health/postgres`

Runs `SELECT 1` against PostgreSQL.

### `GET /health/redis`

Runs `PING` against Redis.

### `GET /health/qdrant`

Checks Qdrant and returns the active collection name.

## Documents

### `GET /documents`

Lists document summaries in a tenant and scope.

```bash
curl "http://127.0.0.1:8000/documents?tenant_id=default&scope=default" \
  -H "Authorization: Bearer $APCONE_API_KEY"
```

Response:

```json
[
  {
    "id": "uuid",
    "tenant_id": "default",
    "scope": "default",
    "title": "Refund Policy",
    "source": "policy.md",
    "checksum": "sha256",
    "chunk_count": 2,
    "created_at": "2026-06-15T00:00:00Z",
    "updated_at": "2026-06-15T00:00:00Z"
  }
]
```

### `GET /documents/{document_id}`

Returns full stored document content and metadata.

```bash
curl "http://127.0.0.1:8000/documents/$DOCUMENT_ID?tenant_id=default&scope=default" \
  -H "Authorization: Bearer $APCONE_API_KEY"
```

Returns `404` when the document does not exist in that tenant and scope.

### `GET /documents/{document_id}/chunks`

Returns all chunks for a document in chunk order.

```bash
curl "http://127.0.0.1:8000/documents/$DOCUMENT_ID/chunks?tenant_id=default&scope=default" \
  -H "Authorization: Bearer $APCONE_API_KEY"
```

Use this when you need to inspect exactly what was embedded and searched.

## Text Ingestion

### `POST /documents/ingest`

Synchronously stores plain text, chunks it, embeds chunks, upserts vectors into
Qdrant, and creates an ingestion job record.

```bash
curl -X POST http://127.0.0.1:8000/documents/ingest \
  -H "Authorization: Bearer $APCONE_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "default",
    "scope": "default",
    "title": "Refund Policy",
    "content": "Customers can request refunds within 14 days.",
    "source": "policy.md",
    "metadata": {"team": "support"}
  }'
```

Response:

```json
{
  "job_id": "uuid",
  "document": {
    "id": "uuid",
    "tenant_id": "default",
    "scope": "default",
    "title": "Refund Policy",
    "source": "policy.md",
    "content": "Customers can request refunds within 14 days.",
    "checksum": "sha256",
    "metadata": {"team": "support"},
    "chunk_count": 1,
    "created_at": "2026-06-15T00:00:00Z",
    "updated_at": "2026-06-15T00:00:00Z"
  },
  "chunks_created": 1,
  "status": "completed"
}
```

If the same payload already exists in the same tenant and scope, Apcone returns
the existing document instead of creating a duplicate.

## File Uploads

### `POST /documents/upload`

Uploads a UTF-8 text file and ingests it synchronously.

```bash
curl -X POST http://127.0.0.1:8000/documents/upload \
  -H "Authorization: Bearer $APCONE_API_KEY" \
  -F title="Release Notes" \
  -F tenant_id="default" \
  -F scope="default" \
  -F source="release-notes.md" \
  -F content_file=@release-notes.md
```

PDF files are rejected here. Use `/documents/upload-document` for PDFs and
background processing.

### `POST /documents/upload-document`

Accepts a file, stores it, creates a pending job, and enqueues background
processing. This endpoint returns `202 Accepted`.

```bash
curl -X POST http://127.0.0.1:8000/documents/upload-document \
  -H "Authorization: Bearer $APCONE_API_KEY" \
  -F title="Vendor Contract" \
  -F tenant_id="default" \
  -F scope="default" \
  -F source="contract.pdf" \
  -F content_file=@contract.pdf
```

Response:

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

Run a worker for this job to finish:

```bash
uv run python -m app.workers.run_worker
```

Read [PDF ingestion](pdf-ingestion.md) for routing and OCR behavior.

## Search

### `POST /documents/search`

Searches embedded chunks inside a tenant and scope. The service combines Qdrant
vector search with a small PostgreSQL lexical fallback so exact terms can still
surface when vector ranking misses them.

```bash
curl -X POST http://127.0.0.1:8000/documents/search \
  -H "Authorization: Bearer $APCONE_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "default",
    "scope": "default",
    "query": "refund window",
    "top_k": 5,
    "source": "policy.md"
  }'
```

Optional filters:

| Field | Meaning |
| --- | --- |
| `top_k` | Result limit. Defaults to `SEARCH_TOP_K`; max is `50`. |
| `source` | Limit search to a source value. |
| `document_id` | Limit search to one document. |

## Jobs

### `GET /documents/jobs/{job_id}`

Returns ingestion job status and progress.

```bash
curl "http://127.0.0.1:8000/documents/jobs/$JOB_ID?tenant_id=default&scope=default" \
  -H "Authorization: Bearer $APCONE_API_KEY"
```

Common statuses are `pending`, `running`, `completed`, and `failed`.

## Maintenance

### `POST /documents/{document_id}/reindex`

Rebuilds vectors for an existing document using its stored chunks.

```bash
curl -X POST "http://127.0.0.1:8000/documents/$DOCUMENT_ID/reindex?tenant_id=default&scope=default" \
  -H "Authorization: Bearer $APCONE_API_KEY"
```

Use this after changing embedding configuration or repairing Qdrant data.

### `DELETE /documents/{document_id}`

Deletes a document and its vectors. Requires an `admin` key.

```bash
curl -X DELETE "http://127.0.0.1:8000/documents/$DOCUMENT_ID?tenant_id=default&scope=default" \
  -H "Authorization: Bearer $APCONE_API_KEY"
```

Successful deletes return `204 No Content`.

## Error Patterns

| Status | Typical cause |
| --- | --- |
| `400` | Invalid upload encoding or wrong upload endpoint for PDF. |
| `401` | Missing or invalid API key. |
| `403` | Role, tenant, or scope mismatch. |
| `404` | Document or job not found in the requested tenant/scope. |
| `413` | Uploaded file exceeds `PDF_MAX_MB`. |
| `503` | Background enqueue failed. |

FastAPI returns error details under the `detail` field. The Python SDK converts
HTTP failures into `ApconeAPIError`.
