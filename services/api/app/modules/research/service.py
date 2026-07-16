from __future__ import annotations

from datetime import timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from services.api.app.core.errors import ApiError, invalid_state, not_found, version_conflict
from services.api.app.db.models import (
    Claim,
    ClaimEvidence,
    ClaimVersion,
    CollectionRun,
    ContentVersion,
    Evidence,
    ImportManifest,
    ImportManifestContentVersion,
    ImportSession,
    Investigation,
    InvestigationScopeVersion,
    RawContentItem,
    ResearchRun,
    Signal,
    SignalEvidence,
    SourceConnection,
    Watchlist,
)
from services.api.app.modules.common import (
    append_run_event,
    audit,
    digest,
    lock_investigation_lineage,
    text_digest,
    utcnow,
)
from services.api.app.modules.evidence.confidence import assess_frozen_claim_evidence


def _require_atomic_signal_triage(signal: Signal) -> None:
    impact = (signal.dimensions_json or {}).get("business_impact", {})
    urgency = (signal.dimensions_json or {}).get("urgency", {})
    if (
        signal.status != "triaged"
        or impact.get("confirmed_level") is None
        or impact.get("confirmed_by") is None
        or impact.get("confirmed_at") is None
        or urgency.get("confirmed_level") is None
        or urgency.get("confirmed_by") is None
        or urgency.get("confirmed_at") is None
    ):
        raise ApiError(
            409,
            "TRIAGE_REQUIRED",
            "Impact and Urgency must be confirmed by one atomic Signal triage before research.",
        )


def create_investigation(
    db: Session,
    *,
    workspace_id: str,
    actor_id: str,
    payload: dict[str, Any],
    request_id: str,
) -> Investigation:
    signal = db.scalar(
        select(Signal).where(Signal.id == payload["signal_id"], Signal.workspace_id == workspace_id)
    )
    if signal is None:
        raise not_found("Signal")
    watchlist = db.scalar(
        select(Watchlist).where(
            Watchlist.id == signal.watchlist_id,
            Watchlist.workspace_id == workspace_id,
        )
    )
    if watchlist is None:
        raise not_found("Watchlist")
    existing = db.scalar(
        select(Investigation).where(
            Investigation.workspace_id == workspace_id,
            Investigation.signal_id == signal.id,
            Investigation.status.not_in(("cancelled", "closed_insufficient")),
        )
    )
    if existing:
        return existing
    _require_atomic_signal_triage(signal)
    _validate_source_scope(
        db,
        workspace_id,
        payload["source_scope"],
        signal=signal,
        watchlist=watchlist,
    )
    investigation = Investigation(
        workspace_id=workspace_id,
        project_id=watchlist.project_id,
        signal_id=signal.id,
        status="draft",
        owner_id=actor_id,
        data_authenticity=signal.data_authenticity,
    )
    db.add(investigation)
    db.flush()
    scope = InvestigationScopeVersion(
        workspace_id=workspace_id,
        investigation_id=investigation.id,
        version_number=1,
        decision_question=payload["decision_question"],
        source_scope_json=payload["source_scope"],
        time_range_json=payload["time_range"],
        budget_json=payload["budget"],
        stop_conditions=payload["stop_conditions"],
        created_by=actor_id,
        change_reason="Initial investigation scope",
        data_authenticity=signal.data_authenticity,
    )
    db.add(scope)
    db.flush()
    investigation.current_scope_version_id = scope.id
    audit(
        db,
        workspace_id=workspace_id,
        actor_id=actor_id,
        action="investigation.created",
        target_type="Investigation",
        target_id=investigation.id,
        request_id=request_id,
        after={"signal_id": signal.id, "scope_version_id": scope.id},
    )
    db.commit()
    return investigation


def revise_investigation_scope(
    db: Session,
    *,
    investigation: Investigation,
    actor_id: str,
    payload: dict[str, Any],
    request_id: str,
) -> Investigation:
    investigation = lock_investigation_lineage(
        db,
        workspace_id=investigation.workspace_id,
        investigation_id=investigation.id,
    )
    if investigation.row_version != payload["expected_row_version"]:
        raise version_conflict(investigation.id, investigation.row_version)
    if investigation.status not in {"draft", "needs_input"}:
        raise invalid_state("Only draft or needs-input Investigations can change scope.")
    signal = db.get(Signal, investigation.signal_id)
    watchlist = db.get(Watchlist, signal.watchlist_id) if signal is not None else None
    if signal is None or watchlist is None:
        raise not_found("Signal Watchlist")
    _validate_source_scope(
        db,
        investigation.workspace_id,
        payload["source_scope"],
        signal=signal,
        watchlist=watchlist,
    )
    latest = db.scalar(
        select(func.coalesce(func.max(InvestigationScopeVersion.version_number), 0)).where(
            InvestigationScopeVersion.investigation_id == investigation.id
        )
    )
    scope = InvestigationScopeVersion(
        workspace_id=investigation.workspace_id,
        investigation_id=investigation.id,
        version_number=int(latest or 0) + 1,
        decision_question=payload["decision_question"],
        source_scope_json=payload["source_scope"],
        time_range_json=payload["time_range"],
        budget_json=payload["budget"],
        stop_conditions=payload["stop_conditions"],
        created_by=actor_id,
        change_reason=payload["change_reason"],
        data_authenticity=investigation.data_authenticity,
    )
    db.add(scope)
    db.flush()
    investigation.current_scope_version_id = scope.id
    investigation.row_version += 1
    audit(
        db,
        workspace_id=investigation.workspace_id,
        actor_id=actor_id,
        action="investigation.scope_revised",
        target_type="Investigation",
        target_id=investigation.id,
        request_id=request_id,
        after={"scope_version_id": scope.id},
        reason=payload["change_reason"],
    )
    db.commit()
    return investigation


