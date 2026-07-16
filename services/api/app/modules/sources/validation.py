from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from packages.domain.redaction import redact_text
from services.api.app.core.errors import ApiError, invalid_state, not_found, version_conflict
from services.api.app.db.models import SourceConnection, SourceValidationJobRecord
from services.api.app.modules.common import audit, text_digest, utcnow

_TERMINAL_SOURCE_STATUSES = {"healthy", "degraded", "auth_required", "failed"}
_SOURCE_FENCE_DRIFT_CODE = "SOURCE_VALIDATION_FENCE_DRIFT"
_SOURCE_FENCE_DRIFT_REASON = "The source changed after this validation was queued."


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _safe_text(value: str | None, *, maximum: int) -> str | None:
    if value is None:
        return None
    return redact_text(value)[:maximum]


class SourceValidationJobRepository:
    """API-owned durable queue and fenced worker lease boundary for source validation."""

    @classmethod
    def _find_idempotent_job(
        cls,
        db: Session,
        *,
        workspace_id: str,
        idempotency_key: str,
    ) -> SourceValidationJobRecord | None:
        return db.scalar(
            select(SourceValidationJobRecord).where(
                SourceValidationJobRecord.workspace_id == workspace_id,
                SourceValidationJobRecord.idempotency_key == idempotency_key,
            )
        )

    @classmethod
    def _validate_idempotent_job(
        cls,
        existing: SourceValidationJobRecord,
        *,
        source_connection_id: str,
        command: str,
    ) -> SourceValidationJobRecord:
        if existing.source_connection_id != source_connection_id or existing.command != command:
            raise ApiError(
                409,
                "IDEMPOTENCY_CONFLICT",
                "The idempotency key belongs to a different source validation.",
            )
        return existing

    @classmethod
    def _lock_source_connection(
        cls,
        db: Session,
        *,
        workspace_id: str,
        source_connection_id: str,
    ) -> SourceConnection | None:
        return db.scalar(
            select(SourceConnection)
            .where(
                SourceConnection.id == source_connection_id,
                SourceConnection.workspace_id == workspace_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )

    @classmethod
    def _active_job_id(
        cls,
        db: Session,
        *,
        workspace_id: str,
        source_connection_id: str,
    ) -> str | None:
        return db.scalar(
            select(SourceValidationJobRecord.id).where(
                SourceValidationJobRecord.workspace_id == workspace_id,
                SourceValidationJobRecord.source_connection_id == source_connection_id,
                SourceValidationJobRecord.state.in_(("queued", "claimed")),
            )
        )

    @classmethod
    def lock_source_for_lifecycle_command(
        cls,
        db: Session,
        *,
        workspace_id: str,
        source_connection_id: str,
    ) -> SourceConnection:
        """Serialize a source mutation with validation enqueue and reject active work."""
        source = cls._lock_source_connection(
            db,
            workspace_id=workspace_id,
            source_connection_id=source_connection_id,
        )
        if source is None:
            raise not_found("SourceConnection")
        if (
            cls._active_job_id(
                db,
                workspace_id=workspace_id,
                source_connection_id=source_connection_id,
            )
            is not None
        ):
            raise ApiError(
                409,
                "SOURCE_VALIDATION_IN_PROGRESS",
                "The source cannot change while its validation is in progress.",
            )
        return source

    @classmethod
    def enqueue(
        cls,
        db: Session,
        *,
        workspace_id: str,
        source_connection_id: str,
        command: str,
        expected_source_row_version: int,
        actor_id: str,
        request_id: str,
        idempotency_key: str,
        reason: str,
    ) -> SourceValidationJobRecord:
        existing = cls._find_idempotent_job(
            db,
            workspace_id=workspace_id,
            idempotency_key=idempotency_key,
        )
        if existing is not None:
            return cls._validate_idempotent_job(
                existing,
                source_connection_id=source_connection_id,
                command=command,
            )
        source = cls._lock_source_connection(
            db,
            workspace_id=workspace_id,
            source_connection_id=source_connection_id,
        )
        if source is None:
            raise not_found("SourceConnection")
        # A duplicate request can commit while this transaction waits for the
        # source lock. Recheck before interpreting the winner as unrelated work.
        existing = cls._find_idempotent_job(
            db,
            workspace_id=workspace_id,
            idempotency_key=idempotency_key,
        )
        if existing is not None:
            return cls._validate_idempotent_job(
                existing,
                source_connection_id=source_connection_id,
                command=command,
            )
        if source.source_kind != "cloud":
            raise ApiError(422, "SOURCE_SCOPE_BLOCKED", "Only a cloud source can be validated.")
        if source.row_version != expected_source_row_version:
            raise version_conflict(source.id, source.row_version)
        active = cls._active_job_id(
            db,
            workspace_id=workspace_id,
            source_connection_id=source_connection_id,
        )
        if active is not None:
            raise ApiError(
                409,
                "SOURCE_VALIDATION_IN_PROGRESS",
                "This source already has a validation in progress.",
            )

        source.status = "validating"
        source.health_state = "unknown"
        source.health_error_code = None
        source.row_version += 1
        job = SourceValidationJobRecord(
            workspace_id=workspace_id,
            source_connection_id=source_connection_id,
            command=command,
            state="queued",
            expected_source_row_version=source.row_version,
            actor_id=actor_id,
            request_id=request_id,
            idempotency_key=idempotency_key,
            data_authenticity="collected",
        )
        db.add(job)
        db.flush()
        audit(
            db,
            workspace_id=workspace_id,
            actor_id=actor_id,
            action="source.validation_requested",
            target_type="SourceValidationJob",
            target_id=job.id,
            request_id=request_id,
            reason=reason,
            after={
                "source_connection_id": source_connection_id,
                "command": command,
                "expected_source_row_version": source.row_version,
            },
        )
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            replay = cls._find_idempotent_job(
                db,
                workspace_id=workspace_id,
                idempotency_key=idempotency_key,
            )
            if replay is not None:
                return cls._validate_idempotent_job(
                    replay,
                    source_connection_id=source_connection_id,
                    command=command,
                )
            raise ApiError(
                409,
                "SOURCE_VALIDATION_IN_PROGRESS",
                "This source already has a validation in progress.",
            ) from exc
        return job

    @classmethod
    def get(cls, db: Session, *, workspace_id: str, job_id: str) -> SourceValidationJobRecord:
        job = db.scalar(
            select(SourceValidationJobRecord).where(
                SourceValidationJobRecord.id == job_id,
                SourceValidationJobRecord.workspace_id == workspace_id,
            )
        )
        if job is None:
            raise not_found("Source validation job")
        return job

    @classmethod
    def claim(
        cls,
        db: Session,
        *,
        workspace_id: str,
        owner_token: str,
        lease_seconds: int = 120,
        job_id: str | None = None,
        now: datetime | None = None,
    ) -> SourceValidationJobRecord | None:
        current = _aware(now or utcnow())
        reclaimable = or_(
            SourceValidationJobRecord.state == "queued",
            (
                (SourceValidationJobRecord.state == "claimed")
                & (SourceValidationJobRecord.lease_expires_at <= current)
            ),
        )
        predicate: list[Any] = [
            SourceValidationJobRecord.workspace_id == workspace_id,
            reclaimable,
        ]
        if job_id is not None:
            predicate.append(SourceValidationJobRecord.id == job_id)
        candidate = db.scalar(
            select(SourceValidationJobRecord.id)
            .where(*predicate)
            .order_by(SourceValidationJobRecord.created_at, SourceValidationJobRecord.id)
            .limit(1)
        )
        if candidate is None:
            return None
        claimed_id = db.scalar(
            update(SourceValidationJobRecord)
            .where(
                SourceValidationJobRecord.id == candidate,
                SourceValidationJobRecord.workspace_id == workspace_id,
                reclaimable,
            )
            .values(
                state="claimed",
                attempt=SourceValidationJobRecord.attempt + 1,
                lease_owner_token=text_digest(owner_token),
                lease_expires_at=current + timedelta(seconds=lease_seconds),
                heartbeat_at=current,
                fencing_version=SourceValidationJobRecord.fencing_version + 1,
            )
            .returning(SourceValidationJobRecord.id)
        )
        if claimed_id is None:
            db.rollback()
            return None
        db.commit()
        return cls.get(db, workspace_id=workspace_id, job_id=claimed_id)

    @classmethod
    def heartbeat(
        cls,
        db: Session,
        *,
        workspace_id: str,
        job_id: str,
        owner_token: str,
        expected_attempt: int,
        expected_fencing_version: int,
        lease_seconds: int = 120,
    ) -> SourceValidationJobRecord:
        current = utcnow()
        updated_id = db.scalar(
            update(SourceValidationJobRecord)
            .where(
                SourceValidationJobRecord.id == job_id,
                SourceValidationJobRecord.workspace_id == workspace_id,
                SourceValidationJobRecord.state == "claimed",
                SourceValidationJobRecord.lease_owner_token == text_digest(owner_token),
                SourceValidationJobRecord.lease_expires_at > current,
                SourceValidationJobRecord.attempt == expected_attempt,
                SourceValidationJobRecord.fencing_version == expected_fencing_version,
            )
            .values(
                heartbeat_at=current,
                lease_expires_at=current + timedelta(seconds=lease_seconds),
            )
            .returning(SourceValidationJobRecord.id)
        )
        if updated_id is None:
            db.rollback()
            raise ApiError(409, "JOB_LEASE_EXPIRED", "The source validation lease is invalid.")
        db.commit()
        return cls.get(db, workspace_id=workspace_id, job_id=updated_id)

    @classmethod
    def _locked_claim(
        cls,
        db: Session,
        *,
        workspace_id: str,
        job_id: str,
        owner_token: str,
        expected_attempt: int,
        expected_fencing_version: int,
    ) -> SourceValidationJobRecord:
        job = db.scalar(
            select(SourceValidationJobRecord)
            .where(
                SourceValidationJobRecord.id == job_id,
                SourceValidationJobRecord.workspace_id == workspace_id,
            )
            .with_for_update()
        )
        if job is None:
            raise not_found("Source validation job")
        cls._require_current_claim(
            job,
            owner_token=owner_token,
            expected_attempt=expected_attempt,
            expected_fencing_version=expected_fencing_version,
        )
        return job

    @classmethod
    def _require_current_claim(
        cls,
        job: SourceValidationJobRecord,
        *,
        owner_token: str,
        expected_attempt: int,
        expected_fencing_version: int,
    ) -> None:
        if (
            job.state != "claimed"
            or job.lease_owner_token != text_digest(owner_token)
            or job.lease_expires_at is None
            or _aware(job.lease_expires_at) <= utcnow()
            or job.attempt != expected_attempt
            or job.fencing_version != expected_fencing_version
        ):
            raise ApiError(409, "JOB_LEASE_EXPIRED", "The source validation lease is invalid.")

    @classmethod
    def _locked_source(cls, db: Session, job: SourceValidationJobRecord) -> SourceConnection | None:
        return cls._lock_source_connection(
            db,
            workspace_id=job.workspace_id,
            source_connection_id=job.source_connection_id,
        )

    @classmethod
    def _source_fence_matches(
        cls,
        job: SourceValidationJobRecord,
        source: SourceConnection | None,
    ) -> bool:
        return (
            source is not None
            and source.row_version == job.expected_source_row_version
            and source.status == "validating"
        )

    @classmethod
    def _terminalize_source_fence_drift(
        cls,
        db: Session,
        *,
        job: SourceValidationJobRecord,
        source: SourceConnection | None,
    ) -> SourceValidationJobRecord:
        job.state = "failed"
        job.result_source_status = "failed"
        job.failure_code = _SOURCE_FENCE_DRIFT_CODE
        job.failure_reason = _SOURCE_FENCE_DRIFT_REASON
        job.lease_owner_token = None
        job.lease_expires_at = None
        job.heartbeat_at = None
        audit(
            db,
            workspace_id=job.workspace_id,
            actor_id=job.actor_id,
            action="source.validation_failed",
            target_type="SourceValidationJob",
            target_id=job.id,
            request_id=job.request_id,
            reason=_SOURCE_FENCE_DRIFT_REASON,
            after={
                "source_connection_id": job.source_connection_id,
                "failure_code": _SOURCE_FENCE_DRIFT_CODE,
                "source_write": "skipped",
                "expected_source_row_version": job.expected_source_row_version,
                "current_source_row_version": source.row_version if source is not None else None,
                "current_source_status": source.status if source is not None else None,
            },
        )
        db.commit()
        return job

    @classmethod
    def complete(
        cls,
        db: Session,
        *,
        workspace_id: str,
        job_id: str,
        owner_token: str,
        expected_attempt: int,
        expected_fencing_version: int,
        source_status: str,
        health_error_code: str | None = None,
        reason: str | None = None,
    ) -> SourceValidationJobRecord:
        if source_status not in _TERMINAL_SOURCE_STATUSES:
            raise ValueError("source_status must be a terminal source validation status")
        job = cls.get(db, workspace_id=workspace_id, job_id=job_id)
        safe_code = _safe_text(health_error_code, maximum=80)
        safe_reason = _safe_text(reason, maximum=2000)
        if job.state == "completed":
            if (
                job.result_source_status == source_status
                and job.failure_code == safe_code
                and job.failure_reason == safe_reason
            ):
                return job
            raise invalid_state("The source validation already completed with another outcome.")
        job = cls._locked_claim(
            db,
            workspace_id=workspace_id,
            job_id=job_id,
            owner_token=owner_token,
            expected_attempt=expected_attempt,
            expected_fencing_version=expected_fencing_version,
        )
        source = cls._locked_source(db, job)
        # The source lock may block long enough for a once-valid lease to
        # expire. Revalidate immediately before any terminal mutation.
        cls._require_current_claim(
            job,
            owner_token=owner_token,
            expected_attempt=expected_attempt,
            expected_fencing_version=expected_fencing_version,
        )
        if not cls._source_fence_matches(job, source):
            return cls._terminalize_source_fence_drift(db, job=job, source=source)
        assert source is not None
        checked_at = utcnow()
        source.status = source_status
        source.health_state = source_status
        source.health_checked_at = checked_at
        source.health_error_code = safe_code
        source.row_version += 1
        job.state = "completed"
        job.result_source_status = source_status
        job.failure_code = safe_code
        job.failure_reason = safe_reason
        job.lease_owner_token = None
        job.lease_expires_at = None
        job.heartbeat_at = None
        audit(
            db,
            workspace_id=workspace_id,
            actor_id=job.actor_id,
            action="source.validation_completed",
            target_type="SourceValidationJob",
            target_id=job.id,
            request_id=job.request_id,
            reason=safe_reason,
            after={
                "source_connection_id": source.id,
                "source_status": source_status,
                "health_error_code": safe_code,
            },
        )
        db.commit()
        return job

    @classmethod
    def fail(
        cls,
        db: Session,
        *,
        workspace_id: str,
        job_id: str,
        owner_token: str,
        expected_attempt: int,
        expected_fencing_version: int,
        failure_code: str,
        reason: str,
    ) -> SourceValidationJobRecord:
        safe_code = _safe_text(failure_code, maximum=80)
        safe_reason = _safe_text(reason, maximum=2000)
        if not safe_code:
            raise ValueError("failure_code must not be empty")
        job = cls.get(db, workspace_id=workspace_id, job_id=job_id)
        if job.state == "failed":
            if job.failure_code == safe_code and job.failure_reason == safe_reason:
                return job
            raise invalid_state("The source validation already failed with another outcome.")
        job = cls._locked_claim(
            db,
            workspace_id=workspace_id,
            job_id=job_id,
            owner_token=owner_token,
            expected_attempt=expected_attempt,
            expected_fencing_version=expected_fencing_version,
        )
        source = cls._locked_source(db, job)
        cls._require_current_claim(
            job,
            owner_token=owner_token,
            expected_attempt=expected_attempt,
            expected_fencing_version=expected_fencing_version,
        )
        if not cls._source_fence_matches(job, source):
            return cls._terminalize_source_fence_drift(db, job=job, source=source)
        assert source is not None
        source.status = "failed"
        source.health_state = "failed"
        source.health_checked_at = utcnow()
        source.health_error_code = safe_code
        source.row_version += 1
        job.state = "failed"
        job.result_source_status = "failed"
        job.failure_code = safe_code
        job.failure_reason = safe_reason
        job.lease_owner_token = None
        job.lease_expires_at = None
        job.heartbeat_at = None
        audit(
            db,
            workspace_id=workspace_id,
            actor_id=job.actor_id,
            action="source.validation_failed",
            target_type="SourceValidationJob",
            target_id=job.id,
            request_id=job.request_id,
            reason=safe_reason,
            after={
                "source_connection_id": source.id,
                "source_status": "failed",
                "failure_code": safe_code,
            },
        )
        db.commit()
        return job
