from __future__ import annotations

from fastmcp import FastMCP
from fastmcp.server.auth import AccessToken, TokenVerifier

from app.db.session import SessionLocal
from app.services.api_keys import ApiKeyService


class ApiKeyTokenVerifier(TokenVerifier):
    async def verify_token(self, token: str) -> AccessToken | None:
        db = SessionLocal()
        try:
            api_key = ApiKeyService(db).verify_key(token)
            if api_key is None:
                return None
            claims = {
                "api_key_id": str(api_key.id),
                "tenant_id": api_key.tenant_id,
                "scope": api_key.scope,
                "role": api_key.role,
            }
            return AccessToken(
                token=token,
                client_id=str(api_key.id),
                scopes=[api_key.role],
                claims=claims,
            )
        finally:
            db.close()


mcp = FastMCP("RAG Tools", "0.1.0", auth=ApiKeyTokenVerifier())

# Import tool registrations after the MCP instance exists.
from app.mcp import tools as _tools  # noqa: E402,F401

mcp_app = mcp.http_app(path="/", transport="streamable-http", stateless_http=True)
