#!/usr/bin/env python3
"""Run and retain the focused V1 Kraken -> DeepSeek -> E0 proof.

The verifier creates an isolated persistent SQLite runtime, fetches one real
Kraken BTCUSD 4h dataset through the fixed D1 connector, executes one bounded
DeepSeek market Run with Mock fallback disabled, exports the server-owned E0
JSON bundle, and re-reads the same Run through the historical snapshot path.

No credential value is accepted as an argument, printed, or written. The
launch-compatible session file contains only the existing six allowlisted
session fields. A pre-existing target fails closed unless ``--reset`` is
explicit; reset preserves the old directory by moving it to a timestamped
sibling rather than deleting it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

REPO_ROOT = Path(__file__).resolve().parents[1]
# Direct script execution starts with ``scripts/`` on sys.path; make repository
# packages importable exactly as the existing live-session preparation script does.
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

V1_SCHEMA_VERSION = "qurio-v1-live-connector-proof-v1"
SESSION_FILE_NAME = "pokiequant-live-session.json"
DATABASE_FILE_NAME = "pokiequant-live.db"
OBJECT_DIRECTORY_NAME = "pokiequant-live-objects"
EVIDENCE_FILE_NAME = "v1-kraken-evidence.json"

KRAKEN_CONNECTOR_ID = "kraken-spot-ohlc-v1"
KRAKEN_FETCH_PATH = "/v1/quant/connectors/kraken-spot-ohlc-v1/fetch"
KRAKEN_SYMBOL = "BTCUSD"
KRAKEN_INTERVAL = "4h"
KRAKEN_BAR_LIMIT = 548
KRAKEN_PERIODS_PER_YEAR = 2_190
KRAKEN_TERMS_REFERENCE = "https://www.kraken.com/legal"
OFFICIAL_DEEPSEEK_BASE_URL = "https://api.deepseek.com"

RESEARCH_QUESTION = (
    "Research simple, interpretable long-or-cash BTCUSD 4h trend and breakout "
    "strategies. Compare risk-adjusted return and drawdown, make one "
    "training-evidence-driven adjustment, then stop with an honest conclusion."
)

SESSION_KEYS = frozenset(
    {
        "principal_id",
        "workspace_id",
        "run_id",
        "dataset_id",
        "database_path",
        "model",
    }
)
FORBIDDEN_EVIDENCE_KEYS = frozenset(
    {
        "api_key",
        "authorization",
        "bearer",
        "database_path",
        "deepseek_api_key",
        "pokiequant_agent_api_key",
        "principal_id",
        "prompt",
        "provider_output",
        "raw_bars",
        "secret",
        "token",
        "trace_id",
        "tool_args",
        "workspace_id",
    }
)
TERMINAL_STATES = frozenset({"completed", "failed", "cancelled"})
ITERATION_CANDIDATE_ACTIONS = frozenset({"refine_parameters", "switch_approved_family"})
STRUCTURED_STOP_ACTIONS = frozenset({"stop_insufficient_budget", "stop_no_novel_candidate"})
SAFE_EXPORT_FILE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*\.json$")
SAFE_API_ERROR_CODE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")


class V1ProofError(RuntimeError):
    """A closed, non-secret failure used by the retained proof summary."""

    def __init__(self, stage: str, code: str) -> None:
        self.stage = stage
        self.code = code
        super().__init__(f"{stage}: {code}")


@dataclass(frozen=True, slots=True)
class RuntimePaths:
    target: Path
    database: Path
    objects: Path
    session: Path
    evidence: Path


def default_target() -> Path:
    stamp = datetime.now(tz=UTC).strftime("%Y%m%d-%H%M%S")
    return REPO_ROOT / ".run" / f"v1-kraken-deepseek-{stamp}"


def prepare_target(target: Path, *, reset: bool) -> tuple[RuntimePaths, Path | None]:
    """Create one exact target, preserving an old target on explicit reset."""

    resolved = target.expanduser().resolve()
    if resolved in {Path("/").resolve(), Path.home().resolve(), REPO_ROOT.resolve()}:
        raise V1ProofError("target", "broad_target_refused")
    backup: Path | None = None
    if resolved.exists():
        if not resolved.is_dir():
            raise V1ProofError("target", "target_is_not_directory")
        if not reset:
            raise V1ProofError("target", "target_exists_use_reset_or_new_target")
        stamp = datetime.now(tz=UTC).strftime("%Y%m%d-%H%M%S")
        backup = resolved.with_name(f"{resolved.name}.previous-{stamp}-{uuid4().hex[:8]}")
        if backup.exists():
            raise V1ProofError("target", "reset_backup_collision")
        resolved.rename(backup)
    resolved.mkdir(parents=True, exist_ok=False)
    objects = resolved / OBJECT_DIRECTORY_NAME
    objects.mkdir(parents=False, exist_ok=False)
    return (
        RuntimePaths(
            target=resolved,
            database=resolved / DATABASE_FILE_NAME,
            objects=objects,
            session=resolved / SESSION_FILE_NAME,
            evidence=resolved / EVIDENCE_FILE_NAME,
        ),
        backup,
    )


def validate_session_payload(payload: dict[str, Any]) -> dict[str, str]:
    extra = set(payload) - SESSION_KEYS
    missing = SESSION_KEYS - set(payload)
    if extra or missing:
        raise V1ProofError("session", "session_metadata_shape_invalid")
    normalized = {key: str(value) for key, value in payload.items()}
    if any(not value.strip() for value in normalized.values()):
        raise V1ProofError("session", "session_metadata_value_missing")
    return normalized


def find_forbidden_evidence_key(value: Any) -> str | None:
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).lower() in FORBIDDEN_EVIDENCE_KEYS:
                return str(key)
            nested = find_forbidden_evidence_key(item)
            if nested is not None:
                return nested
    elif isinstance(value, list):
        for item in value:
            nested = find_forbidden_evidence_key(item)
            if nested is not None:
                return nested
    return None


def _write_text(path: Path, content: str) -> None:
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.chmod(0o600)
    os.replace(temporary, path)
    path.chmod(0o600)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    forbidden = find_forbidden_evidence_key(payload)
    if path.name == EVIDENCE_FILE_NAME and forbidden is not None:
        raise V1ProofError("evidence", "forbidden_evidence_field")
    rendered = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    _write_text(path, rendered)


def write_session(path: Path, payload: dict[str, Any]) -> None:
    write_json(path, validate_session_payload(payload))


def _model_name() -> str:
    return (
        os.environ.get("POKIEQUANT_AGENT_MODEL")
        or os.environ.get("DEEPSEEK_MODEL")
        or "deepseek-v4-flash"
    ).strip()


def _credential_name_is_present() -> bool:
    return bool(
        os.environ.get("POKIEQUANT_AGENT_API_KEY", "").strip()
        or os.environ.get("DEEPSEEK_API_KEY", "").strip()
    )


def _official_deepseek_origin_is_configured() -> bool:
    raw = os.environ.get(
        "POKIEQUANT_AGENT_BASE_URL",
        OFFICIAL_DEEPSEEK_BASE_URL,
    ).strip()
    try:
        parsed = urlsplit(raw)
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and parsed.hostname == "api.deepseek.com"
        and port in {None, 443}
        and parsed.username is None
        and parsed.password is None
        and parsed.path.rstrip("/") in {"", "/v1"}
        and not parsed.query
        and not parsed.fragment
    )


def _configure_runtime(paths: RuntimePaths, model: str) -> None:
    os.environ["GLINT_ENVIRONMENT"] = "development"
    os.environ["GLINT_SERVICE_ROLE"] = "api"
    os.environ["GLINT_DATABASE_URL"] = f"sqlite:///{paths.database.resolve()}"
    os.environ["GLINT_OBJECT_STORE_BACKEND"] = "filesystem"
    os.environ["GLINT_OBJECT_STORE_ROOT"] = str(paths.objects.resolve())
    os.environ["GLINT_CREATE_SCHEMA_ON_STARTUP"] = "true"
    os.environ["POKIEQUANT_AGENT_PROVIDER"] = "deepseek"
    os.environ["POKIEQUANT_AGENT_MODEL"] = model
    os.environ["POKIEQUANT_AGENT_ALLOW_MOCK_FALLBACK"] = "false"


def _headers(principal_id: str, workspace_id: str | None = None) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {principal_id}",
        "Idempotency-Key": str(uuid4()),
    }
    if workspace_id is not None:
        headers["X-Workspace-ID"] = workspace_id
    return headers


def _response_json(response: Any, *, stage: str, expected_status: int) -> Any:
    if response.status_code != expected_status:
        safe_error_code: str | None = None
        try:
            body = response.json()
        except (TypeError, ValueError):
            body = None
        if isinstance(body, dict) and isinstance(body.get("error"), dict):
            candidate = body["error"].get("code")
            if isinstance(candidate, str) and SAFE_API_ERROR_CODE.fullmatch(candidate):
                safe_error_code = candidate.lower()
        suffix = f"_{safe_error_code}" if safe_error_code is not None else ""
        raise V1ProofError(stage, f"http_{response.status_code}{suffix}")
    try:
        return response.json()
    except (TypeError, ValueError):
        raise V1ProofError(stage, "response_json_invalid") from None


def _mapping(value: Any, *, stage: str, code: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise V1ProofError(stage, code)
    return value


def _text(value: Any, *, stage: str, code: str) -> str:
    if not isinstance(value, str) or not value:
        raise V1ProofError(stage, code)
    return value


def _parse_utc(value: Any, *, stage: str, code: str) -> datetime:
    text = _text(value, stage=stage, code=code)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        raise V1ProofError(stage, code) from None
    offset = parsed.utcoffset()
    if parsed.tzinfo is None or offset is None or offset.total_seconds() != 0:
        raise V1ProofError(stage, code)
    return parsed.astimezone(UTC)


def _sha256(content: str) -> str:
    return "sha256:" + hashlib.sha256(content.encode("utf-8")).hexdigest()


def _validate_connector_directory(rows: Any) -> None:
    if not isinstance(rows, list) or len(rows) != 1:
        raise V1ProofError("connector_directory", "closed_directory_shape_changed")
    connector = _mapping(
        rows[0],
        stage="connector_directory",
        code="connector_descriptor_invalid",
    )
    expected = {
        "connector_id": KRAKEN_CONNECTOR_ID,
        "provider": "kraken_spot",
        "supported_symbols": ["BTCUSD", "BTCUSDT", "ETHUSD", "ETHUSDT"],
        "supported_intervals": ["4h", "1D"],
        "maximum_recent_bars": 719,
        "connector_version": KRAKEN_CONNECTOR_ID,
        "source_terms_url": KRAKEN_TERMS_REFERENCE,
    }
    if any(connector.get(key) != value for key, value in expected.items()):
        raise V1ProofError("connector_directory", "connector_descriptor_changed")
    if connector.get("minimum_recent_bars") != {"4h": 548, "1D": 252}:
        raise V1ProofError("connector_directory", "connector_minimum_changed")
    if connector.get("data_authenticity") != "generated":
        raise V1ProofError("connector_directory", "connector_authenticity_changed")
    if connector.get("fetch_endpoint") != KRAKEN_FETCH_PATH:
        raise V1ProofError("connector_directory", "connector_fetch_endpoint_changed")


def _validate_dataset(dataset: dict[str, Any]) -> None:
    evidence = _mapping(
        dataset.get("evidence"),
        stage="kraken_fetch",
        code="dataset_evidence_missing",
    )
    quality = _mapping(
        dataset.get("quality"),
        stage="kraken_fetch",
        code="dataset_quality_missing",
    )
    expected = {
        "symbol": KRAKEN_SYMBOL,
        "interval": KRAKEN_INTERVAL,
        "bar_count": KRAKEN_BAR_LIMIT,
        "periods_per_year": KRAKEN_PERIODS_PER_YEAR,
        "research_eligible": True,
        "data_authenticity": "collected",
    }
    if any(dataset.get(key) != value for key, value in expected.items()):
        raise V1ProofError("kraken_fetch", "dataset_contract_mismatch")
    expected_evidence = {
        "source_kind": "provider_fetch",
        "source_name": "Kraken Spot public OHLC",
        "requested_bar_count": KRAKEN_BAR_LIMIT,
        "retained_bar_count": KRAKEN_BAR_LIMIT,
        "closed_dropped_count": 1,
        "deduplicated_count": 0,
        "termination_reason": "requested_limit",
        "target_satisfied": True,
        "normalizer_version": KRAKEN_CONNECTOR_ID,
        "connector_version": KRAKEN_CONNECTOR_ID,
        "terms_reference": KRAKEN_TERMS_REFERENCE,
    }
    if any(evidence.get(key) != value for key, value in expected_evidence.items()):
        raise V1ProofError("kraken_fetch", "connector_evidence_mismatch")
    returned = evidence.get("returned_bar_count")
    if not isinstance(returned, int) or not KRAKEN_BAR_LIMIT + 1 <= returned <= 721:
        raise V1ProofError("kraken_fetch", "provider_row_boundary_invalid")
    for key in (
        "dataset_id",
        "digest",
        "record_digest",
    ):
        _text(dataset.get(key), stage="kraken_fetch", code=f"{key}_missing")
    for key in ("batch_digest", "source_request_digest"):
        value = _text(evidence.get(key), stage="kraken_fetch", code=f"{key}_missing")
        if not value.startswith("sha256:"):
            raise V1ProofError("kraken_fetch", f"{key}_invalid")
    page_hashes = evidence.get("page_raw_sha256")
    if (
        not isinstance(page_hashes, list)
        or len(page_hashes) != 1
        or not isinstance(page_hashes[0], str)
        or not page_hashes[0].startswith("sha256:")
    ):
        raise V1ProofError("kraken_fetch", "provider_page_digest_invalid")
    if quality.get("status") != "accepted" or quality.get("cadence_gap_count") != 0:
        raise V1ProofError("kraken_fetch", "dataset_cadence_not_accepted")
    covered_end = _parse_utc(
        dataset.get("covered_end"),
        stage="kraken_fetch",
        code="covered_end_invalid",
    )
    retrieved = _parse_utc(
        evidence.get("retrieved_at_utc"),
        stage="kraken_fetch",
        code="retrieved_at_invalid",
    )
    if covered_end + timedelta(hours=4) > retrieved:
        raise V1ProofError("kraken_fetch", "uncommitted_bar_entered_dataset")


def _selected_candidate(snapshot: dict[str, Any], *, stage: str) -> str:
    report = _mapping(snapshot.get("report"), stage=stage, code="report_missing")
    selection = _mapping(
        report.get("selectionDecision"),
        stage=stage,
        code="selection_decision_missing",
    )
    generalization = _mapping(
        report.get("generalization"),
        stage=stage,
        code="generalization_missing",
    )
    selected = _text(
        selection.get("selectedCandidateId"),
        stage=stage,
        code="selected_candidate_missing",
    )
    if generalization.get("selectedCandidateId") != selected:
        raise V1ProofError(stage, "report_selection_identity_mismatch")
    return selected


def _snapshot_identity(snapshot: dict[str, Any], *, stage: str) -> dict[str, Any]:
    run = _mapping(snapshot.get("run"), stage=stage, code="snapshot_run_missing")
    dataset = _mapping(
        snapshot.get("dataset"),
        stage=stage,
        code="snapshot_dataset_missing",
    )
    selected = _selected_candidate(snapshot, stage=stage)
    return {
        "run_id": run.get("id"),
        "run_state": run.get("state"),
        "provider": run.get("provider"),
        "model": run.get("model"),
        "dataset_id": dataset.get("id"),
        "dataset_digest": dataset.get("digest"),
        "symbol": dataset.get("symbol"),
        "interval": dataset.get("interval"),
        "bar_count": dataset.get("barCount"),
        "runtime_descriptor_digest": dataset.get("runtimeDescriptorDigest"),
        "sealed_split_digest": dataset.get("sealedSplitDigest"),
        "selected_candidate_id": selected,
    }


def _dataset_identity(dataset: dict[str, Any]) -> dict[str, Any]:
    evidence = _mapping(
        dataset.get("evidence"),
        stage="identity",
        code="dataset_evidence_missing",
    )
    return {
        "dataset_id": dataset.get("dataset_id"),
        "dataset_digest": dataset.get("digest"),
        "record_digest": dataset.get("record_digest"),
        "symbol": dataset.get("symbol"),
        "interval": dataset.get("interval"),
        "covered_start": dataset.get("covered_start"),
        "covered_end": dataset.get("covered_end"),
        "bar_count": dataset.get("bar_count"),
        "market_calendar": dataset.get("market_calendar"),
        "market_session": dataset.get("market_session"),
        "time_zone": dataset.get("time_zone"),
        "periods_per_year": dataset.get("periods_per_year"),
        "research_eligible": dataset.get("research_eligible"),
        "data_authenticity": dataset.get("data_authenticity"),
        "source_kind": evidence.get("source_kind"),
        "source_name": evidence.get("source_name"),
        "source_reference": evidence.get("source_reference"),
        "requested_bar_count": evidence.get("requested_bar_count"),
        "connector_version": evidence.get("connector_version"),
        "source_request_digest": evidence.get("source_request_digest"),
        "batch_digest": evidence.get("batch_digest"),
        "page_raw_sha256": evidence.get("page_raw_sha256"),
        "retrieved_at_utc": evidence.get("retrieved_at_utc"),
        "returned_bar_count": evidence.get("returned_bar_count"),
        "retained_bar_count": evidence.get("retained_bar_count"),
        "closed_dropped_count": evidence.get("closed_dropped_count"),
        "target_satisfied": evidence.get("target_satisfied"),
        "termination_reason": evidence.get("termination_reason"),
        "normalizer_version": evidence.get("normalizer_version"),
        "terms_reference": evidence.get("terms_reference"),
        "quality_status": (
            dataset.get("quality", {}).get("status")
            if isinstance(dataset.get("quality"), dict)
            else None
        ),
        "cadence_gap_count": (
            dataset.get("quality", {}).get("cadence_gap_count")
            if isinstance(dataset.get("quality"), dict)
            else None
        ),
    }


def _market_run_identity(run: dict[str, Any]) -> dict[str, Any]:
    return {
        "run_id": run.get("id"),
        "contract": run.get("schema_version"),
        "dataset_id": run.get("dataset_id"),
        "dataset_digest": run.get("dataset_digest"),
        "symbol": run.get("symbol"),
        "interval": run.get("interval"),
        "periods_per_year": run.get("periods_per_year"),
        "research_start_utc": run.get("research_start_utc"),
        "research_end_utc": run.get("research_end_utc"),
        "runtime_descriptor_digest": run.get("runtime_descriptor_digest"),
        "sealed_split_digest": run.get("sealed_split_digest"),
        "state": run.get("state"),
        "attempt_number": run.get("attempt_number"),
        "question": run.get("question"),
        "provider": run.get("provider"),
        "model": run.get("model"),
        "agent_status": run.get("agent_status"),
        "agent_iteration": run.get("agent_iteration"),
        "used_experiments": run.get("used_experiments"),
        "failure_reason": run.get("failure_reason"),
    }


def validate_agent_decision_path(
    *,
    bundle: dict[str, Any],
    candidates: list[Any],
    run: dict[str, Any],
    comparison_artifact: dict[str, Any],
) -> dict[str, Any]:
    """Require either the complete A/B -> C path or one valid structured stop."""

    plan = _mapping(bundle.get("plan"), stage="decision", code="e0_plan_missing")
    budgets = _mapping(
        plan.get("budgets"),
        stage="decision",
        code="e0_plan_budgets_missing",
    )
    if budgets.get("max_experiments") != 3:
        raise V1ProofError("decision", "iteration_experiment_budget_invalid")

    normalized: list[dict[str, Any]] = []
    candidate_ids: list[str] = []
    canonical_keys: list[str] = []
    for item in candidates:
        candidate = _mapping(
            item,
            stage="decision",
            code="e0_candidate_shape_invalid",
        )
        candidate_id = _text(
            candidate.get("candidate_id"),
            stage="decision",
            code="e0_candidate_id_missing",
        )
        canonical_key = _text(
            candidate.get("canonical_key"),
            stage="decision",
            code="e0_candidate_canonical_key_missing",
        )
        normalized.append(candidate)
        candidate_ids.append(candidate_id)
        canonical_keys.append(canonical_key)
    if len(set(candidate_ids)) != len(candidate_ids):
        raise V1ProofError("decision", "iteration_candidate_id_reused")
    if len(set(canonical_keys)) != len(canonical_keys):
        raise V1ProofError("decision", "iteration_candidate_not_novel")

    used_experiments = run.get("used_experiments")
    if isinstance(used_experiments, bool) or not isinstance(used_experiments, int):
        raise V1ProofError("decision", "run_used_experiments_invalid")
    if used_experiments != len(normalized):
        raise V1ProofError("decision", "run_candidate_count_mismatch")
    if len(normalized) not in {2, 3}:
        raise V1ProofError("decision", "iteration_requires_two_or_three_candidates")
    if any(item.get("replan_decision") is not None for item in normalized[:2]):
        raise V1ProofError("decision", "base_candidate_has_replan_decision")

    selected_result = _mapping(
        bundle.get("selected_result"),
        stage="decision",
        code="e0_selected_result_missing",
    )
    report_replan = selected_result.get("replan_decision")
    comparison_artifact_id = _text(
        comparison_artifact.get("artifact_id"),
        stage="decision",
        code="e0_comparison_artifact_id_missing",
    )

    if len(normalized) == 3:
        if report_replan is not None:
            raise V1ProofError("decision", "iteration_and_stop_decision_conflict")
        iteration_replan = _mapping(
            normalized[2].get("replan_decision"),
            stage="decision",
            code="iteration_replan_decision_missing",
        )
        action = iteration_replan.get("action")
        if action not in ITERATION_CANDIDATE_ACTIONS:
            raise V1ProofError("decision", "iteration_replan_action_invalid")
        reference_id = iteration_replan.get("improvement_reference_candidate_id")
        if reference_id not in set(candidate_ids[:2]):
            raise V1ProofError("decision", "iteration_replan_reference_invalid")
        _text(
            iteration_replan.get("source_comparison_artifact_id"),
            stage="decision",
            code="iteration_replan_comparison_missing",
        )
        return {
            "path": "A/B -> C",
            "completion_kind": "evidence_driven_iteration",
            "replan_action": action,
            "base_candidate_count": 2,
            "iteration_candidate_count": 1,
            "structured_stop": False,
        }

    if any(item.get("replan_decision") is not None for item in normalized):
        raise V1ProofError("decision", "structured_stop_requires_a_b_only")
    stop = _mapping(
        report_replan,
        stage="decision",
        code="structured_stop_missing",
    )
    action = stop.get("action")
    if action not in STRUCTURED_STOP_ACTIONS:
        raise V1ProofError("decision", "structured_stop_action_invalid")
    if stop.get("source_comparison_artifact_id") != comparison_artifact_id:
        raise V1ProofError("decision", "structured_stop_comparison_mismatch")
    if stop.get("improvement_reference_candidate_id") not in set(candidate_ids):
        raise V1ProofError("decision", "structured_stop_reference_invalid")

    if action == "stop_insufficient_budget":
        if stop.get("proposed_template") is not None or stop.get("proposed_parameters") is not None:
            raise V1ProofError("decision", "insufficient_budget_stop_has_proposal")
        max_iterations = budgets.get("max_agent_iterations")
        used_iterations = run.get("agent_iteration")
        if (
            isinstance(max_iterations, bool)
            or not isinstance(max_iterations, int)
            or isinstance(used_iterations, bool)
            or not isinstance(used_iterations, int)
            or max_iterations - used_iterations >= 4
        ):
            raise V1ProofError("decision", "structured_stop_budget_still_sufficient")
    else:
        proposed_template = _text(
            stop.get("proposed_template"),
            stage="decision",
            code="no_novel_stop_template_missing",
        )
        proposed_parameters = _mapping(
            stop.get("proposed_parameters"),
            stage="decision",
            code="no_novel_stop_parameters_missing",
        )
        from packages.domain.canonical import canonical_digest

        proposed_key = canonical_digest(
            {"template": proposed_template, "parameters": proposed_parameters}
        )
        if proposed_key not in set(canonical_keys):
            raise V1ProofError("decision", "no_novel_stop_proposal_is_novel")

    return {
        "path": "A/B -> Stop",
        "completion_kind": "structured_stop",
        "replan_action": action,
        "base_candidate_count": 2,
        "iteration_candidate_count": 0,
        "structured_stop": True,
    }


def _failure_evidence(stage: str, code: str) -> dict[str, Any]:
    return {
        "schema_version": V1_SCHEMA_VERSION,
        "status": "failed_before_terminal_evidence",
        "acceptance_met": False,
        "verified_at_utc": datetime.now(tz=UTC).isoformat(),
        "stopped_at": stage,
        "failure_code": code,
        "claims": {
            "live_market_data": None,
            "live_model": None,
            "fixture_used": False,
            "alpha_claim": False,
            "production_reliability_claim": False,
        },
    }


def _terminal_failure_evidence(
    *,
    dataset: dict[str, Any],
    run: dict[str, Any],
    event_counts: Counter[str],
    historical_identity: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "schema_version": V1_SCHEMA_VERSION,
        "status": "terminal_without_e0",
        "acceptance_met": False,
        "verified_at_utc": datetime.now(tz=UTC).isoformat(),
        "claims": {
            "live_market_data": True,
            "live_model": run.get("provider") == "deepseek",
            "fixture_used": False,
            "alpha_claim": False,
            "production_reliability_claim": False,
        },
        "connector_dataset": _dataset_identity(dataset),
        "run": _market_run_identity(run),
        "agent": {
            "mock_fallback_allowed": False,
            "provider_fallback_event_count": event_counts["agent.provider_fallback"],
            "provider_decision_failure_count": event_counts["agent.decision_failed"],
            "event_type_counts": dict(sorted(event_counts.items())),
        },
        "e0": {
            "available": False,
            "reason": "E0 requires a completed retained report-selected candidate.",
        },
        "history": {
            "reopened": historical_identity is not None,
            "identity": historical_identity,
        },
        "stopping_rule": (
            "The real connector/model outcome is retained, but V1 is incomplete. "
            "Do not substitute a fixture, Mock provider, alternate data source, or "
            "client-authored report."
        ),
    }


def run_proof(
    paths: RuntimePaths,
    *,
    model: str,
    max_worker_polls: int,
) -> tuple[dict[str, Any], str | None]:
    _configure_runtime(paths, model)

    try:
        from fastapi.testclient import TestClient

        from services.api.app.core.config import get_settings
        from services.api.app.db.session import reset_database_caches

        get_settings.cache_clear()
        reset_database_caches()

        from services.api.app.main import app
        from services.api.app.modules.quant.store import QuantStore
        from services.worker.app.pipelines.quant_agent import run_quant_agent_once
        from services.worker.app.quant_agent.provider import load_quant_agent_provider
    except Exception:
        raise V1ProofError("runtime_bootstrap", "runtime_import_failed") from None

    principal_id = str(uuid4())
    with TestClient(app) as client:
        workspace = _mapping(
            _response_json(
                client.post(
                    "/v1/workspaces",
                    headers=_headers(principal_id),
                    json={
                        "name": "Qurio V1 Kraken Connector Evidence",
                        "data_region": "local",
                        "retention_policy_version": "retention-v1",
                    },
                ),
                stage="workspace",
                expected_status=201,
            ),
            stage="workspace",
            code="workspace_response_invalid",
        )
        workspace_id = _text(
            workspace.get("workspace_id"),
            stage="workspace",
            code="workspace_id_missing",
        )

        directory = _response_json(
            client.get(
                "/v1/quant/connectors",
                headers=_headers(principal_id, workspace_id),
            ),
            stage="connector_directory",
            expected_status=200,
        )
        _validate_connector_directory(directory)

        dataset = _mapping(
            _response_json(
                client.post(
                    KRAKEN_FETCH_PATH,
                    headers=_headers(principal_id, workspace_id),
                    json={
                        "name": "BTCUSD Kraken Spot 4 hour",
                        "symbol": KRAKEN_SYMBOL,
                        "interval": KRAKEN_INTERVAL,
                        "limit": KRAKEN_BAR_LIMIT,
                    },
                ),
                stage="kraken_fetch",
                expected_status=201,
            ),
            stage="kraken_fetch",
            code="dataset_response_invalid",
        )
        _validate_dataset(dataset)
        dataset_id = _text(
            dataset.get("dataset_id"),
            stage="kraken_fetch",
            code="dataset_id_missing",
        )

        project = _mapping(
            _response_json(
                client.post(
                    "/v1/quant/projects",
                    headers=_headers(principal_id, workspace_id),
                    json={
                        "name": "BTCUSD 4h bounded connector research",
                        "objective": RESEARCH_QUESTION,
                    },
                ),
                stage="project",
                expected_status=201,
            ),
            stage="project",
            code="project_response_invalid",
        )
        project_id = _text(
            project.get("id"),
            stage="project",
            code="project_id_missing",
        )
        row_version = project.get("row_version")
        if not isinstance(row_version, int) or row_version < 1:
            raise V1ProofError("project", "project_row_version_invalid")

        created_run = _mapping(
            _response_json(
                client.post(
                    "/v1/quant/market-runs",
                    headers=_headers(principal_id, workspace_id),
                    json={
                        "project_id": project_id,
                        "mode": "auto",
                        "question": RESEARCH_QUESTION,
                        "expected_project_row_version": row_version,
                        "dataset_id": dataset_id,
                        "research_start_utc": dataset["covered_start"],
                        "research_end_utc": dataset["covered_end"],
                    },
                ),
                stage="market_run_create",
                expected_status=201,
            ),
            stage="market_run_create",
            code="market_run_response_invalid",
        )
        run_id = _text(
            created_run.get("id"),
            stage="market_run_create",
            code="run_id_missing",
        )
        write_session(
            paths.session,
            {
                "principal_id": principal_id,
                "workspace_id": workspace_id,
                "run_id": run_id,
                "dataset_id": dataset_id,
                "database_path": str(paths.database.resolve()),
                "model": model,
            },
        )

        provider = load_quant_agent_provider()
        if getattr(provider, "provider_name", None) == "mock":
            raise V1ProofError("agent", "mock_provider_loaded")
        if getattr(provider, "model_name", None) != model:
            raise V1ProofError("agent", "provider_model_mismatch")

        current = QuantStore().get_market_run(workspace_id=workspace_id, run_id=run_id)
        for _ in range(max_worker_polls):
            if current.state.value in TERMINAL_STATES:
                break
            did_work = run_quant_agent_once(
                provider=provider,
                workspace_id=workspace_id,
                worker_id="qurio-v1-kraken-verifier",
            )
            current = QuantStore().get_market_run(workspace_id=workspace_id, run_id=run_id)
            if not did_work and current.state.value not in TERMINAL_STATES:
                raise V1ProofError("agent", "worker_stalled_before_terminal_state")
        if current.state.value not in TERMINAL_STATES:
            raise V1ProofError("agent", "bounded_worker_poll_limit_reached")

        event_counts = Counter(
            event["event_type"]
            for event in QuantStore().events_for_run(
                workspace_id=workspace_id,
                run_id=run_id,
            )
        )
        current_run = _mapping(
            _response_json(
                client.get(
                    f"/v1/quant/market-runs/{run_id}",
                    headers=_headers(principal_id, workspace_id),
                ),
                stage="current_run",
                expected_status=200,
            ),
            stage="current_run",
            code="current_run_response_invalid",
        )
        if current_run.get("provider") != "deepseek" or current_run.get("model") != model:
            raise V1ProofError("agent", "retained_provider_identity_mismatch")

        if current.state.value != "completed":
            historical_response = client.get(
                f"/v1/quant/runs/{run_id}/workspace-snapshot",
                headers=_headers(principal_id, workspace_id),
            )
            historical_identity = None
            if historical_response.status_code == 200:
                historical = _mapping(
                    historical_response.json(),
                    stage="history",
                    code="historical_snapshot_invalid",
                )
                run_projection = historical.get("run")
                if isinstance(run_projection, dict) and run_projection.get("id") == run_id:
                    historical_identity = {
                        "run_id": run_id,
                        "run_state": run_projection.get("state"),
                        "dataset_id": (
                            historical.get("dataset", {}).get("id")
                            if isinstance(historical.get("dataset"), dict)
                            else None
                        ),
                    }
            return (
                _terminal_failure_evidence(
                    dataset=dataset,
                    run=current_run,
                    event_counts=event_counts,
                    historical_identity=historical_identity,
                ),
                None,
            )

        current_snapshot = _mapping(
            _response_json(
                client.get(
                    "/v1/quant/workspace-snapshot",
                    headers=_headers(principal_id, workspace_id),
                ),
                stage="current_snapshot",
                expected_status=200,
            ),
            stage="current_snapshot",
            code="current_snapshot_invalid",
        )
        current_identity = _snapshot_identity(
            current_snapshot,
            stage="current_snapshot",
        )
        selected_candidate_id = current_identity["selected_candidate_id"]

        export_payload = {
            "export_type": "strategy_evidence_bundle_json",
            "run_id": run_id,
            "candidate_id": selected_candidate_id,
        }
        current_export = _mapping(
            _response_json(
                client.post(
                    "/v1/quant/strategy-report-exports/preview",
                    headers=_headers(principal_id, workspace_id),
                    json=export_payload,
                ),
                stage="e0_current",
                expected_status=200,
            ),
            stage="e0_current",
            code="e0_response_invalid",
        )

        historical_snapshot = _mapping(
            _response_json(
                client.get(
                    f"/v1/quant/runs/{run_id}/workspace-snapshot",
                    headers=_headers(principal_id, workspace_id),
                ),
                stage="history",
                expected_status=200,
            ),
            stage="history",
            code="historical_snapshot_invalid",
        )
        historical_identity = _snapshot_identity(
            historical_snapshot,
            stage="history",
        )
        reloaded_dataset = _mapping(
            _response_json(
                client.get(
                    f"/v1/quant/datasets/v2/{dataset_id}",
                    headers=_headers(principal_id, workspace_id),
                ),
                stage="history_dataset",
                expected_status=200,
            ),
            stage="history_dataset",
            code="historical_dataset_invalid",
        )
        reloaded_run = _mapping(
            _response_json(
                client.get(
                    f"/v1/quant/market-runs/{run_id}",
                    headers=_headers(principal_id, workspace_id),
                ),
                stage="history_run",
                expected_status=200,
            ),
            stage="history_run",
            code="historical_run_invalid",
        )
        historical_export = _mapping(
            _response_json(
                client.post(
                    "/v1/quant/strategy-report-exports/preview",
                    headers=_headers(principal_id, workspace_id),
                    json=export_payload,
                ),
                stage="e0_history",
                expected_status=200,
            ),
            stage="e0_history",
            code="historical_e0_response_invalid",
        )

    if event_counts["agent.provider_fallback"]:
        raise V1ProofError("agent", "provider_fallback_detected")
    if _dataset_identity(reloaded_dataset) != _dataset_identity(dataset):
        raise V1ProofError("history", "dataset_or_connector_identity_changed")
    if _market_run_identity(reloaded_run) != _market_run_identity(current_run):
        raise V1ProofError("history", "market_run_identity_changed")
    if historical_identity != current_identity:
        raise V1ProofError("history", "workspace_snapshot_identity_changed")
    if current_export != historical_export:
        raise V1ProofError("history", "e0_export_changed_after_reopen")

    rendered_content = _text(
        current_export.get("rendered_content"),
        stage="e0",
        code="e0_rendered_content_missing",
    )
    if current_export.get("content_digest") != _sha256(rendered_content):
        raise V1ProofError("e0", "e0_content_digest_mismatch")
    filename = _text(
        current_export.get("filename"),
        stage="e0",
        code="e0_filename_missing",
    )
    if not SAFE_EXPORT_FILE.fullmatch(filename) or Path(filename).name != filename:
        raise V1ProofError("e0", "e0_filename_invalid")
    try:
        bundle = json.loads(rendered_content)
    except json.JSONDecodeError:
        raise V1ProofError("e0", "e0_bundle_json_invalid") from None
    bundle = _mapping(bundle, stage="e0", code="e0_bundle_shape_invalid")
    bundle_dataset = _mapping(
        bundle.get("dataset"),
        stage="e0",
        code="e0_dataset_missing",
    )
    bundle_source = _mapping(
        bundle_dataset.get("source_metadata"),
        stage="e0",
        code="e0_source_metadata_missing",
    )
    selected_result = _mapping(
        bundle.get("selected_result"),
        stage="e0",
        code="e0_selected_result_missing",
    )
    expected_bundle = {
        "schema_version": "strategy_evidence_bundle_v1",
        "run_id": run_id,
        "dataset_id": dataset_id,
        "dataset_digest": dataset["digest"],
        "runtime_descriptor_digest": current_run["runtime_descriptor_digest"],
        "sealed_split_digest": current_run["sealed_split_digest"],
        "selected_candidate_id": selected_candidate_id,
        "connector_version": KRAKEN_CONNECTOR_ID,
        "source_request_digest": dataset["evidence"]["source_request_digest"],
    }
    actual_bundle = {
        "schema_version": bundle.get("schema_version"),
        "run_id": (
            bundle.get("run", {}).get("run_id") if isinstance(bundle.get("run"), dict) else None
        ),
        "dataset_id": bundle_dataset.get("dataset_id"),
        "dataset_digest": bundle_dataset.get("dataset_digest"),
        "runtime_descriptor_digest": bundle_dataset.get("runtime_descriptor_digest"),
        "sealed_split_digest": bundle_dataset.get("sealed_split_digest"),
        "selected_candidate_id": selected_result.get("candidate_id"),
        "connector_version": bundle_source.get("connector_version"),
        "source_request_digest": bundle_source.get("source_request_digest"),
    }
    if actual_bundle != expected_bundle:
        raise V1ProofError("e0", "e0_identity_chain_mismatch")
    if (
        bundle_source.get("closed_dropped_count") != 1
        or bundle_source.get("terms_reference") != KRAKEN_TERMS_REFERENCE
    ):
        raise V1ProofError("e0", "e0_connector_boundary_missing")

    candidates = bundle.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise V1ProofError("e0", "e0_candidates_missing")
    selected_candidate = next(
        (
            item
            for item in candidates
            if isinstance(item, dict) and item.get("candidate_id") == selected_candidate_id
        ),
        None,
    )
    if not isinstance(selected_candidate, dict):
        raise V1ProofError("e0", "e0_selected_candidate_missing")
    canonical_key = _text(
        selected_candidate.get("canonical_key"),
        stage="e0",
        code="selected_candidate_canonical_key_missing",
    )
    validation = _mapping(
        bundle.get("validation"),
        stage="e0",
        code="e0_validation_missing",
    )
    generalization = _mapping(
        validation.get("generalization"),
        stage="e0",
        code="e0_generalization_missing",
    )
    comparison = _mapping(
        bundle.get("final_training_comparison"),
        stage="e0",
        code="e0_comparison_missing",
    )
    comparison_artifact = _mapping(
        comparison.get("artifact"),
        stage="e0",
        code="e0_comparison_artifact_missing",
    )
    decision_path = validate_agent_decision_path(
        bundle=bundle,
        candidates=candidates,
        run=current_run,
        comparison_artifact=comparison_artifact,
    )

    evidence = {
        "schema_version": V1_SCHEMA_VERSION,
        "status": "passed",
        "acceptance_met": True,
        "verified_at_utc": datetime.now(tz=UTC).isoformat(),
        "claims": {
            "live_market_data": True,
            "live_model": True,
            "fixture_used": False,
            "alpha_claim": False,
            "production_reliability_claim": False,
        },
        "connector_dataset": _dataset_identity(dataset),
        "run": _market_run_identity(current_run),
        "agent": {
            "provider": "deepseek",
            "model": model,
            "mock_fallback_allowed": False,
            "provider_fallback_event_count": event_counts["agent.provider_fallback"],
            "provider_decision_failure_count": event_counts["agent.decision_failed"],
            "event_type_counts": dict(sorted(event_counts.items())),
        },
        "decision": {
            **decision_path,
            "candidate_count": len(candidates),
            "selected_candidate_id": selected_candidate_id,
            "selected_candidate_canonical_key": canonical_key,
            "final_comparison_artifact_id": comparison_artifact.get("artifact_id"),
            "final_comparison_digest": comparison_artifact.get("stored_digest"),
            "holdout_status": generalization.get("status"),
            "next_step": selected_result.get("next_step"),
            "profitable_result_required": False,
        },
        "e0": {
            "available": True,
            "schema_version": bundle.get("schema_version"),
            "filename": filename,
            "content_digest": current_export.get("content_digest"),
            "media_type": current_export.get("media_type"),
            "run_id": current_export.get("run_id"),
            "candidate_id": current_export.get("candidate_id"),
        },
        "history": {
            "reopened": True,
            "read_only_snapshot": True,
            "current_identity": current_identity,
            "historical_identity": historical_identity,
            "dataset_record_identity_equal": True,
            "market_run_identity_equal": True,
            "e0_export_equal": True,
        },
        "limitations": [
            "This is one bounded live Kraken/DeepSeek engineering proof.",
            "It is not an alpha, profitability, production-reliability, or user-demand claim.",
            "No broker, order, arbitrary Python, shell, or eighth Research Agent tool was used.",
        ],
    }
    return evidence, rendered_content


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--target",
        type=Path,
        default=None,
        help=(
            "Dedicated output/runtime directory. Default: a new timestamped "
            ".run/v1-kraken-deepseek-* directory."
        ),
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Preserve an existing target as a timestamped sibling, then create a clean target.",
    )
    parser.add_argument(
        "--max-worker-polls",
        type=int,
        default=24,
        help="Bounded worker polls; the Run's own 12-action budget remains authoritative.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not 1 <= args.max_worker_polls <= 48:
        print("V1 verifier stopped: max worker polls must be from 1 to 48.", file=sys.stderr)
        return 2
    if not _credential_name_is_present():
        print(
            "V1 verifier stopped: configure one supported DeepSeek credential "
            "environment variable; its value is never printed or persisted.",
            file=sys.stderr,
        )
        return 2
    if not _official_deepseek_origin_is_configured():
        print(
            "V1 verifier stopped: the live-model claim requires the official "
            "https://api.deepseek.com origin.",
            file=sys.stderr,
        )
        return 2

    target = args.target if args.target is not None else default_target()
    try:
        paths, backup = prepare_target(target, reset=args.reset)
    except V1ProofError as exc:
        print(f"V1 verifier stopped at {exc.stage}: {exc.code}.", file=sys.stderr)
        return 2

    model = _model_name()
    if not model:
        write_json(paths.evidence, _failure_evidence("configuration", "model_missing"))
        print(f"V1 verifier failed; sanitized evidence: {paths.evidence}", file=sys.stderr)
        return 1

    try:
        evidence, e0_content = run_proof(
            paths,
            model=model,
            max_worker_polls=args.max_worker_polls,
        )
        e0_path: Path | None = None
        if e0_content is not None:
            e0_filename = _mapping(
                evidence.get("e0"),
                stage="evidence",
                code="e0_summary_missing",
            ).get("filename")
            if not isinstance(e0_filename, str):
                raise V1ProofError("evidence", "e0_summary_filename_missing")
            e0_path = paths.target / e0_filename
            _write_text(e0_path, e0_content)
        write_json(paths.evidence, evidence)
    except V1ProofError as exc:
        write_json(paths.evidence, _failure_evidence(exc.stage, exc.code))
        print(f"V1 verifier failed; sanitized evidence: {paths.evidence}", file=sys.stderr)
        return 1
    except Exception:  # noqa: BLE001 - retain only a closed failure code, never exception text.
        write_json(paths.evidence, _failure_evidence("unexpected", "unexpected_failure"))
        print(f"V1 verifier failed; sanitized evidence: {paths.evidence}", file=sys.stderr)
        return 1

    print(f"V1 status: {evidence['status']}")
    print(f"Sanitized evidence: {paths.evidence}")
    print(f"Launch-compatible session: {paths.session}")
    if e0_path is not None:
        print(f"Authoritative E0 bundle: {e0_path}")
    if backup is not None:
        print(f"Previous target preserved at: {backup}")
    return 0 if evidence.get("acceptance_met") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