def transition_investigation(
    db: Session,
    *,
    investigation: Investigation,
    actor_id: str,
    action: str,
    expected_row_version: int,
    reason: str,
    request_id: str,
) -> Investigation:
    if investigation.row_version != expected_row_version:
        raise version_conflict(investigation.id, investigation.row_version)
    transitions = {
        ("active", "request_input"): "needs_input",
        ("needs_input", "provide_input"): "active",
        ("active", "start_review"): "reviewing",
        ("needs_input", "start_review"): "reviewing",
        ("reviewing", "complete"): "completed",
        ("active", "close_insufficient"): "closed_insufficient",
        ("needs_input", "close_insufficient"): "closed_insufficient",
    }
    if action == "cancel" and investigation.status in {
        "draft",
        "active",
        "needs_input",
        "reviewing",
    }:
        target = "cancelled"
    else:
        target = transitions.get((investigation.status, action))
    if target is None:
        raise invalid_state(f"Cannot {action} an Investigation in {investigation.status}.")
    before = investigation.status
    investigation.status = target
    investigation.row_version += 1
    audit(
        db,
        workspace_id=investigation.workspace_id,
        actor_id=actor_id,
        action=f"investigation.{action}",
        target_type="Investigation",
        target_id=investigation.id,
        request_id=request_id,
        before={"status": before},
        after={"status": target},
        reason=reason,
    )
    db.commit()
    return investigation


def _collection_run_snapshot(row: CollectionRun) -> dict[str, Any]:
    snapshot: dict[str, Any] = {
        "collection_run_id": row.id,
        "source_connection_id": row.source_connection_id,
        "watchlist_id": row.watchlist_id,
        "stable_key": row.stable_key,
        "state": row.state,
        "scheduled_for": row.scheduled_for.isoformat(),
        "attempt": row.attempt,
        "input_window": row.input_window_json,
        "counters": row.counters_json,
        "partial_success": row.partial_success,
        "freshness": row.freshness_json,
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "finished_at": row.finished_at.isoformat() if row.finished_at else None,
        "data_authenticity": row.data_authenticity,
    }
    return {**snapshot, "collection_run_digest": digest(snapshot)}


