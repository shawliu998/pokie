"""SQLAlchemy WorkerDomainAdapter for the real API repository boundary."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from packages.contracts.enums import DataAuthenticity as ContractDataAuthenticity
from packages.contracts.schemas import (
    ImportManifestProposal,
    ImportNormalizationProposal,
    NormalizedContentItemProposal,
    NormalizedContentVersionProposal,
    NormalizedRawContentProposal,
)
from packages.domain.errors import ObjectScopeMismatch
from packages.domain.imports import require_import_payload_object_key
from services.api.app.core.errors import ApiError
from services.api.app.db.models import (
    CollectionRun,
    ImportFinalizationJobRecord,
    ImportManifestContentVersion,
    SignalEvidence,
    SourceValidationJobRecord,
    UploadGrant,
    Watchlist,
)
from services.api.app.db.models import (
    CollectionSchedule as DbCollectionSchedule,
)
from services.api.app.db.models import (
    ContentItem as DbContentItem,
)
from services.api.app.db.models import (
    ContentVersion as DbContentVersion,
)
from services.api.app.db.models import (
    ImportManifest as DbImportManifest,
)
from services.api.app.db.models import (
    ImportSession as DbImportSession,
)
from services.api.app.db.models import (
    RawContentItem as DbRawContentItem,
)
from services.api.app.db.models import (
    ResearchRun as DbResearchRun,
)
from services.api.app.db.models import (
    Signal as DbSignal,
)
from services.api.app.db.models import (
    SourceConnection as DbSourceConnection,
)
from services.api.app.db.models import (
    TransferConsentRecord as DbTransferConsentRecord,
)
from services.api.app.db.session import get_session_factory, set_rls_context
from services.api.app.modules.common import append_run_event as api_append_run_event
from services.api.app.modules.common import digest, text_digest, utcnow
from services.api.app.modules.research.service import ResearchRunResultRepository
from services.api.app.modules.sources.service import ImportFinalizationRepository
from services.api.app.modules.sources.validation import SourceValidationJobRepository
from services.worker.app.contracts import (
    ClaimVersionProposal,
    CollectionLeaseContext,
    ConsentDecision,
    ConsentError,
    ContentItem,
    ContentVersion,
    DataAuthenticity,
    EvidenceProposal,
    ImportFinalizationCommand,
    ImportManifest,
    ImportSession,
    ImportSessionState,
    InitialBaselineProjection,
    NonTerminalImportError,
    ObjectVerificationError,
    RawContentItem,
    ResearchRun,
    ResearchRunClaim,
    ResearchRunState,
    RetryableJobError,
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
    TransferConsentRecord,
    UploadObjectScope,
)
from services.worker.app.pipelines.digests import deterministic_id
from services.worker.app.run_events import validate_run_event_payload


class ProductionAdapterError(RuntimeError):
    """Raised when the real repository cannot satisfy worker invariants."""


class SQLAlchemyWorkerDomainAdapter:
    def __init__(
        self,
        session_factory: sessionmaker[Session] | None = None,
        worker_id: str = "glint-worker",
        workspace_id: str | None = None,
        object_store: Any | None = None,
        clock: Any | None = None,
    ) -> None:
        self.session_factory = session_factory or get_session_factory()
        self.worker_id = worker_id
        resolved_workspace_id = workspace_id or os.environ.get("GLINT_WORKSPACE_ID")
        if not resolved_workspace_id:
            raise ProductionAdapterError(
                "GLINT_WORKSPACE_ID is required for the production worker adapter"
            )
        self.workspace_id: str = resolved_workspace_id
        self.object_store = object_store or create_object_store()
        self.clock = clock or utcnow
        self._assert_backend_capabilities()

    def _assert_backend_capabilities(self) -> None:
        if not hasattr(ImportFinalizationJobRecord, "lease_expires_at"):
            raise ProductionAdapterError("ImportFinalizationJobRecord lacks lease fields")
        if not hasattr(ImportManifestContentVersion, "content_version_id"):
            raise ProductionAdapterError("ImportManifestContentVersion relation is required")
        if not hasattr(DbRawContentItem, "collection_run_id"):
            raise ProductionAdapterError(
                "RawContentItem.collection_run_id is required for P2 collection"
            )
        if not hasattr(DbContentVersion, "raw_content_item_id"):
            raise ProductionAdapterError(
                "ContentVersion.raw_content_item_id is required for raw lineage"
            )

    def claim_next_import_finalization_command(
        self, worker_id: str, lease_for: timedelta
    ) -> ImportFinalizationCommand | None:
        now = utcnow()
        with self.session_factory() as db:
            self._set_workspace(db, self.workspace_id, worker_id)
            command_id = db.scalar(
                select(ImportFinalizationJobRecord.id)
                .where(
                    ImportFinalizationJobRecord.workspace_id == self.workspace_id,
                    ImportFinalizationJobRecord.state.in_(["queued", "claimed", "failed"]),
                    (ImportFinalizationJobRecord.state != "failed")
                    | (ImportFinalizationJobRecord.retryable.is_(True)),
                    (ImportFinalizationJobRecord.lease_expires_at.is_(None))
                    | (ImportFinalizationJobRecord.lease_expires_at <= now),
                )
                .order_by(ImportFinalizationJobRecord.created_at.asc())
                .limit(1)
            )
            if command_id is None:
                return None
            failed_job = db.scalar(
                select(ImportFinalizationJobRecord)
                .where(
                    ImportFinalizationJobRecord.id == command_id,
                    ImportFinalizationJobRecord.workspace_id == self.workspace_id,
                    ImportFinalizationJobRecord.state == "failed",
                    ImportFinalizationJobRecord.retryable.is_(True),
                )
                .with_for_update()
            )
            if failed_job is not None:
                session = db.scalar(
                    select(DbImportSession)
                    .where(
                        DbImportSession.id == failed_job.import_session_id,
                        DbImportSession.workspace_id == self.workspace_id,
                    )
                    .with_for_update()
                )
                if session is None or session.state != "failed" or not session.retryable:
                    db.rollback()
                    return None
                session.state = "validating"
                session.failure_code = None
                session.retryable = False
                session.row_version += 1
                failed_job.expected_session_row_version = session.row_version
                failed_job.state = "claimed"
                failed_job.claimed_by = worker_id
                failed_job.lease_acquired_at = now
                failed_job.lease_expires_at = now + lease_for
                failed_job.attempt += 1
                failed_job.failure_code = None
                failed_job.retryable = False
                db.commit()
                return self._command_from_record(failed_job, worker_id)
            record = ImportFinalizationRepository.claim(
                db,
                workspace_id=self.workspace_id,
                command_id=command_id,
                worker_id=worker_id,
                lease_seconds=max(1, int(lease_for.total_seconds())),
            )
            return self._command_from_record(record, worker_id)

    def replay_completed_import_finalization(
        self, command: ImportFinalizationCommand
    ) -> ImportManifest | None:
        with self.session_factory() as db:
            self._set_workspace(db, command.workspace_id, command.lease_token or self.worker_id)
            record = db.get(ImportFinalizationJobRecord, command.finalize_command_id)
            if record is None or record.state != "completed" or not record.result_manifest_id:
                return None
            manifest = db.get(DbImportManifest, record.result_manifest_id)
            return self._manifest(manifest) if manifest is not None else None

    def heartbeat_import_finalization(
        self,
        command: ImportFinalizationCommand,
        now: datetime,
        lease_for: timedelta,
    ) -> None:
        with self.session_factory() as db:
            self._set_workspace(db, command.workspace_id, command.lease_token or self.worker_id)
            current = _as_utc(now)
            job = self._require_job_lease(db, command, current)
            updated = db.scalar(
                update(ImportFinalizationJobRecord)
                .where(
                    ImportFinalizationJobRecord.id == command.finalize_command_id,
                    ImportFinalizationJobRecord.workspace_id == command.workspace_id,
                    ImportFinalizationJobRecord.state == "claimed",
                    ImportFinalizationJobRecord.claimed_by == command.lease_token,
                    ImportFinalizationJobRecord.lease_expires_at.is_not(None),
                    ImportFinalizationJobRecord.lease_expires_at > current,
                )
                .values(
                    lease_expires_at=current + lease_for,
                    lease_acquired_at=job.lease_acquired_at or current,
                )
                .returning(ImportFinalizationJobRecord.id)
            )
            if updated is None:
                db.rollback()
                raise NonTerminalImportError("finalization job lease expired")
            db.commit()

    def get_import_session_for_finalization(
        self, command: ImportFinalizationCommand
    ) -> ImportSession:
        with self.session_factory() as db:
            self._set_workspace(db, command.workspace_id, command.lease_token or self.worker_id)
            self._require_job_lease(db, command)
            row = db.scalar(
                select(DbImportSession).where(
                    DbImportSession.id == command.import_session_id,
                    DbImportSession.workspace_id == command.workspace_id,
                )
            )
            if row is None:
                raise NonTerminalImportError("import session not found")
            if row.row_version != command.expected_session_row_version:
                raise NonTerminalImportError("stale import session row version")
            if row.state != "validating":
                raise NonTerminalImportError("finalizer requires a validating import session")
            return self._session(row)

    def get_source_connection(self, source_connection_id: str) -> SourceConnection:
        with self.session_factory() as db:
            self._set_workspace(db)
            row = db.get(DbSourceConnection, source_connection_id)
            if row is None:
                raise SourcePointerError("source connection not found")
            return self._source(row)

    def resolve_effective_consent(
        self, session: ImportSession, at: datetime
    ) -> TransferConsentRecord:
        with self.session_factory() as db:
            self._set_workspace(db, session.workspace_id)
            row = db.get(DbImportSession, session.id)
            if row is None:
                raise ConsentError("import session not found")
            consent = self._resolve_effective_consent_row(db, row, at)
            return self._consent(consent)

    def finalize_import(
        self,
        command: ImportFinalizationCommand,
        manifest: ImportManifest,
        raw_items: list[RawContentItem],
        content_items: list[ContentItem],
        content_versions: list[ContentVersion],
    ) -> ImportManifest:
        with self.session_factory() as db:
            self._set_workspace(db, command.workspace_id, command.lease_token or self.worker_id)
            self._require_job_lease(db, command)
            session = db.get(DbImportSession, command.import_session_id)
            if session is None or session.workspace_id != command.workspace_id:
                raise SourcePointerError("import session not found")
            self._validate_import_outputs(
                session, manifest, raw_items, content_items, content_versions
            )
            proposal = _import_normalization_proposal(
                manifest, raw_items, content_items, content_versions
            )
            try:
                completed = ImportFinalizationRepository.complete(
                    db,
                    workspace_id=command.workspace_id,
                    command_id=command.finalize_command_id,
                    worker_id=command.lease_token or self.worker_id,
                    proposal=proposal,
                )
            except ApiError as exc:
                raise _map_import_api_error(exc) from exc
            return self._manifest(completed)

    def fail_import_finalization(
        self, command: ImportFinalizationCommand, failure_code: str, retryable: bool
    ) -> None:
        with self.session_factory() as db:
            self._set_workspace(db, command.workspace_id, command.lease_token or self.worker_id)
            self._require_job_lease(db, command)
            ImportFinalizationRepository.fail(
                db,
                workspace_id=command.workspace_id,
                command_id=command.finalize_command_id,
                worker_id=command.lease_token or self.worker_id,
                failure_code=failure_code,
                retryable=retryable,
            )

    def fail_import_session(self, session_id: str, failure_code: str, retryable: bool) -> None:
        with self.session_factory() as db:
            self._set_workspace(db)
            session = db.get(DbImportSession, session_id)
            if session and session.state != "finalized":
                session.state = "failed"
                session.failure_code = failure_code
                session.retryable = retryable
                session.row_version += 1
                db.commit()

    def cancel_import_session(self, session_id: str, reason: str) -> None:
        raise ProductionAdapterError("worker may not cancel imports; use API cancel command")

    def get_terminal_manifest(self, manifest_id: str) -> ImportManifest:
        with self.session_factory() as db:
            self._set_workspace(db)
            manifest = db.get(DbImportManifest, manifest_id)
            if manifest is None:
                raise NonTerminalImportError("unknown terminal manifest")
            session = db.get(DbImportSession, manifest.import_session_id)
            if (
                session is None
                or session.state != "finalized"
                or session.terminal_manifest_id != manifest.id
            ):
                raise NonTerminalImportError("manifest is not terminal")
            return self._manifest(manifest)

    def get_content_versions_for_manifest(self, manifest_id: str) -> list[ContentVersion]:
        with self.session_factory() as db:
            self._set_workspace(db)
            rows = db.scalars(
                select(DbContentVersion)
                .join(
                    ImportManifestContentVersion,
                    ImportManifestContentVersion.content_version_id == DbContentVersion.id,
                )
                .where(ImportManifestContentVersion.import_manifest_id == manifest_id)
                .order_by(ImportManifestContentVersion.ordinal.asc())
            ).all()
            return [self._content_version(row) for row in rows]

    def upsert_collected_raw_items(
        self,
        workspace_id: str,
        source_connection_id: str,
        items: list[RawContentItem],
        collection_key: str,
        lease: CollectionLeaseContext,
    ) -> list[ContentVersion]:
        self._require_workspace(workspace_id)
        with self.session_factory() as db:
            self._set_workspace(db, workspace_id)
            run = self._require_collection_run_lease(
                db,
                lease,
                expected_workspace_id=workspace_id,
                expected_source_connection_id=source_connection_id,
                expected_collection_key=collection_key,
            )
            versions: list[ContentVersion] = []
            for raw in items:
                self._require_collection_run_lease(
                    db,
                    lease,
                    expected_workspace_id=workspace_id,
                    expected_source_connection_id=source_connection_id,
                    expected_collection_key=collection_key,
                )
                self._require_workspace(raw.workspace_id)
                if raw.source_connection_id != source_connection_id:
                    raise ProductionAdapterError("raw item source_connection_id mismatch")
                raw_digest = str(raw.metadata.get("raw_digest", raw.content_digest))
                raw_row_id = deterministic_id(
                    "db-collected-raw", run.id, raw.source_item_id, raw_digest
                )
                raw_row = db.get(DbRawContentItem, raw_row_id)
                if raw_row is not None:
                    if (
                        raw_row.collection_run_id != run.id
                        or raw_row.source_connection_id != source_connection_id
                        or raw_row.raw_digest != raw_digest
                    ):
                        raise ProductionAdapterError(
                            "raw replay collided outside this collection run"
                        )
                    raw_snapshot_uri = raw_row.raw_snapshot_uri
                else:
                    raw_snapshot_uri = self._write_collected_snapshot(
                        f"{collection_key}/{run.id}", raw
                    )
                    self._require_collection_run_lease(
                        db,
                        lease,
                        expected_workspace_id=workspace_id,
                        expected_source_connection_id=source_connection_id,
                        expected_collection_key=collection_key,
                    )
                    raw_row = DbRawContentItem(
                        id=raw_row_id,
                        workspace_id=workspace_id,
                        import_manifest_id=None,
                        collection_run_id=run.id,
                        source_connection_id=source_connection_id,
                        source_external_id=raw.source_item_id,
                        raw_snapshot_uri=raw_snapshot_uri,
                        raw_digest=raw_digest,
                        data_authenticity=raw.data_authenticity.value,
                    )
                    db.add(raw_row)
                    db.flush()
                identity_key = raw.canonical_url or f"{source_connection_id}:{raw.source_item_id}"
                item = db.scalar(
                    select(DbContentItem)
                    .where(
                        DbContentItem.workspace_id == workspace_id,
                        DbContentItem.source_connection_id == source_connection_id,
                        DbContentItem.identity_key == identity_key,
                    )
                    .with_for_update()
                )
                if item is None:
                    item = DbContentItem(
                        workspace_id=workspace_id,
                        source_connection_id=source_connection_id,
                        source_item_id=raw.source_item_id,
                        canonical_url=raw.canonical_url,
                        identity_key=identity_key,
                        title=raw.title,
                        data_authenticity=raw.data_authenticity.value,
                    )
                    db.add(item)
                    db.flush()
                    version_number = 1
                else:
                    existing = db.scalar(
                        select(DbContentVersion).where(
                            DbContentVersion.content_item_id == item.id,
                            DbContentVersion.content_digest == raw.content_digest,
                        )
                    )
                    if existing is not None:
                        versions.append(self._content_version_from_item(existing, item))
                        continue
                    version_number = (
                        db.scalar(
                            select(func.coalesce(func.max(DbContentVersion.version_number), 0))
                            .where(DbContentVersion.content_item_id == item.id)
                            .with_for_update()
                        )
                        or 0
                    ) + 1
                version = DbContentVersion(
                    workspace_id=workspace_id,
                    content_item_id=item.id,
                    source_connection_id=source_connection_id,
                    raw_content_item_id=raw_row.id,
                    version_number=version_number,
                    content_digest=raw.content_digest,
                    normalized_title=raw.title,
                    normalized_body=raw.body,
                    metadata_json={
                        **raw.metadata,
                        "author": raw.author,
                        "source_connection_id": source_connection_id,
                        "source_item_id": raw.source_item_id,
                        "published_at": raw.published_at.isoformat() if raw.published_at else None,
                        "captured_at": raw.captured_at.isoformat(),
                    },
                    captured_at=raw.captured_at,
                    raw_snapshot_uri=raw_snapshot_uri,
                    parser_version=raw.metadata.get("connector_type", "connector-v1"),
                    availability=_availability_from_metadata(raw.metadata),
                    availability_last_checked_at=_availability_checked_at(
                        raw.metadata, raw.captured_at
                    ),
                    availability_reason=_availability_reason(raw.metadata),
                    data_authenticity=raw.data_authenticity.value,
                )
                db.add(version)
                try:
                    db.flush()
                except IntegrityError:
                    db.rollback()
                    return self.upsert_collected_raw_items(
                        workspace_id, source_connection_id, items, collection_key, lease
                    )
                item.current_version_id = version.id
                versions.append(self._content_version_from_item(version, item))
            self._require_collection_run_lease(
                db,
                lease,
                expected_workspace_id=workspace_id,
                expected_source_connection_id=source_connection_id,
                expected_collection_key=collection_key,
            )
            db.commit()
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
        del terms
        self._require_workspace(workspace_id)
        with self.session_factory() as db:
            self._set_workspace(db, workspace_id)
            self._require_collection_run_lease(
                db,
                lease,
                expected_workspace_id=workspace_id,
                expected_collection_key=collection_key,
            )
            watchlist = db.get(Watchlist, watchlist_id)
            if (
                watchlist is None
                or watchlist.workspace_id != workspace_id
                or watchlist.status != "active"
            ):
                raise ProductionAdapterError("signal candidate read requires active watchlist")
            allowed_sources = _watchlist_source_ids(watchlist.rules_json or {})
            if not allowed_sources:
                raise ProductionAdapterError("watchlist does not explicitly allow sources")
            window_start = min(_as_utc(current_window[0]), _as_utc(baseline_window[0]))
            window_end = max(_as_utc(current_window[1]), _as_utc(baseline_window[1]))
            published_at = DbContentVersion.metadata_json["published_at"].as_string()
            rows = db.execute(
                select(DbContentVersion, DbContentItem)
                .join(DbContentItem, DbContentItem.id == DbContentVersion.content_item_id)
                .join(
                    DbSourceConnection,
                    DbSourceConnection.id == DbContentItem.source_connection_id,
                )
                .where(
                    DbContentVersion.workspace_id == workspace_id,
                    DbContentItem.workspace_id == workspace_id,
                    DbContentItem.source_connection_id.in_(allowed_sources),
                    DbSourceConnection.workspace_id == workspace_id,
                    DbSourceConnection.status != "disabled",
                    DbSourceConnection.approved_by.is_not(None),
                    or_(
                        and_(
                            published_at.is_not(None),
                            published_at != "",
                            published_at >= window_start.isoformat(),
                            published_at < window_end.isoformat(),
                        ),
                        and_(
                            or_(published_at.is_(None), published_at == ""),
                            DbContentVersion.captured_at >= window_start,
                            DbContentVersion.captured_at < window_end,
                        ),
                    ),
                )
            ).all()
            candidates = [
                self._content_version_from_item(version_row, item_row)
                for version_row, item_row in rows
            ]
            self._require_collection_run_lease(
                db,
                lease,
                expected_workspace_id=workspace_id,
                expected_collection_key=collection_key,
            )
            return sorted(candidates, key=lambda item: item.id)

    def get_initial_baseline_projection(
        self,
        workspace_id: str,
        watchlist_id: str,
        collection_key: str,
        lease: CollectionLeaseContext,
        current_candidate_count: int,
    ) -> InitialBaselineProjection:
        self._require_workspace(workspace_id)
        with self.session_factory() as db:
            self._set_workspace(db, workspace_id)
            run = self._require_collection_run_lease(
                db,
                lease,
                expected_workspace_id=workspace_id,
                expected_collection_key=collection_key,
            )
            if run.watchlist_id != watchlist_id:
                raise ProductionAdapterError("collection run watchlist mismatch")
            watchlist = db.get(Watchlist, watchlist_id)
            if (
                watchlist is None
                or watchlist.workspace_id != workspace_id
                or watchlist.status != "active"
            ):
                raise ProductionAdapterError("initial baseline requires active watchlist")
            source_ids = sorted(_watchlist_source_ids(watchlist.rules_json or {}))
            required_count = max(2, len(source_ids))
            terminal_runs = list(
                db.scalars(
                    select(CollectionRun)
                    .where(
                        CollectionRun.workspace_id == workspace_id,
                        CollectionRun.watchlist_id == watchlist_id,
                        CollectionRun.state.in_(
                            {"succeeded", "partial_success", "failed", "cancelled"}
                        ),
                    )
                    .order_by(CollectionRun.finished_at.desc(), CollectionRun.created_at.desc())
                ).all()
            )
            latest_by_source: dict[str, CollectionRun] = {}
            for terminal_run in terminal_runs:
                latest_by_source.setdefault(terminal_run.source_connection_id, terminal_run)
            current_run_version_count = (
                db.scalar(
                    select(func.count(DbContentVersion.id))
                    .join(
                        DbRawContentItem,
                        DbRawContentItem.id == DbContentVersion.raw_content_item_id,
                    )
                    .where(
                        DbContentVersion.workspace_id == workspace_id,
                        DbRawContentItem.collection_run_id == run.id,
                    )
                )
                or 0
            )
            if current_run_version_count > 0:
                latest_by_source[run.source_connection_id] = run
            successful_source_ids = {
                source_id
                for source_id, latest_run in latest_by_source.items()
                if latest_run.state in {"succeeded", "partial_success"}
                or (latest_run.id == run.id and current_run_version_count > 0)
            }
            current_count = 0
            if successful_source_ids:
                current_count = (
                    db.scalar(
                        select(func.count(func.distinct(DbContentVersion.id))).where(
                            DbContentVersion.workspace_id == workspace_id,
                            DbContentVersion.source_connection_id.in_(successful_source_ids),
                        )
                    )
                    or 0
                )
            terminal_candidate_count = sum(
                max(0, int((terminal_run.freshness_json or {}).get("signal_candidate_count", 0)))
                for terminal_run in latest_by_source.values()
                if terminal_run.id != run.id
            )
            next_run_at = db.scalar(
                select(DbCollectionSchedule.next_run_at)
                .where(
                    DbCollectionSchedule.workspace_id == workspace_id,
                    DbCollectionSchedule.watchlist_id == watchlist_id,
                    DbCollectionSchedule.enabled.is_(True),
                )
                .order_by(DbCollectionSchedule.next_run_at)
                .limit(1)
            )
            last_terminal = next(
                (
                    terminal_run.finished_at or terminal_run.created_at
                    for terminal_run in terminal_runs
                ),
                None,
            )
            if current_count >= required_count:
                status = "ready"
                expected_detectable_at = None
                reason = None
            elif not terminal_runs and current_count == 0:
                status = "collecting"
                expected_detectable_at = next_run_at
                reason = None if next_run_at is not None else "initial_baseline_collecting"
            else:
                status = "insufficient"
                expected_detectable_at = next_run_at
                failed = bool(latest_by_source) and all(
                    latest_run.state not in {"succeeded", "partial_success"}
                    and latest_run.id != run.id
                    for latest_run in latest_by_source.values()
                )
                reason = "initial_baseline_failed" if failed else "initial_baseline_insufficient"
            self._require_collection_run_lease(
                db,
                lease,
                expected_workspace_id=workspace_id,
                expected_collection_key=collection_key,
            )
            return InitialBaselineProjection(
                status=status,
                current_count=int(current_count),
                required_count=required_count,
                candidate_count=terminal_candidate_count + max(0, current_candidate_count),
                expected_detectable_at=(
                    _as_utc(expected_detectable_at) if expected_detectable_at else None
                ),
                reason=reason,
                last_terminal_run_at=_as_utc(last_terminal) if last_terminal else None,
            )

    def get_source_refetch_targets(
        self,
        workspace_id: str,
        source_connection_id: str,
        collection_key: str,
        lease: CollectionLeaseContext,
        limit: int,
    ) -> list[SourceRefetchTarget]:
        self._require_workspace(workspace_id)
        if limit <= 0:
            return []
        with self.session_factory() as db:
            self._set_workspace(db, workspace_id)
            self._require_collection_run_lease(
                db,
                lease,
                expected_workspace_id=workspace_id,
                expected_source_connection_id=source_connection_id,
                expected_collection_key=collection_key,
            )
            rows = db.execute(
                select(DbContentItem, DbContentVersion)
                .join(DbContentVersion, DbContentVersion.id == DbContentItem.current_version_id)
                .where(
                    DbContentItem.workspace_id == workspace_id,
                    DbContentItem.source_connection_id == source_connection_id,
                    DbContentItem.current_version_id.is_not(None),
                )
                .order_by(DbContentItem.updated_at.desc(), DbContentItem.id.asc())
                .limit(limit)
            ).all()
            self._require_collection_run_lease(
                db,
                lease,
                expected_workspace_id=workspace_id,
                expected_source_connection_id=source_connection_id,
                expected_collection_key=collection_key,
            )
            return [
                SourceRefetchTarget(
                    source_item_id=item.source_item_id,
                    current_content_version_id=version.id,
                    canonical_url=item.canonical_url,
                    checked_at=_metadata_dt(version.metadata_json or {}, "checked_at"),
                )
                for item, version in rows
            ]

    def persist_dedupe_assignments(
        self,
        workspace_id: str,
        assignments: dict[str, dict[str, str]],
        collection_key: str,
        lease: CollectionLeaseContext,
    ) -> None:
        self._require_workspace(workspace_id)
        if not assignments:
            return
        with self.session_factory() as db:
            self._set_workspace(db, workspace_id)
            self._require_collection_run_lease(
                db,
                lease,
                expected_workspace_id=workspace_id,
                expected_collection_key=collection_key,
            )
            rows = db.execute(
                select(DbContentVersion, DbContentItem)
                .join(DbContentItem, DbContentItem.id == DbContentVersion.content_item_id)
                .where(
                    DbContentVersion.workspace_id == workspace_id,
                    DbContentVersion.id.in_(assignments.keys()),
                    DbContentItem.workspace_id == workspace_id,
                )
            ).all()
            for version, item in rows:
                assignment = assignments.get(version.id)
                if assignment is None:
                    continue
                duplicate_cluster_id = assignment.get("duplicate_cluster_id")
                item.duplicate_cluster_id = duplicate_cluster_id
                if hasattr(item, "independence_group_id"):
                    item.independence_group_id = assignment.get("independence_group_id")
            self._require_collection_run_lease(
                db,
                lease,
                expected_workspace_id=workspace_id,
                expected_collection_key=collection_key,
            )
            db.commit()

    def begin_collection_run(
        self,
        workspace_id: str,
        source_connection_id: str,
        stable_key: str,
        metadata: dict[str, Any],
    ) -> str:
        self._require_workspace(workspace_id)
        with self.session_factory() as db:
            self._set_workspace(db, workspace_id)
            schedule_id = metadata.get("schedule_id")
            lease_token = metadata.get("schedule_lease_token")
            if not schedule_id or not lease_token:
                raise ProductionAdapterError("collection run requires schedule lease metadata")
            lease_checked_at = (
                _parse_dt(metadata["lease_checked_at"])
                if metadata.get("lease_checked_at")
                else utcnow()
            )
            schedule = self._require_schedule_lease(
                db, str(schedule_id), str(lease_token), lease_checked_at
            )
            if int(metadata.get("schedule_fencing_version") or -1) != int(
                schedule.lease_fencing_version
            ):
                raise ProductionAdapterError("schedule lease fencing version mismatch")
            attempt = int(metadata.get("attempt") or 1)
            existing = db.scalar(
                select(CollectionRun).where(
                    CollectionRun.workspace_id == workspace_id,
                    CollectionRun.stable_key == stable_key,
                    CollectionRun.attempt == attempt,
                )
            )
            if existing is not None:
                self._require_collection_run_lease(
                    db,
                    CollectionLeaseContext(
                        collection_run_id=existing.id,
                        schedule_id=str(schedule_id),
                        schedule_lease_token=str(lease_token),
                        schedule_fencing_version=int(schedule.lease_fencing_version),
                    ),
                    expected_workspace_id=workspace_id,
                    expected_source_connection_id=source_connection_id,
                    expected_collection_key=stable_key,
                )
                if existing.state not in {"succeeded", "partial_success"}:
                    existing.state = "running"
                    existing.started_at = existing.started_at or utcnow()
                    db.commit()
                return existing.id
            run = CollectionRun(
                workspace_id=workspace_id,
                watchlist_id=metadata["watchlist_id"],
                source_connection_id=source_connection_id,
                stable_key=stable_key,
                state="running",
                cadence=metadata.get("cadence", "manual"),
                timezone=metadata.get("timezone", "UTC"),
                scheduled_for=_parse_dt(metadata["scheduled_for"]),
                attempt=attempt,
                input_window_json=metadata,
                counters_json={},
                freshness_json={
                    "schedule_id": metadata.get("schedule_id"),
                    "schedule_fencing_version": metadata.get("schedule_fencing_version"),
                    "schedule_lease_token_digest": text_digest(str(lease_token)),
                    "scheduled_for": metadata.get("scheduled_for"),
                },
                started_at=utcnow(),
                data_authenticity=metadata.get("data_authenticity", "collected"),
            )
            stored_metadata = dict(metadata)
            stored_metadata.pop("schedule_lease_token", None)
            stored_metadata["schedule_lease_token_digest"] = text_digest(str(lease_token))
            run.input_window_json = stored_metadata
            db.add(run)
            db.commit()
            return run.id

    def complete_collection_run(
        self,
        lease: CollectionLeaseContext,
        state: str,
        counters: dict[str, Any],
        freshness: dict[str, Any],
        failure_code: str | None = None,
    ) -> None:
        with self.session_factory() as db:
            self._set_workspace(db)
            run = self._require_collection_run_lease(db, lease)
            if state not in {"succeeded", "partial_success", "failed", "cancelled"}:
                raise ProductionAdapterError("collection run state is outside public contract")
            run.state = state
            run.counters_json = counters
            run.partial_success = state == "partial_success"
            run.freshness_json = freshness
            run.failure_code = failure_code
            run.finished_at = utcnow()
            db.commit()

    def update_source_health(
        self,
        source_connection_id: str,
        status: SourceHealthStatus,
        details: dict[str, Any],
        lease: CollectionLeaseContext,
    ) -> None:
        with self.session_factory() as db:
            self._set_workspace(db)
            self._require_collection_run_lease(
                db,
                lease,
                expected_source_connection_id=source_connection_id,
                expected_collection_key=str(details.get("collection_key") or ""),
            )
            source = db.get(DbSourceConnection, source_connection_id)
            if source is None:
                return
            source.status = _source_status_for_health(status)
            source.health_state = status.value
            source.health_checked_at = utcnow()
            source.health_error_code = (
                str(details.get("error") or details.get("failure_code") or "")[:80] or None
            )
            source.last_run_at = utcnow()
            freshness_state = str(details.get("freshness_state") or details.get("state") or "stale")
            source.freshness_state = (
                freshness_state if freshness_state in {"current", "stale", "never"} else "stale"
            )
            last_success_at = details.get("last_success_at")
            if last_success_at and status == SourceHealthStatus.HEALTHY:
                source.last_success_at = _parse_dt(str(last_success_at))
            source.row_version += 1
            db.commit()

    def create_signal(
        self, signal: Signal, lease: CollectionLeaseContext | None = None
    ) -> SignalPersistenceResult:
        with self.session_factory() as db:
            self._set_workspace(db, signal.workspace_id)
            self._require_workspace(signal.workspace_id)
            if lease is not None:
                self._require_collection_run_lease(
                    db,
                    lease,
                    expected_workspace_id=signal.workspace_id,
                    expected_collection_key=str(signal.dimensions.get("collection_key") or ""),
                )
            existing = db.get(DbSignal, signal.id)
            if existing is not None:
                return SignalPersistenceResult(
                    signal_id=signal.id,
                    created=False,
                    suppressed_reason="duplicate_signal_id",
                    existing_signal_id=existing.id,
                )
            existing_by_evidence = self._existing_signal_for_content_set(db, signal)
            if existing_by_evidence is not None:
                return SignalPersistenceResult(
                    signal_id=signal.id,
                    created=False,
                    suppressed_reason="duplicate_evidence_set",
                    existing_signal_id=existing_by_evidence.id,
                )
            cooldown_seconds = _signal_cooldown_seconds(signal)
            now = _as_utc(self.clock())
            existing_by_topic = self._existing_signal_in_cooldown(db, signal, now, cooldown_seconds)
            if existing_by_topic is not None:
                return SignalPersistenceResult(
                    signal_id=signal.id,
                    created=False,
                    suppressed_reason="cooldown_active",
                    existing_signal_id=existing_by_topic.id,
                    cooldown_until=_as_utc(existing_by_topic.created_at)
                    + timedelta(seconds=cooldown_seconds),
                )
            row = DbSignal(
                id=signal.id,
                workspace_id=signal.workspace_id,
                watchlist_id=signal.watchlist_id,
                title=signal.title,
                detector_version=signal.detector_version,
                window_json={
                    "current_start": signal.detection_window[0].isoformat(),
                    "current_end": signal.detection_window[1].isoformat(),
                    "baseline_start": signal.baseline_window[0].isoformat(),
                    "baseline_end": signal.baseline_window[1].isoformat(),
                },
                metrics_json=signal.metrics,
                dimensions_json=signal.dimensions,
                explanation=signal.explanation,
                data_authenticity=signal.data_authenticity.value,
            )
            db.add(row)
            evidence_roles = {version_id: "trigger" for version_id in signal.content_version_ids}
            candidate_ids = signal.dimensions.get("candidate_content_version_ids")
            if isinstance(candidate_ids, (list, tuple)):
                for version_id in candidate_ids:
                    evidence_roles.setdefault(str(version_id), "context")
            dedupe_assignments = signal.dimensions.get("dedupe_assignments")
            if not isinstance(dedupe_assignments, dict):
                dedupe_assignments = {}
            for version_id, role in evidence_roles.items():
                assignment = dedupe_assignments.get(version_id)
                independence_group_id = (
                    assignment.get("independence_group_id")
                    if isinstance(assignment, dict)
                    else None
                )
                db.add(
                    SignalEvidence(
                        workspace_id=signal.workspace_id,
                        signal_id=signal.id,
                        content_version_id=version_id,
                        role=role,
                        independence_group_id=independence_group_id,
                        contribution=1.0 if role == "trigger" else 0.0,
                        added_by="worker",
                        data_authenticity=signal.data_authenticity.value,
                    )
                )
            db.commit()
            return SignalPersistenceResult(signal_id=signal.id, created=True)

    def _existing_signal_for_content_set(self, db: Session, signal: Signal) -> DbSignal | None:
        content_ids = set(signal.content_version_ids)
        if not content_ids:
            return None
        candidates = db.scalars(
            select(DbSignal).where(
                DbSignal.workspace_id == signal.workspace_id,
                DbSignal.watchlist_id == signal.watchlist_id,
                DbSignal.detector_version == signal.detector_version,
            )
        ).all()
        for candidate in candidates:
            linked = set(
                db.scalars(
                    select(SignalEvidence.content_version_id).where(
                        SignalEvidence.signal_id == candidate.id,
                        SignalEvidence.role == "trigger",
                    )
                ).all()
            )
            if linked == content_ids:
                return candidate
        return None

    def _existing_signal_in_cooldown(
        self, db: Session, signal: Signal, now: datetime, cooldown_seconds: int
    ) -> DbSignal | None:
        if cooldown_seconds <= 0:
            return None
        topic_key = signal.dimensions.get("topic_key")
        if not isinstance(topic_key, str) or not topic_key:
            return None
        since = now - timedelta(seconds=cooldown_seconds)
        candidates = db.scalars(
            select(DbSignal)
            .where(
                DbSignal.workspace_id == signal.workspace_id,
                DbSignal.watchlist_id == signal.watchlist_id,
                DbSignal.detector_version == signal.detector_version,
                DbSignal.created_at >= since,
            )
            .order_by(DbSignal.created_at.desc(), DbSignal.id.desc())
        ).all()
        for candidate in candidates:
            if candidate.dimensions_json.get("topic_key") == topic_key:
                return candidate
        return None

    def claim_next_source_validation_job(
        self, worker_id: str, lease_for: timedelta
    ) -> SourceValidationClaim | None:
        owner_token = f"{worker_id}:{uuid4()}"
        with self.session_factory() as db:
            self._set_workspace(db, self.workspace_id, worker_id)
            try:
                job = SourceValidationJobRepository.claim(
                    db,
                    workspace_id=self.workspace_id,
                    owner_token=owner_token,
                    lease_seconds=int(lease_for.total_seconds()),
                    now=_as_utc(self.clock()),
                )
            except ApiError as exc:
                raise _map_source_validation_api_error(exc) from exc
            if job is None:
                return None
            source = db.get(DbSourceConnection, job.source_connection_id)
            if source is None:
                raise ProductionAdapterError("source validation job lost its source")
            return self._source_validation_claim(job, owner_token, source)

    def heartbeat_source_validation_job(
        self, claim: SourceValidationClaim, lease_for: timedelta
    ) -> None:
        self._require_workspace(claim.workspace_id)
        with self.session_factory() as db:
            self._set_workspace(db, claim.workspace_id, claim.lease_token)
            try:
                SourceValidationJobRepository.heartbeat(
                    db,
                    workspace_id=claim.workspace_id,
                    job_id=claim.job_id,
                    owner_token=claim.lease_token,
                    expected_attempt=claim.attempt,
                    expected_fencing_version=claim.fencing_version,
                    lease_seconds=int(lease_for.total_seconds()),
                )
            except ApiError as exc:
                raise _map_source_validation_api_error(exc) from exc

    def complete_source_validation_job(
        self,
        claim: SourceValidationClaim,
        source_status: str,
        health_error_code: str | None = None,
        reason: str | None = None,
    ) -> None:
        self._require_workspace(claim.workspace_id)
        with self.session_factory() as db:
            self._set_workspace(db, claim.workspace_id, claim.lease_token)
            try:
                SourceValidationJobRepository.complete(
                    db,
                    workspace_id=claim.workspace_id,
                    job_id=claim.job_id,
                    owner_token=claim.lease_token,
                    expected_attempt=claim.attempt,
                    expected_fencing_version=claim.fencing_version,
                    source_status=source_status,
                    health_error_code=health_error_code,
                    reason=reason,
                )
            except ApiError as exc:
                raise _map_source_validation_api_error(exc) from exc

    def fail_source_validation_job(
        self,
        claim: SourceValidationClaim,
        failure_code: str,
        reason: str,
    ) -> None:
        self._require_workspace(claim.workspace_id)
        with self.session_factory() as db:
            self._set_workspace(db, claim.workspace_id, claim.lease_token)
            try:
                SourceValidationJobRepository.fail(
                    db,
                    workspace_id=claim.workspace_id,
                    job_id=claim.job_id,
                    owner_token=claim.lease_token,
                    expected_attempt=claim.attempt,
                    expected_fencing_version=claim.fencing_version,
                    failure_code=failure_code,
                    reason=reason,
                )
            except ApiError as exc:
                raise _map_source_validation_api_error(exc) from exc

    def get_research_run(self, run_id: str) -> ResearchRun:
        with self.session_factory() as db:
            self._set_workspace(db)
            run = db.get(DbResearchRun, run_id)
            if run is None:
                raise ProductionAdapterError("research run not found")
            content_version_ids, manifest_ids = self._validate_run_input_lineage(db, run)
            manifest = run.run_input_manifest_json or {}
            return ResearchRun(
                id=run.id,
                workspace_id=run.workspace_id,
                investigation_id=run.investigation_id,
                investigation_scope_version_id=run.investigation_scope_version_id,
                state=ResearchRunState(run.state),
                graph_version=run.graph_version,
                run_input_manifest_digest=run.run_input_manifest_digest,
                source_manifest_id=manifest_ids[0] if manifest_ids else None,
                content_version_ids=tuple(content_version_ids),
                data_authenticity=DataAuthenticity(run.data_authenticity),
                row_version=run.row_version,
                provider=str(manifest.get("provider") or "deterministic"),
                model=str(manifest["model"]) if manifest.get("model") else None,
                prompt_refs=tuple(str(item) for item in manifest.get("prompt_refs", [])),
                question=str(manifest.get("question") or ""),
            )

    def claim_next_research_run_command(
        self, worker_id: str, lease_for: timedelta
    ) -> ResearchRunClaim | None:
        with self.session_factory() as db:
            self._set_workspace(db, self.workspace_id, worker_id)
            attempt_id = f"{worker_id}:{uuid4()}"
            claimed = ResearchRunResultRepository.claim_queued(
                db,
                workspace_id=self.workspace_id,
                worker_id=worker_id,
                worker_attempt_id=attempt_id,
                lease_seconds=max(1, int(lease_for.total_seconds())),
            )
            if claimed is None:
                return None
            if claimed.worker_lease_expires_at is None:
                raise ProductionAdapterError("claimed research run lacks lease expiry")
            return ResearchRunClaim(
                run_id=claimed.id,
                worker_attempt_id=attempt_id,
                lease_expires_at=_as_utc(claimed.worker_lease_expires_at),
            )

    def get_content_versions_for_research_run(self, run_id: str) -> list[ContentVersion]:
        with self.session_factory() as db:
            self._set_workspace(db)
            run = db.get(DbResearchRun, run_id)
            if run is None:
                raise ProductionAdapterError("research run not found")
            content_ids, _ = self._validate_run_input_lineage(db, run)
            rows = {
                row.id: row
                for row in db.scalars(
                    select(DbContentVersion).where(
                        DbContentVersion.workspace_id == run.workspace_id,
                        DbContentVersion.id.in_(content_ids),
                    )
                ).all()
            }
            return [self._content_version(rows[content_id]) for content_id in content_ids]

    def heartbeat_research_run(
        self,
        run_id: str,
        worker_attempt_id: str,
        now: datetime,
        lease_for: timedelta,
    ) -> None:
        with self.session_factory() as db:
            self._set_workspace(db)
            current = _as_utc(now)
            updated = db.scalar(
                update(DbResearchRun)
                .where(
                    DbResearchRun.id == run_id,
                    DbResearchRun.workspace_id == self.workspace_id,
                    DbResearchRun.worker_attempt_id == worker_attempt_id,
                    DbResearchRun.worker_lease_expires_at.is_not(None),
                    DbResearchRun.worker_lease_expires_at > current,
                )
                .values(
                    worker_heartbeat_at=current,
                    worker_lease_expires_at=current + lease_for,
                    worker_fencing_version=DbResearchRun.worker_fencing_version + 1,
                )
                .returning(DbResearchRun.id)
            )
            if updated is None:
                db.rollback()
                raise ProductionAdapterError("research run worker lease expired")
            db.commit()

    def transition_research_run(
        self,
        run_id: str,
        state: ResearchRunState,
        worker_attempt_id: str | None = None,
    ) -> None:
        with self.session_factory() as db:
            self._set_workspace(db)
            run = db.scalar(
                select(DbResearchRun).where(DbResearchRun.id == run_id).with_for_update()
            )
            if run is None:
                raise ProductionAdapterError("research run not found")
            if run.workspace_id != self.workspace_id:
                raise ProductionAdapterError("workspace mismatch")
            if run.state == state.value:
                return
            if not worker_attempt_id:
                raise ProductionAdapterError("research run worker attempt is required")
            if run.worker_attempt_id != worker_attempt_id:
                raise ProductionAdapterError("research run worker attempt mismatch")
            if state == ResearchRunState.RUNNING and run.state not in {
                ResearchRunState.QUEUED.value,
                ResearchRunState.RUNNING.value,
            }:
                raise ProductionAdapterError("only queued research runs can start")
            if state == ResearchRunState.COMPLETED and run.state != ResearchRunState.RUNNING.value:
                raise ProductionAdapterError("only running research runs can complete")
            if state == ResearchRunState.RUNNING:
                ResearchRunResultRepository.mark_started(
                    db,
                    workspace_id=run.workspace_id,
                    run_id=run.id,
                    worker_attempt_id=worker_attempt_id,
                )
                return
            if state == ResearchRunState.COMPLETED:
                self._require_research_lease(run, worker_attempt_id)
                return
            run.state = state.value
            run.row_version += 1
            db.commit()

    def append_run_event(
        self, run_id: str, event_type: str, payload: dict[str, Any], trace_id: str
    ) -> RunEvent:
        validate_run_event_payload(event_type, payload)
        with self.session_factory() as db:
            self._set_workspace(db)
            run = db.get(DbResearchRun, run_id)
            if run is None:
                raise ProductionAdapterError("research run not found")
            event = api_append_run_event(
                db,
                workspace_id=run.workspace_id,
                investigation_id=run.investigation_id,
                run_id=run_id,
                event_type=event_type,
                payload=payload,
                trace_id=trace_id,
                event_idempotency_key=text_digest(f"{run_id}:{event_type}:{digest(payload)}"),
            )
            db.commit()
            return RunEvent(
                event.event_id,
                event.research_run_id,
                event.sequence,
                event.occurred_at,
                event.type,
                event.payload_json,
                event.trace_id,
            )

    def persist_research_proposals(
        self,
        run_id: str,
        evidence: list[EvidenceProposal],
        claims: list[ClaimVersionProposal],
        synthesis: object | None,
        worker_attempt_id: str | None = None,
    ) -> None:
        if synthesis is not None:
            raise ProductionAdapterError("worker must not persist synthesis proposals")
        if not worker_attempt_id:
            raise ProductionAdapterError("research run worker attempt is required")
        if not evidence or not claims:
            raise ProductionAdapterError(
                "research must persist evidence and claim proposals together"
            )
        with self.session_factory() as db:
            self._set_workspace(db)
            run = db.get(DbResearchRun, run_id)
            if run is None:
                raise ProductionAdapterError("research run not found")
            if run.workspace_id != self.workspace_id:
                raise ProductionAdapterError("workspace mismatch")
            self._require_research_lease(run, worker_attempt_id)
            pinned, _ = self._validate_run_input_lineage(db, run)
            pinned_set = set(pinned)
            evidence_payloads: list[dict[str, Any]] = []
            for proposal in evidence:
                if proposal.content_version_id not in pinned_set:
                    raise ProductionAdapterError("evidence escaped the frozen run input manifest")
                version = db.get(DbContentVersion, proposal.content_version_id)
                if version is None:
                    raise ProductionAdapterError("content version not found for evidence proposal")
                quote = version.normalized_body[proposal.quote_start : proposal.quote_end]
                if text_digest(quote) != proposal.quote_text_digest:
                    raise ProductionAdapterError("evidence quote digest mismatch")
                evidence_payloads.append(
                    {
                        "content_version_id": proposal.content_version_id,
                        "quote_start": proposal.quote_start,
                        "quote_end": proposal.quote_end,
                        "stance": proposal.stance,
                        "relevance": proposal.relevance,
                        "reliability": proposal.reliability,
                        "independence": proposal.independence,
                        "recency": proposal.recency,
                        "specificity": proposal.specificity,
                    }
                )
            claim = claims[0]
            if not set(claim.evidence_ids).issubset({item.id for item in evidence}):
                raise ProductionAdapterError("claim references unknown evidence proposal")
            ResearchRunResultRepository.persist_deterministic_result(
                db,
                workspace_id=run.workspace_id,
                run_id=run.id,
                actor_id=run.initiated_by,
                request_id=f"worker:{worker_attempt_id}",
                worker_attempt_id=worker_attempt_id,
                evidence_proposals=evidence_payloads,
                claim_proposal={
                    "claim_type": "observation",
                    "text": claim.text,
                    "limitations": list(claim.limitations),
                    "generation_method": claim.generation_method,
                    "generator_version": claim.generator_version,
                    "suggestion_origin": claim.suggestion_origin,
                },
            )

    def claim_due_collection_schedule(
        self, worker_id: str, now: datetime, lease_for: timedelta
    ) -> ScheduledCollectionClaim | None:
        with self.session_factory() as db:
            self._set_workspace(db, self.workspace_id, worker_id)
            current = _as_utc(now)
            candidates = db.execute(
                select(
                    DbCollectionSchedule.id,
                    DbCollectionSchedule.source_connection_id,
                    DbCollectionSchedule.next_run_at,
                    DbCollectionSchedule.cadence_seconds,
                    DbCollectionSchedule.misfire_policy,
                    DbCollectionSchedule.catch_up,
                    DbCollectionSchedule.overlap_policy,
                    DbSourceConnection.status,
                    Watchlist.rules_json,
                )
                .join(
                    DbSourceConnection,
                    DbSourceConnection.id == DbCollectionSchedule.source_connection_id,
                )
                .join(Watchlist, Watchlist.id == DbCollectionSchedule.watchlist_id)
                .where(
                    DbCollectionSchedule.workspace_id == self.workspace_id,
                    DbCollectionSchedule.enabled.is_(True),
                    DbCollectionSchedule.next_run_at <= current,
                    (
                        DbCollectionSchedule.lease_expires_at.is_(None)
                        | (DbCollectionSchedule.lease_expires_at <= current)
                    ),
                    DbSourceConnection.workspace_id == self.workspace_id,
                    DbSourceConnection.status != "disabled",
                    DbSourceConnection.approved_by.is_not(None),
                    Watchlist.workspace_id == self.workspace_id,
                    Watchlist.status == "active",
                )
                .order_by(DbCollectionSchedule.next_run_at.asc())
                .limit(20)
            ).all()
            for (
                schedule_id,
                source_connection_id,
                next_run_at,
                cadence_seconds,
                misfire_policy,
                catch_up,
                overlap_policy,
                source_status,
                rules_json,
            ) in candidates:
                if not _watchlist_allows_source(rules_json or {}, source_connection_id):
                    continue
                del overlap_policy
                if not catch_up:
                    if misfire_policy == "skip":
                        self._advance_schedule_without_claim(db, schedule_id, current)
                        db.commit()
                        continue
                else:
                    self._cap_catch_up_backlog(
                        db,
                        schedule_id,
                        _as_utc(next_run_at),
                        int(cadence_seconds),
                        current,
                    )
                owner_token = f"{worker_id}:{uuid4()}"
                claimed_id = db.scalar(
                    update(DbCollectionSchedule)
                    .where(
                        DbCollectionSchedule.id == schedule_id,
                        DbCollectionSchedule.workspace_id == self.workspace_id,
                        DbCollectionSchedule.enabled.is_(True),
                        (
                            DbCollectionSchedule.lease_expires_at.is_(None)
                            | (DbCollectionSchedule.lease_expires_at <= current)
                        ),
                    )
                    .values(
                        lease_owner_token=text_digest(owner_token),
                        lease_expires_at=current + lease_for,
                        heartbeat_at=current,
                        lease_attempt=DbCollectionSchedule.lease_attempt + 1,
                        lease_fencing_version=DbCollectionSchedule.lease_fencing_version + 1,
                    )
                    .returning(DbCollectionSchedule.id)
                )
                if claimed_id is None:
                    db.rollback()
                    continue
                schedule = db.scalar(
                    select(DbCollectionSchedule).where(DbCollectionSchedule.id == claimed_id)
                )
                db.commit()
                if schedule is None:
                    return None
                collection_kind = (
                    "source_validation"
                    if source_status == "validating"
                    else str((schedule.query_json or {}).get("kind") or "collection")
                )
                command = self._collection_command_from_schedule(
                    schedule, owner_token, collection_kind, rules_json or {}
                )
                return ScheduledCollectionClaim(schedule.id, owner_token, command)
            return None

    def _collection_overlap_exists(self, db: Session, source_connection_id: str) -> bool:
        return (
            db.scalar(
                select(func.count(CollectionRun.id)).where(
                    CollectionRun.workspace_id == self.workspace_id,
                    CollectionRun.source_connection_id == source_connection_id,
                    CollectionRun.state == "running",
                )
            )
            or 0
        ) > 0

    def _advance_schedule_without_claim(
        self, db: Session, schedule_id: str, current: datetime
    ) -> None:
        schedule = db.get(DbCollectionSchedule, schedule_id)
        if schedule is None:
            return
        schedule.next_run_at = _first_future_slot(
            _as_utc(schedule.next_run_at), schedule.cadence_seconds, current
        )
        schedule.lease_owner_token = None
        schedule.lease_expires_at = None
        schedule.heartbeat_at = None
        schedule.row_version += 1

    def _defer_schedule_without_claim(
        self, db: Session, schedule_id: str, current: datetime
    ) -> None:
        schedule = db.get(DbCollectionSchedule, schedule_id)
        if schedule is None:
            return
        schedule.next_run_at = max(_as_utc(schedule.next_run_at), current + timedelta(seconds=60))
        schedule.lease_owner_token = None
        schedule.lease_expires_at = None
        schedule.heartbeat_at = None
        schedule.row_version += 1

    def _cap_catch_up_backlog(
        self,
        db: Session,
        schedule_id: str,
        next_run_at: datetime,
        cadence_seconds: int,
        current: datetime,
    ) -> None:
        schedule = db.get(DbCollectionSchedule, schedule_id)
        if schedule is None:
            return
        limit = int((schedule.query_json or {}).get("catch_up_limit", 3) or 3)
        limit = max(1, min(limit, 24))
        capped = _latest_allowed_backlog_slot(next_run_at, cadence_seconds, current, limit)
        if capped != _as_utc(schedule.next_run_at):
            schedule.next_run_at = capped
            schedule.row_version += 1
            db.flush()

    def heartbeat_collection_schedule(
        self, schedule_id: str, lease_token: str, now: datetime, lease_for: timedelta
    ) -> None:
        with self.session_factory() as db:
            self._set_workspace(db, self.workspace_id)
            schedule = self._require_schedule_lease(db, schedule_id, lease_token, now)
            updated = db.scalar(
                update(DbCollectionSchedule)
                .where(
                    DbCollectionSchedule.id == schedule_id,
                    DbCollectionSchedule.lease_owner_token == text_digest(lease_token),
                    DbCollectionSchedule.lease_expires_at > _as_utc(now),
                    DbCollectionSchedule.lease_fencing_version == schedule.lease_fencing_version,
                )
                .values(
                    heartbeat_at=_as_utc(now),
                    lease_expires_at=_as_utc(now) + lease_for,
                )
                .returning(DbCollectionSchedule.id)
            )
            if updated is None:
                db.rollback()
                raise ProductionAdapterError("schedule lease expired")
            db.commit()

    def release_collection_schedule(self, schedule_id: str, lease_token: str) -> None:
        with self.session_factory() as db:
            self._set_workspace(db, self.workspace_id)
            current = utcnow()
            schedule = self._require_schedule_lease(db, schedule_id, lease_token, current)
            updated = db.scalar(
                update(DbCollectionSchedule)
                .where(
                    DbCollectionSchedule.id == schedule_id,
                    DbCollectionSchedule.lease_owner_token == text_digest(lease_token),
                    DbCollectionSchedule.lease_expires_at > current,
                    DbCollectionSchedule.lease_fencing_version == schedule.lease_fencing_version,
                )
                .values(
                    lease_owner_token=None,
                    lease_expires_at=None,
                    heartbeat_at=None,
                )
                .returning(DbCollectionSchedule.id)
            )
            if updated is None:
                db.rollback()
                raise ProductionAdapterError("schedule lease expired")
            db.commit()

    def complete_collection_schedule(
        self,
        schedule_id: str,
        lease_token: str,
        success: bool,
        next_run_at: datetime | None,
        now: datetime | None = None,
    ) -> None:
        with self.session_factory() as db:
            self._set_workspace(db, self.workspace_id)
            current = _as_utc(now) if now is not None else None
            if current is None:
                current = utcnow()
            schedule = self._require_schedule_lease(db, schedule_id, lease_token, current)
            if success:
                target_next_run = next_run_at or (
                    schedule.next_run_at + timedelta(seconds=schedule.cadence_seconds)
                )
                if not schedule.catch_up:
                    target_next_run = _first_future_slot(
                        target_next_run, schedule.cadence_seconds, current
                    )
            else:
                backoff_seconds = min(3600, max(60, 60 * (2 ** max(schedule.lease_attempt - 1, 0))))
                target_next_run = next_run_at or (current + timedelta(seconds=backoff_seconds))
            updated = db.scalar(
                update(DbCollectionSchedule)
                .where(
                    DbCollectionSchedule.id == schedule_id,
                    DbCollectionSchedule.lease_owner_token == text_digest(lease_token),
                    DbCollectionSchedule.lease_expires_at > current,
                    DbCollectionSchedule.lease_fencing_version == schedule.lease_fencing_version,
                )
                .values(
                    next_run_at=target_next_run,
                    lease_owner_token=None,
                    lease_expires_at=None,
                    heartbeat_at=None,
                )
                .returning(DbCollectionSchedule.id)
            )
            if updated is None:
                db.rollback()
                raise ProductionAdapterError("schedule lease expired")
            db.commit()

    def _require_job_lease(
        self, db: Session, command: ImportFinalizationCommand, now: datetime | None = None
    ) -> ImportFinalizationJobRecord:
        job = db.get(ImportFinalizationJobRecord, command.finalize_command_id)
        if job is None:
            raise NonTerminalImportError("finalization job not found")
        if job.state != "claimed" or job.claimed_by != command.lease_token:
            raise NonTerminalImportError("finalization job lease is not held by this worker")
        current = _as_utc(now) if now is not None else utcnow()
        if job.lease_expires_at is None or _as_utc(job.lease_expires_at) <= current:
            raise NonTerminalImportError("finalization job lease expired")
        return job

    def _final_object_matches(
        self,
        session: DbImportSession,
        consent: DbTransferConsentRecord,
        grant: UploadGrant | None,
        manifest: ImportManifest,
    ) -> bool:
        scope = consent.upload_object_scope
        return bool(
            grant is not None
            and grant.revoked_at is None
            and session.uploaded_object_key
            == scope["object_key"]
            == grant.object_key
            == manifest.uploaded_object_key
            and grant.observed_size_bytes == session.file_size_bytes
            and grant.observed_media_type == session.media_type
            and grant.media_type == scope["media_type"]
            and grant.observed_digest
            == session.expected_upload_digest
            == session.uploaded_object_digest
            == manifest.uploaded_object_digest
        )

    def _validate_import_outputs(
        self,
        session: DbImportSession,
        manifest: ImportManifest,
        raw_items: list[RawContentItem],
        content_items: list[ContentItem],
        content_versions: list[ContentVersion],
    ) -> None:
        if (
            manifest.workspace_id != session.workspace_id
            or manifest.import_session_id != session.id
        ):
            raise ProductionAdapterError("manifest escaped import session workspace")
        if manifest.source_connection_id != session.source_connection_id:
            raise ProductionAdapterError("manifest source mismatch")
        if manifest.content_count != len(content_versions) or len(raw_items) != len(
            content_versions
        ):
            raise ProductionAdapterError("manifest content count mismatch")
        if {item.id for item in content_items} != {
            version.content_item_id for version in content_versions
        }:
            raise ProductionAdapterError("content item/version IDs do not align")
        digest_input = "\n".join(version.content_digest for version in content_versions)
        if text_digest(digest_input) != manifest.normalized_payload_digest:
            raise ProductionAdapterError("normalized payload digest mismatch")
        for raw, version in zip(raw_items, content_versions, strict=True):
            if (
                raw.workspace_id != session.workspace_id
                or version.workspace_id != session.workspace_id
            ):
                raise ProductionAdapterError("content output workspace mismatch")
            if raw.source_connection_id != session.source_connection_id:
                raise ProductionAdapterError("raw output source mismatch")
            if raw.content_digest != version.content_digest:
                raise ProductionAdapterError("raw/version content digest mismatch")

    def _require_schedule_lease(
        self, db: Session, schedule_id: str, lease_token: str, now: datetime
    ) -> DbCollectionSchedule:
        schedule = db.get(DbCollectionSchedule, schedule_id)
        if schedule is None:
            raise ProductionAdapterError("schedule not found")
        if schedule.lease_owner_token != text_digest(lease_token):
            raise ProductionAdapterError("schedule lease token mismatch")
        if schedule.lease_expires_at is None or _as_utc(schedule.lease_expires_at) <= _as_utc(now):
            raise ProductionAdapterError("schedule lease expired")
        return schedule

    def _require_research_lease(self, run: DbResearchRun, worker_attempt_id: str) -> None:
        self._require_workspace(run.workspace_id)
        if run.worker_lease_expires_at is None or not run.worker_attempt_id:
            raise ProductionAdapterError("research run has no worker lease")
        if run.worker_attempt_id != worker_attempt_id:
            raise ProductionAdapterError("research run worker attempt mismatch")
        if _as_utc(run.worker_lease_expires_at) <= utcnow():
            raise ProductionAdapterError("research run worker lease expired")

    def _resolve_effective_consent_row(
        self, db: Session, session: DbImportSession, at: datetime
    ) -> DbTransferConsentRecord:
        consent = db.scalar(
            select(DbTransferConsentRecord)
            .where(
                DbTransferConsentRecord.import_session_id == session.id,
                DbTransferConsentRecord.decision == "grant",
            )
            .order_by(DbTransferConsentRecord.recorded_at.desc())
        )
        if consent is None or _as_utc(consent.expires_at) <= at:
            raise ConsentError("consent expired or absent")
        revoked = db.scalar(
            select(DbTransferConsentRecord.id).where(
                DbTransferConsentRecord.import_session_id == session.id,
                DbTransferConsentRecord.decision == "revoke",
                DbTransferConsentRecord.supersedes_id == consent.id,
            )
        )
        pinned = (
            consent.local_manifest_digest == session.local_manifest_digest
            and consent.file_digest == session.file_digest
            and consent.expected_upload_digest == session.expected_upload_digest
            and consent.selected_scope_digest == session.selected_scope_digest
            and consent.destination_workspace_id == session.workspace_id
            and consent.model_egress_authorization == "none"
        )
        if revoked or not pinned:
            raise ConsentError("consent revoked or not exact")
        return consent

    def _write_collected_snapshot(self, collection_key: str, raw: RawContentItem) -> str:
        object_key = f"workspaces/{raw.workspace_id}/collections/{collection_key}/{raw.id}.json"
        metadata = {key: value for key, value in raw.metadata.items() if key not in {"raw_digest"}}
        payload = {
            "source_item_id": raw.source_item_id,
            "title": raw.title,
            "body": raw.body,
            "canonical_url": raw.canonical_url,
            "author": raw.author,
            "published_at": raw.published_at.isoformat() if raw.published_at else None,
            "captured_at": raw.captured_at.isoformat(),
            "raw_digest": raw.metadata.get("raw_digest", raw.content_digest),
            "content_digest": raw.content_digest,
            "metadata": metadata,
        }
        uri = self.object_store.put_json(object_key, payload)
        return uri or f"object://{object_key}"

    def _collection_command_from_schedule(
        self,
        schedule: DbCollectionSchedule,
        lease_token: str,
        collection_kind: str,
        rules_json: dict[str, Any] | None = None,
    ):
        from services.worker.app.jobs.collection import CollectionCommand

        meta = schedule.query_json or {}
        rules = _watchlist_rule_set(rules_json or {})
        scheduled_for = _as_utc(schedule.next_run_at)
        include_terms = _rule_terms(rules, "include_terms")
        exclude_terms = _rule_terms(rules, "exclude_terms")
        languages = _rule_terms(rules, "languages")
        regions = _rule_terms(rules, "regions")
        entities = _list_strings(rules.get("entities"))
        topics = _rule_terms(rules, "topics") or _list_strings(rules.get("topics"))
        fallback_query = str(meta.get("query") or meta.get("q") or "")
        rule_terms = include_terms + entities + topics
        fallback_terms = _list_strings(meta.get("terms")) + (
            [fallback_query] if fallback_query else []
        )
        terms = _unique_terms(rule_terms if rule_terms else fallback_terms)
        query = _query_from_rules(
            positive_terms=terms,
            exclude_terms=exclude_terms,
            languages=languages,
            regions=regions,
            fallback=fallback_query,
        )
        current_window, baseline_window = _adjacent_windows_from_rules(rules, scheduled_for, meta)
        collection_key = deterministic_id(
            "collection-window",
            schedule.workspace_id,
            schedule.watchlist_id,
            schedule.source_connection_id,
            query,
            scheduled_for.isoformat(),
        )
        return CollectionCommand(
            workspace_id=schedule.workspace_id,
            watchlist_id=schedule.watchlist_id,
            source_connection_id=schedule.source_connection_id,
            query=query,
            collection_key=collection_key,
            terms=terms,
            current_window=current_window,
            baseline_window=baseline_window,
            scheduled_for=scheduled_for,
            exclude_terms=tuple(exclude_terms),
            languages=tuple(languages),
            regions=tuple(regions),
            entities=tuple(entities),
            topics=tuple(topics),
            detector_version=meta.get("detector_version", "signal-v1"),
            max_pages=int(meta.get("max_pages", 5)),
            schedule_id=schedule.id,
            schedule_lease_token=lease_token,
            schedule_fencing_version=schedule.lease_fencing_version,
            schedule_attempt=schedule.lease_attempt,
            cadence_seconds=schedule.cadence_seconds,
            timezone=schedule.timezone,
            connector_config=meta,
            collection_kind=collection_kind,
            refetch_limit=int(meta.get("refetch_limit", 0) or 0),
        )

    def _set_workspace(
        self, db: Session, workspace_id: str | None = None, principal_id: str | None = None
    ) -> None:
        effective_workspace = workspace_id or self.workspace_id
        self._require_workspace(effective_workspace)
        set_rls_context(db, effective_workspace, principal_id or self.worker_id)

    def _require_workspace(self, workspace_id: str | None) -> None:
        if workspace_id != self.workspace_id:
            raise ProductionAdapterError("workspace mismatch")

    def _require_collection_run_lease(
        self,
        db: Session,
        lease: CollectionLeaseContext,
        expected_workspace_id: str | None = None,
        expected_source_connection_id: str | None = None,
        expected_collection_key: str | None = None,
    ) -> CollectionRun:
        run = db.get(CollectionRun, lease.collection_run_id)
        if run is None:
            raise ProductionAdapterError("collection run not found")
        if run.state != "running":
            raise ProductionAdapterError("collection run is not running")
        self._require_workspace(run.workspace_id)
        if expected_workspace_id is not None and run.workspace_id != expected_workspace_id:
            raise ProductionAdapterError("collection run workspace mismatch")
        if (
            expected_source_connection_id is not None
            and run.source_connection_id != expected_source_connection_id
        ):
            raise ProductionAdapterError("collection run source mismatch")
        if expected_collection_key and run.stable_key != expected_collection_key:
            raise ProductionAdapterError("collection run key mismatch")
        metadata = run.input_window_json or {}
        if str(metadata.get("schedule_id") or "") != lease.schedule_id:
            raise ProductionAdapterError("collection run schedule mismatch")
        if metadata.get("schedule_lease_token"):
            raise ProductionAdapterError("collection run persisted a raw schedule lease token")
        if str(metadata.get("schedule_lease_token_digest") or "") != text_digest(
            lease.schedule_lease_token
        ):
            raise ProductionAdapterError("collection run schedule lease token mismatch")
        if int(metadata.get("schedule_fencing_version") or -1) != int(
            lease.schedule_fencing_version
        ):
            raise ProductionAdapterError("schedule lease fencing version mismatch")
        schedule = self._require_schedule_lease(
            db, lease.schedule_id, lease.schedule_lease_token, utcnow()
        )
        if int(schedule.lease_fencing_version) != int(lease.schedule_fencing_version):
            raise ProductionAdapterError("schedule lease fencing version mismatch")
        return run

    def _content_version_from_item(
        self, row: DbContentVersion, item: DbContentItem | None
    ) -> ContentVersion:
        metadata = dict(row.metadata_json or {})
        metadata.setdefault("source_connection_id", row.source_connection_id)
        if item is not None:
            metadata.setdefault("source_item_id", item.source_item_id)
        return ContentVersion(
            id=row.id,
            workspace_id=row.workspace_id,
            content_item_id=row.content_item_id,
            version_number=row.version_number,
            content_digest=row.content_digest,
            normalized_title=row.normalized_title,
            normalized_body=row.normalized_body,
            captured_at=row.captured_at,
            parser_version=row.parser_version,
            canonical_url=item.canonical_url if item else None,
            author=metadata.get("author"),
            data_authenticity=DataAuthenticity(row.data_authenticity),
            metadata=metadata,
        )

    def _validate_run_input_lineage(
        self, db: Session, run: DbResearchRun
    ) -> tuple[list[str], list[str]]:
        manifest = run.run_input_manifest_json or {}
        if digest(manifest) != run.run_input_manifest_digest:
            raise ProductionAdapterError("research run input manifest digest mismatch")
        terminal = manifest.get("terminal_import_manifests") or []
        content = manifest.get("content_versions") or []
        content_ids = [item["content_version_id"] for item in content]
        if not content_ids:
            raise ProductionAdapterError("research run lacks frozen content versions")
        if len(content_ids) != len(set(content_ids)):
            raise ProductionAdapterError("research run input repeats a content version")
        terminal_by_id = {item["import_manifest_id"]: item for item in terminal}
        content_by_id = {item["content_version_id"]: item for item in content}
        collection_by_id = {
            item["collection_run_id"]: item
            for item in (
                manifest.get("terminal_collection_runs") or manifest.get("collection_runs") or []
            )
            if isinstance(item, dict) and item.get("collection_run_id")
        }
        import_content = [
            item
            for item in content
            if item.get("import_manifest_id") or item.get("origin_type") == "import_manifest"
        ]
        collection_content = [
            item for item in content if _collection_snapshot(item, collection_by_id) is not None
        ]
        if len(import_content) + len(collection_content) != len(content):
            raise ProductionAdapterError("research run content origin is not frozen")
        manifest_ids = sorted({item["import_manifest_id"] for item in import_content})
        if terminal_by_id and set(manifest_ids) - set(terminal_by_id):
            raise ProductionAdapterError("terminal import manifest snapshot is missing")
        if import_content and not terminal_by_id:
            raise ProductionAdapterError("import content requires terminal manifest snapshots")

        db_manifests = db.scalars(
            select(DbImportManifest).where(
                DbImportManifest.workspace_id == run.workspace_id,
                DbImportManifest.id.in_(manifest_ids),
            )
        ).all()
        if len(db_manifests) != len(set(manifest_ids)):
            raise ProductionAdapterError("terminal import manifest is missing")
        for row in db_manifests:
            session = db.get(DbImportSession, row.import_session_id)
            snapshot = terminal_by_id[row.id]
            if (
                session is None
                or session.state != "finalized"
                or session.terminal_manifest_id != row.id
            ):
                raise ProductionAdapterError(
                    "research run references a non-terminal import manifest"
                )
            if (
                snapshot.get("file_digest") != row.file_digest
                or snapshot.get("uploaded_object_digest") != row.uploaded_object_digest
                or snapshot.get("normalized_payload_digest") != row.normalized_payload_digest
                or snapshot.get("source_connection_id") != row.source_connection_id
            ):
                raise ProductionAdapterError("terminal import manifest digest changed")
        if import_content:
            rows = db.execute(
                select(
                    ImportManifestContentVersion.import_manifest_id,
                    ImportManifestContentVersion.content_version_id,
                    DbContentVersion.content_digest,
                    DbContentVersion.source_connection_id,
                    DbContentVersion.raw_content_item_id,
                    DbRawContentItem.import_manifest_id,
                    DbRawContentItem.collection_run_id,
                    DbRawContentItem.raw_digest,
                )
                .join(
                    DbContentVersion,
                    DbContentVersion.id == ImportManifestContentVersion.content_version_id,
                )
                .join(DbRawContentItem, DbRawContentItem.id == DbContentVersion.raw_content_item_id)
                .where(
                    ImportManifestContentVersion.workspace_id == run.workspace_id,
                    ImportManifestContentVersion.import_manifest_id.in_(manifest_ids),
                    ImportManifestContentVersion.content_version_id.in_(
                        [item["content_version_id"] for item in import_content]
                    ),
                )
            ).all()
        else:
            rows = []
        if len(rows) != len({item["content_version_id"] for item in import_content}):
            raise ProductionAdapterError("research run import content lineage is incomplete")
        for (
            manifest_id,
            content_version_id,
            content_digest,
            source_connection_id,
            _raw_content_item_id,
            raw_import_manifest_id,
            raw_collection_run_id,
            raw_digest,
        ) in rows:
            snapshot = content_by_id[content_version_id]
            manifest_snapshot = terminal_by_id[manifest_id]
            if (
                snapshot.get("import_manifest_id") != manifest_id
                or snapshot.get("content_digest") != content_digest
            ):
                raise ProductionAdapterError("research run content digest changed")
            if source_connection_id != manifest_snapshot.get("source_connection_id"):
                raise ProductionAdapterError(
                    "content version escaped terminal manifest source scope"
                )
            if raw_import_manifest_id != manifest_id or raw_collection_run_id is not None:
                raise ProductionAdapterError("import content version origin is not exact")
            if snapshot.get("raw_digest") and snapshot.get("raw_digest") != raw_digest:
                raise ProductionAdapterError("research run raw digest changed")
        self._validate_collected_run_input_lineage(db, run, collection_content, collection_by_id)
        return content_ids, manifest_ids

    def _validate_collected_run_input_lineage(
        self,
        db: Session,
        run: DbResearchRun,
        content_snapshots: list[dict[str, Any]],
        collection_by_id: dict[str, dict[str, Any]],
    ) -> None:
        for snapshot in content_snapshots:
            origin = _collection_snapshot(snapshot, collection_by_id)
            if origin is None:
                raise ProductionAdapterError("collection content origin is not frozen")
            rows = db.execute(
                select(DbContentVersion, DbRawContentItem, CollectionRun)
                .join(DbRawContentItem, DbRawContentItem.id == DbContentVersion.raw_content_item_id)
                .join(CollectionRun, CollectionRun.id == DbRawContentItem.collection_run_id)
                .where(
                    DbContentVersion.id == snapshot["content_version_id"],
                    DbContentVersion.workspace_id == run.workspace_id,
                    DbRawContentItem.workspace_id == run.workspace_id,
                    CollectionRun.workspace_id == run.workspace_id,
                )
            ).all()
            if len(rows) != 1:
                raise ProductionAdapterError("collection content lineage is incomplete")
            version, raw, collection_run = rows[0]
            collection_run_id = str(origin.get("collection_run_id") or "")
            if collection_run_id != collection_run.id or raw.collection_run_id != collection_run.id:
                raise ProductionAdapterError("collection content did not freeze actual origin run")
            if raw.import_manifest_id is not None:
                raise ProductionAdapterError("collection raw content has multiple origins")
            if version.raw_content_item_id != raw.id:
                raise ProductionAdapterError("content version raw lineage changed")
            if version.content_digest != snapshot.get("content_digest"):
                raise ProductionAdapterError("research run content digest changed")
            if raw.raw_digest != origin.get("raw_digest"):
                raise ProductionAdapterError("research run raw digest changed")
            if version.source_connection_id != raw.source_connection_id:
                raise ProductionAdapterError("content version escaped raw source scope")
            if collection_run.source_connection_id != raw.source_connection_id:
                raise ProductionAdapterError("collection content escaped source scope")
            if origin.get("source_connection_id") != collection_run.source_connection_id:
                raise ProductionAdapterError("collection source snapshot changed")
            if origin.get("watchlist_id") != collection_run.watchlist_id:
                raise ProductionAdapterError("collection watchlist snapshot changed")
            if collection_run.state not in {"succeeded", "partial_success"}:
                raise ProductionAdapterError("collection run is not terminal")
            if collection_run.finished_at is None:
                raise ProductionAdapterError("collection run has no finished_at")
            if origin.get("state") and origin.get("state") != collection_run.state:
                raise ProductionAdapterError("collection state snapshot changed")
            if origin.get("stable_key") != collection_run.stable_key:
                raise ProductionAdapterError("collection stable key snapshot changed")
            if int(origin.get("attempt") or -1) != int(collection_run.attempt):
                raise ProductionAdapterError("collection attempt snapshot changed")
            if _parse_dt(str(origin.get("scheduled_for"))) != _as_utc(collection_run.scheduled_for):
                raise ProductionAdapterError("collection scheduled_for snapshot changed")
            if _parse_dt(str(origin.get("finished_at"))) != _as_utc(collection_run.finished_at):
                raise ProductionAdapterError("collection finished_at snapshot changed")

    def _command_from_record(
        self, record: ImportFinalizationJobRecord, lease_token: str
    ) -> ImportFinalizationCommand:
        return ImportFinalizationCommand(
            workspace_id=record.workspace_id,
            import_session_id=record.import_session_id,
            finalize_command_id=record.id,
            expected_session_row_version=record.expected_session_row_version,
            expected_source_row_version=record.expected_source_row_version,
            expected_current_import_manifest_id=record.expected_current_import_manifest_id,
            consent_record_id=record.consent_record_id,
            actor_id=record.actor_id,
            request_id=record.request_id,
            lease_token=lease_token,
        )

    def _source_validation_claim(
        self,
        job: SourceValidationJobRecord,
        lease_token: str,
        source: DbSourceConnection,
    ) -> SourceValidationClaim:
        if job.lease_expires_at is None:
            raise ProductionAdapterError("source validation claim has no lease expiry")
        return SourceValidationClaim(
            job_id=job.id,
            workspace_id=job.workspace_id,
            source_connection_id=job.source_connection_id,
            command=job.command,
            connector_config=_source_validation_connector_config(source),
            lease_token=lease_token,
            attempt=job.attempt,
            fencing_version=job.fencing_version,
            lease_expires_at=_as_utc(job.lease_expires_at),
        )

    def _source(self, row: DbSourceConnection) -> SourceConnection:
        return SourceConnection(
            id=row.id,
            workspace_id=row.workspace_id,
            source_kind=row.source_kind,
            runtime=row.runtime,
            connector_type=row.connector_type,
            connector_version=row.connector_version,
            status=SourceHealthStatus(row.status)
            if row.status in SourceHealthStatus._value2member_map_
            else SourceHealthStatus.DEGRADED,
            credential_ref=row.credential_ref,
            data_scope=row.data_scope,
            current_import_manifest_id=row.current_import_manifest_id,
            row_version=row.row_version,
            data_authenticity=DataAuthenticity(row.data_authenticity),
            freshness={
                "config": row.config_json or {},
                "last_run_at": row.last_run_at.isoformat() if row.last_run_at else None,
                "last_success_at": row.last_success_at.isoformat() if row.last_success_at else None,
                "freshness_state": row.freshness_state,
                "health_state": row.health_state,
            },
        )

    def _session(self, row: DbImportSession) -> ImportSession:
        return ImportSession(
            id=row.id,
            workspace_id=row.workspace_id,
            source_connection_id=row.source_connection_id,
            expected_source_row_version=row.expected_source_row_version,
            expected_current_import_manifest_id=row.expected_current_import_manifest_id,
            local_manifest_digest=row.local_manifest_digest,
            file_digest=row.file_digest,
            expected_upload_digest=row.expected_upload_digest,
            client_file_name=row.client_file_name,
            file_size_bytes=row.file_size_bytes,
            media_type=row.media_type,
            parser_version=row.parser_version,
            schema_version=row.schema_version,
            selected_scope_json=row.selected_scope_json,
            selected_scope_digest=row.selected_scope_digest,
            state=ImportSessionState(row.state),
            uploaded_object_key=row.uploaded_object_key,
            uploaded_object_digest=row.uploaded_object_digest,
            terminal_manifest_id=row.terminal_manifest_id,
            failure_code=row.failure_code,
            retryable=row.retryable,
            row_version=row.row_version,
            data_authenticity=DataAuthenticity(row.data_authenticity),
        )

    def _consent(self, row: DbTransferConsentRecord) -> TransferConsentRecord:
        return TransferConsentRecord(
            id=row.id,
            workspace_id=row.workspace_id,
            import_session_id=row.import_session_id,
            decision=ConsentDecision(row.decision),
            local_manifest_digest=row.local_manifest_digest,
            file_digest=row.file_digest,
            expected_upload_digest=row.expected_upload_digest,
            selected_scope_digest=row.selected_scope_digest,
            destination_workspace_id=row.destination_workspace_id,
            upload_object_scope=UploadObjectScope(**row.upload_object_scope),
            model_egress_authorization=row.model_egress_authorization,
            policy_version=row.policy_version,
            actor_id=row.actor_id,
            recorded_at=row.recorded_at,
            expires_at=row.expires_at,
            supersedes_id=row.supersedes_id,
            data_authenticity=DataAuthenticity(row.data_authenticity),
        )

    def _manifest(self, row: DbImportManifest) -> ImportManifest:
        return ImportManifest(
            id=row.id,
            workspace_id=row.workspace_id,
            import_session_id=row.import_session_id,
            source_connection_id=row.source_connection_id,
            file_digest=row.file_digest,
            uploaded_object_key=row.uploaded_object_key,
            uploaded_object_digest=row.uploaded_object_digest,
            parser_version=row.parser_version,
            schema_version=row.schema_version,
            selected_scope_digest=row.selected_scope_digest,
            consent_record_id=row.consent_record_id,
            normalized_payload_digest=row.normalized_payload_digest,
            content_count=row.content_count,
            finalized_at=row.finalized_at,
            data_authenticity=DataAuthenticity(row.data_authenticity),
        )

    def _content_version(self, row: DbContentVersion) -> ContentVersion:
        item = None
        with self.session_factory() as db:
            self._set_workspace(db, row.workspace_id)
            item = db.get(DbContentItem, row.content_item_id)
        return self._content_version_from_item(row, item)


class ConfiguredApiObjectStore:
    """Thin worker-side wrapper around the API-owned object store implementation."""

    def __init__(self, backend: Any) -> None:
        self.backend = backend

    def get_import_object(
        self,
        *,
        workspace_id: str,
        import_session_id: str,
        key: str,
    ) -> StoredObject:
        try:
            require_import_payload_object_key(workspace_id, import_session_id, key)
        except ObjectScopeMismatch as exc:
            raise ObjectVerificationError("object key is outside the import workspace") from exc
        observed = self._get_object(key)
        try:
            require_import_payload_object_key(workspace_id, import_session_id, observed.key)
        except ObjectScopeMismatch as exc:
            raise ObjectVerificationError(
                "object store returned a key outside the import workspace"
            ) from exc
        return observed

    def _get_object(self, key: str) -> StoredObject:
        from services.worker.app.contracts import (
            ObjectNotFoundError,
            ObjectUnavailableError,
        )

        getter = getattr(self.backend, "get", None) or getattr(self.backend, "get_object", None)
        if not callable(getter):
            raise ProductionAdapterError("API object store must expose get(key)")
        try:
            obj = getter(key)
        except KeyError as exc:
            raise ObjectNotFoundError("object store key not found") from exc
        except Exception as exc:
            code = _exception_error_code(exc)
            if code in {"NoSuchKey", "404", "NotFound"}:
                raise ObjectNotFoundError("object store key not found") from exc
            if exc.__class__.__name__ in {
                "EndpointConnectionError",
                "ConnectTimeoutError",
                "ReadTimeoutError",
            } or code in {
                "RequestTimeout",
                "SlowDown",
                "ServiceUnavailable",
                "InternalError",
            }:
                raise ObjectUnavailableError("object store is temporarily unavailable") from exc
            raise
        if isinstance(obj, StoredObject):
            return obj
        if isinstance(obj, dict):
            body = obj["body"]
            if body is None:
                raise ProductionAdapterError("API object store get() returned no body")
            return StoredObject(
                key=str(obj.get("key") or key),
                body=body,
                digest=str(obj.get("digest") or digest(body)),
                size_bytes=int(obj.get("size_bytes") or len(body)),
                media_type=str(obj.get("media_type") or "application/octet-stream"),
            )
        body = getattr(obj, "body", None)
        if body is None:
            raise ProductionAdapterError("API object store get() returned no body")
        return StoredObject(
            key=str(getattr(obj, "key", key)),
            body=body,
            digest=str(getattr(obj, "digest", digest(body))),
            size_bytes=int(getattr(obj, "size_bytes", len(body))),
            media_type=str(getattr(obj, "media_type", "application/octet-stream")),
        )

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
        quarantine = getattr(self.backend, "quarantine", None)
        if not callable(quarantine):
            raise ProductionAdapterError("API object store must expose quarantine(key, reason)")
        quarantine(key, reason)

    def put_json(self, key: str, payload: dict[str, Any]) -> str:
        put_json = getattr(self.backend, "put_json", None)
        if callable(put_json):
            return str(put_json(key, payload))
        putter = getattr(self.backend, "put", None) or getattr(self.backend, "put_object", None)
        if callable(putter):
            import json

            body = json.dumps(
                payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
            ).encode("utf-8")
            result = putter(key, body, media_type="application/json")
            if isinstance(result, str):
                return result
            return str(getattr(result, "uri", f"object://{key}"))
        raise ProductionAdapterError(
            "API object store must expose put_json(key, payload) or put(key, body, media_type)"
        )


def create_adapter() -> SQLAlchemyWorkerDomainAdapter:
    return SQLAlchemyWorkerDomainAdapter()


def create_object_store() -> ConfiguredApiObjectStore:
    factory_path = os.environ.get("GLINT_WORKER_OBJECT_STORE") or os.environ.get(
        "GLINT_API_OBJECT_STORE"
    )
    if not factory_path:
        raise ProductionAdapterError(
            "GLINT_WORKER_OBJECT_STORE or GLINT_API_OBJECT_STORE is required in production"
        )
    module_name, sep, factory_name = factory_path.partition(":")
    if not sep:
        raise ProductionAdapterError("object store factory must be module.path:factory")
    module = __import__(module_name, fromlist=[factory_name])
    factory = getattr(module, factory_name)
    return ConfiguredApiObjectStore(factory())


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _signal_cooldown_seconds(signal: Signal) -> int:
    policy = signal.dimensions.get("detector_policy")
    if isinstance(policy, dict):
        value = policy.get("cooldown_seconds")
        if isinstance(value, int) and not isinstance(value, bool):
            return max(0, value)
    return 0


def _metadata_dt(metadata: dict[str, Any], key: str) -> datetime | None:
    value = metadata.get(key)
    if isinstance(value, datetime):
        return _as_utc(value)
    if isinstance(value, str) and value:
        try:
            return _parse_dt(value)
        except ValueError:
            return None
    return None


def _availability_from_metadata(metadata: dict[str, Any]) -> str:
    value = str(metadata.get("availability") or "captured")
    return value if value in {"captured", "deleted", "unavailable"} else "captured"


def _availability_checked_at(metadata: dict[str, Any], fallback: datetime) -> datetime:
    return _metadata_dt(metadata, "checked_at") or _as_utc(fallback)


def _availability_reason(metadata: dict[str, Any]) -> str | None:
    value = metadata.get("availability_reason") or metadata.get("failure_reason")
    return str(value) if value else None


def _first_future_slot(start: datetime, cadence_seconds: int, current: datetime) -> datetime:
    cadence = timedelta(seconds=max(1, cadence_seconds))
    slot = _as_utc(start)
    now = _as_utc(current)
    while slot <= now:
        slot += cadence
    return slot


def _latest_allowed_backlog_slot(
    start: datetime, cadence_seconds: int, current: datetime, catch_up_limit: int
) -> datetime:
    cadence = timedelta(seconds=max(1, cadence_seconds))
    slot = _as_utc(start)
    now = _as_utc(current)
    slots: list[datetime] = []
    while slot <= now:
        slots.append(slot)
        slot += cadence
    if len(slots) <= catch_up_limit:
        return _as_utc(start)
    return slots[-catch_up_limit]


def _parse_dt(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        return _as_utc(value)
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    return datetime.fromisoformat(text).astimezone(UTC)


def _watchlist_rule_set(rules_json: dict[str, Any]) -> dict[str, Any]:
    value = rules_json.get("rules")
    return value if isinstance(value, dict) else {}


def _rule_terms(rules: dict[str, Any], key: str) -> list[str]:
    query_rules = rules.get("query_rules")
    nested = query_rules.get(key) if isinstance(query_rules, dict) else None
    return _list_strings(nested if nested is not None else rules.get(key))


def _list_strings(value: object) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = str(item).strip()
        folded = text.casefold()
        if text and folded not in seen:
            seen.add(folded)
            result.append(text)
    return result


def _unique_terms(values: list[str]) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = value.strip()
        folded = text.casefold()
        if text and folded not in seen:
            seen.add(folded)
            result.append(text)
    return tuple(result)


def _query_from_rules(
    *,
    positive_terms: tuple[str, ...],
    exclude_terms: list[str],
    languages: list[str],
    regions: list[str],
    fallback: str,
) -> str:
    parts = [_query_token(term) for term in positive_terms]
    parts.extend(f"-{_query_token(term)}" for term in exclude_terms)
    parts.extend(f"language:{_query_token(value)}" for value in languages)
    parts.extend(f"region:{_query_token(value)}" for value in regions)
    query = " ".join(part for part in parts if part)
    return query or fallback


def _query_token(value: str) -> str:
    text = value.strip()
    if not text:
        return ""
    if any(char.isspace() for char in text):
        return '"' + text.replace('"', "") + '"'
    return text


def _adjacent_windows_from_rules(
    rules: dict[str, Any], scheduled_for: datetime, meta: dict[str, Any]
) -> tuple[tuple[datetime, datetime], tuple[datetime, datetime]]:
    current_days = _positive_int(
        rules.get("current_window_days"),
        meta.get("current_window_days", meta.get("current_days", 1)),
    )
    baseline_days = _positive_int(
        rules.get("baseline_window_days"),
        meta.get("baseline_window_days", meta.get("baseline_days", 7)),
    )
    current_end = _as_utc(scheduled_for)
    current_start = current_end - timedelta(days=current_days)
    baseline_end = current_start
    baseline_start = baseline_end - timedelta(days=baseline_days)
    return (current_start, current_end), (baseline_start, baseline_end)


def _positive_int(primary: object, fallback: object) -> int:
    for value in (primary, fallback):
        if isinstance(value, bool) or not isinstance(value, (int, float, str)):
            continue
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            continue
        if parsed > 0:
            return parsed
    return 1


def _source_status_for_health(status: SourceHealthStatus) -> str:
    if status == SourceHealthStatus.HEALTHY:
        return "healthy"
    if status == SourceHealthStatus.AUTH_REQUIRED:
        return "auth_required"
    if status == SourceHealthStatus.FAILED:
        return "failed"
    if status == SourceHealthStatus.DISABLED:
        return "disabled"
    return "degraded"


def _collection_snapshot(
    content_snapshot: dict[str, Any], collection_by_id: dict[str, dict[str, Any]]
) -> dict[str, Any] | None:
    origin = content_snapshot.get("origin")
    if isinstance(origin, dict) and origin.get("collection_run_id"):
        return {**collection_by_id.get(str(origin["collection_run_id"]), {}), **origin}
    if content_snapshot.get("collection_run_id"):
        return {
            **collection_by_id.get(str(content_snapshot["collection_run_id"]), {}),
            **content_snapshot,
        }
    return None


def _uuid(value: str | None) -> UUID | None:
    return UUID(value) if value else None


def _authenticity(value: DataAuthenticity) -> ContractDataAuthenticity:
    return ContractDataAuthenticity(value.value)


def _import_normalization_proposal(
    manifest: ImportManifest,
    raw_items: list[RawContentItem],
    content_items: list[ContentItem],
    content_versions: list[ContentVersion],
) -> ImportNormalizationProposal:
    return ImportNormalizationProposal(
        manifest=ImportManifestProposal(
            id=UUID(manifest.id),
            workspace_id=UUID(manifest.workspace_id),
            import_session_id=UUID(manifest.import_session_id),
            source_connection_id=UUID(manifest.source_connection_id),
            file_digest=manifest.file_digest,
            uploaded_object_key=manifest.uploaded_object_key,
            uploaded_object_digest=manifest.uploaded_object_digest,
            parser_version=manifest.parser_version,
            schema_version=manifest.schema_version,
            selected_scope_digest=manifest.selected_scope_digest,
            consent_record_id=UUID(manifest.consent_record_id),
            normalized_payload_digest=manifest.normalized_payload_digest,
            content_count=manifest.content_count,
            finalized_at=manifest.finalized_at,
            data_authenticity=_authenticity(manifest.data_authenticity),
        ),
        raw_items=[
            NormalizedRawContentProposal(
                id=UUID(raw.id),
                workspace_id=UUID(raw.workspace_id),
                source_connection_id=UUID(raw.source_connection_id),
                source_item_id=raw.source_item_id,
                title=raw.title,
                body=raw.body,
                canonical_url=raw.canonical_url,
                author=raw.author,
                published_at=raw.published_at,
                captured_at=raw.captured_at,
                content_digest=raw.content_digest,
                data_authenticity=_authenticity(raw.data_authenticity),
                metadata=raw.metadata,
            )
            for raw in raw_items
        ],
        content_items=[
            NormalizedContentItemProposal(
                id=UUID(item.id),
                workspace_id=UUID(item.workspace_id),
                source_connection_id=UUID(item.source_connection_id),
                source_item_id=item.source_item_id,
                canonical_url=item.canonical_url,
                identity_key=item.identity_key,
                title=item.title,
                current_version_id=UUID(item.current_version_id),
                duplicate_cluster_id=_uuid(item.duplicate_cluster_id),
                independence_group_id=_uuid(item.independence_group_id),
                data_authenticity=_authenticity(item.data_authenticity),
            )
            for item in content_items
        ],
        content_versions=[
            NormalizedContentVersionProposal(
                id=UUID(version.id),
                workspace_id=UUID(version.workspace_id),
                content_item_id=UUID(version.content_item_id),
                version_number=version.version_number,
                content_digest=version.content_digest,
                normalized_title=version.normalized_title,
                normalized_body=version.normalized_body,
                captured_at=version.captured_at,
                parser_version=version.parser_version,
                canonical_url=version.canonical_url,
                author=version.author,
                data_authenticity=_authenticity(version.data_authenticity),
                metadata=version.metadata,
            )
            for version in content_versions
        ],
    )


def _map_import_api_error(error: ApiError) -> Exception:
    if error.code in {"CONSENT_EXPIRED_OR_REVOKED"}:
        return ConsentError(error.message)
    if error.code in {"OBJECT_SCOPE_MISMATCH", "NORMALIZATION_LINEAGE_MISMATCH"}:
        return ObjectVerificationError(error.message)
    if error.code in {"STALE_SOURCE_VERSION", "VERSION_CONFLICT", "FINALIZATION_CONFLICT"}:
        return SourcePointerError(error.message)
    if error.code in {"JOB_LEASE_EXPIRED", "JOB_ALREADY_CLAIMED", "INVALID_STATE"}:
        return NonTerminalImportError(error.message)
    return RetryableJobError(error.message)


def _watchlist_allows_source(rules: dict[str, Any], source_connection_id: str) -> bool:
    return source_connection_id in _watchlist_source_ids(rules)


def _watchlist_source_ids(rules: dict[str, Any]) -> set[str]:
    allowed = rules.get("source_connection_ids")
    if isinstance(allowed, (list, tuple)):
        return {str(item) for item in allowed}
    return set()


def _source_validation_connector_config(source: DbSourceConnection) -> dict[str, object]:
    config = dict(source.config_json or {})
    connector_type = str(source.connector_type).lower()
    if connector_type == "github":
        if config.get("owner") and (config.get("repo") or config.get("repository")):
            return config
        repositories = config.get("repositories")
        if isinstance(repositories, list) and len(repositories) == 1:
            repository = repositories[0]
            if isinstance(repository, dict):
                owner = repository.get("owner")
                repo = repository.get("repo") or repository.get("repository")
                if owner and repo:
                    return {
                        "owner": str(owner),
                        "repo": str(repo),
                        "include_repository": repository.get("include_repository", True),
                        "include_issues": repository.get("include_issues", True),
                        "include_discussions": repository.get("include_discussions", True),
                        "include_releases": repository.get("include_releases", True),
                    }
        return {}
    if connector_type in {"rss", "atom"}:
        if config.get("feed_url") or config.get("url"):
            return config
        feeds = config.get("feeds")
        if isinstance(feeds, list) and len(feeds) == 1:
            feed = feeds[0]
            if isinstance(feed, dict):
                feed_url = feed.get("feed_url") or feed.get("url")
                if feed_url:
                    return {
                        "feed_url": str(feed_url),
                        **({"feed_title": feed.get("name")} if feed.get("name") else {}),
                    }
        return {}
    return config


def _map_source_validation_api_error(error: ApiError) -> ProductionAdapterError:
    return ProductionAdapterError(f"{error.code}: {error.message}")


def _exception_error_code(exc: Exception) -> str | None:
    response = getattr(exc, "response", None)
    if isinstance(response, dict):
        error = response.get("Error")
        if isinstance(error, dict):
            code = error.get("Code")
            return str(code) if code is not None else None
    return None
