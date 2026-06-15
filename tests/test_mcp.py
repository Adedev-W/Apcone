from __future__ import annotations

import asyncio
from contextlib import contextmanager
from types import SimpleNamespace

from fastmcp import Client

from app.main import app
from app.mcp.server import mcp
from app.schemas import DocumentCreate
from app.services.storage import RagStorageService


def _build_service(test_context, session):
    return RagStorageService(
        db=session,
        chunker=test_context["chunker"],
        embedder=test_context["embedder"],
        qdrant_store=test_context["qdrant_store"],
    )


def test_mcp_mount_is_registered() -> None:
    mount_paths = [getattr(route, "path", None) for route in app.routes]
    assert "/mcp" in mount_paths


def test_mcp_registers_agent_tools() -> None:
    tools = asyncio.run(mcp.list_tools())
    tool_by_name = {tool.name: tool for tool in tools}

    assert {
        "search_documents",
        "ingest_document",
        "reindex_document",
        "delete_document",
        "health",
    }.issubset(tool_by_name)


def test_mcp_tools_describe_tenant_scope_contract() -> None:
    tools = asyncio.run(mcp.list_tools())
    tool_by_name = {tool.name: tool for tool in tools}

    for tool_name in ["search_documents", "ingest_document", "reindex_document", "delete_document"]:
        tool = tool_by_name[tool_name]
        assert tool.description
        assert "tenant" in tool.description.lower()
        assert "tenant_id" in tool.parameters["required"]
        assert tool.parameters["properties"]["tenant_id"]["pattern"] == "^[A-Za-z0-9_.:-]+$"
        assert tool.parameters["properties"]["scope"]["default"] == "default"

    assert tool_by_name["search_documents"].annotations.readOnlyHint is True
    assert tool_by_name["delete_document"].annotations.destructiveHint is True


def test_mcp_http_requires_api_key(client) -> None:
    response = client.post("/mcp/", json={})
    assert response.status_code == 401


def test_mcp_http_accepts_valid_api_key(client, auth_headers, monkeypatch, test_context) -> None:
    from app.mcp import server as mcp_server

    monkeypatch.setattr(mcp_server, "SessionLocal", test_context["session_factory"])

    response = client.post("/mcp/", headers=auth_headers, json={})
    assert response.status_code != 401


def test_mcp_search_tool_runs_with_valid_tenant_context(monkeypatch, test_context) -> None:
    from app.mcp import tools as mcp_tools

    session = test_context["session_factory"]()
    try:
        service = _build_service(test_context, session)
        created = service.ingest_document(
            DocumentCreate(
                tenant_id="tenant-a",
                scope="project-x",
                title="MCP Search",
                content="mcp tool should find this knowledge",
                source="mcp.md",
            )
        )
        document_id = str(created.document.id)
    finally:
        session.close()

    @contextmanager
    def storage_service():
        current_session = test_context["session_factory"]()
        try:
            yield _build_service(test_context, current_session)
        finally:
            current_session.close()

    monkeypatch.setattr(mcp_tools, "_storage_service", storage_service)
    monkeypatch.setattr(
        mcp_tools,
        "get_access_token",
        lambda: SimpleNamespace(
            claims={
                "tenant_id": "tenant-a",
                "scope": "project-x",
                "role": "read",
            }
        ),
    )

    async def call_tool():
        async with Client(mcp) as mcp_client:
            return await mcp_client.call_tool(
                "search_documents",
                {
                    "tenant_id": "tenant-a",
                    "scope": "project-x",
                    "query": "knowledge",
                },
            )

    result = asyncio.run(call_tool())
    payload = result.structured_content

    assert payload is not None
    assert payload["result_count"] >= 1
    assert payload["results"][0]["document_id"] == document_id