def _resolve_signal_content_lineage(
    db: Session,
    *,
    workspace_id: str,
    signal: Signal,
    watchlist: Watchlist,
    sources: dict[str, SourceConnection],
    requested_content_ids: list[str],
) -> dict[str, list[dict[str, Any]]]:
    evidence_rows = db.execute(
        select(SignalEvidence.content_version_id, SignalEvidence.independence_group_id)
        .join(ContentVersion, ContentVersion.id == SignalEvidence.content_version_id)
        .where(
            SignalEvidence.workspace_id == workspace_id,
            SignalEvidence.signal_id == signal.id,
            ContentVersion.workspace_id == workspace_id,
            ContentVersion.source_connection_id.in_(sources),
        )
        .order_by(SignalEvidence.content_version_id)
    ).all()
    evidence_groups = {
        content_version_id: group_id for content_version_id, group_id in evidence_rows
    }
    evidence_ids = list(evidence_groups)
    content_ids = [str(value) for value in requested_content_ids] or evidence_ids
    if not content_ids or len(content_ids) != len(set(content_ids)):
        raise ApiError(
            422, "SOURCE_SCOPE_BLOCKED", "Signal content selection is empty or repeated."
        )
    if not set(content_ids).issubset(evidence_ids):
        raise ApiError(
            422,
            "SOURCE_SCOPE_BLOCKED",
            "Every selected ContentVersion must be frozen SignalEvidence for this Signal.",
        )
    rows = db.execute(
        select(ContentVersion, RawContentItem)
        .join(RawContentItem, RawContentItem.id == ContentVersion.raw_content_item_id)
        .where(
            ContentVersion.workspace_id == workspace_id,
            ContentVersion.id.in_(content_ids),
            RawContentItem.workspace_id == workspace_id,
        )
    ).all()
    if len(rows) != len(content_ids):
        raise ApiError(422, "LINEAGE_INTEGRITY_ERROR", "Content raw lineage is incomplete.")

    terminal_manifests: dict[str, dict[str, Any]] = {}
    terminal_collection_runs: dict[str, dict[str, Any]] = {}
    content_snapshots: list[dict[str, Any]] = []
    represented_sources: set[str] = set()
    for version, raw in rows:
        source = sources.get(version.source_connection_id)
        if source is None or raw.source_connection_id != source.id:
            raise ApiError(
                422, "SOURCE_SCOPE_BLOCKED", "Content escaped the selected source scope."
            )
        represented_sources.add(source.id)
        base: dict[str, Any] = {
            "content_version_id": version.id,
            "content_digest": version.content_digest,
            "source_connection_id": source.id,
            "data_authenticity": version.data_authenticity,
            "raw_content_item_id": raw.id,
            "raw_snapshot_uri": raw.raw_snapshot_uri,
            "raw_digest": raw.raw_digest,
            "signal_evidence_independence_group_id": evidence_groups[version.id],
        }
        if source.source_kind == "imported_dataset":
            if (
                version.data_authenticity != "imported"
                or raw.data_authenticity != "imported"
                or raw.import_manifest_id is None
                or raw.collection_run_id is not None
                or source.current_import_manifest_id is None
            ):
                raise ApiError(
                    422, "LINEAGE_INTEGRITY_ERROR", "Imported content origin is inconsistent."
                )
            manifest = db.scalar(
                select(ImportManifest)
                .join(
                    ImportManifestContentVersion,
                    ImportManifestContentVersion.import_manifest_id == ImportManifest.id,
                )
                .where(
                    ImportManifest.id == source.current_import_manifest_id,
                    ImportManifest.workspace_id == workspace_id,
                    ImportManifest.source_connection_id == source.id,
                    ImportManifestContentVersion.content_version_id == version.id,
                )
            )
            manifest_session = (
                db.get(ImportSession, manifest.import_session_id) if manifest else None
            )
            raw_manifest = db.get(ImportManifest, raw.import_manifest_id)
            raw_session = (
                db.get(ImportSession, raw_manifest.import_session_id)
                if raw_manifest is not None
                else None
            )
            if (
                manifest is None
                or manifest_session is None
                or manifest_session.state != "finalized"
                or manifest_session.terminal_manifest_id != manifest.id
                or raw_manifest is None
                or raw_session is None
                or raw_session.state != "finalized"
                or raw_session.terminal_manifest_id != raw_manifest.id
            ):
                raise ApiError(
                    422,
                    "LINEAGE_INTEGRITY_ERROR",
                    "Imported content is not linked to terminal manifests.",
                )
            terminal_manifests[manifest.id] = {
                "import_manifest_id": manifest.id,
                "source_connection_id": manifest.source_connection_id,
                "file_digest": manifest.file_digest,
                "uploaded_object_digest": manifest.uploaded_object_digest,
                "normalized_payload_digest": manifest.normalized_payload_digest,
            }
            content_snapshots.append(
                {
                    **base,
                    "origin_type": "imported",
                    "import_manifest_id": manifest.id,
                    "raw_origin_import_manifest_id": raw_manifest.id,
                    "collection_run_id": None,
                }
            )
        elif source.source_kind == "cloud":
            if (
                version.data_authenticity != "collected"
                or raw.data_authenticity != "collected"
                or raw.import_manifest_id is not None
                or raw.collection_run_id is None
                or evidence_groups[version.id] is None
            ):
                raise ApiError(
                    422,
                    "LINEAGE_INTEGRITY_ERROR",
                    "Collected content origin or independence group is inconsistent.",
                )
            collection_run = db.get(CollectionRun, raw.collection_run_id)
            if (
                collection_run is None
                or collection_run.workspace_id != workspace_id
                or collection_run.source_connection_id != source.id
                or collection_run.watchlist_id != watchlist.id
                or collection_run.state not in {"succeeded", "partial_success"}
                or collection_run.finished_at is None
            ):
                raise ApiError(
                    422,
                    "LINEAGE_INTEGRITY_ERROR",
                    "Collected content requires a terminal CollectionRun for this "
                    "Signal Watchlist.",
                )
            terminal_collection_runs[collection_run.id] = _collection_run_snapshot(collection_run)
            content_snapshots.append(
                {
                    **base,
                    "origin_type": "collected",
                    "import_manifest_id": None,
                    "collection_run_id": collection_run.id,
                }
            )
        else:
            raise ApiError(422, "SOURCE_SCOPE_BLOCKED", "Local-device content is not available.")
    if represented_sources != set(sources):
        raise ApiError(
            422,
            "SOURCE_SCOPE_BLOCKED",
            "Every selected source must contribute SignalEvidence to the frozen run input.",
        )
    return {
        "terminal_import_manifests": sorted(
            terminal_manifests.values(), key=lambda item: item["import_manifest_id"]
        ),
        "terminal_collection_runs": sorted(
            terminal_collection_runs.values(), key=lambda item: item["collection_run_id"]
        ),
        "content_versions": sorted(content_snapshots, key=lambda item: item["content_version_id"]),
    }


