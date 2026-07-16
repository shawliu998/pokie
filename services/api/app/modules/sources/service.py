from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from packages.contracts.schemas import ImportNormalizationProposal
from packages.domain.canonical import canonical_digest
from packages.domain.errors import ObjectScopeMismatch
from packages.domain.imports import import_payload_object_key
from services.api.app.core.config import get_settings
from services.api.app.core.errors import ApiError, invalid_state, not_found, version_conflict
from services.api.app.core.object_store import WorkspaceImportObjectStore, get_object_store
from services.api.app.db.models import (
    CollectionRun,
    ContentItem,
    ContentVersion,
    ImportFinalizationJobRecord,
    ImportManifest,
    ImportManifestContentVersion,
    ImportSession,
    RawContentItem,
    Signal,
    SignalEvidence,
    SourceConnection,
    TransferConsentRecord,
    UploadGrant,
    Watchlist,
)
from services.api.app.modules.common import audit, text_digest, utcnow
from services.api.app.modules.watchlists.baseline import has_ready_initial_baseline

ACTIVE_IMPORT_STATES = {"draft", "consented", "uploaded", "validating"}
TERMINAL_IMPORT_STATES = {"finalized", "cancelled"}
UPLOAD_CONSENT_POLICY_VERSION = "import-transfer-v1"


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _import_object_store(workspace_id: str, import_session_id: str) -> WorkspaceImportObjectStore:
    return WorkspaceImportObjectStore(get_object_store(), workspace_id, import_session_id)


def create_import_session(
    db: Session,
    *,
    workspace_id: str,
    actor_id: str,
    payload: dict[str, Any],
    request_id: str,
) -> ImportSession:
    source = db.scalar(
        select(SourceConnection).where(
            SourceConnection.id == payload["source_connection_id"],
            SourceConnection.workspace_id == workspace_id,
        )
    )
    if source is None:
        raise not_found("Source connection")
    if source.source_kind != "imported_dataset" or source.runtime != "static_import":
        raise ApiError(
            422, "SOURCE_SCOPE_BLOCKED", "Phase 1 imports require an Imported Dataset source."
        )
    if source.row_version != payload["expected_source_row_version"]:
        raise version_conflict(source.id, source.row_version)
    if source.current_import_manifest_id != payload.get("expected_current_import_manifest_id"):
        raise ApiError(
            412,
            "STALE_SOURCE_VERSION",
            "The imported source pointer changed; create a new import session.",
            {"current_import_manifest_id": source.current_import_manifest_id},
        )
    active = db.scalar(
        select(ImportSession.id).where(
            ImportSession.workspace_id == workspace_id,
            ImportSession.source_connection_id == source.id,
            ImportSession.state.in_(ACTIVE_IMPORT_STATES)
            | ((ImportSession.state == "failed") & ImportSession.retryable.is_(True)),
        )
    )
    if active:
        raise ApiError(409, "ACTIVE_IMPORT_EXISTS", "Finish or cancel the active import first.")
    if payload["file_size_bytes"] > get_settings().max_import_bytes:
        raise ApiError(422, "VALIDATION_ERROR", "The import exceeds the configured byte limit.")
    if payload["media_type"] not in {"text/csv", "application/csv"}:
        raise ApiError(422, "VALIDATION_ERROR", "Phase 1 supports CSV imports only.")
    session = ImportSession(
        workspace_id=workspace_id,
        created_by=actor_id,
        data_authenticity=source.data_authenticity,
        **payload,
    )
    db.add(session)
    db.flush()
    audit(
        db,
        workspace_id=workspace_id,
        actor_id=actor_id,
        action="import.session_created",
        target_type="ImportSession",
        target_id=session.id,
        request_id=request_id,
        after={"source_connection_id": source.id, "file_digest": session.file_digest},
    )
    db.commit()
    return session


