from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from services.api.app.db import models as m
from services.api.app.modules.common import redact
from services.api.app.modules.decisions.service import latest_freshness, synthesis_status
from services.api.app.modules.evidence.service import claim_version_status, evidence_status
from services.api.app.modules.watchlists.baseline import initial_baseline_projection


def workspace(row: m.Workspace) -> dict[str, Any]:
    return {
        "id": row.id,
        "workspace_id": row.id,
        "name": row.name,
        "status": row.status,
        "data_region": row.data_region,
        "retention_policy_version": row.retention_policy_version,
        "row_version": row.row_version,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "data_authenticity": row.data_authenticity,
    }


def project(row: m.Project) -> dict[str, Any]:
    return {
        "id": row.id,
        "workspace_id": row.workspace_id,
        "name": row.name,
        "status": row.status,
        "row_version": row.row_version,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "data_authenticity": row.data_authenticity,
    }


def audit_log(row: m.AuditLog) -> dict[str, Any]:
    safe_reason = redact(row.reason) if row.reason else None
    return {
        "id": row.id,
        "workspace_id": row.workspace_id,
        "actor_id": row.actor_id,
        "action": row.action,
        "target_type": row.target_type,
        "target_id": row.target_id,
        "before_digest": row.before_digest,
        "after_digest": row.after_digest,
        "reason": safe_reason if isinstance(safe_reason, str) else None,
        "request_id": row.request_id,
        "occurred_at": row.occurred_at,
        "data_authenticity": row.data_authenticity,
    }


def watchlist(db: Session, row: m.Watchlist) -> dict[str, Any]:
    return {
        "id": row.id,
        "workspace_id": row.workspace_id,
        "project_id": row.project_id,
        "name": row.name,
        "objective": row.objective,
        "status": row.status,
        "rules_version": row.rules_version,
        "owner_id": row.owner_id,
        "source_connection_ids": row.rules_json["source_connection_ids"],
        "rules": row.rules_json["rules"],
        "initial_baseline": initial_baseline_projection(db, row),
        "row_version": row.row_version,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "data_authenticity": row.data_authenticity,
    }


def source(db: Session, row: m.SourceConnection) -> dict[str, Any]:
    manifest = (
        db.get(m.ImportManifest, row.current_import_manifest_id)
        if row.current_import_manifest_id
        else None
    )
    imported = row.source_kind == "imported_dataset"
    last_success_at = manifest.finalized_at if manifest else row.last_success_at
    freshness_state = "current" if manifest else row.freshness_state
    if last_success_at is None:
        freshness_state = "never"
    health_state = row.health_state
    if imported:
        health_state = "healthy" if manifest else "unknown"
    capabilities = []
    if row.source_kind == "cloud":
        capabilities = ["fetch", "health"]
        if row.connector_type == "github":
            capabilities.insert(0, "search")
    return {
        "id": row.id,
        "workspace_id": row.workspace_id,
        "name": row.name,
        "source_kind": row.source_kind,
        "runtime": row.runtime,
        "connector_type": row.connector_type,
        "connector_version": row.connector_version,
        "status": row.status,
        "source_config": row.config_json or None,
        "cadence": row.cadence,
        "timezone": row.timezone,
        "last_run_at": row.last_run_at,
        "last_success_at": last_success_at,
        "health": {
            "state": health_state,
            "checked_at": row.health_checked_at,
            "last_error_code": row.health_error_code,
        },
        "freshness": {
            "last_success_at": last_success_at,
            "state": freshness_state,
        },
        "capabilities": capabilities,
        "data_scope": row.data_scope,
        "current_import_manifest": (
            {
                "id": manifest.id,
                "content_count": manifest.content_count,
                "finalized_at": manifest.finalized_at,
                "data_authenticity": manifest.data_authenticity,
            }
            if manifest
            else None
        ),
        "row_version": row.row_version,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "data_authenticity": row.data_authenticity,
    }


