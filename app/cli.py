from __future__ import annotations

import argparse
import json
from contextlib import contextmanager
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select, text

from app.core.config import get_settings
from app.db.models import ApiKey, ApiKeyRole, Document, IngestionJob
from app.db.session import SessionLocal
from app.dependencies import build_storage_service
from app.schemas import DEFAULT_SCOPE, DEFAULT_TENANT_ID
from app.services.api_keys import ApiKeyService


@contextmanager
def session_scope():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    return str(value)


def _print_json(payload: Any) -> None:
    print(json.dumps(payload, default=_json_default, indent=2, sort_keys=True))


def _parse_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    normalized = value.replace("Z", "+00:00")
    return datetime.fromisoformat(normalized)


def _api_key_payload(api_key: ApiKey) -> dict[str, Any]:
    return {
        "id": api_key.id,
        "name": api_key.name,
        "key_prefix": api_key.key_prefix,
        "tenant_id": api_key.tenant_id,
        "scope": api_key.scope,
        "role": api_key.role,
        "is_active": api_key.is_active,
        "expires_at": api_key.expires_at,
        "last_used_at": api_key.last_used_at,
        "revoked_at": api_key.revoked_at,
        "created_at": api_key.created_at,
        "updated_at": api_key.updated_at,
    }


def _document_summary(document: Document) -> dict[str, Any]:
    return {
        "id": document.id,
        "tenant_id": document.tenant_id,
        "scope": document.scope,
        "title": document.title,
        "source": document.source,
        "checksum": document.checksum,
        "chunk_count": len(document.chunks),
        "created_at": document.created_at,
        "updated_at": document.updated_at,
    }


def _job_payload(job: IngestionJob) -> dict[str, Any]:
    return {
        "id": job.id,
        "tenant_id": job.tenant_id,
        "scope": job.scope,
        "document_id": job.document_id,
        "source_name": job.source_name,
        "file_name": job.file_name,
        "mime_type": job.mime_type,
        "parser_name": job.parser_name,
        "page_count": job.page_count,
        "progress": job.progress,
        "status": job.status.value,
        "chunk_count": job.chunk_count,
        "error_message": job.error_message,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
    }


def create_api_key(args: argparse.Namespace) -> None:
    with session_scope() as db:
        result = ApiKeyService(db).create_key(
            name=args.name,
            tenant_id=args.tenant_id,
            scope=args.scope,
            role=args.role,
            expires_at=_parse_datetime(args.expires_at),
        )
        payload = _api_key_payload(result.api_key)
        payload["api_key"] = result.secret
        _print_json(payload)


def list_api_keys(args: argparse.Namespace) -> None:
    with session_scope() as db:
        api_keys = ApiKeyService(db).list_keys(
            tenant_id=args.tenant_id,
            include_revoked=args.include_revoked,
        )
        _print_json([_api_key_payload(api_key) for api_key in api_keys])


def revoke_api_key(args: argparse.Namespace) -> None:
    with session_scope() as db:
        api_key = ApiKeyService(db).revoke_key(UUID(args.key_id))
        _print_json(_api_key_payload(api_key))


def rotate_api_key(args: argparse.Namespace) -> None:
    with session_scope() as db:
        result = ApiKeyService(db).rotate_key(UUID(args.key_id))
        payload = _api_key_payload(result.api_key)
        payload["api_key"] = result.secret
        _print_json(payload)


def check_health(_: argparse.Namespace) -> None:
    with session_scope() as db:
        db.execute(text("SELECT 1"))
        _print_json({"status": "ok", "database": "reachable"})


def list_documents(args: argparse.Namespace) -> None:
    with session_scope() as db:
        statement = (
            select(Document)
            .where(Document.tenant_id == args.tenant_id, Document.scope == args.scope)
            .order_by(Document.created_at.desc())
            .limit(args.limit)
        )
        _print_json([_document_summary(document) for document in db.scalars(statement)])


def show_document(args: argparse.Namespace) -> None:
    with session_scope() as db:
        statement = select(Document).where(
            Document.id == UUID(args.document_id),
            Document.tenant_id == args.tenant_id,
            Document.scope == args.scope,
        )
        document = db.scalar(statement)
        if document is None:
            raise SystemExit("document not found")
        payload = _document_summary(document)
        if args.content:
            payload["content"] = document.content
        _print_json(payload)


