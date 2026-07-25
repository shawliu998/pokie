# Qurio External Agent Access

Qurio exposes one bounded external integration layer over the authoritative
quantitative API:

- `QurioClient` for typed Python access;
- `qurio` for non-interactive JSON CLI output;
- `qurio-mcp` for stdio MCP clients.

These surfaces read the same retained datasets, Runs and evidence used by the
Mac workspace. They do not calculate metrics, execute strategies, start
research, run arbitrary Python or place orders.

## Connection

All entry points use the same environment:

```bash
export QURIO_API_URL=http://127.0.0.1:8000
export QURIO_WORKSPACE_ID=<workspace-uuid>
export QURIO_ACCESS_TOKEN=<access-token>
```

`QURIO_ACCESS_TOKEN` intentionally has no command-line flag. Keep it in the
launch environment or the invoking client's credential mechanism rather than a
checked-in MCP configuration.

## Python

```python
from qurio import QurioClient

with QurioClient.from_env() as qurio:
    datasets = qurio.list_datasets()
    runs = qurio.list_runs(limit=20)
    evidence = qurio.get_run_snapshot(runs[0].id)
```

The SDK validates dataset, Run, artifact and export responses against the
public Pydantic contracts. Workspace and historical Run snapshots remain typed
as JSON objects because their current OpenAPI contract is intentionally an
extensible projection.

## CLI

Repository development:

```bash
uv run --project sdk/python qurio datasets
uv run --project sdk/python qurio runs --limit 20
uv run --project sdk/python qurio run <run-uuid>
uv run --project sdk/python qurio snapshot
uv run --project sdk/python qurio snapshot --run-id <run-uuid>
```

An installed wheel exposes the same interface as `qurio`. Successful commands
write JSON to stdout; configuration and API failures write a credential-free
message to stderr and return exit code `2`.

## MCP

Install the stable MCP v1 dependency and start the stdio server:

```bash
uv sync --project sdk/python --locked --extra mcp
uv run --project sdk/python --extra mcp qurio-mcp
```

The server registers exactly:

| Tool | Result |
|---|---|
| `list_datasets` | Retained market datasets and research eligibility |
| `list_runs` | Recent retained Runs and states |
| `get_run` | One typed Run contract |
| `get_run_evidence` | One complete retained Run projection |

No MCP tool maps to a mutating API route. A future write tool requires a
separate product decision, explicit command semantics and tests against the
existing Run lifecycle; it must not bypass plan approval or create a second
quantitative evaluator.
