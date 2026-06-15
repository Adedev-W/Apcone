from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ApiKey, ApiKeyRole


API_KEY_PREFIX = "apc_"
API_KEY_VISIBLE_PREFIX_LENGTH = 12
ROLE_RANK = {
    ApiKeyRole.read.value: 1,
    ApiKeyRole.write.value: 2,
    ApiKeyRole.admin.value: 3,
}


@dataclass(slots=True)
class CreatedApiKey:
    api_key: ApiKey
    secret: str


def generate_api_key() -> str:
    return f"{API_KEY_PREFIX}{secrets.token_urlsafe(32)}"


def hash_api_key(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def validate_role(role: str) -> str:
    if role not in ROLE_RANK:
        raise ValueError("role must be one of: read, write, admin")
    return role


def role_allows(actual_role: str, required_role: str) -> bool:
    validate_role(actual_role)
    validate_role(required_role)
    return ROLE_RANK[actual_role] >= ROLE_RANK[required_role]


class ApiKeyService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create_key(
        self,
        *,
        name: str,
        tenant_id: str,
        scope: str | None = None,
        role: str = ApiKeyRole.read.value,
        expires_at: datetime | None = None,
    ) -> CreatedApiKey:
        role = validate_role(role)
        secret = generate_api_key()
        api_key = ApiKey(
            name=name,
            key_prefix=secret[:API_KEY_VISIBLE_PREFIX_LENGTH],
            key_hash=hash_api_key(secret),
            tenant_id=tenant_id,
            scope=scope,
            role=role,
            expires_at=expires_at,
        )
        self.db.add(api_key)
        self.db.commit()
        self.db.refresh(api_key)
        return CreatedApiKey(api_key=api_key, secret=secret)

    def verify_key(self, secret: str, *, update_last_used: bool = True) -> ApiKey | None:
        if not secret:
            return None
        candidate_hash = hash_api_key(secret)
        api_key = self.db.scalar(select(ApiKey).where(ApiKey.key_hash == candidate_hash))
        if api_key is None:
            return None
        if not secrets.compare_digest(api_key.key_hash, candidate_hash):
            return None
        if not self._is_usable(api_key):
            return None
        if update_last_used:
            api_key.last_used_at = datetime.now(timezone.utc)
            self.db.commit()
            self.db.refresh(api_key)
        return api_key

    def list_keys(
        self,
        *,
        tenant_id: str | None = None,
        include_revoked: bool = False,
    ) -> list[ApiKey]:
        statement = select(ApiKey).order_by(ApiKey.created_at.desc())
        if tenant_id is not None:
            statement = statement.where(ApiKey.tenant_id == tenant_id)
        if not include_revoked:
            statement = statement.where(ApiKey.revoked_at.is_(None))
        return list(self.db.scalars(statement))

    def revoke_key(self, key_id: UUID) -> ApiKey:
        api_key = self._get_key(key_id)
        api_key.is_active = False
        api_key.revoked_at = datetime.now(timezone.utc)
        self.db.commit()
        self.db.refresh(api_key)
        return api_key

    def rotate_key(self, key_id: UUID) -> CreatedApiKey:
        api_key = self._get_key(key_id)
        if api_key.revoked_at is not None:
            raise ValueError("revoked api key cannot be rotated")
        secret = generate_api_key()
        api_key.key_prefix = secret[:API_KEY_VISIBLE_PREFIX_LENGTH]
        api_key.key_hash = hash_api_key(secret)
        api_key.last_used_at = None
        self.db.commit()
        self.db.refresh(api_key)
        return CreatedApiKey(api_key=api_key, secret=secret)

    def _get_key(self, key_id: UUID) -> ApiKey:
        api_key = self.db.get(ApiKey, key_id)
        if api_key is None:
            raise LookupError(f"api key {key_id} not found")
        return api_key

    @staticmethod
    def _is_usable(api_key: ApiKey) -> bool:
        if not api_key.is_active or api_key.revoked_at is not None:
            return False
        if api_key.expires_at is None:
            return True
        expires_at = api_key.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        return expires_at > datetime.now(timezone.utc)
