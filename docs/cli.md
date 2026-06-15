# CLI

The CLI is useful for local administration and debugging because it talks to the
same database and storage services as the API. Run commands from the repository
root.

```bash
uv run python -m app.cli --help
```

## Health

```bash
uv run python -m app.cli health
```

This checks PostgreSQL with `SELECT 1` and prints JSON.

## API Keys

Create a key:

```bash
uv run python -m app.cli api-key create \
  --name local-admin \
  --tenant-id default \
  --role admin
```

Create a scope-bound key:

```bash
uv run python -m app.cli api-key create \
  --name project-reader \
  --tenant-id tenant-a \
  --scope project-x \
  --role read
```

List keys:

```bash
uv run python -m app.cli api-key list
uv run python -m app.cli api-key list --tenant-id tenant-a
uv run python -m app.cli api-key list --include-revoked
```

Rotate a key:

```bash
uv run python -m app.cli api-key rotate <key_id>
```

Revoke a key:

```bash
uv run python -m app.cli api-key revoke <key_id>
```

The full secret is printed only when a key is created or rotated. Store it
immediately.

## Documents

List document summaries:

```bash
uv run python -m app.cli documents list --tenant-id default --scope default
```

Limit output:

```bash
uv run python -m app.cli documents list --limit 20
```

Show a document summary:

```bash
uv run python -m app.cli documents show <document_id>
```

Include full content:

```bash
uv run python -m app.cli documents show <document_id> --content
```

Search:

```bash
uv run python -m app.cli documents search "refund policy" \
  --tenant-id default \
  --scope default \
  --top-k 5
```

The CLI search path builds the same storage service as the API, including the
configured embedding model and Qdrant collection.

## Jobs

List recent jobs:

```bash
uv run python -m app.cli jobs list --tenant-id default --scope default
```

Show one job:

```bash
uv run python -m app.cli jobs show <job_id>
```

Jobs are especially useful after `/documents/upload-document`, because that API
returns before parsing and indexing finishes.

## Output Format

CLI commands print JSON with stable keys. Datetimes and UUIDs are serialized as
strings. This makes the CLI easy to pipe into tools such as `jq`:

```bash
uv run python -m app.cli jobs list | jq '.[0].status'
```
