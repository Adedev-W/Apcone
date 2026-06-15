# Apcone Documentation

This folder is the long-form documentation for Apcone. The root
`README.md` explains the project in about one minute; these guides explain how
to run, use, integrate, and operate the service safely.

## Reading Paths

If you are new to the project, read **[Getting started](getting-started.md)**
first. It takes you from dependencies to the first successful search.

If you are integrating an app, use **[HTTP API](http-api.md)** for raw endpoint
contracts or **[Python SDK](sdk.md)** for the async SDK wrapper.

If you are connecting an agent, start with **[MCP tools](mcp.md)**. It explains
the `/mcp/` endpoint, bearer authentication, and every exposed tool.

If you are running Apcone in a local or server environment, use
**[Configuration](configuration.md)**, **[PDF ingestion](pdf-ingestion.md)**,
and **[Operations](operations.md)**.

## Guide Map

| Guide | What it covers |
| --- | --- |
| [Getting started](getting-started.md) | Install dependencies, start services, migrate the database, create an API key, ingest text, and search. |
| [Configuration](configuration.md) | Environment variables, default ports, storage directories, queue names, embeddings, Qdrant, and PDF scanner settings. |
| [HTTP API](http-api.md) | Health, document, upload, search, job, reindex, and delete endpoints with examples. |
| [Python SDK](sdk.md) | `ApconeAsyncClient`, `ApconeMCPClient`, lifecycle, errors, uploads, search, and MCP calls. |
| [MCP tools](mcp.md) | Streamable HTTP MCP setup, auth, tool inputs, tool outputs, and tool behavior. |
| [PDF ingestion](pdf-ingestion.md) | Background upload flow, profiling, parser selection, OCR scanner, workers, queue routing, and job polling. |
| [CLI](cli.md) | Local commands for health, API keys, documents, search, and jobs. |
| [Operations](operations.md) | Health checks, common failures, worker/scanner startup, Qdrant checks, and performance tuning. |
| [Architecture](architecture.md) | Runtime components, request flows, data model, and why the service is structured this way. |

## Documentation Style

The docs separate **how to do something** from **what each interface means**.
That keeps quick workflows short while still giving enough detail for debugging
and production operation.

When a command includes `$APCONE_API_KEY`, create the key first:

```bash
uv run python -m app.cli api-key create --name local-admin --tenant-id default --role admin
export APCONE_API_KEY=<api_key_from_create_output>
```

Use `tenant_id` for the owner of the knowledge base and `scope` for a namespace
inside that tenant. Most examples use `default/default` because those are the
service defaults.
