# Architecture

Apcone is intentionally small and explicit. The code follows a simple backend
shape: FastAPI routes validate HTTP input, services handle business behavior,
adapters talk to external systems, and schemas define the public data contracts.

## Runtime Components

```text
Client or agent
  -> FastAPI HTTP API or MCP endpoint
  -> service layer
  -> PostgreSQL for metadata and jobs
  -> FastEmbed for embeddings
  -> Qdrant for vectors
  -> Redis/RQ for background document jobs
  -> PDF scanner for OCR when needed
```

## Main Modules

| Module | Responsibility |
| --- | --- |
| `app/main.py` | Creates FastAPI app, mounts MCP, includes routers. |
| `app/routers/` | HTTP route definitions for health and documents. |
| `app/schemas.py` | Pydantic request/response models and tenant/scope validation. |
| `app/services/` | API key logic, chunking, embeddings, storage, file storage, PDF processing. |
| `app/adapters/` | Qdrant and PDF scanner client adapters. |
| `app/db/` | SQLAlchemy models, metadata base, and sessions. |
| `app/tasks/` | Redis/RQ queue construction. |
| `app/workers/` | Background job execution for uploaded documents. |
| `app/mcp/` | FastMCP server, auth verifier, and MCP tool registration. |
| `apcone_sdk/` | Async Python SDK for HTTP API and MCP tools. |

## Data Model

The durable storage model centers around:

| Entity | Purpose |
| --- | --- |
| API key | Authenticates callers and binds them to a tenant, optional scope, and role. |
| Document | Stores original extracted content, checksum, source, tenant, scope, and metadata. |
| Document chunk | Stores chunk text, chunk index, metadata, and relation to a document. |
| Ingestion job | Tracks synchronous and background ingestion status, parser, progress, and errors. |
| Qdrant point | Stores vector embedding plus payload for one chunk. |

Documents are deduplicated by checksum inside a tenant and scope. The same
content can exist separately in different tenants or scopes.

## Text Ingest Flow

```text
POST /documents/ingest
  -> API key role and tenant/scope checks
  -> DocumentCreate validation
  -> checksum lookup
  -> chunking
  -> embedding
  -> Qdrant collection ensure/upsert
  -> PostgreSQL document/chunk/job commit
  -> IngestResponse
```

This path is synchronous and appropriate for small plain-text payloads.

## Search Flow

```text
POST /documents/search
  -> API key read check
  -> SearchRequest validation
  -> query embedding
  -> Qdrant nearest-neighbor search
  -> PostgreSQL lexical fallback
  -> SearchResultItem list
```

The lexical fallback helps exact keywords remain discoverable when vector search
does not rank them highly.

## Background Upload Flow

```text
POST /documents/upload-document
  -> create pending job
  -> save file to UPLOAD_STORAGE_DIR
  -> enqueue profile job
  -> worker profiles file
  -> route to fast or OCR queue
  -> extract text
  -> ingest extracted content
  -> mark job completed or failed
```

The API returns `202 Accepted` after enqueueing. Clients should poll
`GET /documents/jobs/{job_id}`.

## MCP Flow

```text
MCP client
  -> /mcp/ Streamable HTTP
  -> ApiKeyTokenVerifier
  -> tool-level tenant/scope/role check
  -> same RagStorageService used by HTTP API
  -> structured tool response
```

MCP tools reuse the same storage service as the HTTP API. That avoids separate
business rules for agents.

## SDK Flow

`ApconeAsyncClient` wraps HTTP endpoints with `httpx.AsyncClient`.
`ApconeMCPClient` wraps FastMCP `Client` calls and parses structured tool
content into Pydantic models.

The SDK is deliberately thin. It should make correct calls easier, not replace
the documented API contract.

## Design Tradeoffs

Apcone keeps the architecture straightforward:

**Tenant/scope checks live near the API boundary.** This makes access control
visible and easy to test.

**The service layer owns storage behavior.** Routes and MCP tools both call
`RagStorageService`, so document behavior stays consistent.

**Background processing is limited to uploads.** Plain text ingest stays simple
and synchronous. PDF and OCR work move to Redis/RQ.

**Qdrant is an adapter, not a domain model.** The rest of the app talks about
documents and chunks; Qdrant details stay in `app/adapters/qdrant_store.py`.

This is enough structure for a small-to-medium backend without turning the code
into a framework inside a framework.
