#!/usr/bin/env python3
"""Prepare a local-live Qurio session backed by real Binance BTCUSDT daily data.

This script bootstraps a persistent SQLite runtime database, creates a development
workspace/principal, fetches an immutable Binance Spot BTCUSDT daily dataset through
the existing server-owned adapter, and creates an API-owned Auto Quant project/run.
It deliberately does NOT execute the worker.

The session file includes a local development bearer identity and is written
owner-only. Provider secrets are read from process environment variables and
are never printed or persisted.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIR = (
    Path(os.environ.get("POKIEQUANT_LIVE_SESSION_DIR", str(REPO_ROOT / ".run")))
    .expanduser()
    .resolve()
)
DB_PATH = RUNTIME_DIR / "pokiequant-live.db"
OBJECT_ROOT = RUNTIME_DIR / "pokiequant-live-objects"
SESSION_PATH = RUNTIME_DIR / "pokiequant-live-session.json"
LIVE_BTCUSDT_BAR_LIMIT = 1000

# Make repository packages importable before any cache-reset or API imports.
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Local session keys that may be persisted. ``principal_id`` is also the
# development bearer identity, so the file is owner-readable only. Provider
# tokens and API keys are always rejected.
ALLOWED_SESSION_KEYS = frozenset(
    {
        "principal_id",
        "workspace_id",
        "run_id",
        "dataset_id",
        "database_path",
        "model",
    }
)


def _deepseek_key() -> str | None:
    return os.environ.get("POKIEQUANT_AGENT_API_KEY") or os.environ.get("DEEPSEEK_API_KEY")


def resolve_model() -> str:
    return (
        os.environ.get("POKIEQUANT_AGENT_MODEL")
        or os.environ.get("DEEPSEEK_MODEL")
        or "deepseek-v4-flash"
    ).strip()


def _headers(principal_id: str, workspace_id: str | None = None) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {principal_id}",
        "Idempotency-Key": str(uuid4()),
    }
    if workspace_id:
        headers["X-Workspace-ID"] = workspace_id
    return headers


def ensure_runtime_dir() -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    OBJECT_ROOT.mkdir(parents=True, exist_ok=True)


def _configure_live_environment() -> None:
    """Point repository settings at the dedicated live runtime database.

    This mutates ``os.environ`` before repository modules are imported so that
    cached settings and SQLAlchemy engines use the live database path.

    The dedicated SQLite and object-store paths are assigned directly so the
    bootstrap uses them even when the caller has unrelated shell settings.
    Other values only default when absent so repeated invocations are stable.
    """
    os.environ["GLINT_ENVIRONMENT"] = "development"
    os.environ["GLINT_SERVICE_ROLE"] = "api"
    os.environ["GLINT_DATABASE_URL"] = f"sqlite:///{DB_PATH.resolve()}"
    os.environ["GLINT_OBJECT_STORE_BACKEND"] = "filesystem"
    os.environ["GLINT_OBJECT_STORE_ROOT"] = str(OBJECT_ROOT.resolve())
    os.environ["GLINT_CREATE_SCHEMA_ON_STARTUP"] = "true"
    # Provider/model influence recorded run provenance. The key itself is read
    # from the environment and never persisted.
    os.environ["POKIEQUANT_AGENT_PROVIDER"] = "deepseek"
    os.environ["POKIEQUANT_AGENT_MODEL"] = resolve_model()


def reset_live_caches() -> None:
    """Drop cached engines/factories so repeated invocations see the live DB."""
    # Imported here to avoid loading the repository module graph during tests
    # that only exercise the helper functions above.
    from services.api.app.db.session import reset_database_caches

    reset_database_caches()


def create_session(client: Any, principal_id: str, model: str) -> dict[str, str]:
    workspace_response = client.post(
        "/v1/workspaces",
        headers=_headers(principal_id),
        json={
            "name": "Qurio local-live workspace",
            "data_region": "local",
            "retention_policy_version": "retention-v1",
        },
    )
    workspace_response.raise_for_status()
    workspace_id = workspace_response.json()["workspace_id"]

    dataset_response = client.post(
        "/v1/quant/datasets/fetch-binance-spot",
        headers=_headers(principal_id, workspace_id),
        json={"symbol": "BTCUSDT", "limit": LIVE_BTCUSDT_BAR_LIMIT},
    )
    dataset_response.raise_for_status()
    dataset = dataset_response.json()

    project_response = client.post(
        "/v1/quant/projects",
        headers=_headers(principal_id, workspace_id),
        json={
            "name": "BTCUSDT DeepSeek autonomous research",
            "objective": (
                "Research simple, interpretable BTCUSDT daily trend strategies that improve "
                "drawdown while retaining positive return across repeated walk-forward windows."
            ),
        },
    )
    project_response.raise_for_status()
    project = project_response.json()

    run_response = client.post(
        "/v1/quant/runs",
        headers=_headers(principal_id, workspace_id),
        json={
            "project_id": project["id"],
            "mode": "auto",
            "question": (
                "Research simple, interpretable BTCUSDT daily trend strategies that improve "
                "drawdown while retaining positive return across repeated walk-forward windows."
            ),
            "expected_project_row_version": project["row_version"],
            "dataset_id": dataset["dataset_id"],
        },
    )
    run_response.raise_for_status()
    run = run_response.json()

    return {
        "principal_id": principal_id,
        "workspace_id": workspace_id,
        "run_id": run["id"],
        "dataset_id": dataset["dataset_id"],
        "database_path": str(DB_PATH.resolve()),
        "model": model,
    }


def validate_session_metadata(metadata: dict[str, Any]) -> dict[str, str]:
    """Return a sanitized copy of ``metadata`` containing only allowed keys."""
    extra = set(metadata) - ALLOWED_SESSION_KEYS
    if extra:
        raise ValueError(f"Session metadata contains disallowed keys: {sorted(extra)}")
    missing = ALLOWED_SESSION_KEYS - set(metadata)
    if missing:
        raise ValueError(f"Session metadata is missing required keys: {sorted(missing)}")
    return {key: str(value) for key, value in metadata.items()}


def write_session(metadata: dict[str, str]) -> None:
    sanitized = validate_session_metadata(metadata)
    SESSION_PATH.write_text(json.dumps(sanitized, indent=2) + "\n")
    SESSION_PATH.chmod(0o600)


def print_summary(metadata: dict[str, str]) -> None:
    print("Prepared local-live Qurio session")
    print("-" * 40)
    print(f"  principal_id: {metadata['principal_id']}")
    print(f"  workspace_id: {metadata['workspace_id']}")
    print(f"  run_id:       {metadata['run_id']}")
    print(f"  dataset_id:   {metadata['dataset_id']}")
    print(f"  model:        {metadata['model']}")
    print(f"  database:     {metadata['database_path']}")
    print(f"  session file: {SESSION_PATH.resolve()}")
    print()
    print("Next steps:")
    print("  export VITE_GLINT_ACCESS_TOKEN=<principal_id printed above>")
    print("  export DEEPSEEK_API_KEY=<your-key>")
    print("  .venv/bin/python scripts/launch_quant_live_session.py")


def main() -> int:
    if not _deepseek_key():
        print(
            "Error: a DeepSeek API key is required to record a deepseek run. "
            "Set DEEPSEEK_API_KEY or POKIEQUANT_AGENT_API_KEY.",
            file=sys.stderr,
        )
        return 1

    ensure_runtime_dir()
    _configure_live_environment()
    reset_live_caches()

    principal_id = str(uuid4())
    model = resolve_model()

    from fastapi.testclient import TestClient

    from services.api.app.main import app

    with TestClient(app) as client:
        metadata = create_session(client, principal_id, model)

    write_session(metadata)
    print_summary(metadata)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
