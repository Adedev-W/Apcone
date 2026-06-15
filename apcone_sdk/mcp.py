from __future__ import annotations

from typing import Any
from uuid import UUID

from fastmcp import Client

from apcone_sdk.errors import ApconeMCPError
from apcone_sdk.models import (
    Health,
    IngestResponse,
    MCPDeleteResponse,
    MCPReindexResponse,
    MCPSearchResponse,
)


class ApconeMCPClient:
    def __init__(
        self,
        mcp_url: Any,
        api_key: str,
        *,
        tenant_id: str = "default",
        scope: str = "default",
        timeout: float = 10.0,
        transport: Any | None = None,
    ) -> None:
        self.mcp_url = mcp_url
        self.api_key = api_key
        self.tenant_id = tenant_id
        self.scope = scope
        self.timeout = timeout
        self.transport = transport

    @classmethod
    def from_base_url(
        cls,
        base_url: str,
        api_key: str,
        *,
        tenant_id: str = "default",
        scope: str = "default",
        timeout: float = 10.0,
    ) -> ApconeMCPClient:
        return cls(
            f"{base_url.rstrip('/')}/mcp/",
            api_key,
            tenant_id=tenant_id,
            scope=scope,
            timeout=timeout,
        )

    async def _call_tool(self, tool_name: str, arguments: dict[str, Any] | None = None) -> Any:
        target = self.transport or self.mcp_url
        auth = self.api_key if self.transport is None and isinstance(self.mcp_url, str) else None
        try:
            async with Client(target, auth=auth, timeout=self.timeout) as client:
                result = await client.call_tool(tool_name, arguments or {})
        except Exception as exc:
            raise ApconeMCPError(str(exc), tool_name=tool_name) from exc
        if result.structured_content is None:
            raise ApconeMCPError("MCP tool did not return structured content", tool_name=tool_name)
        return result.structured_content

    async def health(self) -> Health:
        payload = await self._call_tool("health")
        return Health.model_validate(payload)

    async def search_documents(
        self,
        query: str,
        *,
        top_k: int | None = None,
        source: str | None = None,
        document_id: UUID | str | None = None,
    ) -> MCPSearchResponse:
        payload = {
            "tenant_id": self.tenant_id,
            "scope": self.scope,
            "query": query,
            "top_k": top_k,
            "source": source,
            "document_id": str(document_id) if document_id is not None else None,
        }
        return MCPSearchResponse.model_validate(await self._call_tool("search_documents", payload))

    async def ingest_document(
        self,
        *,
        title: str,
        content: str,
        source: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> IngestResponse:
        payload = {
            "tenant_id": self.tenant_id,
            "scope": self.scope,
            "title": title,
            "content": content,
            "source": source,
            "metadata": metadata or {},
        }
        return IngestResponse.model_validate(await self._call_tool("ingest_document", payload))

    async def reindex_document(self, document_id: UUID | str) -> MCPReindexResponse:
        payload = {
            "tenant_id": self.tenant_id,
            "scope": self.scope,
            "document_id": str(document_id),
        }
        return MCPReindexResponse.model_validate(await self._call_tool("reindex_document", payload))

    async def delete_document(self, document_id: UUID | str) -> MCPDeleteResponse:
        payload = {
            "tenant_id": self.tenant_id,
            "scope": self.scope,
            "document_id": str(document_id),
        }
        return MCPDeleteResponse.model_validate(await self._call_tool("delete_document", payload))