def source_validation_job(row: m.SourceValidationJobRecord) -> dict[str, Any]:
    safe_reason = redact(row.failure_reason) if row.failure_reason else None
    safe_code = redact(row.failure_code) if row.failure_code else None
    return {
        "id": row.id,
        "workspace_id": row.workspace_id,
        "source_connection_id": row.source_connection_id,
        "command": row.command,
        "state": row.state,
        "expected_source_row_version": row.expected_source_row_version,
        "attempt": row.attempt,
        "result_source_status": row.result_source_status,
        "failure_code": safe_code if isinstance(safe_code, str) else None,
        "failure_reason": safe_reason if isinstance(safe_reason, str) else None,
        "lease_expires_at": row.lease_expires_at if row.state == "claimed" else None,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "data_authenticity": row.data_authenticity,
    }


def import_session(row: m.ImportSession) -> dict[str, Any]:
    return {
        key: getattr(row, key)
        for key in (
            "id",
            "workspace_id",
            "source_connection_id",
            "expected_source_row_version",
            "expected_current_import_manifest_id",
            "local_manifest_digest",
            "file_digest",
            "expected_upload_digest",
            "client_file_name",
            "file_size_bytes",
            "media_type",
            "parser_version",
            "schema_version",
            "selected_scope_json",
            "selected_scope_digest",
            "state",
            "uploaded_object_key",
            "uploaded_object_digest",
            "terminal_manifest_id",
            "failure_code",
            "retryable",
            "row_version",
            "created_at",
            "updated_at",
            "data_authenticity",
        )
    }


def consent(row: m.TransferConsentRecord) -> dict[str, Any]:
    return {
        key: getattr(row, key)
        for key in (
            "id",
            "workspace_id",
            "import_session_id",
            "decision",
            "local_manifest_digest",
            "file_digest",
            "expected_upload_digest",
            "selected_scope_json",
            "selected_scope_digest",
            "destination_workspace_id",
            "upload_object_scope",
            "model_egress_authorization",
            "policy_version",
            "actor_id",
            "recorded_at",
            "expires_at",
            "supersedes_id",
            "data_authenticity",
        )
    }


def finalization_job(row: m.ImportFinalizationJobRecord) -> dict[str, Any]:
    return {
        "id": row.id,
        "command_id": row.id,
        "workspace_id": row.workspace_id,
        "import_session_id": row.import_session_id,
        "expected_session_row_version": row.expected_session_row_version,
        "expected_source_row_version": row.expected_source_row_version,
        "expected_current_import_manifest_id": row.expected_current_import_manifest_id,
        "consent_record_id": row.consent_record_id,
        "state": row.state,
        "attempt": row.attempt,
        "result_manifest_id": row.result_manifest_id,
        "failure_code": row.failure_code,
        "lease_expires_at": row.lease_expires_at,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "data_authenticity": row.data_authenticity,
    }


def manifest(row: m.ImportManifest) -> dict[str, Any]:
    return {
        "id": row.id,
        "workspace_id": row.workspace_id,
        "import_session_id": row.import_session_id,
        "source_connection_id": row.source_connection_id,
        "file_digest": row.file_digest,
        "uploaded_object_key": row.uploaded_object_key,
        "uploaded_object_digest": row.uploaded_object_digest,
        "parser_version": row.parser_version,
        "schema_version": row.schema_version,
        "selected_scope_digest": row.selected_scope_digest,
        "consent_record_id": row.consent_record_id,
        "normalized_payload_digest": row.normalized_payload_digest,
        "content_count": row.content_count,
        "finalized_at": row.finalized_at,
        "data_authenticity": row.data_authenticity,
    }


def collection_run(db: Session, row: m.CollectionRun) -> dict[str, Any]:
    raw_window = row.input_window_json or {}
    start = raw_window.get("start") or raw_window.get("current_start")
    end = raw_window.get("end") or raw_window.get("current_end")
    public_counters = {
        key: max(0, int(row.counters_json.get(key, 0)))
        for key in ("fetched", "created", "updated", "skipped", "failed")
    }
    raw_freshness = row.freshness_json or {}
    public_counters["signal_candidate_count"] = max(
        0, int(raw_freshness.get("signal_candidate_count", 0))
    )
    public_counters["signal_count"] = max(0, int(raw_freshness.get("signal_count", 0)))
    freshness_state = raw_freshness.get("state")
    if freshness_state not in {"current", "stale", "never"}:
        freshness_state = "never"
    last_success_at = raw_freshness.get("last_success_at")
    if last_success_at is None and freshness_state != "never":
        source = db.get(m.SourceConnection, row.source_connection_id)
        last_success_at = source.last_success_at if source is not None else None
    if last_success_at is None:
        freshness_state = "never"
    return {
        "id": row.id,
        "workspace_id": row.workspace_id,
        "watchlist_id": row.watchlist_id,
        "source_connection_id": row.source_connection_id,
        "state": row.state,
        "cadence": row.cadence,
        "timezone": row.timezone,
        "scheduled_for": row.scheduled_for,
        "attempt_number": row.attempt,
        "attempt_of": None,
        "backoff_until": row.backoff_until,
        "input_window": {"start": start, "end": end},
        "counters": public_counters,
        "partial_success": row.partial_success,
        "freshness": {"state": freshness_state, "last_success_at": last_success_at},
        "started_at": row.started_at,
        "finished_at": row.finished_at,
        "row_version": row.row_version,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "data_authenticity": row.data_authenticity,
    }


