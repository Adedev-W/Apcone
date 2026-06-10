from __future__ import annotations

import asyncio

from app.main import app
from app.mcp.server import mcp


def test_mcp_mount_is_registered() -> None:
    mount_paths = [getattr(route, "path", None) for route in app.routes]
    assert "/mcp" in mount_paths


def test_mcp_registers_agent_tools() -> None:
    tools = asyncio.run(mcp.list_tools())
    tool_names = {tool.name for tool in tools}

    assert {
        "search_documents",
        "ingest_document",
        "reindex_document",
        "delete_document",
        "health",
    }.issubset(tool_names)
