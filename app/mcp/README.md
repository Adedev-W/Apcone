# Apcone MCP Module

This directory contains the FastMCP integration for Apcone's tenant-scoped RAG
tools. For the full user guide, read [../../docs/mcp.md](../../docs/mcp.md).

## Runtime Contract

`app/mcp/server.py` creates the MCP server and `app/main.py` mounts it at:

```text
/mcp/
```

Local URL:

```text
http://127.0.0.1:8000/mcp/
```

The transport is **Streamable HTTP** with stateless HTTP mode enabled. MCP
clients must send an Apcone API key as bearer auth:

```http
Authorization: Bearer <apcone_api_key>
```

The token verifier checks the key with `ApiKeyService` and exposes these claims
to tools:

```json
{
  "api_key_id": "uuid",
  "tenant_id": "default",
  "scope": "default",
  "role": "write"
}
```

Each tool enforces tenant, scope, and role before calling storage services.

## Registered Tools

| Tool | Required role | Purpose |
| --- | --- | --- |
| `health` | authenticated MCP call | Check database and Qdrant reachability. |
| `search_documents` | `read` | Search indexed document chunks in one tenant/scope. |
| `ingest_document` | `write` | Ingest small or already-extracted text synchronously. |
| `reindex_document` | `write` | Rebuild vectors for one stored document. |
| `delete_document` | `admin` | Delete one document and its vectors. |

The tools intentionally do not expose PDF upload, OCR, or queue management.
Those workflows remain in the HTTP API and worker stack.

## Local Key Setup

```bash
uv run python -m app.cli api-key create --name mcp-client --tenant-id default --role write
```

Use `admin` instead of `write` only when the client needs `delete_document`.

## Python SDK Example

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

## Data Flow

```text
MCP client
  -> /mcp/ Streamable HTTP
  -> ApiKeyTokenVerifier
  -> tool-level tenant/scope/role check
  -> RagStorageService
  -> PostgreSQL + Qdrant
  -> structured tool response
```

Tool errors are converted to stable `ToolError` messages with prefixes such as
`AUTHENTICATION_REQUIRED`, `AUTHORIZATION_ERROR`, `VALIDATION_ERROR`,
`DOCUMENT_NOT_FOUND`, `STORAGE_ERROR`, and `DEPENDENCY_ERROR`.

## Verification

The MCP contract is covered by:

```bash
uv run pytest tests/test_mcp.py
```

These tests verify that the MCP app is mounted, expected tools are registered,
tenant/scope tool schemas are correct, HTTP auth is enforced, and valid tenant
context can run a search tool.
