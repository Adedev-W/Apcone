from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.services.api_keys import ApiKeyService, hash_api_key, role_allows


def test_api_key_service_hashes_and_verifies_secret(test_context):
    session = test_context["session_factory"]()
    try:
        created = ApiKeyService(session).create_key(
            name="service-key",
            tenant_id="tenant-a",
            scope="project-x",
            role="write",
        )

        assert created.secret.startswith("apc_")
        assert created.secret not in created.api_key.key_hash
        assert created.api_key.key_hash == hash_api_key(created.secret)

        verified = ApiKeyService(session).verify_key(created.secret, update_last_used=False)
        assert verified is not None
        assert verified.id == created.api_key.id
        assert verified.tenant_id == "tenant-a"
        assert verified.scope == "project-x"
    finally:
        session.close()


def test_api_key_service_rejects_revoked_and_expired_keys(test_context):
    session = test_context["session_factory"]()
    try:
        service = ApiKeyService(session)
        revoked = service.create_key(name="revoked", tenant_id="default")
        expired = service.create_key(
            name="expired",
            tenant_id="default",
            expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        )

        service.revoke_key(revoked.api_key.id)

        assert service.verify_key(revoked.secret, update_last_used=False) is None
        assert service.verify_key(expired.secret, update_last_used=False) is None
    finally:
        session.close()


def test_api_key_role_hierarchy() -> None:
    assert role_allows("admin", "read") is True
    assert role_allows("write", "read") is True
    assert role_allows("read", "write") is False
