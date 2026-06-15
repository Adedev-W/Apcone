from __future__ import annotations

import json

from app import cli
from app.db.models import Document, IngestionJob, JobStatus


def test_cli_manages_api_keys(monkeypatch, test_context, capsys):
    monkeypatch.setattr(cli, "SessionLocal", test_context["session_factory"])

    cli.main(
        [
            "api-key",
            "create",
            "--name",
            "cli-key",
            "--tenant-id",
            "tenant-a",
            "--scope",
            "project-x",
            "--role",
            "write",
        ]
    )
    created = json.loads(capsys.readouterr().out)
    assert created["api_key"].startswith("apc_")
    assert "key_hash" not in created
    assert created["tenant_id"] == "tenant-a"
    assert created["scope"] == "project-x"
    assert created["role"] == "write"

    cli.main(["api-key", "list", "--tenant-id", "tenant-a"])
    listed = json.loads(capsys.readouterr().out)
    assert len(listed) == 1
    assert "api_key" not in listed[0]
    assert listed[0]["name"] == "cli-key"

    cli.main(["api-key", "rotate", created["id"]])
    rotated = json.loads(capsys.readouterr().out)
    assert rotated["api_key"].startswith("apc_")
    assert rotated["api_key"] != created["api_key"]

    cli.main(["api-key", "revoke", created["id"]])
    revoked = json.loads(capsys.readouterr().out)
    assert revoked["is_active"] is False
    assert revoked["revoked_at"] is not None


def test_cli_lists_documents_and_jobs(monkeypatch, test_context, capsys):
    monkeypatch.setattr(cli, "SessionLocal", test_context["session_factory"])
    session = test_context["session_factory"]()
    try:
        document = Document(
            tenant_id="tenant-a",
            scope="project-x",
            title="CLI Notes",
            source="cli.md",
            content="content hidden by default",
            checksum="abc123",
            metadata_json={},
        )
        job = IngestionJob(
            tenant_id="tenant-a",
            scope="project-x",
            document=document,
            source_name="cli.md",
            status=JobStatus.completed,
            chunk_count=0,
            progress=100,
        )
        session.add(document)
        session.add(job)
        session.commit()
        session.refresh(document)
        session.refresh(job)
    finally:
        session.close()

    cli.main(["documents", "list", "--tenant-id", "tenant-a", "--scope", "project-x"])
    documents = json.loads(capsys.readouterr().out)
    assert documents[0]["title"] == "CLI Notes"
    assert "content" not in documents[0]

    cli.main(["documents", "show", documents[0]["id"], "--tenant-id", "tenant-a", "--scope", "project-x"])
    document_payload = json.loads(capsys.readouterr().out)
    assert document_payload["title"] == "CLI Notes"
    assert "content" not in document_payload

    cli.main(
        [
            "documents",
            "show",
            documents[0]["id"],
            "--tenant-id",
            "tenant-a",
            "--scope",
            "project-x",
            "--content",
        ]
    )
    document_with_content = json.loads(capsys.readouterr().out)
    assert document_with_content["content"] == "content hidden by default"

    cli.main(["jobs", "list", "--tenant-id", "tenant-a", "--scope", "project-x"])
    jobs = json.loads(capsys.readouterr().out)
    assert jobs[0]["status"] == "completed"