def _validate_source_scope(
    db: Session,
    workspace_id: str,
    source_scope: dict[str, Any],
    *,
    signal: Signal,
    watchlist: Watchlist,
) -> tuple[dict[str, SourceConnection], dict[str, list[dict[str, Any]]]]:
    if source_scope.get("allow_cloud_model"):
        raise ApiError(403, "POLICY_BLOCKED", "Deterministic research forbids cloud models.")
    source_ids = [str(value) for value in source_scope.get("source_connection_ids", [])]
    if not source_ids or len(source_ids) != len(set(source_ids)):
        raise ApiError(422, "SOURCE_SCOPE_BLOCKED", "At least one source is required.")
    if signal.watchlist_id != watchlist.id or watchlist.workspace_id != workspace_id:
        raise ApiError(422, "SOURCE_SCOPE_BLOCKED", "Signal Watchlist scope is inconsistent.")
    approved_source_ids = {
        str(value) for value in (watchlist.rules_json or {}).get("source_connection_ids", [])
    }
    if not set(source_ids).issubset(approved_source_ids):
        raise ApiError(
            422,
            "SOURCE_SCOPE_BLOCKED",
            "Every source must be approved by the Signal Watchlist.",
        )
    source_rows = db.scalars(
        select(SourceConnection).where(
            SourceConnection.workspace_id == workspace_id,
            SourceConnection.id.in_(source_ids),
        )
    ).all()
    if len(source_rows) != len(source_ids):
        raise ApiError(422, "SOURCE_SCOPE_BLOCKED", "Source scope contains unavailable content.")
    sources = {row.id: row for row in source_rows}
    for source in source_rows:
        imported_ready = (
            source.source_kind == "imported_dataset"
            and source.runtime == "static_import"
            and source.current_import_manifest_id is not None
        )
        cloud_ready = (
            source.source_kind == "cloud"
            and source.runtime == "cloud"
            and source.connector_type in {"github", "rss"}
            and source.approved_by is not None
            and source.status in {"healthy", "degraded"}
        )
        if not imported_ready and not cloud_ready:
            raise ApiError(
                422,
                "SOURCE_SCOPE_BLOCKED",
                "Source scope requires a current import or approved healthy/degraded cloud source.",
            )
    lineage = _resolve_signal_content_lineage(
        db,
        workspace_id=workspace_id,
        signal=signal,
        watchlist=watchlist,
        sources=sources,
        requested_content_ids=[str(value) for value in source_scope.get("content_version_ids", [])],
    )
    return sources, lineage


def _validate_v2_run_lineage(db: Session, manifest: dict[str, Any], workspace_id: str) -> None:
    collection_snapshots = {
        item["collection_run_id"]: item for item in manifest.get("terminal_collection_runs", [])
    }
    import_snapshots = {
        item["import_manifest_id"]: item for item in manifest.get("terminal_import_manifests", [])
    }
    for content in manifest.get("content_versions", []):
        import_manifest_id = content.get("import_manifest_id")
        collection_run_id = content.get("collection_run_id")
        if (import_manifest_id is None) == (collection_run_id is None):
            raise ApiError(
                422,
                "LINEAGE_INTEGRITY_ERROR",
                "RunInputManifest content must have exactly one frozen origin.",
            )
        version = db.get(ContentVersion, content["content_version_id"])
        raw = db.get(RawContentItem, content["raw_content_item_id"])
        signal_evidence = db.scalar(
            select(SignalEvidence).where(
                SignalEvidence.workspace_id == workspace_id,
                SignalEvidence.signal_id == manifest["signal_id"],
                SignalEvidence.content_version_id == content["content_version_id"],
            )
        )
        if (
            version is None
            or raw is None
            or signal_evidence is None
            or version.workspace_id != workspace_id
            or raw.workspace_id != workspace_id
            or version.raw_content_item_id != raw.id
            or version.source_connection_id != content["source_connection_id"]
            or raw.source_connection_id != content["source_connection_id"]
            or version.content_digest != content["content_digest"]
            or version.data_authenticity != content["data_authenticity"]
            or raw.raw_digest != content["raw_digest"]
            or raw.raw_snapshot_uri != content["raw_snapshot_uri"]
            or signal_evidence.independence_group_id
            != content.get("signal_evidence_independence_group_id")
        ):
            raise ApiError(422, "LINEAGE_INTEGRITY_ERROR", "Frozen content lineage changed.")
        if collection_run_id is not None:
            snapshot = collection_snapshots.get(collection_run_id)
            collection_run = db.get(CollectionRun, collection_run_id)
            if (
                snapshot is None
                or collection_run is None
                or raw.collection_run_id != collection_run_id
                or raw.import_manifest_id is not None
                or collection_run.state not in {"succeeded", "partial_success"}
                or collection_run.finished_at is None
                or _collection_run_snapshot(collection_run) != snapshot
            ):
                raise ApiError(
                    422, "LINEAGE_INTEGRITY_ERROR", "Frozen CollectionRun lineage changed."
                )
        else:
            snapshot = import_snapshots.get(import_manifest_id)
            imported = db.get(ImportManifest, import_manifest_id)
            session = db.get(ImportSession, imported.import_session_id) if imported else None
            linked = db.scalar(
                select(ImportManifestContentVersion.id).where(
                    ImportManifestContentVersion.import_manifest_id == import_manifest_id,
                    ImportManifestContentVersion.content_version_id == version.id,
                )
            )
            if (
                snapshot is None
                or imported is None
                or session is None
                or session.state != "finalized"
                or session.terminal_manifest_id != imported.id
                or linked is None
                or raw.import_manifest_id is None
                or raw.collection_run_id is not None
                or snapshot
                != {
                    "import_manifest_id": imported.id,
                    "source_connection_id": imported.source_connection_id,
                    "file_digest": imported.file_digest,
                    "uploaded_object_digest": imported.uploaded_object_digest,
                    "normalized_payload_digest": imported.normalized_payload_digest,
                }
            ):
                raise ApiError(
                    422, "LINEAGE_INTEGRITY_ERROR", "Frozen ImportManifest lineage changed."
                )


