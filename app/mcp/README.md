# MCP RAG Tools

This folder contains the Model Context Protocol (MCP) integration for Apcone's
RAG document tools. It exposes a small set of agent-facing tools on top of the
same storage, chunking, embedding, and vector search services used by the HTTP
document API.

The MCP server is built with `FastMCP` and is mounted into the main FastAPI app
at `/mcp`. It uses Streamable HTTP in stateless mode so framework clients such
as Agno and LangChain can connect to one internal HTTP endpoint without relying
on in-memory session affinity.

## Overview

`app/mcp/server.py` creates the MCP server:

- Server name: `RAG Tools`
- Version: `0.1.0`
- HTTP mount path: `/mcp`
- Transport: Streamable HTTP
- HTTP state mode: stateless
- Tool registration module: `app/mcp/tools.py`

`app/main.py` mounts the MCP ASGI app:

```python
app.mount("/mcp", mcp_app)
```

This means MCP clients should connect to the running FastAPI service through the
`/mcp/` path. If the app is running locally with the default Uvicorn command, the
MCP endpoint is available under:

```text
http://127.0.0.1:8000/mcp/
```

Agent frameworks should configure the MCP transport as Streamable HTTP. For
Agno this is `transport="streamable-http"` with `url="http://127.0.0.1:8000/mcp/"`.

MCP clients must send a valid API key as a bearer token:

```text
Authorization: Bearer <apcone_api_key>
```

Create keys locally with:

```bash
uv run python -m app.cli api-key create --name mcp-client --tenant-id default --role write
```

## Runtime Dependencies

The MCP tools depend on the same services as the RAG API:

- PostgreSQL stores documents, document chunks, checksums, and ingestion jobs.
- Qdrant stores embedded chunk vectors and search payloads.
- FastEmbed creates embeddings for document chunks and search queries.
- SQLAlchemy manages database sessions.
- Pydantic validates document input and serializes output models.

Each MCP tool call opens a fresh database session through `SessionLocal`, builds
a `RagStorageService`, runs the requested operation, and closes the session when
the call finishes. This keeps tool calls isolated and avoids sharing database
sessions across requests.

## Configuration

MCP tools read configuration from `app.core.config.Settings`, which loads values
from environment variables and the project `.env` file.

Important settings:

| Setting | Purpose | Default |
| --- | --- | --- |
| `DATABASE_URL` | SQLAlchemy database URL used for document metadata and jobs. | `postgresql+psycopg://apcone:apcone_password@localhost:5433/apcone` |
| `QDRANT_URL` | Qdrant HTTP URL used by the vector store. | `http://localhost:6333` |
| `QDRANT_COLLECTION` | Qdrant collection that stores document chunk vectors. | `rag_chunks` |
| `EMBEDDING_MODEL` | FastEmbed model used for chunk and query embeddings. | `BAAI/bge-small-en-v1.5` |
| `CHUNK_SIZE` | Target maximum text size for each chunk. | `1000` |
| `CHUNK_OVERLAP` | Character overlap between neighboring chunks. | `150` |
| `SEARCH_TOP_K` | Default number of search results when `top_k` is omitted. | `5` |

For local development, start the required backing services and run migrations:

```bash
uv sync
docker compose up -d postgres redis qdrant
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```

Redis is not used directly by the current MCP tools, but it is part of the
project's broader document upload and worker stack.

## Tenant and Scope Model

Every knowledge tool is tenant-scoped:

- `tenant_id` identifies the owner of the knowledge base, such as a team,
  customer, or workspace.
- `scope` identifies a namespace inside that tenant, such as `default`,
  `project-x`, or `prod`.

The MCP tools require `tenant_id` and default `scope` to `default`. Search,
delete, reindex, and vector deletion never cross the provided tenant and scope.
The same document content can be ingested into different tenants or scopes
without sharing document rows or vectors.

Allowed `tenant_id` and `scope` values may contain letters, numbers, `_`, `-`,
`.`, and `:` and are limited to 80 characters.