def content_version(db: Session, row: m.ContentVersion) -> dict[str, Any]:
    item = db.scalar(
        select(m.ContentItem).where(
            m.ContentItem.id == row.content_item_id,
            m.ContentItem.workspace_id == row.workspace_id,
        )
    )
    source = db.scalar(
        select(m.SourceConnection).where(
            m.SourceConnection.id == row.source_connection_id,
            m.SourceConnection.workspace_id == row.workspace_id,
        )
    )
    if item is None or source is None:
        raise ValueError("ContentVersion lineage is missing")
    raw_metadata = row.metadata_json or {}
    safe_metadata = {
        key: raw_metadata[key]
        for key in (
            "author",
            "canonical_url",
            "independence_group_id",
            "published_at",
            "source_item_id",
        )
        if key in raw_metadata and raw_metadata[key] is not None
    }
    return {
        "id": row.id,
        "workspace_id": row.workspace_id,
        "content_item_id": row.content_item_id,
        "source_connection_id": row.source_connection_id,
        "source_name": source.name,
        "source_kind": source.source_kind,
        "source_item_id": item.source_item_id,
        "identity_key": item.identity_key,
        "title": item.title,
        "canonical_url": item.canonical_url,
        "duplicate_cluster_id": item.duplicate_cluster_id,
        "independence_group_id": item.independence_group_id,
        "version_number": row.version_number,
        "content_digest": row.content_digest,
        "normalized_title": row.normalized_title,
        "normalized_body": row.normalized_body,
        "metadata_json": safe_metadata,
        "published_at": raw_metadata.get("published_at"),
        "captured_at": row.captured_at,
        "parser_version": row.parser_version,
        "availability": row.availability,
        "availability_last_checked_at": row.availability_last_checked_at,
        "availability_reason": row.availability_reason,
        "data_scope": source.data_scope,
        "data_authenticity": row.data_authenticity,
    }


def schedule(row: m.CollectionSchedule) -> dict[str, Any]:
    lease_held = row.lease_owner_token is not None and row.lease_expires_at is not None
    return {
        "id": row.id,
        "workspace_id": row.workspace_id,
        "source_connection_id": row.source_connection_id,
        "watchlist_id": row.watchlist_id,
        "query_json": row.query_json,
        "cadence_seconds": row.cadence_seconds,
        "timezone": row.timezone,
        "misfire_policy": row.misfire_policy,
        "catch_up": row.catch_up,
        "overlap_policy": row.overlap_policy,
        "next_run_at": row.next_run_at,
        "enabled": row.enabled,
        "lease_held": lease_held,
        "lease_expires_at": row.lease_expires_at if lease_held else None,
        "heartbeat_at": row.heartbeat_at,
        "row_version": row.row_version,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "data_authenticity": row.data_authenticity,
    }


