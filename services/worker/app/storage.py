"""In-memory domain adapter used by tests and early worker integration.

The adapter is deliberately small but enforces the same safety properties the
real API/domain service must enforce: exact consent, terminal manifests, source
pointer compare-and-set, idempotent content versions, and durable RunEvents.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from packages.domain.errors import ObjectScopeMismatch
from packages.domain.imports import require_import_payload_object_key
from services.worker.app.contracts import (
    ClaimVersionProposal,
    CollectionLeaseContext,
    ConsentDecision,
    ConsentError,
    ContentItem,
    ContentVersion,
    EvidenceProposal,
    ImportFinalizationCommand,
    ImportManifest,
    ImportSession,
    ImportSessionState,
    InitialBaselineProjection,
    ManifestProcessingCommand,
    NonTerminalImportError,
    ObjectStore,
    ObjectVerificationError,
    RawContentItem,
    ResearchRun,
    ResearchRunClaim,
    ResearchRunState,
    RunEvent,
    ScheduledCollectionClaim,
    Signal,
    SignalPersistenceResult,
    SourceConnection,
    SourceHealthStatus,
    SourcePointerError,
    SourceRefetchTarget,
    SourceValidationClaim,
    StoredObject,
    SynthesisProposal,
    TransferConsentRecord,
    now_utc,
)
from services.worker.app.pipelines.digests import deterministic_id
from services.worker.app.run_events import validate_run_event_payload

_SOURCE_VALIDATION_FENCE_DRIFT_CODE = "SOURCE_VALIDATION_FENCE_DRIFT"
_SOURCE_VALIDATION_FENCE_DRIFT_REASON = "The source changed after this validation was queued."


@dataclass(slots=True)
class MemoryImportFinalizationRecord:
    command: ImportFinalizationCommand
    state: str = "queued"
    attempt: int = 0
    result_manifest_id: str | None = None
    failure_code: str | None = None
    retryable: bool = False
    claimed_by: str | None = None
    lease_expires_at: datetime | None = None


class MemoryObjectStore(ObjectStore):
    def __init__(self) -> None:
        self.objects: dict[str, StoredObject] = {}
        self.quarantined: dict[str, str] = {}

    def put_object(self, obj: StoredObject) -> None:
        self.objects[obj.key] = obj

    def get_import_object(
        self,
        *,
        workspace_id: str,
        import_session_id: str,
        key: str,
    ) -> StoredObject:
        try:
            require_import_payload_object_key(workspace_id, import_session_id, key)
            stored = self.objects[key]
            require_import_payload_object_key(workspace_id, import_session_id, stored.key)
        except ObjectScopeMismatch as exc:
            raise ObjectVerificationError("object key is outside the import workspace") from exc
        return stored

    def quarantine_import_object(
        self,
        *,
        workspace_id: str,
        import_session_id: str,
        key: str,
        reason: str,
    ) -> None:
        try:
            require_import_payload_object_key(workspace_id, import_session_id, key)
        except ObjectScopeMismatch as exc:
            raise ObjectVerificationError("object key is outside the import workspace") from exc
        self.quarantined[key] = reason


class InMemoryDomainAdapter:
    def __init__(self) -> None:
        self.sources: dict[str, SourceConnection] = {}
        self.import_sessions: dict[str, ImportSession] = {}
        self.consents: list[TransferConsentRecord] = []
        self.manifests: dict[str, ImportManifest] = {}
        self.raw_items: dict[str, RawContentItem] = {}
        self.content_items: dict[str, ContentItem] = {}
        self.content_versions: dict[str, ContentVersion] = {}
        self.manifest_versions: dict[str, list[str]] = {}
        self.collection_versions: dict[str, list[str]] = {}
        self.collection_keys: set[str] = set()
        self.signals: dict[str, Signal] = {}
        self.research_runs: dict[str, ResearchRun] = {}
        self.research_run_claims: dict[str, dict[str, Any]] = {}
        self.run_events: dict[str, list[RunEvent]] = {}
        self.evidence: dict[str, EvidenceProposal] = {}
        self.claims: dict[str, ClaimVersionProposal] = {}
        self.syntheses: dict[str, SynthesisProposal] = {}
        self.health_updates: dict[str, dict[str, Any]] = {}
        self.import_finalization_jobs: dict[str, MemoryImportFinalizationRecord] = {}
        self.collection_runs: dict[str, dict[str, Any]] = {}
        self.collection_schedules: dict[str, dict[str, Any]] = {}
        self.source_validation_jobs: dict[str, dict[str, Any]] = {}

    def enqueue_import_finalization(self, command: ImportFinalizationCommand) -> None:
        self.import_finalization_jobs[command.finalize_command_id] = MemoryImportFinalizationRecord(
            command
        )

    def claim_next_import_finalization_command(
        self,
        worker_id: str,
        lease_for: timedelta,
    ) -> ImportFinalizationCommand | None:
        now = now_utc()
        for record in sorted(
            self.import_finalization_jobs.values(), key=lambda row: row.command.finalize_command_id
        ):
            if record.state == "queued" or (record.state == "failed" and record.retryable):
                if record.lease_expires_at and record.lease_expires_at > now:
                    continue
                record.state = "running"
                record.attempt += 1
                record.claimed_by = worker_id
                record.lease_expires_at = now + lease_for
                record.command = replace(record.command, lease_token=worker_id)
                return record.command
        return None

    def replay_completed_import_finalization(
        self,
        command: ImportFinalizationCommand,
    ) -> ImportManifest | None:
        record = self.import_finalization_jobs.get(command.finalize_command_id)
        if record and record.state == "completed" and record.result_manifest_id:
            return self.manifests[record.result_manifest_id]
        return None

    def heartbeat_import_finalization(
        self,
        command: ImportFinalizationCommand,
        now: datetime,
        lease_for: timedelta,
    ) -> None:
        self._require_command_lease(command, now)
        record = self.import_finalization_jobs.get(command.finalize_command_id)
        if record:
            record.lease_expires_at = now + lease_for

    def get_import_session_for_finalization(
        self, command: ImportFinalizationCommand
    ) -> ImportSession:
        replayed = self.replay_completed_import_finalization(command)
        if replayed is not None:
            return self.import_sessions[replayed.import_session_id]
        session = self.import_sessions[command.import_session_id]
        if session.workspace_id != command.workspace_id:
            raise NonTerminalImportError("workspace mismatch")
        if session.row_version != command.expected_session_row_version:
            raise NonTerminalImportError("stale import session row version")
        if session.state not in {
            ImportSessionState.UPLOADED,
            ImportSessionState.VALIDATING,
            ImportSessionState.FAILED,
        }:
            raise NonTerminalImportError(
                "finalizer requires uploaded, validating, or retryable failed session"
            )
        if session.state == ImportSessionState.FAILED and not session.retryable:
            raise NonTerminalImportError("failed session is not retryable")
        session.state = ImportSessionState.VALIDATING
        return session

    def get_source_connection(self, source_connection_id: str) -> SourceConnection:
        return self.sources[source_connection_id]

    def resolve_effective_consent(
        self, session: ImportSession, at: datetime
    ) -> TransferConsentRecord:
        exact_grants = [
            consent
            for consent in self.consents
            if consent.import_session_id == session.id
            and consent.decision == ConsentDecision.GRANT
            and consent.workspace_id == session.workspace_id
            and consent.destination_workspace_id == session.workspace_id
            and consent.local_manifest_digest == session.local_manifest_digest
            and consent.file_digest == session.file_digest
            and consent.expected_upload_digest == session.expected_upload_digest
            and consent.selected_scope_digest == session.selected_scope_digest
            and consent.model_egress_authorization == "none"
            and consent.expires_at > at
            and consent.upload_object_scope.max_bytes >= session.file_size_bytes
            and consent.upload_object_scope.media_type == session.media_type
        ]
        if not exact_grants:
            raise ConsentError("no exact unexpired grant")
        grant = max(exact_grants, key=lambda consent: consent.recorded_at)
        revoked = any(
            consent.decision == ConsentDecision.REVOKE
            and consent.supersedes_id == grant.id
            and consent.recorded_at >= grant.recorded_at
            for consent in self.consents
        )
        if revoked:
            raise ConsentError("grant was revoked")
        return grant

    def finalize_import(
        self,
        command: ImportFinalizationCommand,
        manifest: ImportManifest,
        raw_items: list[RawContentItem],
        content_items: list[ContentItem],
        content_versions: list[ContentVersion],
    ) -> ImportManifest:
        session = self.import_sessions[command.import_session_id]
        source = self.sources[session.source_connection_id]
        if source.row_version != command.expected_source_row_version:
            raise SourcePointerError("stale source row version")
        if source.current_import_manifest_id != command.expected_current_import_manifest_id:
            raise SourcePointerError("stale source manifest pointer")
        self._require_command_lease(command)
        if session.terminal_manifest_id is not None:
            return self.manifests[session.terminal_manifest_id]

        for item in raw_items:
            self.raw_items[item.id] = item
        for item in content_items:
            self.content_items[item.id] = item
        for version in content_versions:
            self.content_versions[version.id] = version

        self.manifests[manifest.id] = manifest
        self.manifest_versions[manifest.id] = [version.id for version in content_versions]
        session.state = ImportSessionState.FINALIZED
        session.terminal_manifest_id = manifest.id
        session.row_version += 1
        source.current_import_manifest_id = manifest.id
        source.row_version += 1
        record = self.import_finalization_jobs.get(command.finalize_command_id)
        if record:
            record.state = "completed"
            record.result_manifest_id = manifest.id
            record.failure_code = None
            record.retryable = False
        return manifest

    def fail_import_finalization(
        self,
        command: ImportFinalizationCommand,
        failure_code: str,
        retryable: bool,
    ) -> None:
        self._require_command_lease(command)
        self.fail_import_session(command.import_session_id, failure_code, retryable)

    def fail_import_session(self, session_id: str, failure_code: str, retryable: bool) -> None:
        session = self.import_sessions[session_id]
        if session.state == ImportSessionState.FINALIZED:
            return
        session.state = ImportSessionState.FAILED
        session.failure_code = failure_code
        session.retryable = retryable
        session.row_version += 1
        for record in self.import_finalization_jobs.values():
            if record.command.import_session_id == session_id and record.state == "running":
                record.state = "failed"
                record.failure_code = failure_code
                record.retryable = retryable

    def cancel_import_session(self, session_id: str, reason: str) -> None:
        del reason
        session = self.import_sessions[session_id]
        if session.terminal_manifest_id is not None:
            raise NonTerminalImportError("cannot cancel finalized session")
        session.state = ImportSessionState.CANCELLED
        session.row_version += 1

    def get_terminal_manifest(self, manifest_id: str) -> ImportManifest:
        if manifest_id in self.import_sessions:
            raise NonTerminalImportError(
                "downstream jobs must use import_manifest_id, not import_session_id"
            )
        manifest = self.manifests.get(manifest_id)
        if manifest is None:
            raise NonTerminalImportError("unknown or non-terminal import manifest")
        return manifest

    def get_content_versions_for_manifest(self, manifest_id: str) -> list[ContentVersion]:
        self.get_terminal_manifest(manifest_id)
        return [
            self.content_versions[version_id]
            for version_id in self.manifest_versions.get(manifest_id, [])
        ]

    def upsert_collected_raw_items(
        self,
        workspace_id: str,
        source_connection_id: str,
        items: list[RawContentItem],
        collection_key: str,
        lease: CollectionLeaseContext,
    ) -> list[ContentVersion]:
        self._require_collection_lease(lease, collection_key)
        if collection_key in self.collection_keys:
            return [
                self.content_versions[version_id]
                for version_id in self.collection_versions.get(collection_key, [])
            ]

        versions: list[ContentVersion] = []
        for raw in items:
            self.raw_items[raw.id] = raw
            identity_key = raw.canonical_url or f"{source_connection_id}:{raw.source_item_id}"
            existing = next(
                (
                    item
                    for item in self.content_items.values()
                    if item.workspace_id == workspace_id and item.identity_key == identity_key
                ),
                None,
            )
            if existing is None:
                content_item_id = str(uuid4())
                version_number = 1
            else:
                content_item_id = existing.id
                existing_versions = [
                    v for v in self.content_versions.values() if v.content_item_id == existing.id
                ]
                if any(v.content_digest == raw.content_digest for v in existing_versions):
                    versions.extend(
                        v for v in existing_versions if v.content_digest == raw.content_digest
                    )
                    continue
                version_number = max((v.version_number for v in existing_versions), default=0) + 1

            version = ContentVersion(
                id=str(uuid4()),
                workspace_id=workspace_id,
                content_item_id=content_item_id,
                version_number=version_number,
                content_digest=raw.content_digest,
                normalized_title=raw.title,
                normalized_body=raw.body,
                captured_at=raw.captured_at,
                parser_version="connector-v1",
                canonical_url=raw.canonical_url,
                author=raw.author,
                data_authenticity=raw.data_authenticity,
                metadata=raw.metadata,
            )
            item = ContentItem(
                id=content_item_id,
                workspace_id=workspace_id,
                source_connection_id=source_connection_id,
                source_item_id=raw.source_item_id,
                canonical_url=raw.canonical_url,
                identity_key=identity_key,
                title=raw.title,
                current_version_id=version.id,
                duplicate_cluster_id=None,
                independence_group_id=None,
                data_authenticity=raw.data_authenticity,
            )
            self.content_items[item.id] = item
            self.content_versions[version.id] = version
            versions.append(version)

        self.collection_keys.add(collection_key)
        self.collection_versions[collection_key] = [version.id for version in versions]
        return versions

    def get_signal_candidate_versions(
        self,
        workspace_id: str,
        watchlist_id: str,
        terms: tuple[str, ...],
        current_window: tuple[datetime, datetime],
        baseline_window: tuple[datetime, datetime],
        collection_key: str,
        lease: CollectionLeaseContext,
    ) -> list[ContentVersion]:
        del terms, watchlist_id
        self._require_collection_lease(lease, collection_key)
        start = min(current_window[0], baseline_window[0])
        end = max(current_window[1], baseline_window[1])
        candidates: list[ContentVersion] = []
        for version in self.content_versions.values():
            if version.workspace_id != workspace_id:
                continue
            event_time = _content_version_event_time(version)
            if start <= event_time < end:
                candidates.append(version)
        return sorted(candidates, key=lambda item: item.id)

    def get_initial_baseline_projection(
        self,
        workspace_id: str,
        watchlist_id: str,
        collection_key: str,
        lease: CollectionLeaseContext,
        current_candidate_count: int,
    ) -> InitialBaselineProjection:
        run = self._require_collection_lease(lease, collection_key)
        source_ids = {
            str(getattr(row.get("command"), "source_connection_id", ""))
            for row in self.collection_schedules.values()
            if str(getattr(row.get("command"), "watchlist_id", "")) == watchlist_id
        }
        source_ids.update(
            str(row.get("source_connection_id"))
            for row in self.collection_runs.values()
            if str((row.get("metadata") or {}).get("watchlist_id") or "") == watchlist_id
        )
        source_ids = {source_id for source_id in source_ids if source_id}
        if not source_ids and run.get("source_connection_id"):
            source_ids = {str(run["source_connection_id"])}
        required_count = max(2, len(source_ids))

        latest_by_source: dict[str, dict[str, Any]] = {}
        terminal_runs = [
            row
            for row in self.collection_runs.values()
            if row.get("workspace_id") == workspace_id
            and str((row.get("metadata") or {}).get("watchlist_id") or "") == watchlist_id
            and row.get("state") in {"succeeded", "partial_success", "failed", "cancelled"}
        ]
        for row in terminal_runs:
            source_id = str(row.get("source_connection_id") or "")
            latest_by_source.setdefault(source_id, row)
        if (
            run.get("workspace_id") == workspace_id
            and str((run.get("metadata") or {}).get("watchlist_id") or "") == watchlist_id
            and run.get("stable_key") == collection_key
            and self.collection_versions.get(collection_key)
        ):
            latest_by_source[str(run.get("source_connection_id") or "")] = run

        successful_source_ids = {
            source_id
            for source_id, row in latest_by_source.items()
            if row.get("state") in {"succeeded", "partial_success"}
            or (
                row.get("state") == "running"
                and bool(self.collection_versions.get(str(row.get("stable_key") or "")))
            )
        }
        current_count = sum(
            1
            for version in self.content_versions.values()
            if version.workspace_id == workspace_id
            and str(version.metadata.get("source_connection_id") or "") in successful_source_ids
        )
        terminal_candidate_count = sum(
            max(0, int((row.get("freshness") or {}).get("signal_candidate_count") or 0))
            for row in latest_by_source.values()
            if row.get("state") in {"succeeded", "partial_success", "failed", "cancelled"}
        )
        next_run_at = min(
            (
                row["next_run_at"]
                for row in self.collection_schedules.values()
                if row.get("enabled", True)
                and str(getattr(row.get("command"), "watchlist_id", "")) == watchlist_id
            ),
            default=None,
        )
        if current_count >= required_count:
            status = "ready"
            reason = None
            expected_detectable_at = None
        elif not terminal_runs and current_count == 0:
            status = "collecting"
            reason = None if next_run_at is not None else "initial_baseline_collecting"
            expected_detectable_at = next_run_at
        else:
            status = "insufficient"
            reason = "initial_baseline_insufficient"
            expected_detectable_at = next_run_at
        return InitialBaselineProjection(
            status=status,
            current_count=current_count,
            required_count=required_count,
            candidate_count=terminal_candidate_count + max(0, current_candidate_count),
            expected_detectable_at=expected_detectable_at,
            reason=reason,
            last_terminal_run_at=None,
        )

    def get_source_refetch_targets(
        self,
        workspace_id: str,
        source_connection_id: str,
        collection_key: str,
        lease: CollectionLeaseContext,
        limit: int,
    ) -> list[SourceRefetchTarget]:
        self._require_collection_lease(lease, collection_key)
        if limit <= 0:
            return []
        items = [
            item
            for item in self.content_items.values()
            if item.workspace_id == workspace_id
            and item.source_connection_id == source_connection_id
            and item.current_version_id
        ]
        return [
            SourceRefetchTarget(
                source_item_id=item.source_item_id,
                current_content_version_id=item.current_version_id,
                canonical_url=item.canonical_url,
                checked_at=None,
            )
            for item in sorted(items, key=lambda row: row.id)[:limit]
        ]

    def persist_dedupe_assignments(
        self,
        workspace_id: str,
        assignments: dict[str, dict[str, str]],
        collection_key: str,
        lease: CollectionLeaseContext,
    ) -> None:
        self._require_collection_lease(lease, collection_key)
        for version_id, assignment in assignments.items():
            version = self.content_versions.get(version_id)
            if version is None or version.workspace_id != workspace_id:
                continue
            item = self.content_items.get(version.content_item_id)
            if item is None:
                continue
            item.duplicate_cluster_id = assignment.get("duplicate_cluster_id")
            item.independence_group_id = assignment.get("independence_group_id")

    def _require_command_lease(
        self, command: ImportFinalizationCommand, now: datetime | None = None
    ) -> None:
        record = self.import_finalization_jobs.get(command.finalize_command_id)
        if not record:
            return
        if record.state != "running" or record.claimed_by != command.lease_token:
            raise NonTerminalImportError("finalization command lease is not held by this worker")
        current = now or now_utc()
        if record.lease_expires_at and record.lease_expires_at <= current:
            raise NonTerminalImportError("finalization command lease expired")

    def update_source_health(
        self,
        source_connection_id: str,
        status: SourceHealthStatus,
        details: dict[str, Any],
        lease: CollectionLeaseContext,
    ) -> None:
        self._require_collection_lease(lease, str(details.get("collection_key") or ""))
        source = self.sources[source_connection_id]
        source.status = status
        source.freshness = details
        source.row_version += 1
        self.health_updates[source_connection_id] = {"status": status.value, **details}

    def begin_collection_run(
        self,
        workspace_id: str,
        source_connection_id: str,
        stable_key: str,
        metadata: dict[str, Any],
    ) -> str:
        collection_run_id = deterministic_id(
            "collection-run", workspace_id, source_connection_id, stable_key
        )
        row = self.collection_runs.setdefault(
            collection_run_id,
            {
                "id": collection_run_id,
                "workspace_id": workspace_id,
                "source_connection_id": source_connection_id,
            },
        )
        stored_metadata = dict(metadata)
        lease_token = stored_metadata.pop("schedule_lease_token", "")
        stored_metadata["schedule_lease_token_digest"] = lease_token
        row.update({"stable_key": stable_key, "state": "running", "metadata": stored_metadata})
        return collection_run_id

    def complete_collection_run(
        self,
        lease: CollectionLeaseContext,
        state: str,
        counters: dict[str, Any],
        freshness: dict[str, Any],
        failure_code: str | None = None,
    ) -> None:
        row = self._require_collection_lease(lease)
        row.update(
            {
                "state": state,
                "counters": counters,
                "freshness": freshness,
                "failure_code": failure_code,
            }
        )

    def claim_due_collection_schedule(
        self,
        worker_id: str,
        now: datetime,
        lease_for: timedelta,
    ) -> ScheduledCollectionClaim | None:
        for schedule_id, row in sorted(self.collection_schedules.items()):
            if not row.get("enabled", True) or row["next_run_at"] > now:
                continue
            lease = row.get("lease")
            if lease and lease["expires_at"] > now:
                continue
            token = (
                f"{worker_id}:{deterministic_id('schedule-lease', schedule_id, now.isoformat())}"
            )
            row["lease"] = {"token": token, "owner": worker_id, "expires_at": now + lease_for}
            return ScheduledCollectionClaim(
                schedule_id=schedule_id, lease_token=token, command=row["command"]
            )
        return None

    def heartbeat_collection_schedule(
        self,
        schedule_id: str,
        lease_token: str,
        now: datetime,
        lease_for: timedelta,
    ) -> None:
        row = self.collection_schedules[schedule_id]
        if row.get("lease", {}).get("token") != lease_token:
            raise NonTerminalImportError("schedule lease token mismatch")
        row["lease"]["expires_at"] = now + lease_for

    def release_collection_schedule(self, schedule_id: str, lease_token: str) -> None:
        row = self.collection_schedules[schedule_id]
        if row.get("lease", {}).get("token") == lease_token:
            row["lease"] = None

    def complete_collection_schedule(
        self,
        schedule_id: str,
        lease_token: str,
        success: bool,
        next_run_at: datetime | None,
        now: datetime | None = None,
    ) -> None:
        del now
        row = self.collection_schedules[schedule_id]
        if row.get("lease", {}).get("token") != lease_token:
            raise NonTerminalImportError("schedule lease token mismatch")
        row["last_success_at" if success else "last_failure_at"] = now_utc()
        if success and next_run_at is not None:
            row["next_run_at"] = next_run_at
        row["lease"] = None

    def create_signal(
        self, signal: Signal, lease: CollectionLeaseContext | None = None
    ) -> SignalPersistenceResult:
        if lease is not None:
            self._require_collection_lease(
                lease, str(signal.dimensions.get("collection_key") or "")
            )
        if signal.id in self.signals:
            return SignalPersistenceResult(
                signal_id=signal.id,
                created=False,
                suppressed_reason="duplicate_signal_id",
                existing_signal_id=signal.id,
            )
        self.signals[signal.id] = signal
        return SignalPersistenceResult(signal_id=signal.id, created=True)

    def claim_next_source_validation_job(
        self, worker_id: str, lease_for: timedelta
    ) -> SourceValidationClaim | None:
        now = now_utc()
        for job_id, row in sorted(self.source_validation_jobs.items()):
            if row.get("workspace_id") is None:
                source = self.sources[row["source_connection_id"]]
                row["workspace_id"] = source.workspace_id
            if row.get("state") not in {"queued", "claimed"}:
                continue
            expires_at = row.get("lease_expires_at")
            if (
                row.get("state") == "claimed"
                and isinstance(expires_at, datetime)
                and expires_at > now
            ):
                continue
            source = self.sources[row["source_connection_id"]]
            row["state"] = "claimed"
            row["attempt"] = int(row.get("attempt") or 0) + 1
            row["fencing_version"] = int(row.get("fencing_version") or 0) + 1
            row["lease_token"] = (
                f"{worker_id}:{deterministic_id('source-validation', job_id, now.isoformat())}"
            )
            row["lease_expires_at"] = now + lease_for
            return SourceValidationClaim(
                job_id=job_id,
                workspace_id=row["workspace_id"],
                source_connection_id=row["source_connection_id"],
                command=str(row.get("command") or "health_check"),
                connector_config=dict(
                    row.get("connector_config") or source.freshness.get("config") or {}
                ),
                lease_token=row["lease_token"],
                attempt=row["attempt"],
                fencing_version=row["fencing_version"],
                lease_expires_at=row["lease_expires_at"],
            )
        return None

    def heartbeat_source_validation_job(
        self, claim: SourceValidationClaim, lease_for: timedelta
    ) -> None:
        row = self._require_source_validation_claim(claim)
        row["lease_expires_at"] = now_utc() + lease_for

    def complete_source_validation_job(
        self,
        claim: SourceValidationClaim,
        source_status: str,
        health_error_code: str | None = None,
        reason: str | None = None,
    ) -> None:
        row = self._require_source_validation_claim(claim)
        source = self.sources.get(claim.source_connection_id)
        if not self._source_validation_fence_matches(row, source):
            self._terminalize_source_validation_fence_drift(row)
            return
        assert source is not None
        source.status = SourceHealthStatus(source_status)
        source.freshness = {
            "health_state": source_status,
            "health_error_code": health_error_code,
            "reason": reason,
        }
        source.row_version += 1
        row.update(
            {
                "state": "completed",
                "result_source_status": source_status,
                "failure_code": health_error_code,
                "failure_reason": reason,
                "lease_token": None,
                "lease_expires_at": None,
            }
        )

    def fail_source_validation_job(
        self,
        claim: SourceValidationClaim,
        failure_code: str,
        reason: str,
    ) -> None:
        row = self._require_source_validation_claim(claim)
        source = self.sources.get(claim.source_connection_id)
        if not self._source_validation_fence_matches(row, source):
            self._terminalize_source_validation_fence_drift(row)
            return
        assert source is not None
        source.status = SourceHealthStatus.FAILED
        source.freshness = {
            "health_state": SourceHealthStatus.FAILED.value,
            "health_error_code": failure_code,
            "reason": reason,
        }
        source.row_version += 1
        row.update(
            {
                "state": "failed",
                "result_source_status": SourceHealthStatus.FAILED.value,
                "failure_code": failure_code,
                "failure_reason": reason,
                "lease_token": None,
                "lease_expires_at": None,
            }
        )

    def get_research_run(self, run_id: str) -> ResearchRun:
        return self.research_runs[run_id]

    def claim_next_research_run_command(
        self, worker_id: str, lease_for: timedelta
    ) -> ResearchRunClaim | None:
        now = now_utc()
        for run in self.research_runs.values():
            lease = self.research_run_claims.get(run.id)
            if run.state == ResearchRunState.QUEUED and (
                lease is None or lease["lease_expires_at"] <= now
            ):
                attempt_id = (
                    f"{worker_id}:{deterministic_id('research-attempt', run.id, now.isoformat())}"
                )
                lease_expires_at = now + lease_for
                self.research_run_claims[run.id] = {
                    "worker_id": worker_id,
                    "worker_attempt_id": attempt_id,
                    "lease_expires_at": lease_expires_at,
                }
                return ResearchRunClaim(run.id, attempt_id, lease_expires_at)
        return None

    def get_content_versions_for_research_run(self, run_id: str) -> list[ContentVersion]:
        run = self.research_runs[run_id]
        return [self.content_versions[version_id] for version_id in run.content_version_ids]

    def heartbeat_research_run(
        self,
        run_id: str,
        worker_attempt_id: str,
        now: datetime,
        lease_for: timedelta,
    ) -> None:
        self._require_research_lease(run_id, worker_attempt_id)
        self.research_run_claims[run_id]["lease_expires_at"] = now + lease_for

    def transition_research_run(
        self,
        run_id: str,
        state: ResearchRunState,
        worker_attempt_id: str | None = None,
    ) -> None:
        run = self.research_runs[run_id]
        self._require_research_lease(run_id, worker_attempt_id)
        run.state = state
        run.row_version += 1

    def append_run_event(
        self, run_id: str, event_type: str, payload: dict[str, Any], trace_id: str
    ) -> RunEvent:
        validate_run_event_payload(event_type, payload)
        events = self.run_events.setdefault(run_id, [])
        event = RunEvent(
            event_id=str(uuid4()),
            run_id=run_id,
            sequence=len(events) + 1,
            timestamp=now_utc(),
            event_type=event_type,
            payload=payload,
            trace_id=trace_id,
        )
        events.append(event)
        return event

    def persist_research_proposals(
        self,
        run_id: str,
        evidence: list[EvidenceProposal],
        claims: list[ClaimVersionProposal],
        synthesis: SynthesisProposal | None,
        worker_attempt_id: str | None = None,
    ) -> None:
        self._require_research_lease(run_id, worker_attempt_id)
        self.evidence.update({item.id: item for item in evidence})
        self.claims.update({item.id: item for item in claims})
        self.research_runs[run_id] = replace(
            self.research_runs[run_id], state=ResearchRunState.COMPLETED
        )

    def _require_research_lease(self, run_id: str, worker_attempt_id: str | None) -> None:
        if worker_attempt_id is None:
            return
        lease = self.research_run_claims.get(run_id)
        if lease is None or lease["worker_attempt_id"] != worker_attempt_id:
            raise NonTerminalImportError("research run lease token mismatch")
        if lease["lease_expires_at"] <= now_utc():
            raise NonTerminalImportError("research run lease expired")

    def _require_collection_lease(
        self, lease: CollectionLeaseContext, collection_key: str | None = None
    ) -> dict[str, Any]:
        row = self.collection_runs.get(lease.collection_run_id)
        if row is None:
            raise NonTerminalImportError("collection run not found")
        if collection_key and row.get("stable_key") != collection_key:
            raise NonTerminalImportError("collection run key mismatch")
        metadata = row.get("metadata") or {}
        if str(metadata.get("schedule_id") or "") != lease.schedule_id:
            raise NonTerminalImportError("collection schedule mismatch")
        if str(metadata.get("schedule_lease_token_digest") or "") != lease.schedule_lease_token:
            raise NonTerminalImportError("collection schedule lease token mismatch")
        if int(metadata.get("schedule_fencing_version") or -1) != int(
            lease.schedule_fencing_version
        ):
            raise NonTerminalImportError("collection schedule fencing mismatch")
        schedule = self.collection_schedules.get(lease.schedule_id)
        if schedule is None or schedule.get("lease", {}).get("token") != lease.schedule_lease_token:
            raise NonTerminalImportError("collection schedule lease token mismatch")
        if schedule.get("lease", {}).get("expires_at") <= now_utc():
            raise NonTerminalImportError("collection schedule lease expired")
        return row

    def _require_source_validation_claim(
        self,
        claim: SourceValidationClaim,
    ) -> dict[str, Any]:
        row = self.source_validation_jobs.get(claim.job_id)
        if row is None:
            raise NonTerminalImportError("source validation job not found")
        if row.get("workspace_id") != claim.workspace_id:
            raise NonTerminalImportError("source validation workspace mismatch")
        if row.get("source_connection_id") != claim.source_connection_id:
            raise NonTerminalImportError("source validation source mismatch")
        if row.get("state") != "claimed":
            raise NonTerminalImportError("source validation job is not claimed")
        if row.get("lease_token") != claim.lease_token:
            raise NonTerminalImportError("source validation lease token mismatch")
        if int(row.get("attempt") or -1) != int(claim.attempt):
            raise NonTerminalImportError("source validation attempt mismatch")
        if int(row.get("fencing_version") or -1) != int(claim.fencing_version):
            raise NonTerminalImportError("source validation fencing mismatch")
        expires_at = row.get("lease_expires_at")
        if expires_at is None or expires_at <= now_utc():
            raise NonTerminalImportError("source validation lease expired")
        return row

    @staticmethod
    def _source_validation_fence_matches(
        row: dict[str, Any], source: SourceConnection | None
    ) -> bool:
        if source is None:
            return False
        return (
            source.row_version == int(row.get("expected_source_row_version") or -1)
            and str(source.status) == "validating"
        )

    @staticmethod
    def _terminalize_source_validation_fence_drift(row: dict[str, Any]) -> None:
        row.update(
            {
                "state": "failed",
                "result_source_status": SourceHealthStatus.FAILED.value,
                "failure_code": _SOURCE_VALIDATION_FENCE_DRIFT_CODE,
                "failure_reason": _SOURCE_VALIDATION_FENCE_DRIFT_REASON,
                "lease_token": None,
                "lease_expires_at": None,
                "heartbeat_at": None,
            }
        )


def manifest_command_from_session(
    session: ImportSession, source: SourceConnection
) -> ManifestProcessingCommand:
    if session.terminal_manifest_id is None:
        raise NonTerminalImportError("session has no terminal manifest")
    return ManifestProcessingCommand(
        workspace_id=session.workspace_id, import_manifest_id=session.terminal_manifest_id
    )


def _content_version_event_time(version: ContentVersion) -> datetime:
    value = version.metadata.get("published_at")
    if isinstance(value, str) and value:
        try:
            text = value[:-1] + "+00:00" if value.endswith("Z") else value
            return datetime.fromisoformat(text)
        except ValueError:
            pass
    return version.captured_at
