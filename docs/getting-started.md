# Getting Started

This guide starts Apcone locally and performs a real document ingest plus search.
It assumes a Linux/macOS shell, Docker, and Python 3.12.

## 1. Install Dependencies

Apcone uses `uv` for Python dependency management. From the repository root:

```bash
uv sync
cp .env.example .env
```

The `.env` file is read by `app.core.config.Settings`. Copying the example gives
you the documented local ports: PostgreSQL on `5433`, Redis on `6380`, Qdrant on
`6333`, and the PDF scanner on `50051`.

## 2. Start Backing Services

For text ingest and search, start PostgreSQL, Redis, and Qdrant:

```bash
docker compose up -d postgres redis qdrant
```

Redis is required by the broader upload/worker stack. Qdrant stores vectors.
PostgreSQL stores documents, chunks, API keys, and ingestion jobs.

Check service health:

```bash
docker compose ps
curl http://127.0.0.1:6333/healthz
```

## 3. Apply Database Migrations

```bash
uv run alembic upgrade head
```

Run this before creating API keys or ingesting documents. The migrations create
the RAG storage tables and API key tables used by the HTTP API and MCP tools.

## 4. Start the API

```bash
uv run uvicorn app.main:app --reload
```

The service is now available at `http://127.0.0.1:8000`.

Public health checks:

```bash
curl http://127.0.0.1:8000/
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/health/postgres
curl http://127.0.0.1:8000/health/redis
curl http://127.0.0.1:8000/health/qdrant
```

## 5. Create an API Key

Document APIs and MCP tools require an API key. For local development, create an
admin key:

```bash
uv run python -m app.cli api-key create --name local-admin --tenant-id default --role admin
export APCONE_API_KEY=<api_key_from_create_output>
```

Roles are hierarchical: `admin` can do everything, `write` can read and ingest,
and `read` can only read/search.

## 6. Ingest a Text Document

```bash
curl -X POST http://127.0.0.1:8000/documents/ingest \
  -H "Authorization: Bearer $APCONE_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "default",
    "scope": "default",
    "title": "Refund Policy",
    "content": "Customers can request refunds within 14 days of purchase.",
    "source": "policy.md",
    "metadata": {"team": "support"}
  }'
```

The response includes a `document.id`, an ingestion `job_id`, and the number of
chunks created.

## 7. Search the Knowledge Base

```bash
curl -X POST http://127.0.0.1:8000/documents/search \
  -H "Authorization: Bearer $APCONE_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "default",
    "scope": "default",
    "query": "how long is the refund window",
    "top_k": 3
  }'
```

Search returns chunk-level matches. Each result includes the document ID, title,
source, chunk index, content, score, and metadata.

## 8. Try the SDK

```python
import asyncio

from apcone_sdk import ApconeAsyncClient


async def main() -> None:
    async with ApconeAsyncClient("http://127.0.0.1:8000", "<apcone_api_key>") as client:
        results = await client.search_documents("refund window", top_k=3)
        for item in results:
            print(item.document_title, item.content)


asyncio.run(main())
```

## 9. Run the Worker for Uploads

Plain `/documents/ingest` is synchronous. File uploads through
`/documents/upload-document` create a job and require a worker:

```bash
uv run python -m app.workers.run_worker
```

For scanned PDFs, also start the scanner:

```bash
docker compose up -d pdf-scanner
```

Read [PDF ingestion](pdf-ingestion.md) before relying on PDF uploads in a real
workflow.

## Next Steps

Read [HTTP API](http-api.md) for endpoint details, [Python SDK](sdk.md) for
application integration, and [MCP tools](mcp.md) for agent integration.
