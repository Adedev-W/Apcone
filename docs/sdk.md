# Python SDK

Apcone ships an async Python SDK in the `apcone_sdk` package. It is intentionally
thin: the SDK does not hide service behavior, it gives Python callers typed
methods, lifecycle management, auth headers, and consistent errors.

## Clients

| Client | Use it for |
| --- | --- |
| `ApconeAsyncClient` | Direct HTTP API calls from an application, job, script, or test. |
| `ApconeMCPClient` | Calling Apcone's MCP tools from Python code. |

Both clients default to `tenant_id="default"` and `scope="default"`.

## HTTP SDK Quick Start

```python
import asyncio

from apcone_sdk import ApconeAsyncClient


async def main() -> None:
    async with ApconeAsyncClient(
        "http://127.0.0.1:8000",
        "<apcone_api_key>",
        tenant_id="default",
        scope="default",
    ) as client:
        created = await client.ingest_document(
            title="SDK note",
            content="Apcone can search tenant-scoped documents.",
            source="sdk-example",
            metadata={"kind": "note"},
        )
        results = await client.search_documents("tenant-scoped search", top_k=3)
        print(created.document.id, results[0].content)


asyncio.run(main())
```

Use `async with` unless you inject your own `httpx.AsyncClient`. It closes the
underlying HTTP client when the block exits.

## HTTP SDK Methods

| Method | Returns | API endpoint |
| --- | --- | --- |
| `health()` | `Health` | `GET /health` |
| `health_postgres()` | `Health` | `GET /health/postgres` |
| `health_redis()` | `Health` | `GET /health/redis` |
| `health_qdrant()` | `Health` | `GET /health/qdrant` |
| `list_documents()` | `list[DocumentSummary]` | `GET /documents` |
| `get_document(document_id)` | `Document` | `GET /documents/{document_id}` |
| `get_chunks(document_id)` | `list[Chunk]` | `GET /documents/{document_id}/chunks` |
| `ingest_document(...)` | `IngestResponse` | `POST /documents/ingest` |
| `upload_text_file(...)` | `IngestResponse` | `POST /documents/upload` |
| `upload_document_file(...)` | `UploadAccepted` | `POST /documents/upload-document` |
| `search_documents(...)` | `list[SearchResult]` | `POST /documents/search` |
| `get_job(job_id)` | `IngestionJob` | `GET /documents/jobs/{job_id}` |
| `reindex_document(document_id)` | `IngestResponse` | `POST /documents/{document_id}/reindex` |
| `delete_document(document_id)` | `None` | `DELETE /documents/{document_id}` |

## Upload Example

```python
import asyncio

from apcone_sdk import ApconeAsyncClient


async def main() -> None:
    async with ApconeAsyncClient("http://127.0.0.1:8000", "<apcone_api_key>") as client:
        accepted = await client.upload_document_file(
            "contract.pdf",
            title="Vendor Contract",
            source="contract.pdf",
        )
        print(accepted.job_id, accepted.status)

        job = await client.get_job(accepted.job_id)
        print(job.status, job.progress)


asyncio.run(main())
```

`upload_document_file` creates a background job. A running worker is required for
the job to become `completed`.

## Error Handling

```python
from apcone_sdk import ApconeAPIError

try:
    results = await client.search_documents("refund policy")
except ApconeAPIError as exc:
    print(exc.status_code)
    print(exc.detail)
```

`ApconeAPIError` is raised for HTTP errors and network failures. For HTTP
responses, `status_code` and parsed FastAPI `detail` are available.

## Custom HTTP Client

Use a custom `httpx.AsyncClient` when you need a special transport, test ASGI
transport, proxies, tracing, or shared connection pools:

```python
import httpx

from apcone_sdk import ApconeAsyncClient

async with httpx.AsyncClient(base_url="http://127.0.0.1:8000") as http_client:
    sdk = ApconeAsyncClient(
        "http://127.0.0.1:8000",
        "<apcone_api_key>",
        http_client=http_client,
    )
    health = await sdk.health()
```

When you pass `http_client`, you own its lifecycle.

## MCP SDK Quick Start

```python
import asyncio

from apcone_sdk import ApconeMCPClient


async def main() -> None:
    client = ApconeMCPClient.from_base_url(
        "http://127.0.0.1:8000",
        "<apcone_api_key>",
        tenant_id="default",
        scope="default",
    )
    results = await client.search_documents("refund policy", top_k=3)
    print(results.result_count)


asyncio.run(main())
```

`from_base_url()` appends `/mcp/` for you. If you already have the exact MCP URL,
instantiate `ApconeMCPClient("http://127.0.0.1:8000/mcp/", api_key)`.

## MCP SDK Methods

| Method | MCP tool | Returns |
| --- | --- | --- |
| `health()` | `health` | `Health` |
| `search_documents(...)` | `search_documents` | `MCPSearchResponse` |
| `ingest_document(...)` | `ingest_document` | `IngestResponse` |
| `reindex_document(document_id)` | `reindex_document` | `MCPReindexResponse` |
| `delete_document(document_id)` | `delete_document` | `MCPDeleteResponse` |

MCP errors become `ApconeMCPError` and include the tool name.

## Testing Pattern

The SDK tests use `httpx.ASGITransport` for HTTP calls and an in-memory FastMCP
server transport for MCP calls. That keeps tests deterministic and avoids a live
network server.

Run them with:

```bash
uv run pytest tests/test_sdk.py
```