def _signal_source_freshness(
    db: Session, row: m.Signal, source: m.SourceConnection
) -> dict[str, Any]:
    last_success_at: datetime | str | None = source.last_success_at
    state = source.freshness_state if source.freshness_state in {"current", "stale"} else "never"
    if source.source_kind == "imported_dataset":
        manifest = (
            db.get(m.ImportManifest, source.current_import_manifest_id)
            if source.current_import_manifest_id
            else None
        )
        last_success_at = manifest.finalized_at if manifest is not None else None
        state = "current" if manifest is not None else "never"
    else:
        latest_run = db.scalar(
            select(m.CollectionRun)
            .where(
                m.CollectionRun.workspace_id == row.workspace_id,
                m.CollectionRun.watchlist_id == row.watchlist_id,
                m.CollectionRun.source_connection_id == source.id,
            )
            .order_by(m.CollectionRun.created_at.desc())
            .limit(1)
        )
        if latest_run is not None:
            run_state = latest_run.freshness_json.get("state")
            if run_state in {"current", "stale", "never"}:
                state = run_state
            run_success = latest_run.freshness_json.get("last_success_at")
            if isinstance(run_success, str) and run_success:
                last_success_at = run_success
            elif last_success_at is None and latest_run.state in {"succeeded", "partial_success"}:
                last_success_at = latest_run.finished_at
    if last_success_at is None:
        state = "never"
    return {
        "source_connection_id": source.id,
        "state": state,
        "last_success_at": last_success_at,
    }


def _signal_trigger_rules(row: m.Signal, source_kinds: set[str]) -> list[str]:
    explicit = row.dimensions_json.get("trigger_rules")
    if isinstance(explicit, list) and explicit and all(isinstance(item, str) for item in explicit):
        return explicit
    metrics = row.metrics_json
    if source_kinds == {"imported_dataset"}:
        return ["static_import_content_count > 0"]
    policy = row.dimensions_json.get("detector_policy")
    if not isinstance(policy, dict):
        policy = metrics.get("detector_policy")
    rules = [f"detector_version = {row.detector_version}"]
    if not isinstance(policy, dict):
        return rules
    if policy.get("require_current_mentions", True):
        rules.append("mention_count > 0")
    minimum_sources = policy.get("min_independent_sources")
    if isinstance(minimum_sources, int) and not isinstance(minimum_sources, bool):
        rules.append(f"independent_source_count >= {minimum_sources}")
    maximum_duplicates = policy.get("max_duplicate_concentration")
    if isinstance(maximum_duplicates, int | float) and not isinstance(maximum_duplicates, bool):
        rules.append(f"duplicate_concentration < {maximum_duplicates:g}")
    minimum_growth = policy.get("min_growth_ratio")
    minimum_z = policy.get("min_robust_z")
    if all(
        isinstance(value, int | float) and not isinstance(value, bool)
        for value in (minimum_growth, minimum_z)
    ):
        rules.append(f"growth_ratio >= {minimum_growth:g} OR robust_z >= {minimum_z:g}")
    return rules


def _signal_limitations(row: m.Signal, source_kinds: set[str]) -> list[str]:
    explicit = row.dimensions_json.get("limitations")
    limitations = (
        [item for item in explicit if isinstance(item, str) and item]
        if isinstance(explicit, list)
        else []
    )
    if source_kinds == {"imported_dataset"} and not limitations:
        limitations.append("Static import has no continuous freshness.")
    if (
        source_kinds
        and source_kinds != {"imported_dataset"}
        and not isinstance(
            row.dimensions_json.get("detector_policy") or row.metrics_json.get("detector_policy"),
            dict,
        )
    ):
        limitations.append("Detector policy threshold snapshot is unavailable.")
    if "imported_dataset" in source_kinds and len(source_kinds) > 1:
        limitations.append("Signal combines imported and continuously collected evidence.")
    return list(dict.fromkeys(limitations))


