# MCP Tools

Apcone exposes agent-facing knowledge tools through the Model Context Protocol
using FastMCP. The MCP server is mounted into the FastAPI app at:

```text
http://127.0.0.1:8000/mcp/
```

The transport is **Streamable HTTP** in stateless mode. Stateless HTTP is a good
fit for API deployments because clients do not depend on one long-lived in-memory
server session.

## Authentication

MCP clients must send a valid Apcone API key as a bearer token:

```http
Authorization: Bearer <apcone_api_key>
```

Create a key:

```bash
uv run python -m app.cli api-key create --name mcp-client --tenant-id default --role write
```

The MCP token verifier loads the API key from PostgreSQL and exposes claims to
tools:

```json
{
  "api_key_id": "uuid",
  "tenant_id": "default",
  "scope": "default",
  "role": "write"
}
```

Each tool checks tenant, scope, and role before touching storage.

## Available Tools

| Tool | Role | Behavior |
| --- | --- | --- |
| `health` | none beyond valid MCP setup | Checks database and Qdrant reachability. |
| `search_documents` | `read` | Searches chunks in one tenant and scope. |
| `ingest_document` | `write` | Ingests plain text synchronously. |
| `reindex_document` | `write` | Rebuilds vectors for one document. |
| `delete_document` | `admin` | Deletes one document and its vectors. |

## `health`

Checks the dependencies used by the MCP tools.

Input:

```json
{}
```

Output:

```json
{
  "status": "ok",
  "details": {
    "database": "reachable",
    "qdrant": "reachable",
    "collection": "rag_chunks"
  }
}
```

Use this before agent workflows that depend on search or ingestion.

## `search_documents`

Searches indexed document chunks.

Input:

```json
{
  "tenant_id": "default",
  "scope": "default",
  "query": "refund policy",
  "top_k": 5,
  "source": "policy.md",
  "document_id": null
}
```

Required fields are `tenant_id` and `query`. `scope` defaults to `default`.
`source` and `document_id` are optional filters.

Output:

```json
{
  "status": "ok",
  "tenant_id": "default",
  "scope": "default",
  "query": "refund policy",
  "top_k": 5,
  "result_count": 1,
  "results": [
    {
      "chunk_id": "uuid",
      "document_id": "uuid",
      "tenant_id": "default",
      "scope": "default",
      "document_title": "Refund Policy",
      "source": "policy.md",
      "chunk_index": 0,
      "content": "matching chunk text",
      "score": 0.82,
      "metadata": {}
    }
  ]
}
```

Tool annotations mark this as read-only, idempotent, non-destructive, and not
open-world. Agents should use it when they need evidence from already-ingested
knowledge.

## `ingest_document`

Adds plain text knowledge to one tenant and scope.

Input:

```json
{
  "tenant_id": "default",
  "scope": "default",
  "title": "Refund Policy",
  "content": "Refunds are available within 14 days.",
  "source": "policy.md",
  "metadata": {"team": "support"}
}
```

Output:

```json
{
  "status": "completed",
  "tenant_id": "default",
  "scope": "default",
  "job_id": "uuid",
  "chunks_created": 1,
  "document": {
    "id": "uuid",
    "title": "Refund Policy",
    "content": "Refunds are available within 14 days."
  }
}
```

This tool is synchronous and intended for small or already-extracted text. It
does not upload PDFs, perform OCR, or manage Redis jobs.

## `reindex_document`

Rebuilds Qdrant vectors for one existing document.

Input:

```json
{
  "tenant_id": "default",
  "scope": "default",
  "document_id": "uuid"
}
```

Output:

```json
{
  "status": "completed",
  "tenant_id": "default",
  "scope": "default",
  "job_id": "uuid",
  "chunks_created": 3,
  "document_id": "uuid"
}
```

Use this after vector-store repair or embedding model changes. The document must
exist in the requested tenant and scope.

## `delete_document`

Deletes a document and its vectors. This is the destructive MCP tool and requires
an admin key.

Input:

```json
{
  "tenant_id": "default",
  "scope": "default",
  "document_id": "uuid"
}
```

Output:

```json
{
  "status": "deleted",
  "tenant_id": "default",
  "scope": "default",
  "document_id": "uuid"
}
```

The delete behavior is idempotent from the caller perspective. If the document
does not exist in the tenant/scope, the tool still returns `deleted`.

## Python MCP SDK

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

The SDK sends the API key as bearer auth for HTTP MCP transports and returns
Pydantic models for structured content.

## Framework Client Notes

Configure framework clients for Streamable HTTP. The exact option name depends
on the framework, but the important values are:

```text
transport = streamable-http
url = http://127.0.0.1:8000/mcp/
authorization = Bearer <apcone_api_key>
```

For agent safety, pass explicit `tenant_id` and `scope` in tool arguments. Do
not rely on defaults when multiple customers or projects share one Apcone
deployment.

## Error Messages

Tools raise stable `ToolError` messages with prefixes such as:

| Prefix | Meaning |
| --- | --- |
| `AUTHENTICATION_REQUIRED` | No valid access token reached the tool. |
| `AUTHORIZATION_ERROR` | Tenant, scope, or role check failed. |
| `VALIDATION_ERROR` | Input or storage validation failed. |
| `DOCUMENT_NOT_FOUND` | Reindex target was not found. |
| `STORAGE_ERROR` | Database operation failed. |
| `DEPENDENCY_ERROR` | A non-database dependency failed. |

Log lines include tool name, tenant, scope, duration, and result count or error
code.
