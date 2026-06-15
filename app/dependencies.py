from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from qdrant_client import QdrantClient
from sqlalchemy.orm import Session

from app.adapters.qdrant_store import QdrantChunkStore
from app.core.config import Settings
from app.db.models import ApiKey, ApiKeyRole
from app.db.session import get_db
from app.services.api_keys import ApiKeyService, role_allows, validate_role
from app.services.chunking import ChunkingService
from app.services.embeddings import FastEmbedEmbeddingService
from app.services.storage import RagStorageService


@dataclass(slots=True)
class ApiKeyPrincipal:
    api_key: ApiKey

    @property
    def tenant_id(self) -> str:
        return self.api_key.tenant_id

    @property
    def scope(self) -> str | None:
        return self.api_key.scope

    @property
    def role(self) -> str:
        return self.api_key.role


@lru_cache(maxsize=4)
def get_embedder(model_name: str) -> FastEmbedEmbeddingService:
    return FastEmbedEmbeddingService(model_name)


@lru_cache(maxsize=4)
def get_qdrant_client(qdrant_url: str) -> QdrantClient:
    return QdrantClient(url=qdrant_url)


def build_storage_service(db: Session, settings: Settings) -> RagStorageService:
    chunker = ChunkingService(settings.chunk_size, settings.chunk_overlap)
    embedder = get_embedder(settings.embedding_model)
    qdrant_client = get_qdrant_client(settings.qdrant_url)
    qdrant_store = QdrantChunkStore(qdrant_client, settings.qdrant_collection)
    return RagStorageService(
        db=db,
        chunker=chunker,
        embedder=embedder,
        qdrant_store=qdrant_store,
    )


def _extract_api_key(
    authorization: str | None,
    x_api_key: str | None,
) -> str | None:
    if authorization:
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token.strip():
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid authorization header",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return token.strip()
    if x_api_key:
        return x_api_key.strip()
    return None


def get_api_key_principal(
    db: Session = Depends(get_db),
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
) -> ApiKeyPrincipal:
    secret = _extract_api_key(authorization, x_api_key)
    if secret is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="api key required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    api_key = ApiKeyService(db).verify_key(secret)
    if api_key is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid api key",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return ApiKeyPrincipal(api_key=api_key)


def require_api_key(
    required_role: str = ApiKeyRole.read.value,
) -> Callable[..., ApiKeyPrincipal]:
    validate_role(required_role)

    def dependency(
        principal: ApiKeyPrincipal = Depends(get_api_key_principal),
    ) -> ApiKeyPrincipal:
        if not role_allows(principal.role, required_role):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="insufficient api key role",
            )
        return principal

    return dependency


def ensure_api_key_context(
    principal: ApiKeyPrincipal,
    *,
    tenant_id: str,
    scope: str,
) -> None:
    if principal.tenant_id != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="api key cannot access this tenant",
        )
    if principal.scope is not None and principal.scope != scope:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="api key cannot access this scope",
        )