def signal(db: Session, row: m.Signal) -> dict[str, Any]:
    evidence_source_ids = db.scalars(
        select(m.ContentVersion.source_connection_id)
        .join(
            m.SignalEvidence,
            m.SignalEvidence.content_version_id == m.ContentVersion.id,
        )
        .where(
            m.SignalEvidence.workspace_id == row.workspace_id,
            m.SignalEvidence.signal_id == row.id,
        )
    ).all()
    source_ids = sorted(set(evidence_source_ids))
    sources = (
        list(
            db.scalars(
                select(m.SourceConnection).where(
                    m.SourceConnection.workspace_id == row.workspace_id,
                    m.SourceConnection.id.in_(source_ids),
                )
            ).all()
        )
        if source_ids
        else []
    )
    source_kinds = {source.source_kind for source in sources}
    mention_count = int(row.metrics_json.get("mention_count", len(evidence_source_ids)))
    baseline_count = int(row.metrics_json.get("baseline_mention_count", 0))
    metrics = {
        "current_count": int(row.metrics_json.get("current_count", mention_count)),
        "baseline_count": baseline_count,
        "mention_count": mention_count,
        "independent_source_count": int(
            row.metrics_json.get("independent_source_count", len(source_ids))
        ),
        "platform_count": int(
            row.metrics_json.get(
                "platform_count", len({source.connector_type for source in sources})
            )
        ),
        "growth_ratio": float(
            row.metrics_json.get("growth_ratio", mention_count / max(baseline_count, 1))
        ),
        "robust_z": float(row.metrics_json.get("robust_z", 0.0)),
    }
    raw_dimensions = row.dimensions_json or {}
    dimension_defaults: dict[str, dict[str, Any]] = {
        "detection_confidence": {
            "level": "low",
            "calibration_status": "uncalibrated",
            "explanation": "Legacy Signal projected without a detector confidence snapshot.",
        },
        "business_impact": {
            "suggested_level": None,
            "suggested_explanation": None,
            "suggestion_origin": "none",
            "suggestion_version": None,
            "confirmed_level": None,
            "confirmed_by": None,
            "confirmed_at": None,
            "version": 0,
        },
        "urgency": {
            "suggested_level": None,
            "suggested_explanation": None,
            "suggestion_origin": "none",
            "suggestion_version": None,
            "confirmed_level": None,
            "confirmed_by": None,
            "confirmed_at": None,
            "version": 0,
        },
        "priority": {
            "level": None,
            "status": "pending_confirmation",
            "policy_version": "priority-matrix-v1",
            "explanation": "Impact and urgency require atomic PM confirmation.",
        },
    }
    dimensions = {
        key: {**default, **dict(raw_dimensions.get(key, {}))}
        for key, default in dimension_defaults.items()
    }
    dimensions["business_impact"].setdefault("version", 0)
    dimensions["urgency"].setdefault("version", 0)
    current_end = row.updated_at or row.created_at
    default_window = {
        "current_start": current_end - timedelta(days=7),
        "current_end": current_end,
        "baseline_start": current_end - timedelta(days=35),
        "baseline_end": current_end - timedelta(days=7),
    }
    window = {**default_window, **(row.window_json or {})}
    return {
        "id": row.id,
        "workspace_id": row.workspace_id,
        "watchlist_id": row.watchlist_id,
        "title": row.title,
        "status": row.status,
        "detector_version": row.detector_version,
        "trigger_rules": _signal_trigger_rules(row, source_kinds),
        "limitations": _signal_limitations(row, source_kinds),
        "total_source_count": len(source_ids),
        "independent_source_count": metrics["independent_source_count"],
        "cross_source_confirmation": bool(
            (row.dimensions_json.get("source_coverage") or {}).get(
                "cross_source_confirmed",
                metrics["platform_count"] >= 2 and len(source_ids) >= 2,
            )
        ),
        "per_source_freshness": [
            _signal_source_freshness(db, row, source)
            for source in sorted(sources, key=lambda item: item.id)
        ],
        "window": window,
        "metrics": metrics,
        "dimensions": dimensions,
        "disposition": row.disposition_json or None,
        "row_version": row.row_version,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "data_authenticity": row.data_authenticity,
    }


def investigation(db: Session, row: m.Investigation) -> dict[str, Any]:
    scope = db.get(m.InvestigationScopeVersion, row.current_scope_version_id)
    return {
        "id": row.id,
        "workspace_id": row.workspace_id,
        "project_id": row.project_id,
        "signal_id": row.signal_id,
        "current_scope_version_id": row.current_scope_version_id,
        "status": row.status,
        "owner_id": row.owner_id,
        "current_synthesis_id": row.current_synthesis_id,
        "decision_brief_id": row.decision_brief_id,
        "decision_question": scope.decision_question if scope else "Missing scope",
        "row_version": row.row_version,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "data_authenticity": row.data_authenticity,
    }


