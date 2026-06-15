from __future__ import annotations

import pytest
import httpx

from apcone_sdk import ApconeAPIError, ApconeAsyncClient, ApconeMCPClient, ApconeMCPError
from app.main import app
from app.mcp.server import mcp


@pytest.fixture()
def anyio_backend() -> str:
    return "asyncio"


def _api_key_from_headers(headers: dict[str, str]) -> str:
    return headers["Authorization"].removeprefix("Bearer ")


@pytest.mark.anyio
async def test_async_http_sdk_ingest_search_delete_roundtrip(test_context, auth_headers):
    transport = httpx.ASGITransport(app=app)
    api_key = _api_key_from_headers(auth_headers)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http_client:
        async with ApconeAsyncClient(
            "http://testserver",
            api_key,
            http_client=http_client,
        ) as sdk:
            health = await sdk.health()
            assert health.status == "ok"

            ingested = await sdk.ingest_document(
                title="SDK Notes",
                content="The async SDK wraps Apcone document search.",
                source="sdk.md",
            )
            assert ingested.chunks_created >= 1

            results = await sdk.search_documents("document search", top_k=3)
            assert results
            assert results[0].document_id == ingested.document.id

            document = await sdk.get_document(ingested.document.id)
            assert document.title == "SDK Notes"

            chunks = await sdk.get_chunks(ingested.document.id)
            assert chunks

            job = await sdk.get_job(ingested.job_id)
            assert job.id == ingested.job_id

            await sdk.delete_document(ingested.document.id)

            with pytest.raises(ApconeAPIError) as exc_info:
                await sdk.get_document(ingested.document.id)
            assert exc_info.value.status_code == 404


@pytest.mark.anyio
async def test_async_http_sdk_maps_auth_error(test_context):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http_client:
        sdk = ApconeAsyncClient("http://testserver", "invalid", http_client=http_client)
        with pytest.raises(ApconeAPIError) as exc_info:
            await sdk.search_documents("missing key")
    assert exc_info.value.status_code == 401


@pytest.mark.anyio
async def test_mcp_sdk_searches_with_in_memory_transport(monkeypatch, test_context):
    from app.mcp import tools as mcp_tools
    from app.schemas import DocumentCreate
    from tests.test_mcp import _build_service

    session = test_context["session_factory"]()
    try:
        service = _build_service(test_context, session)
        created = service.ingest_document(
            DocumentCreate(
                tenant_id="tenant-a",
                scope="project-x",
                title="SDK MCP",
                content="mcp sdk should find this knowledge",
                source="mcp-sdk.md",
            )
        )
        document_id = created.document.id
    finally:
        session.close()

    def storage_service():
        from contextlib import contextmanager

        @contextmanager
        def manager():
            current_session = test_context["session_factory"]()
            try:
                yield _build_service(test_context, current_session)
            finally:
                current_session.close()

        return manager()

    monkeypatch.setattr(mcp_tools, "_storage_service", storage_service)

    class Token:
        claims = {"tenant_id": "tenant-a", "scope": "project-x", "role": "read"}

    monkeypatch.setattr(mcp_tools, "get_access_token", lambda: Token())

    sdk = ApconeMCPClient(mcp, "ignored-for-in-memory", tenant_id="tenant-a", scope="project-x")
    response = await sdk.search_documents("knowledge")

    assert response.result_count >= 1
    assert response.results[0].document_id == document_id


@pytest.mark.anyio
async def test_mcp_sdk_maps_tool_error(monkeypatch):
    from app.mcp import tools as mcp_tools

    monkeypatch.setattr(mcp_tools, "get_access_token", lambda: None)

    sdk = ApconeMCPClient(mcp, "ignored-for-in-memory", tenant_id="tenant-a")
    with pytest.raises(ApconeMCPError) as exc_info:
        await sdk.search_documents("knowledge")
    assert "AUTHENTICATION_REQUIRED" in str(exc_info.value)
