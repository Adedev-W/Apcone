from __future__ import annotations

import asyncio

from app.main import app
from app.mcp.server import mcp


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