def create_research_run(
    db: Session,
    *,
    workspace_id: str,
    actor_id: str,
    payload: dict[str, Any],
    request_id: str,
) -> tuple[ResearchRun, dict[str, Any]]:
    investigation = db.scalar(
        select(Investigation).where(
            Investigation.id == payload["investigation_id"],
            Investigation.workspace_id == workspace_id,
        )
    )
    if investigation is None:
        raise not_found("Investigation")
    if investigation.row_version != payload["expected_investigation_row_version"]:
        raise version_conflict(investigation.id, investigation.row_version)
    if investigation.status not in {"draft", "active", "needs_input"}:
        raise invalid_state("Research Runs require a draft, active, or needs-input Investigation.")
    scope = db.scalar(
        select(InvestigationScopeVersion).where(
            InvestigationScopeVersion.id == payload["investigation_scope_version_id"],
            InvestigationScopeVersion.investigation_id == investigation.id,
        )
    )
    if scope is None or scope.id != investigation.current_scope_version_id:
        raise ApiError(412, "VERSION_CONFLICT", "The selected Investigation scope is not current.")
    if payload["source_scope"] != scope.source_scope_json:
        raise ApiError(412, "VERSION_CONFLICT", "Run source scope must match the pinned scope.")
    signal = db.get(Signal, investigation.signal_id)
    watchlist = db.get(Watchlist, signal.watchlist_id) if signal is not None else None
    if signal is None or watchlist is None:
        raise not_found("Signal Watchlist")
    first_activation = investigation.status == "draft"
    if first_activation:
        _require_atomic_signal_triage(signal)
    sources, lineage = _validate_source_scope(
        db,
        workspace_id,
        payload["source_scope"],
        signal=signal,
        watchlist=watchlist,
    )
    if payload["question"] != scope.decision_question:
        raise ApiError(
            422, "SOURCE_SCOPE_BLOCKED", "Run question must match the pinned scope version."
        )
    v2 = any(source.source_kind == "cloud" for source in sources.values())
    graph_version = "deterministic-content-v2" if v2 else "deterministic-import-v1"
    content_snapshots = lineage["content_versions"]
    if not v2:
        content_snapshots = [
            {
                "content_version_id": item["content_version_id"],
                "content_digest": item["content_digest"],
                "import_manifest_id": item["import_manifest_id"],
            }
            for item in content_snapshots
        ]
    content_ids = [item["content_version_id"] for item in content_snapshots]
    manifest = {
        "schema_version": "run-input-manifest-v2" if v2 else "run-input-manifest-v1",
        "investigation_scope_version_id": scope.id,
        "signal_id": investigation.signal_id,
        "question": payload["question"],
        "source_scope": {**payload["source_scope"], "content_version_ids": list(content_ids)},
        "terminal_import_manifests": lineage["terminal_import_manifests"],
        "content_versions": content_snapshots,
        "time_range": payload["time_range"],
        "budget": payload["budget"],
        "provider": "deterministic",
        "graph_version": graph_version,
        "tool_policy_version": "read-only-v1",
    }
    if v2:
        manifest["terminal_collection_runs"] = lineage["terminal_collection_runs"]
    attempt = db.scalar(
        select(func.count(ResearchRun.id)).where(ResearchRun.investigation_id == investigation.id)
    )
    trace_id = uuid4().hex
    run = ResearchRun(
        workspace_id=workspace_id,
        investigation_id=investigation.id,
        investigation_scope_version_id=scope.id,
        state="queued",
        graph_version=graph_version,
        run_input_manifest_json=manifest,
        run_input_manifest_digest=digest(manifest),
        budget_json=payload["budget"],
        attempt_number=int(attempt or 0) + 1,
        initiated_by=actor_id,
        trace_id=trace_id,
        data_authenticity=investigation.data_authenticity,
    )
    db.add(run)
    db.flush()
    if first_activation:
        investigation.status = "active"
        investigation.row_version += 1
        signal.status = "investigating"
        signal.row_version += 1
        append_run_event(
            db,
            workspace_id=workspace_id,
            investigation_id=investigation.id,
            run_id=run.id,
            event_type="investigation.started_from_signal",
            payload={
                "signal_id": signal.id,
                "investigation_scope_version_id": scope.id,
                "safe_summary": "Triaged Signal activated by its first immutable Research Run.",
            },
            trace_id=trace_id,
            event_idempotency_key=f"investigation:{investigation.id}:started-from-signal",
        )
    append_run_event(
        db,
        workspace_id=workspace_id,
        investigation_id=investigation.id,
        run_id=run.id,
        event_type="run.queued",
        payload={"state": "queued", "safe_summary": "Immutable run input accepted."},
        trace_id=trace_id,
        event_idempotency_key=f"run:{run.id}:queued",
    )
    audit(
        db,
        workspace_id=workspace_id,
        actor_id=actor_id,
        action="research_run.queued",
        target_type="ResearchRun",
        target_id=run.id,
        request_id=request_id,
        after={
            "manifest_digest": run.run_input_manifest_digest,
            "first_activation": first_activation,
            "signal_status": signal.status,
        },
    )
    db.commit()
    command = {
        "workspace_id": workspace_id,
        "run_id": run.id,
        "actor_id": actor_id,
        "request_id": request_id,
    }
    return run, command


