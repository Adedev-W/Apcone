# Operations

This guide focuses on running Apcone locally or in a small internal deployment.
It covers health checks, worker behavior, common failures, and practical tuning
points.

## Start Order

For the full stack:

```bash
docker compose up -d postgres redis qdrant pdf-scanner
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
uv run python -m app.workers.run_worker
```

For text-only API development, `pdf-scanner` and the worker are optional until
you use `/documents/upload-document`.

## Health Checks

API process:

```bash
curl http://127.0.0.1:8000/health
```

PostgreSQL:

```bash
curl http://127.0.0.1:8000/health/postgres
```

Redis:

```bash
curl http://127.0.0.1:8000/health/redis
```

Qdrant:

```bash
curl http://127.0.0.1:8000/health/qdrant
curl http://127.0.0.1:6333/healthz
```

MCP dependencies:

```python
from apcone_sdk import ApconeMCPClient

client = ApconeMCPClient.from_base_url("http://127.0.0.1:8000", "<api_key>")
health = await client.health()
```

## Logs to Watch

| Component | What to inspect |
| --- | --- |
| FastAPI | Request failures, auth errors, upload rejection, enqueue failures. |
| Worker | Job routing, PDF parser errors, scanner errors, timeout errors. |
| PostgreSQL | Connection failures and migration mismatch. |
| Redis | Queue connectivity and worker heartbeats. |
| Qdrant | Collection creation, vector dimension mismatch, search availability. |
| PDF scanner | OCR runtime errors, language issues, timeout errors. |

For Docker services:

```bash
docker compose logs -f postgres redis qdrant pdf-scanner
```

## Common Problems

**`401 api key required`** means no API key reached a protected endpoint. Send
`Authorization: Bearer <key>` or `X-API-Key: <key>`.

**`403 api key cannot access this tenant`** means the key's `tenant_id` differs
from the request. Create a key for the right tenant or change the request.

**`403 api key cannot access this scope`** means the key is scope-bound and the
request uses another scope.

**`403 insufficient api key role`** means the key role is too low. Use `write`
for ingest/reindex and `admin` for delete.

**`document not found`** is tenant/scope-aware. A document in another tenant or
scope is treated as missing.

**Upload job never completes** usually means the worker is not running, Redis is
unreachable, or the job failed. Check `/documents/jobs/{job_id}` and worker logs.

**Qdrant vector dimension errors** can happen after changing the embedding model.
Use a compatible collection or reindex after aligning model and collection.

## Performance Notes

Start with the defaults. Tune only after measuring a real bottleneck.

| Bottleneck | First checks |
| --- | --- |
| Slow search | Qdrant health, embedding latency, `top_k`, collection size, exact source/document filters. |
| Slow ingest | Embedding model speed, chunk count, Qdrant upsert latency, PostgreSQL commit time. |
| Slow PDF jobs | Page count, OCR pages, scanner CPU, `PDF_SCANNER_OCR_JOBS`, worker count. |
| Redis disconnects | Socket timeout, health check interval, worker TTL, network path. |

For high upload volume, run more worker processes for regular parsing. Keep OCR
parallelism close to available CPU capacity; OCR scales differently from normal
text extraction.

## Backups and Data

Apcone stores durable data in:

| Store | Data |
| --- | --- |
| PostgreSQL | API keys, documents, chunks, jobs, checksums, metadata. |
| Qdrant | Chunk vectors and search payloads. |
| File storage | Uploaded files waiting for or used by background jobs. |
| Redis | Queue state and short-lived job results. |

Back up PostgreSQL and Qdrant together if you need point-in-time consistency
between document metadata and vectors.

## Deployment Notes

The repository is optimized for a small service, not a complex platform. Keep
the deployment simple:

1. One FastAPI process or a small replica set.
2. One PostgreSQL database.
3. One Redis instance for RQ.
4. One Qdrant instance or managed Qdrant endpoint.
5. Worker processes sized separately from API traffic.
6. Scanner capacity sized by CPU and OCR workload.

Do not expose local Docker ports publicly without network controls and secret
management. API keys are application credentials and should be treated like
passwords.
