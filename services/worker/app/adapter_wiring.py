"""Domain adapter wiring for worker entrypoints.

Production defaults to the SQLAlchemy adapter in
``services.worker.app.repositories.sqlalchemy_adapter:create_adapter``. The
in-memory adapter is available only when GLINT_WORKER_MODE is explicitly
``test`` or ``dev``.
"""

from __future__ import annotations

import importlib
import os
from typing import Any

from services.worker.app.storage import InMemoryDomainAdapter

REQUIRED_ADAPTER_METHODS = (
    "claim_next_import_finalization_command",
    "replay_completed_import_finalization",
    "heartbeat_import_finalization",
    "get_import_session_for_finalization",
    "get_source_connection",
    "resolve_effective_consent",
    "finalize_import",
    "fail_import_finalization",
    "fail_import_session",
    "cancel_import_session",
    "get_terminal_manifest",
    "get_content_versions_for_manifest",
    "upsert_collected_raw_items",
    "get_signal_candidate_versions",
    "get_initial_baseline_projection",
    "get_source_refetch_targets",
    "persist_dedupe_assignments",
    "begin_collection_run",
    "complete_collection_run",
    "claim_due_collection_schedule",
    "heartbeat_collection_schedule",
    "release_collection_schedule",
    "complete_collection_schedule",
    "update_source_health",
    "create_signal",
    "claim_next_source_validation_job",
    "heartbeat_source_validation_job",
    "complete_source_validation_job",
    "fail_source_validation_job",
    "get_research_run",
    "claim_next_research_run_command",
    "get_content_versions_for_research_run",
    "heartbeat_research_run",
    "transition_research_run",
    "append_run_event",
    "persist_research_proposals",
)


class AdapterWiringError(RuntimeError):
    """Raised when the configured domain adapter cannot satisfy worker calls."""


def load_domain_adapter(env_var: str = "GLINT_WORKER_DOMAIN_ADAPTER") -> Any:
    mode = os.environ.get("GLINT_WORKER_MODE", "production")
    adapter_path = os.environ.get(env_var)
    if not adapter_path and mode in {"test", "dev"}:
        adapter = InMemoryDomainAdapter()
        _validate_adapter(adapter)
        return adapter
    if not adapter_path:
        adapter_path = "services.worker.app.repositories.sqlalchemy_adapter:create_adapter"
    if mode not in {"production", "test", "dev"}:
        raise AdapterWiringError("GLINT_WORKER_MODE must be production, test, or dev")
    module_name, sep, factory_name = adapter_path.partition(":")
    if not sep or not module_name or not factory_name:
        raise AdapterWiringError(f"{env_var} must be module.path:factory")
    module = importlib.import_module(module_name)
    factory = getattr(module, factory_name)
    adapter = factory()
    _validate_adapter(adapter)
    return adapter


def _validate_adapter(adapter: Any) -> None:
    missing = [
        name for name in REQUIRED_ADAPTER_METHODS if not callable(getattr(adapter, name, None))
    ]
    if missing:
        raise AdapterWiringError(f"domain adapter missing methods: {', '.join(missing)}")