## Tools

### `search_documents`

Searches indexed document chunks using semantic similarity.

Inputs:

| Parameter | Type | Required | Description |
| --- | --- | --- | --- |
| `query` | `str` | Yes | Natural-language search query. |
| `tenant_id` | `str` | Yes | Tenant whose knowledge base should be searched. |
| `scope` | `str` | No | Knowledge namespace inside the tenant. Defaults to `default`. |
| `top_k` | `int \| None` | No | Maximum number of results. Uses `SEARCH_TOP_K` when omitted. |
| `source` | `str \| None` | No | Optional source filter. |
| `document_id` | `UUID \| None` | No | Optional document filter. |

Output:

```json
{
  "status": "ok",
  "tenant_id": "team-a",
  "scope": "default",
  "query": "refund policy",
  "top_k": 5,
  "result_count": 1,
  "results": [
    {
      "chunk_id": "uuid",
      "document_id": "uuid",
      "tenant_id": "team-a",
      "scope": "default",
      "document_title": "Policy Handbook",
      "source": "handbook",
      "chunk_index": 0,
      "content": "matching chunk text",
      "score": 0.82,
      "metadata": {}
    }
  ]
}
```

How it works:

1. Embeds the query with the configured embedding model.
2. Searches Qdrant for the nearest chunk vectors.
3. Applies optional `source` and `document_id` filters.
4. Returns chunk-level results with document metadata and similarity scores.

Use this tool when an agent needs to answer questions from already-ingested
documents.

### `ingest_document`

Creates or reuses a text document, chunks its content, embeds the chunks, stores
metadata in PostgreSQL, and stores vectors in Qdrant.

Inputs:

| Parameter | Type | Required | Description |
| --- | --- | --- | --- |
| `tenant_id` | `str` | Yes | Tenant that owns the new knowledge document. |
| `scope` | `str` | No | Knowledge namespace inside the tenant. Defaults to `default`. |
| `title` | `str` | Yes | Document title. Must not be empty and must be at most 255 characters. |
| `content` | `str` | Yes | Plain text document content. Must not be empty. |
| `source` | `str \| None` | No | Optional source name or external reference. |
| `metadata` | `dict[str, Any] \| None` | No | Optional metadata stored with the document. Defaults to `{}`. |

Output:

```json
{
  "status": "completed",
  "tenant_id": "team-a",
  "scope": "default",
  "job_id": "uuid",
  "chunks_created": 3,
  "document": {
    "id": "uuid",
    "tenant_id": "team-a",
    "scope": "default",
    "title": "Policy Handbook",
    "source": "handbook",
    "content": "full document text",
    "checksum": "sha256-checksum",
    "metadata": {},
    "chunk_count": 3,
    "created_at": "2026-06-12T00:00:00Z",
    "updated_at": "2026-06-12T00:00:00Z"
  }
}
```

Important behavior:

- Ingestion is synchronous for MCP calls.
- Content is split using the configured chunk size and overlap.
- Existing documents are detected by checksum. If the same payload already
  exists, the service returns the existing document instead of duplicating it.
- The tool creates an ingestion job record even though the MCP call completes
  synchronously.
- This MCP tool only accepts text content. PDF uploads and background parsing
  are handled by the HTTP document endpoints and worker stack, not by MCP.

Use this tool when an agent needs to add plain text knowledge to the RAG index.

### `reindex_document`

Rebuilds Qdrant vectors for an existing document using its current stored
chunks.

Inputs:

| Parameter | Type | Required | Description |
| --- | --- | --- | --- |
| `tenant_id` | `str` | Yes | Tenant that owns the document. |
| `document_id` | `UUID` | Yes | ID of the document to reindex. |
| `scope` | `str` | No | Knowledge namespace inside the tenant. Defaults to `default`. |

Output:

```json
{
  "status": "completed",
  "tenant_id": "team-a",
  "scope": "default",
  "job_id": "uuid",
  "chunks_created": 3,
  "document_id": "uuid"
}
```

