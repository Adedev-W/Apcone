from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID

import httpx

from apcone_sdk.errors import ApconeAPIError
from apcone_sdk.models import (
    Chunk,
    Document,
    DocumentSummary,
    Health,
    IngestResponse,
    IngestionJob,
    SearchResult,
    UploadAccepted,
)


class ApconeAsyncClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        tenant_id: str = "default",
        scope: str = "default",
        timeout: float = 10.0,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.tenant_id = tenant_id
        self.scope = scope
        self._owns_client = http_client is None
        self._client = http_client or httpx.AsyncClient(base_url=self.base_url, timeout=timeout)

    async def __aenter__(self) -> ApconeAsyncClient:
        return self

    async def __aexit__(self, *_exc_info: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    def _auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"}

    def _tenant_params(self) -> dict[str, str]:
        return {"tenant_id": self.tenant_id, "scope": self.scope}

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        headers = dict(kwargs.pop("headers", {}) or {})
        headers.update(self._auth_headers())
        try:
            response = await self._client.request(method, path, headers=headers, **kwargs)
        except httpx.HTTPError as exc:
            raise ApconeAPIError(str(exc)) from exc
        if response.status_code >= 400:
            raise self._api_error(response)
        return response

    @staticmethod
    def _api_error(response: httpx.Response) -> ApconeAPIError:
        detail: Any
        try:
            payload = response.json()
        except ValueError:
            detail = response.text
        else:
            detail = payload.get("detail", payload) if isinstance(payload, dict) else payload
        return ApconeAPIError(
            f"Apcone API request failed with status {response.status_code}: {detail}",
            status_code=response.status_code,
            detail=detail,
        )

    async def health(self) -> Health:
        response = await self._request("GET", "/health")
        return Health.model_validate(response.json())

    async def health_postgres(self) -> Health:
        response = await self._request("GET", "/health/postgres")
        return Health.model_validate(response.json())

    async def health_redis(self) -> Health:
        response = await self._request("GET", "/health/redis")
        return Health.model_validate(response.json())

    async def health_qdrant(self) -> Health:
        response = await self._request("GET", "/health/qdrant")
        return Health.model_validate(response.json())

    async def list_documents(self) -> list[DocumentSummary]:
        response = await self._request("GET", "/documents", params=self._tenant_params())
        return [DocumentSummary.model_validate(item) for item in response.json()]

    async def get_document(self, document_id: UUID | str) -> Document:
        response = await self._request("GET", f"/documents/{document_id}", params=self._tenant_params())
        return Document.model_validate(response.json())

    async def get_chunks(self, document_id: UUID | str) -> list[Chunk]:
        response = await self._request("GET", f"/documents/{document_id}/chunks", params=self._tenant_params())
        return [Chunk.model_validate(item) for item in response.json()]

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
        response = await self._request("POST", "/documents/ingest", json=payload)
        return IngestResponse.model_validate(response.json())

    async def upload_text_file(
        self,
        path: str | Path,
        *,
        title: str,
        source: str | None = None,
    ) -> IngestResponse:
        file_path = Path(path)
        data = {"title": title, "tenant_id": self.tenant_id, "scope": self.scope}
        if source is not None:
            data["source"] = source
        with file_path.open("rb") as handle:
            response = await self._request(
                "POST",
                "/documents/upload",
                data=data,
                files={"content_file": (file_path.name, handle, "text/plain")},
            )
        return IngestResponse.model_validate(response.json())

    async def upload_document_file(
        self,
        path: str | Path,
        *,
        title: str,
        source: str | None = None,
        mime_type: str = "application/pdf",
    ) -> UploadAccepted:
        file_path = Path(path)
        data = {"title": title, "tenant_id": self.tenant_id, "scope": self.scope}
        if source is not None:
            data["source"] = source
        with file_path.open("rb") as handle:
            response = await self._request(
                "POST",
                "/documents/upload-document",
                data=data,
                files={"content_file": (file_path.name, handle, mime_type)},
            )
        return UploadAccepted.model_validate(response.json())

    async def search_documents(
        self,
        query: str,
        *,
        top_k: int | None = None,
        source: str | None = None,
        document_id: UUID | str | None = None,
    ) -> list[SearchResult]:
        payload: dict[str, Any] = {
            "tenant_id": self.tenant_id,
            "scope": self.scope,
            "query": query,
            "top_k": top_k,
            "source": source,
            "document_id": str(document_id) if document_id is not None else None,
        }
        response = await self._request("POST", "/documents/search", json=payload)
        return [SearchResult.model_validate(item) for item in response.json()]

    async def get_job(self, job_id: UUID | str) -> IngestionJob:
        response = await self._request("GET", f"/documents/jobs/{job_id}", params=self._tenant_params())
        return IngestionJob.model_validate(response.json())

    async def reindex_document(self, document_id: UUID | str) -> IngestResponse:
        response = await self._request("POST", f"/documents/{document_id}/reindex", params=self._tenant_params())
        return IngestResponse.model_validate(response.json())

    async def delete_document(self, document_id: UUID | str) -> None:
        await self._request("DELETE", f"/documents/{document_id}", params=self._tenant_params())
