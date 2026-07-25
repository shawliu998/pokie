#!/usr/bin/env python3
"""Verify real DeepSeek Research Memory duplicate avoidance on a copied C5 database.

The script never fetches market data and never enables Mock fallback. It can copy the
retained C5/P5 SQLite database and create one same-window Continue / Refine, or inspect
an already preserved Run without executing another provider decision. It writes only a
sanitized P17-specific evidence file.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any
from uuid import uuid4

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = REPO_ROOT / ".run" / "c5-btc-multiinterval-20260722"
TARGET_DIR = REPO_ROOT / ".run" / "p17-research-memory-20260723"
SOURCE_DB = SOURCE_DIR / "pokiequant-live.db"
TARGET_DB = TARGET_DIR / "pokiequant-live.db"
TARGET_OBJECTS = TARGET_DIR / "pokiequant-live-objects"
EVIDENCE_PATH = TARGET_DIR / "p17-research-memory-evidence.json"
SOURCE_WORKSPACE_ID = "3ac2822d-9220-4559-9f1b-644702e80123"
SOURCE_RUN_ID = "a7bd7568-3cd5-51bc-bdb1-a655dd3d4515"
PRE_P17_BASELINE_REVISION = "20260722_0007"

FORBIDDEN_MEMORY_TERMS = frozenset(
    {
        "holdout",
        "generalization",
        "report",
        "trades",
        "bars",
        "conclusion",
        "conclusions",
        "metrics",
        "raw_response",
        "provider_response",
    }
)


def _deepseek_key_present() -> bool:
    return bool(os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("POKIEQUANT_AGENT_API_KEY"))


def _headers(principal_id: str, workspace_id: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {principal_id}",
        "X-Workspace-ID": workspace_id,
        "Idempotency-Key": str(uuid4()),
    }


def _configure_environment() -> None:
    os.environ["GLINT_ENVIRONMENT"] = "development"
    os.environ["GLINT_SERVICE_ROLE"] = "api"
    os.environ["GLINT_DATABASE_URL"] = f"sqlite:///{TARGET_DB.resolve()}"
    os.environ["GLINT_OBJECT_STORE_BACKEND"] = "filesystem"
    os.environ["GLINT_OBJECT_STORE_ROOT"] = str(TARGET_OBJECTS.resolve())
    os.environ["GLINT_CREATE_SCHEMA_ON_STARTUP"] = "false"
    os.environ["POKIEQUANT_AGENT_PROVIDER"] = "deepseek"
    os.environ["POKIEQUANT_AGENT_ALLOW_MOCK_FALLBACK"] = "false"


def _copy_runtime(*, reset: bool, resume_run_id: str | None) -> None:
    if resume_run_id is not None:
        if reset:
            raise RuntimeError("--reset and --resume-run-id cannot be used together.")
        if not TARGET_DB.is_file():
            raise RuntimeError(f"The copied P17 database is missing: {TARGET_DB}")
        TARGET_OBJECTS.mkdir(parents=True, exist_ok=True)
        return
    if not SOURCE_DB.is_file():
        raise RuntimeError(f"Required C5 source database is missing: {SOURCE_DB}")
    if TARGET_DIR.exists():
        if not reset:
            raise RuntimeError(
                f"Target directory already exists: {TARGET_DIR}; rerun with --reset."
            )
        shutil.rmtree(TARGET_DIR)
    TARGET_DIR.mkdir(parents=True)
    TARGET_OBJECTS.mkdir()
    shutil.copy2(SOURCE_DB, TARGET_DB)
    source_objects = SOURCE_DIR / "pokiequant-live-objects"
    if source_objects.is_dir():
        shutil.copytree(source_objects, TARGET_OBJECTS, dirs_exist_ok=True)


def _migrate_copy() -> None:
    # The retained C5 SQLite state predates Alembic version tracking but already
    # contains the Phase 1 schema through 0007. Establish that baseline before
    # applying only the P17 migration to the copy. Run Alembic in-process so
    # one verifier does not depend on launching another Python interpreter.
    from alembic import command
    from alembic.config import Config

    with sqlite3.connect(TARGET_DB) as connection:
        has_revision_table = (
            connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'alembic_version'"
            ).fetchone()
            is not None
        )

    config = Config(str(REPO_ROOT / "infra" / "migrations" / "alembic.ini"))
    config.attributes["database_url"] = os.environ["GLINT_DATABASE_URL"]
    try:
        if not has_revision_table:
            command.stamp(config, PRE_P17_BASELINE_REVISION)
        command.upgrade(config, "head")
    except Exception:
        raise RuntimeError("Migration of the copied P17 database failed.") from None


def _nested_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        keys = {str(key).lower() for key in value}
        for item in value.values():
            keys.update(_nested_keys(item))
        return keys
    if isinstance(value, list):
        return set().union(*(_nested_keys(item) for item in value)) if value else set()
    return set()


def _event_value(event: Any, key: str) -> Any:
    if isinstance(event, dict):
        return event.get(key)
    return getattr(event, key)


def _event_types(events: Iterable[Any]) -> set[str]:
    return {str(_event_value(event, "event_type")) for event in events}


def _memory_is_whitelisted(memory: dict[str, Any]) -> bool:
    source_keys = {
        "run_id",
        "relationship",
        "attempt_number",
        "retry_of_run_id",
        "dataset_id",
        "dataset_digest",
        "symbol",
        "interval",
        "periods_per_year",
        "range_start",
        "range_end",
        "runtime_descriptor_digest",
        "training_split_digest",
        "selection_objective",
        "comparability",
        "limitations",
    }
    candidate_keys = {
        "source_run_id",
        "candidate_key",
        "template",
        "parameters",
        "training_rank",
        "training_failure_category",
    }
    return (
        set(memory)
        == {
            "schema_version",
            "source_run_ids",
            "sources",
            "tested_candidate_keys",
            "candidates",
            "comparability",
            "context_digest",
        }
        and all(set(source) == source_keys for source in memory["sources"])
        and all(set(candidate) == candidate_keys for candidate in memory["candidates"])
    )


def _write_evidence(payload: dict[str, Any]) -> None:
    prohibited = {"tested_candidate_keys", "candidate_keys", "raw_response", "api_key"}
    if prohibited.intersection(_nested_keys(payload)):
        raise RuntimeError("Evidence payload includes prohibited sensitive or detailed fields.")
    EVIDENCE_PATH.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reset", action="store_true", help="replace the prior copied P17 runtime")
    parser.add_argument(
        "--resume-run-id",
        help=(
            "inspect an existing Run in the copied runtime without creating a new Run or "
            "executing another provider decision"
        ),
    )
    args = parser.parse_args()
    if not _deepseek_key_present():
        print("Blocked: DeepSeek credential is not configured.", file=sys.stderr)
        return 2

    print(
        (
            "P17 verifier: resuming retained runtime"
            if args.resume_run_id is not None
            else "P17 verifier: copying retained runtime"
        ),
        flush=True,
    )
    _copy_runtime(reset=args.reset, resume_run_id=args.resume_run_id)
    _configure_environment()
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    print("P17 verifier: migrating copied runtime", flush=True)
    _migrate_copy()

    from fastapi.testclient import TestClient

    from services.api.app.db.session import reset_database_caches
    from services.api.app.main import app
    from services.api.app.modules.quant.store import QuantStore
    from services.worker.app.pipelines.quant_agent import run_quant_agent_once
    from services.worker.app.quant_agent.provider import load_quant_agent_provider

    print("P17 verifier: loading copied runtime", flush=True)
    reset_database_caches()
    store = QuantStore()
    source = store.get_run(workspace_id=SOURCE_WORKSPACE_ID, run_id=SOURCE_RUN_ID)
    if source.state.value != "completed" or source.parent_run_id is None:
        raise RuntimeError("The retained P5 source Run is not a completed Continue / Refine Run.")
    if source.research_start_utc is None or source.research_end_utc is None:
        raise RuntimeError("The retained P5 source Run has no pinned UTC range.")
    reports = [
        artifact
        for artifact in store.artifacts_for_run(workspace_id=source.workspace_id, run_id=source.id)
        if artifact.kind.value == "research_report"
    ]
    if len(reports) != 1:
        raise RuntimeError("The retained P5 source Run has no unique final report.")
    seed_id = str(reports[0].content.get("selected_candidate_id") or "")
    source_candidates = {
        candidate.id: candidate
        for candidate in store.experiments_for_run(
            workspace_id=source.workspace_id, run_id=source.id
        )
    }
    if not seed_id or seed_id not in source_candidates:
        raise RuntimeError("The P5 report-selected candidate is not owned by its source Run.")
    seed_key = source_candidates[seed_id].candidate_key
    if not seed_key:
        raise RuntimeError("The P5 report-selected candidate has no canonical key.")
    project = store.get_project(workspace_id=source.workspace_id, project_id=source.project_id)

    provider = load_quant_agent_provider()
    if provider.provider_name != "openai_compatible" or provider.model_name != source.model:
        raise RuntimeError("Configured provider is not the real DeepSeek provider.")

    if args.resume_run_id is not None:
        run_id = args.resume_run_id
        print(f"P17 verifier: inspecting preserved Run {run_id}", flush=True)
        created = QuantStore().get_run(workspace_id=source.workspace_id, run_id=run_id)
        if (
            created.project_id != source.project_id
            or created.dataset_id != source.dataset_id
            or created.parent_run_id != source.id
            or created.seed_candidate_id != seed_id
        ):
            raise RuntimeError("The preserved Run does not match the pinned P17 lineage.")
    else:
        principal_id = "66c54575-9e06-45cc-b874-9669d40d451f"
        print("P17 verifier: creating same-window Continue", flush=True)
        with TestClient(app) as client:
            response = client.post(
                "/v1/quant/market-runs",
                headers=_headers(principal_id, source.workspace_id),
                json={
                    "project_id": source.project_id,
                    "mode": "auto",
                    "question": (
                        "Refine the retained same-window BTCUSDT 4h strategy without recreating "
                        "prior canonical candidates."
                    ),
                    "expected_project_row_version": project.row_version,
                    "dataset_id": source.dataset_id,
                    "research_start_utc": source.research_start_utc.isoformat(),
                    "research_end_utc": source.research_end_utc.isoformat(),
                    "parent_run_id": source.id,
                    "seed_candidate_id": seed_id,
                    "refinement_reason": (
                        "Test only canonical-distinct candidates after reviewing retained "
                        "same-window training evidence."
                    ),
                },
            )
            response.raise_for_status()
            run_id = str(response.json()["id"])

            created = QuantStore().get_run(workspace_id=source.workspace_id, run_id=run_id)

    memory = QuantStore().agent_context_data(workspace_id=source.workspace_id, run_id=run_id)[
        "research_memory"
    ]
    source_count = len(memory["source_run_ids"])
    tested_count = len(memory["tested_candidate_keys"])
    if source_count <= 0 or tested_count <= 0:
        raise RuntimeError("The new Run did not receive a non-empty pinned Research Memory.")
    memory_whitelist_accepted = _memory_is_whitelisted(memory)
    if not memory_whitelist_accepted or set(_nested_keys(memory)).intersection(
        FORBIDDEN_MEMORY_TERMS
    ):
        raise RuntimeError("Pinned Research Memory contains prohibited evidence fields.")
    if created.provider != "deepseek":
        raise RuntimeError("New Run provider identity is not deepseek.")
    if source.id not in memory["source_run_ids"]:
        raise RuntimeError("The new pinned memory does not include the P5 source Run.")
    selected_seed_memory = [
        candidate
        for candidate in memory["candidates"]
        if candidate["source_run_id"] == source.id and candidate["candidate_key"] == seed_key
    ]
    if len(selected_seed_memory) != 1 or seed_key not in memory["tested_candidate_keys"]:
        raise RuntimeError("The P5 report-selected candidate is absent from the pinned key set.")

    if args.resume_run_id is None:
        print("P17 verifier: running bounded DeepSeek Agent", flush=True)
        for _ in range(created.max_agent_iterations + 1):
            did_work = run_quant_agent_once(provider=provider, workspace_id=source.workspace_id)
            current = QuantStore().get_run(workspace_id=source.workspace_id, run_id=run_id)
            if current.state.value in {"completed", "failed", "cancelled"}:
                break
            if not did_work:
                raise RuntimeError("The Agent stopped before reaching a terminal Run state.")

    current_store = QuantStore()
    current = current_store.get_run(workspace_id=source.workspace_id, run_id=run_id)
    events = current_store.events_for_run(workspace_id=source.workspace_id, run_id=run_id)
    experiments = current_store.experiments_for_run(workspace_id=source.workspace_id, run_id=run_id)
    pinned_keys = set(memory["tested_candidate_keys"])
    created_keys = {item.candidate_key for item in experiments if item.candidate_key}
    event_types = _event_types(events)
    provider_fallback = "agent.provider_fallback" in event_types
    provider_failures = sum(
        _event_value(event, "event_type") == "agent.decision_failed" for event in events
    )
    finish_tool_completed = any(
        _event_value(event, "event_type") == "tool.completed"
        and _event_value(event, "payload").get("action") == "finish_research"
        and _event_value(event, "payload").get("success") is True
        for event in events
    )
    reports = [
        artifact
        for artifact in current_store.artifacts_for_run(
            workspace_id=source.workspace_id, run_id=run_id
        )
        if artifact.kind.value == "research_report"
    ]
    selected_candidate_id = (
        str(reports[0].content.get("selected_candidate_id") or "") if len(reports) == 1 else ""
    )
    selected_candidate_owned = selected_candidate_id in {item.id for item in experiments}
    provider_identity_verified = (
        provider.provider_name == "openai_compatible" and provider.model_name == current.model
    )
    p17_acceptance_met = bool(
        current.provider == "deepseek"
        and provider_identity_verified
        and not provider_fallback
        and provider_failures == 0
        and source_count > 0
        and tested_count > 0
        and memory_whitelist_accepted
        and len(created_keys) >= 1
        and not (created_keys & pinned_keys)
    )
    evidence = {
        "schema_version": "pokiequant-p17-research-memory-evidence-v1",
        "source_run_id": source.id,
        "run_id": run_id,
        "dataset_id": source.dataset_id,
        "runtime_descriptor_digest": current.runtime_descriptor_digest,
        "sealed_split_digest": current.runtime_split_digest,
        "provider": current.provider,
        "model": current.model,
        "provider_identity_verified": provider_identity_verified,
        "mock_fallback_allowed": False,
        "provider_fallback": provider_fallback,
        "provider_decision_failure_count": provider_failures,
        "pinned_memory_source_run_count": source_count,
        "pinned_memory_tested_candidate_count": tested_count,
        "memory_whitelist_accepted": memory_whitelist_accepted,
        "memory_forbidden_fields_present": False,
        "created_candidate_count": len(created_keys),
        "created_candidate_overlaps_pinned_memory": bool(created_keys & pinned_keys),
        "p17_acceptance_met": p17_acceptance_met,
        "state": current.state.value,
        "terminal": current.state.value in {"completed", "failed", "cancelled"},
        "strict_finish_action": current.last_action == "finish_research",
        "finish_tool_event_present": finish_tool_completed,
        "final_conclusion_present": bool(current.final_conclusion),
        "unique_final_report": len(reports) == 1,
        "selected_candidate_owned_by_run": selected_candidate_owned,
    }
    _write_evidence(evidence)
    print(json.dumps(evidence, sort_keys=True))
    if not p17_acceptance_met:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