How it works:

1. Loads the document and its chunks from PostgreSQL.
2. Re-embeds all chunks with the configured embedding model.
3. Deletes the document's existing vectors from Qdrant.
4. Upserts the new vectors into Qdrant.
5. Records the operation as an ingestion job.

Important behavior:

- The document must exist.
- A document in another tenant or scope is treated as not found.
- The document must already have chunks.
- This tool does not re-chunk the original document content. It reuses the
  existing stored chunks.

Use this tool after changing vector-store data, changing embedding behavior, or
repairing a Qdrant collection.

### `delete_document`

Deletes a document from PostgreSQL and removes its vectors from Qdrant.

Inputs:

| Parameter | Type | Required | Description |
| --- | --- | --- | --- |
| `tenant_id` | `str` | Yes | Tenant that owns the document. |
| `document_id` | `UUID` | Yes | ID of the document to delete. |
| `scope` | `str` | No | Knowledge namespace inside the tenant. Defaults to `default`. |

Output:

```json
{
  "status": "deleted",
  "tenant_id": "team-a",
  "scope": "default",
  "document_id": "uuid"
}
```

Important behavior:

- If the document exists in the provided tenant and scope, its Qdrant vectors
  are deleted first, then the PostgreSQL document row is deleted.
- If the document does not exist in that tenant and scope, the storage service
  returns without raising an error. The MCP tool still returns a `deleted`
  status for the requested ID.
- Related chunks are removed through the database relationship behavior defined
  by the document model.

Use this tool when an agent needs to remove stale or incorrect knowledge from
the index.

### `health`

Checks whether the MCP-backed RAG dependencies are reachable.

Inputs:

This tool has no input parameters.

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

How it works:

- Runs `SELECT 1` against the configured database.
- Calls the Qdrant store health check.
- Returns the active Qdrant collection name.

Important behavior:

- If the database query fails, the tool call fails.
- If Qdrant responds as unhealthy, the response reports `"qdrant":
  "unreachable"`.

Use this tool before running ingest, search, reindex, or delete operations from
an MCP client.

## Data Flow

Text ingestion flow:

```text
MCP client
  -> ingest_document tool
  -> DocumentCreate validation
  -> RagStorageService
  -> PostgreSQL document/job/chunk rows
  -> FastEmbed chunk embeddings
  -> Qdrant vector upsert
  -> JSON response
```

Search flow:

```text
MCP client
  -> search_documents tool
  -> FastEmbed query embedding
  -> Qdrant vector search
  -> SearchResultItem serialization
  -> JSON response
```

Delete flow:

```text
MCP client
  -> delete_document tool
  -> Qdrant vector deletion
  -> PostgreSQL document deletion
  -> JSON response
```

## Notes and Limitations

- MCP currently exposes tenant-scoped document search, text ingestion, reindex,
  delete, and dependency health tools.
- MCP does not expose PDF upload, PDF profiling, OCR fallback, or Redis queue
  management.
- Tool errors are converted into stable MCP `ToolError` messages such as
  `VALIDATION_ERROR`, `DOCUMENT_NOT_FOUND`, `STORAGE_ERROR`, and
  `DEPENDENCY_ERROR`.
- The current MCP module does not define authentication or authorization. If the
  app is exposed outside a trusted development environment, protect the FastAPI
  service at the deployment or middleware layer.
- `top_k` defaults to `SEARCH_TOP_K` when omitted. MCP clients should keep this
  value small because it maps directly to the Qdrant search limit.

## Verification

The MCP contract is covered by `tests/test_mcp.py`.

Run the focused MCP tests with:

```bash
uv run pytest tests/test_mcp.py
```

These tests verify that:

- The main FastAPI app mounts MCP at `/mcp`.
- The expected MCP tools are registered:
  - `search_documents`
  - `ingest_document`
  - `reindex_document`
  - `delete_document`
  - `health`
