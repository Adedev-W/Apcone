# Apcone

![Python](https://img.shields.io/badge/python-3.12%2B-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.136-009688?logo=fastapi&logoColor=white)
![FastMCP](https://img.shields.io/badge/MCP-FastMCP-blue)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-18-4169E1?logo=postgresql&logoColor=white)
![Redis](https://img.shields.io/badge/Redis-8-DC382D?logo=redis&logoColor=white)
![Qdrant](https://img.shields.io/badge/Qdrant-vector_search-DC244C)
![Docker](https://img.shields.io/badge/Docker_Compose-ready-2496ED?logo=docker&logoColor=white)
![Tests](https://img.shields.io/badge/tests-pytest-green)

**Apcone is a tenant-scoped RAG storage service for internal knowledge.** It gives
your backend or agent stack one place to ingest documents, chunk and embed text,
store vectors in Qdrant, search with semantic plus lexical fallback, and expose
the same knowledge through HTTP APIs, a Python SDK, CLI commands, and MCP tools.

Use it when you need a small, understandable retrieval layer before building a
full agent platform: upload text or PDFs, index them by `tenant_id` and `scope`,
then search them from an app, script, worker, or MCP-compatible agent.

## What It Includes

| Area | What you get |
| --- | --- |
| **HTTP API** | Document ingest, upload, search, chunk read, reindex, delete, job polling, health checks. |
| **Background ingestion** | Redis/RQ worker pipeline for text and PDF uploads, including OCR routing for scanned PDFs. |
| **Vector storage** | Qdrant collection management, embeddings with FastEmbed, PostgreSQL metadata and lexical fallback. |
| **MCP server** | Streamable HTTP MCP endpoint at `/mcp/` with authenticated knowledge tools for agents. |
| **Python SDK** | Async `ApconeAsyncClient` and `ApconeMCPClient` wrappers for app and agent code. |
| **CLI** | Local admin commands for API keys, health, documents, search, and jobs. |

## Quick Start

```bash
uv sync
cp .env.example .env
docker compose up -d postgres redis qdrant
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```

Create an API key:

```bash
uv run python -m app.cli api-key create --name local-admin --tenant-id default --role admin
export APCONE_API_KEY=<api_key_from_create_output>
```

Ingest and search a note:

```bash
curl -X POST http://127.0.0.1:8000/documents/ingest \
  -H "Authorization: Bearer $APCONE_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Refund Policy",
    "content": "Refunds are available within 14 days.",
    "source": "policy.md"
  }'

curl -X POST http://127.0.0.1:8000/documents/search \
  -H "Authorization: Bearer $APCONE_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"query": "refund window", "top_k": 3}'
```

The API key may be sent as `Authorization: Bearer <key>` or `X-API-Key: <key>`.
Health endpoints stay public for liveness checks.

## Python SDK In 30 Seconds

```python
import asyncio

from apcone_sdk import ApconeAsyncClient, ApconeMCPClient


async def main() -> None:
    api_key = "<apcone_api_key>"

    async with ApconeAsyncClient("http://127.0.0.1:8000", api_key) as client:
        created = await client.ingest_document(
            title="SDK note",
            content="Apcone can search tenant-scoped documents.",
            source="sdk-example",
        )
        results = await client.search_documents("tenant-scoped search")
        print(created.document.id, results[0].content)

    mcp_client = ApconeMCPClient.from_base_url("http://127.0.0.1:8000", api_key)
    mcp_results = await mcp_client.search_documents("tenant-scoped search")
    print(mcp_results.result_count)


asyncio.run(main())
```

## Documentation

Start with **[docs/getting-started.md](docs/getting-started.md)** if this is
your first run. Use **[docs/http-api.md](docs/http-api.md)** for endpoint
contracts, **[docs/sdk.md](docs/sdk.md)** for Python integration, and
**[docs/mcp.md](docs/mcp.md)** for agent tooling.

| Guide | Purpose |
| --- | --- |
| [Documentation index](docs/README.md) | Choose the right reading path. |
| [Getting started](docs/getting-started.md) | Run Apcone locally and perform the first search. |
| [Configuration](docs/configuration.md) | Understand every important environment variable. |
| [HTTP API](docs/http-api.md) | Use every endpoint with request and response examples. |
| [Python SDK](docs/sdk.md) | Integrate Apcone from async Python code. |
| [MCP tools](docs/mcp.md) | Connect MCP clients and call agent-facing tools. |
| [PDF ingestion](docs/pdf-ingestion.md) | Upload PDFs, run workers, and understand OCR routing. |
| [CLI](docs/cli.md) | Manage keys, inspect documents, search, and view jobs. |
| [Operations](docs/operations.md) | Health checks, troubleshooting, and performance notes. |
| [Architecture](docs/architecture.md) | How FastAPI, PostgreSQL, Redis, Qdrant, workers, SDK, and MCP fit together. |

## Local Service Map

With `.env.example` copied to `.env`, local ports are:

| Service | URL |
| --- | --- |
| Apcone API | `http://127.0.0.1:8000` |
| MCP endpoint | `http://127.0.0.1:8000/mcp/` |
| PostgreSQL | `127.0.0.1:5433` |
| Redis | `127.0.0.1:6380` |
| Qdrant API/UI | `http://127.0.0.1:6333` |
| Qdrant dashboard | `http://127.0.0.1:6333/dashboard` |
| PDF scanner gRPC | `127.0.0.1:50051` |

Run the full test suite with:

```bash
uv run pytest
```

Apcone is intentionally small: clear FastAPI routes, focused services, explicit
Pydantic schemas, SQLAlchemy models, and tests around the core API, MCP, SDK,
storage, queue, scanner, and CLI behavior.