def scope(row: m.InvestigationScopeVersion) -> dict[str, Any]:
    return {
        "id": row.id,
        "workspace_id": row.workspace_id,
        "investigation_id": row.investigation_id,
        "version_number": row.version_number,
        "decision_question": row.decision_question,
        "source_scope_json": row.source_scope_json,
        "time_range": row.time_range_json,
        "budget": row.budget_json,
        "stop_conditions": row.stop_conditions,
        "created_by": row.created_by,
        "change_reason": row.change_reason,
        "created_at": row.created_at,
        "data_authenticity": row.data_authenticity,
    }


def research_run(row: m.ResearchRun) -> dict[str, Any]:
    manifest = row.run_input_manifest_json or {}
    provider = str(manifest.get("provider") or "deterministic")
    prompt_refs = [str(item) for item in manifest.get("prompt_refs", []) if item]
    return {
        "id": row.id,
        "workspace_id": row.workspace_id,
        "investigation_id": row.investigation_id,
        "investigation_scope_version_id": row.investigation_scope_version_id,
        "state": row.state,
        "waiting_for_input_reason": None,
        "graph_version": row.graph_version,
        "generation_method": str(
            manifest.get("generation_method")
            or ("model" if provider != "deterministic" else "deterministic")
        ),
        "provider": provider,
        "model": manifest.get("model"),
        "prompt_refs": prompt_refs,
        "trace_ref": manifest.get("trace_ref"),
        "run_input_manifest_digest": row.run_input_manifest_digest,
        "budget": row.budget_json,
        "used_cost_usd": row.used_cost,
        "attempt_number": row.attempt_number,
        "initiated_by": row.initiated_by,
        "latest_sequence": row.latest_sequence,
        "row_version": row.row_version,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "data_authenticity": row.data_authenticity,
    }


def evidence(db: Session, row: m.Evidence) -> dict[str, Any]:
    latest_review = db.scalar(
        select(m.EvidenceReview)
        .where(m.EvidenceReview.evidence_id == row.id)
        .order_by(m.EvidenceReview.reviewed_at.desc(), m.EvidenceReview.id.desc())
        .limit(1)
    )
    return {
        "id": row.id,
        "workspace_id": row.workspace_id,
        "investigation_id": row.investigation_id,
        "research_run_id": row.research_run_id,
        "content_version_id": row.content_version_id,
        "quote_start": row.quote_start,
        "quote_end": row.quote_end,
        "quote_text": row.quote_text,
        "quote_text_digest": row.quote_text_digest,
        "stance": row.stance,
        "status": evidence_status(db, row.id),
        "latest_review": (
            {
                "id": latest_review.id,
                "decision": latest_review.decision,
                "policy_version": latest_review.policy_version,
                "reviewed_at": latest_review.reviewed_at,
            }
            if latest_review is not None
            else None
        ),
        "relevance": row.relevance,
        "reliability": row.reliability,
        "independence": row.independence,
        "recency": row.recency,
        "specificity": row.specificity,
        "provenance": {
            "research_run_id": row.research_run_id,
            "extraction_method": row.extraction_method,
        },
        "data_authenticity": row.data_authenticity,
    }


def claim_version(db: Session, row: m.ClaimVersion, claim: m.Claim) -> dict[str, Any]:
    return {
        "id": row.id,
        "claim_id": row.claim_id,
        "version_number": row.version_number,
        "claim_type": row.claim_type,
        "text": row.text,
        "confidence_inputs_json": row.confidence_inputs_json,
        "confidence_score": row.confidence_score,
        "confidence_level": row.confidence_level,
        "confidence_policy_version": row.confidence_policy_version,
        "confidence_input_digest": row.confidence_input_digest,
        "calibration_status": row.calibration_status,
        "limitations": row.limitations,
        "generation_method": row.generation_method,
        "generator_version": row.generator_version,
        "suggestion_origin": row.suggestion_origin,
        "status": claim_version_status(db, row.id),
        "created_by": row.created_by,
        "created_at": row.created_at,
        "data_authenticity": row.data_authenticity,
    }


def claim(db: Session, row: m.Claim) -> dict[str, Any]:
    version = db.get(m.ClaimVersion, row.current_version_id)
    if version is None:
        raise ValueError("Claim current version is missing")
    links = db.scalars(
        select(m.ClaimEvidence).where(m.ClaimEvidence.claim_version_id == version.id)
    ).all()
    return {
        "id": row.id,
        "workspace_id": row.workspace_id,
        "investigation_id": row.investigation_id,
        "research_run_id": row.research_run_id,
        "current_version": claim_version(db, version, row),
        "evidence_links": [
            {
                "id": link.id,
                "evidence_id": link.evidence_id,
                "stance": link.stance,
                "weight": link.weight,
                "rationale": link.rationale,
            }
            for link in links
        ],
        "owner_id": row.owner_id,
        "row_version": row.row_version,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "data_authenticity": row.data_authenticity,
    }