def search_documents(args: argparse.Namespace) -> None:
    settings = get_settings()
    with session_scope() as db:
        service = build_storage_service(db, settings)
        results = service.search(
            query=args.query,
            top_k=args.top_k,
            tenant_id=args.tenant_id,
            scope=args.scope,
        )
        _print_json([item.model_dump(mode="json") for item in results])


def list_jobs(args: argparse.Namespace) -> None:
    with session_scope() as db:
        statement = (
            select(IngestionJob)
            .where(IngestionJob.tenant_id == args.tenant_id, IngestionJob.scope == args.scope)
            .order_by(IngestionJob.created_at.desc())
            .limit(args.limit)
        )
        _print_json([_job_payload(job) for job in db.scalars(statement)])


def show_job(args: argparse.Namespace) -> None:
    with session_scope() as db:
        statement = select(IngestionJob).where(
            IngestionJob.id == UUID(args.job_id),
            IngestionJob.tenant_id == args.tenant_id,
            IngestionJob.scope == args.scope,
        )
        job = db.scalar(statement)
        if job is None:
            raise SystemExit("job not found")
        _print_json(_job_payload(job))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="apcone")
    subparsers = parser.add_subparsers(dest="command", required=True)

    health_parser = subparsers.add_parser("health")
    health_parser.set_defaults(func=check_health)

    api_key_parser = subparsers.add_parser("api-key")
    api_key_subparsers = api_key_parser.add_subparsers(dest="api_key_command", required=True)

    api_key_create = api_key_subparsers.add_parser("create")
    api_key_create.add_argument("--name", required=True)
    api_key_create.add_argument("--tenant-id", default=DEFAULT_TENANT_ID)
    api_key_create.add_argument("--scope")
    api_key_create.add_argument(
        "--role",
        choices=[role.value for role in ApiKeyRole],
        default=ApiKeyRole.read.value,
    )
    api_key_create.add_argument("--expires-at")
    api_key_create.set_defaults(func=create_api_key)

    api_key_list = api_key_subparsers.add_parser("list")
    api_key_list.add_argument("--tenant-id")
    api_key_list.add_argument("--include-revoked", action="store_true")
    api_key_list.set_defaults(func=list_api_keys)

    api_key_revoke = api_key_subparsers.add_parser("revoke")
    api_key_revoke.add_argument("key_id")
    api_key_revoke.set_defaults(func=revoke_api_key)

    api_key_rotate = api_key_subparsers.add_parser("rotate")
    api_key_rotate.add_argument("key_id")
    api_key_rotate.set_defaults(func=rotate_api_key)

    documents_parser = subparsers.add_parser("documents")
    documents_subparsers = documents_parser.add_subparsers(dest="documents_command", required=True)

    documents_list = documents_subparsers.add_parser("list")
    documents_list.add_argument("--tenant-id", default=DEFAULT_TENANT_ID)
    documents_list.add_argument("--scope", default=DEFAULT_SCOPE)
    documents_list.add_argument("--limit", type=int, default=100)
    documents_list.set_defaults(func=list_documents)

    documents_show = documents_subparsers.add_parser("show")
    documents_show.add_argument("document_id")
    documents_show.add_argument("--tenant-id", default=DEFAULT_TENANT_ID)
    documents_show.add_argument("--scope", default=DEFAULT_SCOPE)
    documents_show.add_argument("--content", action="store_true")
    documents_show.set_defaults(func=show_document)

    documents_search = documents_subparsers.add_parser("search")
    documents_search.add_argument("query")
    documents_search.add_argument("--tenant-id", default=DEFAULT_TENANT_ID)
    documents_search.add_argument("--scope", default=DEFAULT_SCOPE)
    documents_search.add_argument("--top-k", type=int, default=5)
    documents_search.set_defaults(func=search_documents)

    jobs_parser = subparsers.add_parser("jobs")
    jobs_subparsers = jobs_parser.add_subparsers(dest="jobs_command", required=True)

    jobs_list = jobs_subparsers.add_parser("list")
    jobs_list.add_argument("--tenant-id", default=DEFAULT_TENANT_ID)
    jobs_list.add_argument("--scope", default=DEFAULT_SCOPE)
    jobs_list.add_argument("--limit", type=int, default=100)
    jobs_list.set_defaults(func=list_jobs)

    jobs_show = jobs_subparsers.add_parser("show")
    jobs_show.add_argument("job_id")
    jobs_show.add_argument("--tenant-id", default=DEFAULT_TENANT_ID)
    jobs_show.add_argument("--scope", default=DEFAULT_SCOPE)
    jobs_show.set_defaults(func=show_job)

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