class ResearchRunResultRepository:
    """Worker-facing persistence adapter; it validates proposals but never runs a provider."""

    @classmethod
    def claim_queued(
        cls,
        db: Session,
        *,
        workspace_id: str,
        worker_id: str,
        worker_attempt_id: str,
        lease_seconds: int = 120,
        run_id: str | None = None,
    ) -> ResearchRun | None:
        now = utcnow()
        query = select(ResearchRun.id).where(
            ResearchRun.workspace_id == workspace_id,
            (
                (
                    (ResearchRun.state == "queued")
                    & (
                        ResearchRun.worker_lease_expires_at.is_(None)
                        | (ResearchRun.worker_lease_expires_at <= now)
                    )
                )
                | (
                    (ResearchRun.state == "running")
                    & (
                        ResearchRun.worker_lease_expires_at.is_(None)
                        | (ResearchRun.worker_lease_expires_at <= now)
                    )
                )
            ),
        )
        if run_id:
            query = query.where(ResearchRun.id == run_id)
        candidate = db.scalar(query.order_by(ResearchRun.created_at).limit(1))
        if candidate is None:
            return None
        claimed = db.scalar(
            update(ResearchRun)
            .where(
                ResearchRun.id == candidate,
                ResearchRun.workspace_id == workspace_id,
                ResearchRun.state.in_(("queued", "running")),
                (
                    ResearchRun.worker_lease_expires_at.is_(None)
                    | (ResearchRun.worker_lease_expires_at <= now)
                ),
            )
            .values(
                worker_claimed_by=worker_id,
                worker_attempt_id=worker_attempt_id,
                worker_lease_expires_at=now + timedelta(seconds=lease_seconds),
                worker_heartbeat_at=now,
                worker_fencing_version=ResearchRun.worker_fencing_version + 1,
            )
            .returning(ResearchRun.id)
        )
        if claimed is None:
            db.rollback()
            return None
        db.commit()
        return db.get(ResearchRun, claimed)

    @classmethod
    def mark_started(
        cls, db: Session, *, workspace_id: str, run_id: str, worker_attempt_id: str
    ) -> ResearchRun:
        run = db.scalar(
            select(ResearchRun).where(
                ResearchRun.id == run_id,
                ResearchRun.workspace_id == workspace_id,
            )
        )
        if run is None:
            raise not_found("Research Run")
        if run.worker_attempt_id != worker_attempt_id or run.worker_lease_expires_at is None:
            raise invalid_state("The worker must atomically claim the queued Research Run.")
        if run.worker_lease_expires_at <= utcnow():
            raise ApiError(409, "JOB_LEASE_EXPIRED", "The Research Run lease expired.")
        if run.state == "running":
            return run
        if run.state != "queued":
            raise invalid_state("Only a queued Research Run can start.")
        run.state = "running"
        run.row_version += 1
        append_run_event(
            db,
            workspace_id=workspace_id,
            investigation_id=run.investigation_id,
            run_id=run.id,
            event_type="run.started",
            payload={"state": "running", "safe_summary": "Deterministic worker started."},
            trace_id=run.trace_id,
            event_idempotency_key=f"worker:{worker_attempt_id}:started",
        )
        db.commit()
        return run

    @classmethod
    def heartbeat(
        cls,
        db: Session,
        *,
        workspace_id: str,
        run_id: str,
        worker_attempt_id: str,
        expected_fencing_version: int,
        lease_seconds: int = 120,
    ) -> ResearchRun:
        now = utcnow()
        updated = db.scalar(
            update(ResearchRun)
            .where(
                ResearchRun.id == run_id,
                ResearchRun.workspace_id == workspace_id,
                ResearchRun.state == "running",
                ResearchRun.worker_attempt_id == worker_attempt_id,
                ResearchRun.worker_fencing_version == expected_fencing_version,
                ResearchRun.worker_lease_expires_at > now,
            )
            .values(
                worker_heartbeat_at=now,
                worker_lease_expires_at=now + timedelta(seconds=lease_seconds),
            )
            .returning(ResearchRun.id)
        )
        if updated is None:
            db.rollback()
            raise ApiError(409, "JOB_LEASE_EXPIRED", "The Research Run lease is invalid.")
        db.commit()
        run = db.get(ResearchRun, updated)
        if run is None:
            raise not_found("Research Run")
        return run

    @classmethod
    def persist_deterministic_result(
        cls,
        db: Session,
        *,
        workspace_id: str,
        run_id: str,
        actor_id: str,
        request_id: str,
        worker_attempt_id: str,
        evidence_proposals: list[dict[str, Any]],
        claim_proposal: dict[str, Any],
    ) -> tuple[list[Evidence], ClaimVersion]:
        run = db.scalar(
            select(ResearchRun).where(
                ResearchRun.id == run_id,
                ResearchRun.workspace_id == workspace_id,
            )
        )
        if run is None:
            raise not_found("Research Run")
        if run.state == "completed":
            existing_evidence = db.scalars(
                select(Evidence).where(Evidence.research_run_id == run.id)
            ).all()
            existing_version = db.scalar(
                select(ClaimVersion)
                .join(Claim, Claim.id == ClaimVersion.claim_id)
                .where(Claim.research_run_id == run.id)
                .order_by(ClaimVersion.version_number.desc())
            )
            if existing_evidence and existing_version:
                return list(existing_evidence), existing_version
        if run.state != "running":
            raise invalid_state("The worker must start the Research Run before persisting results.")
        if run.worker_attempt_id != worker_attempt_id or run.worker_lease_expires_at is None:
            raise invalid_state("The worker does not own this Research Run attempt.")
        if run.worker_lease_expires_at <= utcnow():
            raise ApiError(409, "JOB_LEASE_EXPIRED", "The Research Run lease expired.")
        if run.run_input_manifest_json.get("schema_version") == "run-input-manifest-v2":
            _validate_v2_run_lineage(db, run.run_input_manifest_json, workspace_id)
        pinned = {
            item["content_version_id"]: item["content_digest"]
            for item in run.run_input_manifest_json["content_versions"]
        }
        if not evidence_proposals:
            raise ApiError(422, "VALIDATION_ERROR", "At least one Evidence proposal is required.")
        content_ids = [proposal.get("content_version_id") for proposal in evidence_proposals]
        if not set(content_ids).issubset(pinned):
            raise ApiError(
                422, "SOURCE_SCOPE_BLOCKED", "Evidence escaped the pinned content manifest."
            )
        versions = {
            row.id: row
            for row in db.scalars(
                select(ContentVersion).where(
                    ContentVersion.workspace_id == workspace_id,
                    ContentVersion.id.in_(content_ids),
                )
            ).all()
        }
        evidence_rows: list[Evidence] = []
        injection_flag = False
        for index, proposal in enumerate(evidence_proposals):
            version = versions.get(proposal["content_version_id"])
            if version is None or version.content_digest != pinned[version.id]:
                raise ApiError(422, "LINEAGE_INTEGRITY_ERROR", "Pinned content digest changed.")
            start = int(proposal["quote_start"])
            end = int(proposal["quote_end"])
            if start < 0 or end <= start or end > len(version.normalized_body):
                raise ApiError(422, "VALIDATION_ERROR", "Evidence quote range is invalid.")
            quote = version.normalized_body[start:end]
            injection_flag = injection_flag or any(
                marker in version.normalized_body.lower()
                for marker in ("ignore system", "exfiltrate", "call shell", "reveal token")
            )
            scores = [
                float(proposal[key])
                for key in ("relevance", "reliability", "independence", "recency", "specificity")
            ]
            if any(score < 0 or score > 1 for score in scores):
                raise ApiError(422, "VALIDATION_ERROR", "Evidence scores must be within 0..1.")
            evidence = Evidence(
                workspace_id=workspace_id,
                investigation_id=run.investigation_id,
                research_run_id=run.id,
                content_version_id=version.id,
                quote_start=start,
                quote_end=end,
                quote_text=quote,
                quote_text_digest=text_digest(quote),
                stance=proposal["stance"],
                relevance=scores[0],
                reliability=scores[1],
                independence=scores[2],
                recency=scores[3],
                specificity=scores[4],
                extraction_method=(
                    "deterministic_content_v2"
                    if run.graph_version == "deterministic-content-v2"
                    else "deterministic_import_v1"
                ),
                data_authenticity=run.data_authenticity,
            )
            db.add(evidence)
            db.flush()
            evidence_rows.append(evidence)
            append_run_event(
                db,
                workspace_id=workspace_id,
                investigation_id=run.investigation_id,
                run_id=run.id,
                event_type="evidence.proposed",
                payload={"evidence_id": evidence.id},
                trace_id=run.trace_id,
                event_idempotency_key=f"worker:{worker_attempt_id}:evidence:{index}",
            )
        claim = Claim(
            workspace_id=workspace_id,
            investigation_id=run.investigation_id,
            research_run_id=run.id,
            aggregate_status="needs_review",
            owner_id=actor_id,
            data_authenticity=run.data_authenticity,
        )
        db.add(claim)
        db.flush()
        confidence = assess_frozen_claim_evidence(
            db,
            evidence_rows=evidence_rows,
            links_by_evidence_id={
                evidence.id: {
                    "stance": proposal["stance"],
                    "weight": round(1 / len(evidence_rows), 4),
                }
                for proposal, evidence in zip(evidence_proposals, evidence_rows, strict=True)
            },
        )
        limitations = list(claim_proposal.get("limitations", []))
        frozen_origins = {
            item.get("origin_type", "imported")
            for item in run.run_input_manifest_json["content_versions"]
        }
        limitations.extend(
            item
            for item in (
                "Imported static dataset; no continuous-source freshness."
                if "imported" in frozen_origins
                else None,
                "Collected content is pinned to terminal CollectionRun snapshots."
                if "collected" in frozen_origins
                else None,
                "Deterministic output; not model-generated research.",
                "Untrusted instruction-like text was flagged for human review."
                if injection_flag
                else None,
            )
            if item and item not in limitations
        )
        generation_method = str(claim_proposal.get("generation_method", "deterministic"))
        suggestion_origin = str(claim_proposal.get("suggestion_origin", "deterministic_rule"))
        if generation_method != "deterministic" or suggestion_origin != "deterministic_rule":
            raise ApiError(
                422,
                "VALIDATION_ERROR",
                "The deterministic ResearchRun cannot persist model or human Claim provenance.",
            )
        claim_version = ClaimVersion(
            workspace_id=workspace_id,
            claim_id=claim.id,
            version_number=1,
            claim_type=claim_proposal["claim_type"],
            text=claim_proposal["text"],
            confidence_inputs_json=confidence.breakdown,
            confidence_score=confidence.score.as_float,
            confidence_level=confidence.score.level.value,
            confidence_policy_version=confidence.score.policy_version,
            confidence_input_digest=confidence.input_digest,
            limitations=limitations,
            generation_method=generation_method,
            generator_version=str(claim_proposal.get("generator_version", run.graph_version)),
            suggestion_origin=suggestion_origin,
            created_by=actor_id,
            data_authenticity=run.data_authenticity,
        )
        db.add(claim_version)
        db.flush()
        claim.current_version_id = claim_version.id
        for proposal, evidence in zip(evidence_proposals, evidence_rows, strict=True):
            db.add(
                ClaimEvidence(
                    workspace_id=workspace_id,
                    claim_version_id=claim_version.id,
                    evidence_id=evidence.id,
                    stance=proposal["stance"],
                    weight=round(1 / len(evidence_rows), 4),
                    rationale="Validated worker proposal against the immutable RunInputManifest.",
                    linked_by=actor_id,
                    data_authenticity=run.data_authenticity,
                )
            )
        append_run_event(
            db,
            workspace_id=workspace_id,
            investigation_id=run.investigation_id,
            run_id=run.id,
            event_type="claim.version_proposed",
            payload={
                "claim_id": claim.id,
                "claim_version_id": claim_version.id,
            },
            trace_id=run.trace_id,
            event_idempotency_key=f"worker:{worker_attempt_id}:claim",
        )
        if injection_flag:
            append_run_event(
                db,
                workspace_id=workspace_id,
                investigation_id=run.investigation_id,
                run_id=run.id,
                event_type="review.required",
                payload={
                    "target_type": "ClaimVersion",
                    "target_id": claim_version.id,
                    "reason_code": "prompt_injection_marker",
                },
                trace_id=run.trace_id,
                event_idempotency_key=f"worker:{worker_attempt_id}:injection-review",
            )
        run.state = "completed"
        run.worker_lease_expires_at = None
        run.worker_heartbeat_at = None
        run.row_version += 1
        append_run_event(
            db,
            workspace_id=workspace_id,
            investigation_id=run.investigation_id,
            run_id=run.id,
            event_type="run.completed",
            payload={
                "state": "completed",
                "safe_summary": "Evidence and Claim proposal persisted.",
            },
            trace_id=run.trace_id,
            event_idempotency_key=f"worker:{worker_attempt_id}:completed",
        )
        audit(
            db,
            workspace_id=workspace_id,
            actor_id=actor_id,
            action="research_run.completed",
            target_type="ResearchRun",
            target_id=run.id,
            request_id=request_id,
            after={"evidence_count": len(evidence_rows), "claim_version_id": claim_version.id},
        )
        db.commit()
        return evidence_rows, claim_version


def latest_sequence(db: Session, run_id: str) -> int:
    return int(db.scalar(select(ResearchRun.latest_sequence).where(ResearchRun.id == run_id)) or 0)