def synthesis_version(
    db: Session, row: m.InvestigationSynthesisVersion, investigation_id: str
) -> dict[str, Any]:
    return {
        "id": row.id,
        "synthesis_id": row.synthesis_id,
        "investigation_id": investigation_id,
        "version_number": row.version_number,
        "verified_claim_version_snapshot_json": row.verified_claim_version_snapshot_json,
        "claim_review_snapshot_json": row.claim_review_snapshot_json,
        "generation_method": row.generation_method,
        "generator_version": row.generator_version,
        "model_prompt_refs_json": row.model_prompt_refs_json,
        "executive_summary": row.executive_summary,
        "business_implications": row.business_implications,
        "limitations": row.limitations,
        "provenance_digest": row.provenance_digest,
        "status": synthesis_status(db, row.id),
        "created_by": row.created_by,
        "created_at": row.created_at,
        "data_authenticity": row.data_authenticity,
    }


def synthesis(db: Session, row: m.InvestigationSynthesis) -> dict[str, Any]:
    version = db.get(m.InvestigationSynthesisVersion, row.current_version_id)
    if version is None:
        raise ValueError("Synthesis current version is missing")
    return {
        "id": row.id,
        "workspace_id": row.workspace_id,
        "investigation_id": row.investigation_id,
        "current_version": synthesis_version(db, version, row.investigation_id),
        "row_version": row.row_version,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "data_authenticity": row.data_authenticity,
    }


def brief_version(
    db: Session, row: m.DecisionBriefVersion, investigation_id: str
) -> dict[str, Any]:
    ready = db.scalar(
        select(func.count(m.DecisionBriefReadinessReview.id)).where(
            m.DecisionBriefReadinessReview.decision_brief_version_id == row.id,
            m.DecisionBriefReadinessReview.decision == "mark_decision_ready",
        )
    )
    freshness = latest_freshness(db, row.id)
    return {
        "id": row.id,
        "decision_brief_id": row.decision_brief_id,
        "investigation_id": investigation_id,
        "version_number": row.version_number,
        "synthesis_version_id": row.synthesis_version_id,
        "synthesis_review_id": row.synthesis_review_id,
        "block_document": row.block_document,
        "reference_snapshot_json": row.reference_snapshot_json,
        "template_version": row.template_version,
        "human_edit_digest": row.human_edit_digest,
        "readiness": "decision_ready" if ready else "draft",
        "freshness": freshness.status if freshness else "current",
        "created_by": row.created_by,
        "created_at": row.created_at,
        "data_authenticity": row.data_authenticity,
    }


def brief(db: Session, row: m.DecisionBrief) -> dict[str, Any]:
    version = db.get(m.DecisionBriefVersion, row.current_version_id)
    if version is None:
        raise ValueError("Brief current version is missing")
    return {
        "id": row.id,
        "workspace_id": row.workspace_id,
        "investigation_id": row.investigation_id,
        "current_version": brief_version(db, version, row.investigation_id),
        "status": row.status,
        "owner_id": row.owner_id,
        "decision_outcome": row.decision_outcome,
        "next_checkpoint_at": row.next_checkpoint_at,
        "row_version": row.row_version,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "data_authenticity": row.data_authenticity,
    }


def brief_export(row: m.BriefExport) -> dict[str, Any]:
    return {
        "id": row.id,
        "workspace_id": row.workspace_id,
        "decision_brief_version_id": row.decision_brief_version_id,
        "export_type": row.export_type,
        "destination": row.destination,
        "selection_manifest_json": row.selection_manifest_json,
        "reference_digest": row.reference_digest,
        "policy_version": row.policy_version,
        "template_version": row.template_version,
        "output_digest": row.output_digest,
        "created_by": row.created_by,
        "created_at": row.created_at,
        "data_authenticity": row.data_authenticity,
    }