def grant_upload_consent(
    db: Session,
    *,
    session: ImportSession,
    actor_id: str,
    preview_scope: dict[str, Any],
    scope_digest: str,
    expires_at: datetime,
    confirmation: bool,
    request_id: str,
) -> tuple[TransferConsentRecord, UploadGrant, str]:
    locked_session = db.scalar(
        select(ImportSession)
        .where(
            ImportSession.id == session.id,
            ImportSession.workspace_id == session.workspace_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if locked_session is None:
        raise not_found("Import session")
    session = locked_session
    if session.state != "draft":
        raise invalid_state("Upload consent can be granted only for a draft import.")
    source = db.scalar(
        select(SourceConnection)
        .where(
            SourceConnection.id == session.source_connection_id,
            SourceConnection.workspace_id == session.workspace_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if source is None:
        raise not_found("Source connection")
    expected_scope = build_upload_consent_scope(session=session, source=source)
    expected_digest = canonical_digest(expected_scope)
    if preview_scope != expected_scope or scope_digest != expected_digest:
        raise ApiError(
            412,
            "CONSENT_SCOPE_STALE",
            "The upload consent scope changed; request a new preview.",
            {
                "import_session_id": session.id,
                "current_import_session_row_version": session.row_version,
                "current_source_row_version": source.row_version,
            },
        )
    if not confirmation:
        raise ApiError(409, "APPROVAL_REQUIRED", "Explicit transfer confirmation is required.")
    now = utcnow()
    expiry = _as_utc(expires_at)
    maximum_expiry = now.timestamp() + get_settings().upload_grant_ttl_seconds
    if expiry <= now or expiry.timestamp() > maximum_expiry:
        raise ApiError(
            422, "VALIDATION_ERROR", "Consent expiry is outside the allowed grant window."
        )
    scope = expected_scope["upload_object_scope"]
    object_key = str(scope["object_key"])
    consent = TransferConsentRecord(
        workspace_id=session.workspace_id,
        import_session_id=session.id,
        decision="grant",
        local_manifest_digest=session.local_manifest_digest,
        file_digest=session.file_digest,
        expected_upload_digest=session.expected_upload_digest,
        selected_scope_json=session.selected_scope_json,
        selected_scope_digest=session.selected_scope_digest,
        destination_workspace_id=session.workspace_id,
        upload_object_scope=scope,
        model_egress_authorization="none",
        policy_version=UPLOAD_CONSENT_POLICY_VERSION,
        actor_id=actor_id,
        expires_at=expiry,
        data_authenticity=session.data_authenticity,
    )
    db.add(consent)
    db.flush()
    raw_token = secrets.token_urlsafe(32)
    grant = UploadGrant(
        workspace_id=session.workspace_id,
        import_session_id=session.id,
        consent_record_id=consent.id,
        token_digest=text_digest(raw_token),
        object_key=object_key,
        max_bytes=session.file_size_bytes,
        media_type=session.media_type,
        expires_at=expiry,
    )
    db.add(grant)
    session.state = "consented"
    session.row_version += 1
    audit(
        db,
        workspace_id=session.workspace_id,
        actor_id=actor_id,
        action="import.transfer_consent_granted",
        target_type="ImportSession",
        target_id=session.id,
        request_id=request_id,
        after={"consent_record_id": consent.id, "upload_object_scope": scope},
    )
    db.commit()
    return consent, grant, raw_token


def build_upload_consent_scope(
    *, session: ImportSession, source: SourceConnection
) -> dict[str, Any]:
    if session.state != "draft":
        raise invalid_state("Upload consent can be previewed only for a draft import.")
    if session.source_connection_id != source.id or session.workspace_id != source.workspace_id:
        raise ApiError(409, "SOURCE_SCOPE_MISMATCH", "The import source scope is invalid.")
    if (
        source.row_version != session.expected_source_row_version
        or source.current_import_manifest_id != session.expected_current_import_manifest_id
    ):
        raise ApiError(
            412,
            "STALE_SOURCE_VERSION",
            "The imported source changed; create a new import session.",
            {
                "current_source_row_version": source.row_version,
                "current_import_manifest_id": source.current_import_manifest_id,
            },
        )
    return {
        "destination_workspace_id": session.workspace_id,
        "import_session_id": session.id,
        "import_session_row_version": session.row_version,
        "source_connection_id": source.id,
        "source_row_version": source.row_version,
        "current_import_manifest_id": source.current_import_manifest_id,
        "local_manifest_digest": session.local_manifest_digest,
        "file_digest": session.file_digest,
        "expected_upload_digest": session.expected_upload_digest,
        "selected_scope_digest": session.selected_scope_digest,
        "upload_object_scope": {
            "object_key": import_payload_object_key(session.workspace_id, session.id),
            "max_bytes": session.file_size_bytes,
            "media_type": session.media_type,
        },
        "policy_version": UPLOAD_CONSENT_POLICY_VERSION,
    }


def preview_upload_consent(
    db: Session, *, session: ImportSession, expected_row_version: int
) -> tuple[dict[str, Any], str]:
    if session.row_version != expected_row_version:
        raise version_conflict(session.id, session.row_version)
    source = db.scalar(
        select(SourceConnection).where(
            SourceConnection.id == session.source_connection_id,
            SourceConnection.workspace_id == session.workspace_id,
        )
    )
    if source is None:
        raise not_found("Source connection")
    scope = build_upload_consent_scope(session=session, source=source)
    return scope, canonical_digest(scope)


def authorize_upload_grant(
    db: Session,
    *,
    workspace_id: str,
    import_session_id: str,
    raw_token: str,
    content_type: str,
) -> UploadGrant:
    grant = db.scalar(
        select(UploadGrant).where(
            UploadGrant.workspace_id == workspace_id,
            UploadGrant.import_session_id == import_session_id,
            UploadGrant.token_digest == text_digest(raw_token),
        )
    )
    now = utcnow()
    normalized_content_type = content_type.split(";", 1)[0]
    if (
        grant is None
        or grant.revoked_at is not None
        or _as_utc(grant.expires_at) <= now
        or normalized_content_type != grant.media_type
    ):
        raise ApiError(403, "POLICY_BLOCKED", "The upload capability is invalid or out of scope.")
    session = db.scalar(
        select(ImportSession).where(
            ImportSession.id == import_session_id,
            ImportSession.workspace_id == workspace_id,
        )
    )
    if session is None or session.state != "consented":
        raise ApiError(403, "POLICY_BLOCKED", "The import session cannot accept an upload.")
    consent = resolve_effective_consent(db, session)
    try:
        scoped_store = _import_object_store(session.workspace_id, session.id)
        scoped_store.require_key(grant.object_key)
        scoped_store.require_key(str(consent.upload_object_scope["object_key"]))
    except (KeyError, ObjectScopeMismatch) as exc:
        raise ApiError(
            403,
            "POLICY_BLOCKED",
            "The upload capability is invalid or out of scope.",
        ) from exc
    if grant.object_key != consent.upload_object_scope["object_key"]:
        raise ApiError(403, "POLICY_BLOCKED", "The upload capability is invalid or out of scope.")
    return grant


def store_uploaded_object(
    db: Session,
    *,
    workspace_id: str,
    import_session_id: str,
    raw_token: str,
    content_type: str,
    body: bytes,
    observed_digest: str | None = None,
) -> str:
    grant = authorize_upload_grant(
        db,
        workspace_id=workspace_id,
        import_session_id=import_session_id,
        raw_token=raw_token,
        content_type=content_type,
    )
    actual_digest = f"sha256:{hashlib.sha256(body).hexdigest()}"
    if len(body) > grant.max_bytes or (
        observed_digest is not None and observed_digest != actual_digest
    ):
        raise ApiError(413, "POLICY_BLOCKED", "The upload exceeded its authorized size.")
    normalized_content_type = content_type.split(";", 1)[0]
    scoped_store = _import_object_store(workspace_id, import_session_id)
    try:
        scoped_store.require_key(grant.object_key)
        observed = scoped_store.put(body, normalized_content_type)
    except ObjectScopeMismatch as exc:
        raise ApiError(
            403,
            "POLICY_BLOCKED",
            "The upload capability is invalid or out of scope.",
        ) from exc
    grant.observed_size_bytes = len(body)
    grant.observed_media_type = normalized_content_type
    grant.observed_digest = observed.digest
    grant.uploaded_at = utcnow()
    db.commit()
    return grant.object_key


def resolve_effective_consent(db: Session, session: ImportSession) -> TransferConsentRecord:
    grant_record = db.scalar(
        select(TransferConsentRecord)
        .where(
            TransferConsentRecord.import_session_id == session.id,
            TransferConsentRecord.decision == "grant",
        )
        .order_by(TransferConsentRecord.recorded_at.desc())
    )
    if grant_record is None or _as_utc(grant_record.expires_at) <= utcnow():
        raise ApiError(409, "CONSENT_EXPIRED_OR_REVOKED", "Upload consent expired or was revoked.")
    revoked = db.scalar(
        select(TransferConsentRecord.id).where(
            TransferConsentRecord.import_session_id == session.id,
            TransferConsentRecord.decision == "revoke",
            TransferConsentRecord.supersedes_id == grant_record.id,
        )
    )
    pinned = (
        grant_record.local_manifest_digest == session.local_manifest_digest
        and grant_record.file_digest == session.file_digest
        and grant_record.expected_upload_digest == session.expected_upload_digest
        and grant_record.selected_scope_digest == session.selected_scope_digest
        and grant_record.destination_workspace_id == session.workspace_id
        and grant_record.model_egress_authorization == "none"
    )
    if revoked or not pinned:
        raise ApiError(409, "CONSENT_EXPIRED_OR_REVOKED", "Upload consent expired or was revoked.")
    return grant_record


def complete_upload(
    db: Session,
    *,
    session: ImportSession,
    actor_id: str,
    expected_row_version: int,
    object_key: str,
    request_id: str,
) -> ImportSession:
    if session.row_version != expected_row_version:
        raise version_conflict(session.id, session.row_version)
    if session.state != "consented":
        raise invalid_state("Upload completion requires a consented import.")
    consent = resolve_effective_consent(db, session)
    scope = consent.upload_object_scope
    scoped_store = _import_object_store(session.workspace_id, session.id)
    try:
        scoped_store.require_key(object_key)
        scoped_store.require_key(str(scope["object_key"]))
    except (KeyError, ObjectScopeMismatch) as exc:
        raise ApiError(
            422, "OBJECT_SCOPE_MISMATCH", "The uploaded object key does not match consent."
        ) from exc
    if object_key != scope["object_key"]:
        raise ApiError(
            422, "OBJECT_SCOPE_MISMATCH", "The uploaded object key does not match consent."
        )
    try:
        stored = scoped_store.get()
    except (OSError, KeyError, ObjectScopeMismatch) as exc:
        raise ApiError(422, "OBJECT_SCOPE_MISMATCH", "The uploaded object does not exist.") from exc
    observed = stored.digest
    mismatch = (
        stored.size_bytes > int(scope["max_bytes"])
        or stored.size_bytes != session.file_size_bytes
        or stored.media_type != session.media_type
        or scope["media_type"] != stored.media_type
        or observed != session.expected_upload_digest
    )
    if mismatch:
        session.state = "failed"
        session.failure_code = "OBJECT_VERIFICATION_FAILED"
        session.retryable = False
        session.row_version += 1
        scoped_store.quarantine("upload verification failed")
        audit(
            db,
            workspace_id=session.workspace_id,
            actor_id=actor_id,
            action="import.upload_verification_failed",
            target_type="ImportSession",
            target_id=session.id,
            request_id=request_id,
            details={"object_key": object_key, "observed_digest": observed},
        )
        db.commit()
        raise ApiError(422, "OBJECT_SCOPE_MISMATCH", "The uploaded object failed verification.")
    session.uploaded_object_key = object_key
    session.uploaded_object_digest = observed
    session.state = "uploaded"
    session.row_version += 1
    audit(
        db,
        workspace_id=session.workspace_id,
        actor_id=actor_id,
        action="import.upload_verified",
        target_type="ImportSession",
        target_id=session.id,
        request_id=request_id,
        after={"object_key": object_key, "observed_digest": observed},
    )
    db.commit()
    return session


def begin_finalize(
    db: Session,
    *,
    session: ImportSession,
    actor_id: str,
    expected_row_version: int,
    request_id: str,
    idempotency_key: str,
) -> ImportFinalizationJobRecord:
    existing = db.scalar(
        select(ImportFinalizationJobRecord).where(
            ImportFinalizationJobRecord.workspace_id == session.workspace_id,
            ImportFinalizationJobRecord.import_session_id == session.id,
        )
    )
    if existing and existing.state == "completed":
        return existing
    if session.row_version != expected_row_version:
        raise version_conflict(session.id, session.row_version)
    if session.state not in {"uploaded", "failed"}:
        raise invalid_state("Finalize requires an uploaded or retryable failed import.")
    if session.state == "failed" and not session.retryable:
        raise invalid_state("This failed import must be cancelled and recreated.")
    consent = resolve_effective_consent(db, session)
    source = db.scalar(
        select(SourceConnection).where(
            SourceConnection.id == session.source_connection_id,
            SourceConnection.workspace_id == session.workspace_id,
        )
    )
    if source is None:
        raise not_found("Source connection")
    if (
        source.row_version != session.expected_source_row_version
        or source.current_import_manifest_id != session.expected_current_import_manifest_id
    ):
        raise ApiError(412, "STALE_SOURCE_VERSION", "The imported source pointer changed.")
    session.state = "validating"
    session.failure_code = None
    session.retryable = False
    session.row_version += 1
    if existing is None:
        command = ImportFinalizationJobRecord(
            workspace_id=session.workspace_id,
            import_session_id=session.id,
            expected_session_row_version=session.row_version,
            expected_source_row_version=source.row_version,
            expected_current_import_manifest_id=source.current_import_manifest_id,
            consent_record_id=consent.id,
            actor_id=actor_id,
            request_id=request_id,
            idempotency_key=idempotency_key,
            state="queued",
            data_authenticity=session.data_authenticity,
        )
        db.add(command)
    elif existing.state == "failed" and existing.retryable:
        command = existing
        command.expected_session_row_version = session.row_version
        command.expected_source_row_version = source.row_version
        command.expected_current_import_manifest_id = source.current_import_manifest_id
        command.consent_record_id = consent.id
        command.actor_id = actor_id
        command.request_id = request_id
        command.idempotency_key = idempotency_key
        command.state = "queued"
        command.attempt += 1
        command.failure_code = None
        command.retryable = False
        command.claimed_by = None
        command.lease_acquired_at = None
        command.lease_expires_at = None
    else:
        raise invalid_state("This finalization command is already in progress.")
    db.flush()
    audit(
        db,
        workspace_id=session.workspace_id,
        actor_id=actor_id,
        action="import.finalization_queued",
        target_type="ImportSession",
        target_id=session.id,
        request_id=request_id,
        after={"finalize_command_id": command.id},
    )
    db.commit()
    return command


def cancel_import(
    db: Session,
    *,
    session: ImportSession,
    actor_id: str,
    expected_row_version: int,
    reason: str,
    request_id: str,
) -> ImportSession:
    if session.row_version != expected_row_version:
        raise version_conflict(session.id, session.row_version)
    if session.state in TERMINAL_IMPORT_STATES:
        raise invalid_state("A terminal import cannot be cancelled.")
    grant_record = db.scalar(
        select(TransferConsentRecord)
        .where(
            TransferConsentRecord.import_session_id == session.id,
            TransferConsentRecord.decision == "grant",
        )
        .order_by(TransferConsentRecord.recorded_at.desc())
    )
    if grant_record is not None:
        already_revoked = db.scalar(
            select(TransferConsentRecord.id).where(
                TransferConsentRecord.import_session_id == session.id,
                TransferConsentRecord.decision == "revoke",
                TransferConsentRecord.supersedes_id == grant_record.id,
            )
        )
        if not already_revoked:
            db.add(
                TransferConsentRecord(
                    workspace_id=session.workspace_id,
                    import_session_id=session.id,
                    decision="revoke",
                    local_manifest_digest=session.local_manifest_digest,
                    file_digest=session.file_digest,
                    expected_upload_digest=session.expected_upload_digest,
                    selected_scope_json=session.selected_scope_json,
                    selected_scope_digest=session.selected_scope_digest,
                    destination_workspace_id=session.workspace_id,
                    upload_object_scope=grant_record.upload_object_scope,
                    model_egress_authorization="none",
                    policy_version="import-transfer-v1",
                    actor_id=actor_id,
                    expires_at=utcnow(),
                    supersedes_id=grant_record.id,
                    data_authenticity=session.data_authenticity,
                )
            )
        grant = db.scalar(select(UploadGrant).where(UploadGrant.import_session_id == session.id))
        if grant:
            grant.revoked_at = utcnow()
            scoped_store = _import_object_store(session.workspace_id, session.id)
            try:
                scoped_store.require_key(grant.object_key)
                scoped_store.require_key(str(grant_record.upload_object_scope["object_key"]))
            except (KeyError, ObjectScopeMismatch) as exc:
                raise ApiError(
                    422,
                    "OBJECT_SCOPE_MISMATCH",
                    "The upload object is outside the import workspace scope.",
                ) from exc
            if grant.object_key != grant_record.upload_object_scope["object_key"]:
                raise ApiError(
                    422,
                    "OBJECT_SCOPE_MISMATCH",
                    "The upload object is outside the import workspace scope.",
                )
            scoped_store.delete()
    session.state = "cancelled"
    session.failure_code = None
    session.retryable = False
    session.row_version += 1
    audit(
        db,
        workspace_id=session.workspace_id,
        actor_id=actor_id,
        action="import.cancelled",
        target_type="ImportSession",
        target_id=session.id,
        request_id=request_id,
        reason=reason,
    )
    db.commit()
    return session


class ImportFinalizationRepository:
    """Persistent adapter called by the sole worker ImportFinalizationJob, never by an API task."""

    @classmethod
    def get(cls, db: Session, *, workspace_id: str, command_id: str) -> ImportFinalizationJobRecord:
        job = db.scalar(
            select(ImportFinalizationJobRecord).where(
                ImportFinalizationJobRecord.id == command_id,
                ImportFinalizationJobRecord.workspace_id == workspace_id,
            )
        )
        if job is None:
            raise not_found("Import finalization command")
        return job

    @classmethod
    def claim(
        cls,
        db: Session,
        *,
        workspace_id: str,
        command_id: str,
        worker_id: str,
        lease_seconds: int = 120,
    ) -> ImportFinalizationJobRecord:
        job = db.scalar(
            select(ImportFinalizationJobRecord)
            .where(
                ImportFinalizationJobRecord.id == command_id,
                ImportFinalizationJobRecord.workspace_id == workspace_id,
            )
            .with_for_update()
        )
        if job is None:
            raise not_found("Import finalization command")
        if job.state == "completed":
            return job
        now = utcnow()
        lease_active = job.lease_expires_at is not None and _as_utc(job.lease_expires_at) > now
        if job.state == "claimed" and lease_active and job.claimed_by != worker_id:
            raise ApiError(
                409, "JOB_ALREADY_CLAIMED", "The finalization command has an active lease."
            )
        if job.state not in {"queued", "claimed"}:
            raise invalid_state("Only a queued finalization command can be claimed.")
        session = db.scalar(
            select(ImportSession).where(
                ImportSession.id == job.import_session_id,
                ImportSession.workspace_id == workspace_id,
            )
        )
        if (
            session is None
            or session.state != "validating"
            or session.row_version != job.expected_session_row_version
        ):
            raise invalid_state("The import is not in the command's validating state.")
        if job.state == "claimed" and not lease_active:
            job.attempt += 1
        job.state = "claimed"
        job.claimed_by = worker_id
        job.lease_acquired_at = now
        job.lease_expires_at = now + timedelta(seconds=lease_seconds)
        db.commit()
        return job

    @classmethod
    def fail(
        cls,
        db: Session,
        *,
        workspace_id: str,
        command_id: str,
        worker_id: str,
        failure_code: str,
        retryable: bool,
    ) -> ImportFinalizationJobRecord:
        job = cls.get(db, workspace_id=workspace_id, command_id=command_id)
        if job.state == "completed":
            return job
        if job.claimed_by not in {None, worker_id}:
            raise ApiError(409, "JOB_ALREADY_CLAIMED", "A different worker owns this lease.")
        session = db.scalar(
            select(ImportSession).where(
                ImportSession.id == job.import_session_id,
                ImportSession.workspace_id == workspace_id,
            )
        )
        job.state = "failed"
        job.failure_code = failure_code
        job.retryable = retryable
        job.lease_expires_at = None
        if session and session.state == "validating":
            session.state = "failed"
            session.failure_code = failure_code
            session.retryable = retryable
            session.row_version += 1
        audit(
            db,
            workspace_id=workspace_id,
            actor_id=job.actor_id,
            action="import.finalization_failed",
            target_type="ImportFinalizationJob",
            target_id=job.id,
            request_id=job.request_id,
            details={"failure_code": failure_code, "retryable": retryable},
        )
        db.commit()
        return job

    @classmethod
    def complete(
        cls,
        db: Session,
        *,
        workspace_id: str,
        command_id: str,
        worker_id: str,
        proposal: ImportNormalizationProposal,
    ) -> ImportManifest:
        job = db.scalar(
            select(ImportFinalizationJobRecord)
            .where(
                ImportFinalizationJobRecord.id == command_id,
                ImportFinalizationJobRecord.workspace_id == workspace_id,
            )
            .with_for_update()
        )
        if job is None:
            raise not_found("Import finalization command")
        if job.state == "completed" and job.result_manifest_id:
            replay = db.scalar(
                select(ImportManifest).where(
                    ImportManifest.id == job.result_manifest_id,
                    ImportManifest.workspace_id == workspace_id,
                )
            )
            if replay is None:
                raise ApiError(
                    500, "LINEAGE_INTEGRITY_ERROR", "Completed command lost its manifest."
                )
            return replay
        if job.state != "claimed" or job.claimed_by != worker_id:
            raise invalid_state("The worker must hold the finalization lease before completion.")
        if job.lease_expires_at is None or _as_utc(job.lease_expires_at) <= utcnow():
            raise ApiError(409, "JOB_LEASE_EXPIRED", "The finalization lease expired.")
        session = db.scalar(
            select(ImportSession).where(
                ImportSession.id == job.import_session_id,
                ImportSession.workspace_id == workspace_id,
            )
        )
        if (
            session is None
            or session.state != "validating"
            or session.row_version != job.expected_session_row_version
        ):
            raise invalid_state("The import changed after the command was claimed.")
        consent = resolve_effective_consent(db, session)
        if consent.id != job.consent_record_id or not session.uploaded_object_key:
            raise ApiError(409, "CONSENT_EXPIRED_OR_REVOKED", "Finalization consent changed.")
        grant = db.scalar(
            select(UploadGrant).where(
                UploadGrant.import_session_id == session.id,
                UploadGrant.consent_record_id == consent.id,
            )
        )
        scope = consent.upload_object_scope
        if grant is None or grant.revoked_at is not None:
            raise ApiError(422, "OBJECT_SCOPE_MISMATCH", "Final object verification failed.")
        scoped_store = _import_object_store(session.workspace_id, session.id)
        try:
            scoped_store.require_key(session.uploaded_object_key)
            scoped_store.require_key(grant.object_key)
            scoped_store.require_key(str(scope["object_key"]))
            stored = scoped_store.get()
        except (OSError, KeyError, ObjectScopeMismatch) as exc:
            raise ApiError(
                422, "OBJECT_SCOPE_MISMATCH", "The uploaded object is unavailable."
            ) from exc
        observed_digest = stored.digest
        if (
            session.uploaded_object_key != scope["object_key"]
            or grant.object_key != session.uploaded_object_key
            or stored.size_bytes != session.file_size_bytes
            or stored.size_bytes > int(scope["max_bytes"])
            or grant.observed_size_bytes != stored.size_bytes
            or grant.observed_media_type != stored.media_type
            or stored.media_type != session.media_type
            or grant.media_type != scope["media_type"]
            or observed_digest != session.expected_upload_digest
            or observed_digest != session.uploaded_object_digest
            or observed_digest != grant.observed_digest
        ):
            raise ApiError(422, "OBJECT_SCOPE_MISMATCH", "Final object verification failed.")
        proposal = ImportNormalizationProposal.model_validate(proposal)
        manifest_proposal = proposal.manifest
        if (
            str(manifest_proposal.workspace_id) != workspace_id
            or str(manifest_proposal.import_session_id) != session.id
            or str(manifest_proposal.source_connection_id) != session.source_connection_id
            or manifest_proposal.file_digest != session.file_digest
            or manifest_proposal.uploaded_object_key != session.uploaded_object_key
            or manifest_proposal.uploaded_object_digest != observed_digest
            or manifest_proposal.parser_version != session.parser_version
            or manifest_proposal.schema_version != session.schema_version
            or manifest_proposal.selected_scope_digest != session.selected_scope_digest
            or str(manifest_proposal.consent_record_id) != consent.id
            or manifest_proposal.data_authenticity.value != session.data_authenticity
        ):
            raise ApiError(
                422,
                "NORMALIZATION_LINEAGE_MISMATCH",
                "Worker normalization proposal does not match the claimed import command.",
            )
        source = db.scalar(
            select(SourceConnection).where(
                SourceConnection.id == session.source_connection_id,
                SourceConnection.workspace_id == workspace_id,
            )
        )
        if (
            source is None
            or source.row_version != job.expected_source_row_version
            or source.current_import_manifest_id != job.expected_current_import_manifest_id
        ):
            raise ApiError(412, "STALE_SOURCE_VERSION", "The imported source pointer changed.")
        manifest = ImportManifest(
            id=str(manifest_proposal.id),
            workspace_id=workspace_id,
            import_session_id=session.id,
            source_connection_id=session.source_connection_id,
            file_digest=session.file_digest,
            uploaded_object_key=session.uploaded_object_key,
            uploaded_object_digest=observed_digest,
            parser_version=session.parser_version,
            schema_version=session.schema_version,
            selected_scope_json=session.selected_scope_json,
            selected_scope_digest=session.selected_scope_digest,
            consent_record_id=consent.id,
            normalized_payload_digest=manifest_proposal.normalized_payload_digest,
            content_count=manifest_proposal.content_count,
            finalized_at=manifest_proposal.finalized_at,
            data_authenticity=session.data_authenticity,
        )
        db.add(manifest)
        db.flush()
        if db.get_bind().dialect.name == "postgresql":
            for identity_key in sorted({item.identity_key for item in proposal.content_items}):
                db.execute(
                    text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                    {"key": (f"{workspace_id}:{session.source_connection_id}:{identity_key}")},
                )
        content_versions: list[ContentVersion] = []
        for ordinal, (raw_proposal, item_proposal, version_proposal) in enumerate(
            zip(
                proposal.raw_items,
                proposal.content_items,
                proposal.content_versions,
                strict=True,
            ),
            start=1,
        ):
            item = db.scalar(
                select(ContentItem)
                .where(
                    ContentItem.workspace_id == workspace_id,
                    ContentItem.source_connection_id == session.source_connection_id,
                    ContentItem.identity_key == item_proposal.identity_key,
                )
                .with_for_update()
            )
            item_existed = item is not None
            if item is None:
                item = ContentItem(
                    id=str(item_proposal.id),
                    workspace_id=workspace_id,
                    source_connection_id=session.source_connection_id,
                    source_item_id=item_proposal.source_item_id,
                    canonical_url=item_proposal.canonical_url,
                    identity_key=item_proposal.identity_key,
                    title=item_proposal.title,
                    duplicate_cluster_id=(
                        str(item_proposal.duplicate_cluster_id)
                        if item_proposal.duplicate_cluster_id is not None
                        else None
                    ),
                    data_authenticity=session.data_authenticity,
                )
                db.add(item)
                db.flush()
            elif item.id != str(item_proposal.id):
                raise ApiError(
                    422,
                    "NORMALIZATION_LINEAGE_MISMATCH",
                    "Worker ContentItem ID does not match the stable imported identity.",
                )
            raw_uri = f"object://{manifest.uploaded_object_key}#{raw_proposal.id}"
            raw = RawContentItem(
                id=str(raw_proposal.id),
                workspace_id=workspace_id,
                import_manifest_id=manifest.id,
                collection_run_id=None,
                source_connection_id=session.source_connection_id,
                source_external_id=raw_proposal.source_item_id,
                raw_snapshot_uri=raw_uri,
                raw_digest=raw_proposal.content_digest,
                received_at=raw_proposal.captured_at,
                data_authenticity=session.data_authenticity,
            )
            db.add(raw)
            db.flush()
            version = db.scalar(
                select(ContentVersion).where(
                    ContentVersion.content_item_id == item.id,
                    ContentVersion.content_digest == version_proposal.content_digest,
                )
            )
            if version is not None:
                if (
                    version.id != str(version_proposal.id)
                    or version.normalized_title != version_proposal.normalized_title
                    or version.normalized_body != version_proposal.normalized_body
                    or version.parser_version != version_proposal.parser_version
                ):
                    raise ApiError(
                        422,
                        "NORMALIZATION_LINEAGE_MISMATCH",
                        "A frozen ContentVersion conflicts with the normalized proposal.",
                    )
            else:
                next_version = (
                    db.scalar(
                        select(func.max(ContentVersion.version_number)).where(
                            ContentVersion.content_item_id == item.id
                        )
                    )
                    or 0
                ) + 1
                version_metadata = dict(version_proposal.metadata)
                version_metadata.update(
                    {
                        "source_item_id": raw_proposal.source_item_id,
                        "canonical_url": version_proposal.canonical_url,
                        "author": version_proposal.author,
                        "published_at": (
                            raw_proposal.published_at.isoformat()
                            if raw_proposal.published_at is not None
                            else None
                        ),
                        "raw_metadata": raw_proposal.metadata,
                        "independence_group_id": (
                            str(item_proposal.independence_group_id)
                            if item_proposal.independence_group_id is not None
                            else None
                        ),
                    }
                )
                version = ContentVersion(
                    id=str(version_proposal.id),
                    workspace_id=workspace_id,
                    content_item_id=item.id,
                    source_connection_id=session.source_connection_id,
                    raw_content_item_id=raw.id,
                    version_number=next_version,
                    content_digest=version_proposal.content_digest,
                    normalized_title=version_proposal.normalized_title,
                    normalized_body=version_proposal.normalized_body,
                    metadata_json=version_metadata,
                    captured_at=version_proposal.captured_at,
                    raw_snapshot_uri=raw_uri,
                    parser_version=version_proposal.parser_version,
                    data_authenticity=session.data_authenticity,
                )
                db.add(version)
                db.flush()
                item.source_item_id = item_proposal.source_item_id
                item.canonical_url = item_proposal.canonical_url
                item.title = item_proposal.title
                item.current_version_id = version.id
                if item_existed:
                    item.row_version += 1
            db.add(
                ImportManifestContentVersion(
                    workspace_id=workspace_id,
                    import_manifest_id=manifest.id,
                    content_version_id=version.id,
                    ordinal=ordinal,
                    data_authenticity=session.data_authenticity,
                )
            )
            if item.current_version_id is None:
                item.current_version_id = version.id
            content_versions.append(version)
        pointer_predicate = (
            SourceConnection.current_import_manifest_id.is_(None)
            if job.expected_current_import_manifest_id is None
            else SourceConnection.current_import_manifest_id
            == job.expected_current_import_manifest_id
        )
        updated_source_id = db.scalar(
            update(SourceConnection)
            .where(
                SourceConnection.id == source.id,
                SourceConnection.row_version == job.expected_source_row_version,
                pointer_predicate,
            )
            .values(
                current_import_manifest_id=manifest.id, row_version=SourceConnection.row_version + 1
            )
            .returning(SourceConnection.id)
        )
        if updated_source_id is None:
            raise ApiError(412, "STALE_SOURCE_VERSION", "The imported source pointer changed.")
        cls._create_signals(db, session, manifest, content_versions)
        session.state = "finalized"
        session.terminal_manifest_id = manifest.id
        session.row_version += 1
        job.state = "completed"
        job.result_manifest_id = manifest.id
        job.failure_code = None
        job.retryable = False
        job.lease_expires_at = None
        audit(
            db,
            workspace_id=workspace_id,
            actor_id=job.actor_id,
            action="import.finalized",
            target_type="ImportManifest",
            target_id=manifest.id,
            request_id=job.request_id,
            after={"content_count": manifest.content_count, "source_connection_id": source.id},
        )
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            replay = db.scalar(
                select(ImportManifest).where(ImportManifest.import_session_id == session.id)
            )
            if replay is not None:
                return replay
            raise ApiError(409, "FINALIZATION_CONFLICT", "Finalization conflicted.") from exc
        return manifest

    @classmethod
    def _create_signals(
        cls,
        db: Session,
        session: ImportSession,
        manifest: ImportManifest,
        versions: list[ContentVersion],
    ) -> None:
        watchlists = db.scalars(
            select(Watchlist).where(
                Watchlist.workspace_id == session.workspace_id,
                Watchlist.status == "active",
            )
        ).all()
        for watchlist in watchlists:
            source_ids = watchlist.rules_json.get("source_connection_ids", [])
            if source_ids and session.source_connection_id not in source_ids:
                continue
            now = utcnow()
            collection_run = CollectionRun(
                workspace_id=session.workspace_id,
                watchlist_id=watchlist.id,
                source_connection_id=session.source_connection_id,
                stable_key=f"import:{manifest.id}:{watchlist.rules_version}",
                state="succeeded",
                cadence="manual",
                timezone="UTC",
                scheduled_for=now,
                attempt=1,
                input_window_json={
                    "start": (now - timedelta(microseconds=1)).isoformat(),
                    "end": now.isoformat(),
                },
                counters_json={
                    "fetched": len(versions),
                    "created": len(versions),
                    "updated": 0,
                    "skipped": 0,
                    "failed": 0,
                },
                partial_success=False,
                freshness_json={
                    "state": "current",
                    "last_success_at": now.isoformat(),
                    "signal_candidate_count": len(versions),
                    "signal_count": 0,
                },
                started_at=now,
                finished_at=now,
                data_authenticity=session.data_authenticity,
            )
            db.add(collection_run)
            db.flush()
            if not has_ready_initial_baseline(db, watchlist):
                continue
            collection_run.freshness_json = {
                **collection_run.freshness_json,
                "signal_count": 1,
            }
            signal = Signal(
                workspace_id=session.workspace_id,
                watchlist_id=watchlist.id,
                title=f"Imported dataset contains {len(versions)} scoped records",
                window_json={
                    "current_start": (now - timedelta(days=7)).isoformat(),
                    "current_end": now.isoformat(),
                    "baseline_start": (now - timedelta(days=35)).isoformat(),
                    "baseline_end": (now - timedelta(days=7)).isoformat(),
                },
                metrics_json={
                    "mention_count": len(versions),
                    "independent_source_count": len(versions),
                    "platform_count": 1,
                },
                dimensions_json={
                    "trigger_rules": ["static_import_content_count > 0"],
                    "detector_policy": {
                        "require_current_mentions": True,
                        "min_content_count": 1,
                    },
                    "limitations": ["Static import has no continuous freshness."],
                    "detection_confidence": {
                        "level": "medium" if len(versions) >= 2 else "low",
                        "calibration_status": "uncalibrated",
                        "explanation": (
                            "Static-import sample sufficiency under deterministic detector v1."
                        ),
                    },
                    "business_impact": {
                        "suggested_level": "medium",
                        "suggested_explanation": "The import matches the active Watchlist scope.",
                        "suggestion_origin": "deterministic_rule",
                        "suggestion_version": "impact-rules-v1",
                        "confirmed_level": None,
                        "confirmed_by": None,
                        "confirmed_at": None,
                        "version": 0,
                    },
                    "urgency": {
                        "suggested_level": "monitor",
                        "suggested_explanation": "Static imports have no live incident deadline.",
                        "suggestion_origin": "deterministic_rule",
                        "suggestion_version": "urgency-rules-v1",
                        "confirmed_level": None,
                        "confirmed_by": None,
                        "confirmed_at": None,
                        "version": 0,
                    },
                    "priority": {
                        "level": None,
                        "status": "pending_confirmation",
                        "policy_version": "priority-matrix-v1",
                        "explanation": "Confirm Business Impact and Urgency.",
                    },
                },
                explanation="Deterministic import rule; this is not a model-generated signal.",
                data_authenticity=session.data_authenticity,
            )
            db.add(signal)
            db.flush()
            for version in versions[:20]:
                db.add(
                    SignalEvidence(
                        workspace_id=session.workspace_id,
                        signal_id=signal.id,
                        content_version_id=version.id,
                        role="trigger",
                        contribution=1.0,
                        added_by=session.created_by,
                    )
                )
