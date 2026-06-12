from __future__ import annotations

from fastmcp import FastMCP


mcp = FastMCP("RAG Tools", "0.1.0")

# Import tool registrations after the MCP instance exists.
from app.mcp import tools as _tools  # noqa: E402,F401

mcp_app = mcp.http_app(transport="streamable-http", stateless_http=True)
