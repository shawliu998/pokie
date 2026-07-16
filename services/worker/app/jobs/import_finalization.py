"""Dedicated ImportFinalizationJob implementation."""

from __future__ import annotations

import csv
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from datetime import timedelta
from typing import NoReturn

from packages.domain.errors import ObjectScopeMismatch
from packages.domain.imports import require_import_payload_object_key
from services.worker.app.contracts import (
    ConsentError,
    ImportFinalizationCommand,
    ImportManifest,
    ImportSession,
    ImportSessionState,
    ObjectNotFoundError,
    ObjectStore,
    ObjectUnavailableError,
    ObjectVerificationError,
    RetryableJobError,
    SourcePointerError,
    StoredObject,
    TransferConsentRecord,
    WorkerDomainAdapter,
    now_utc,
)
from services.worker.app.pipelines.csv_import import normalize_csv_import
from services.worker.app.pipelines.digests import deterministic_id


class ImportFinalizationHandledError(RuntimeError):
    """Raised after a finalization command has been durably failed."""

    def __init__(self, failure_code: str, retryable: bool) -> None:
        super().__init__(failure_code)
        self.failure_code = failure_code
        self.retryable = retryable


class ImportFinalizationJob:
    """The only worker job allowed to resolve an ImportSession ID."""

    def __init__(
        self,
        domain: WorkerDomainAdapter,
        object_store: ObjectStore,
        lease_for: timedelta = timedelta(seconds=120),
    ) -> None:
        self.domain = domain
        self.object_store = object_store
        self.lease_for = lease_for

    def run(self, command: ImportFinalizationCommand) -> ImportManifest:
        replayed = self.domain.replay_completed_import_finalization(command)
        if replayed is not None:
            return replayed
        self._heartbeat(command)
        session = self.domain.get_import_session_for_finalization(command)
        source = self.domain.get_source_connection(session.source_connection_id)
        if source.row_version != command.expected_source_row_version:
            self._fail_handled(
                command,
                "STALE_SOURCE_ROW_VERSION",
                retryable=False,
                cause=SourcePointerError("stale source row version"),
            )
        if source.current_import_manifest_id != command.expected_current_import_manifest_id:
            self._fail_handled(
                command,
                "STALE_SOURCE_POINTER",
                retryable=False,
                cause=SourcePointerError("stale source manifest pointer"),
            )

        safe_object_key: str | None = None
        try:
            consent = self.domain.resolve_effective_consent(session, now_utc())
            object_key = session.uploaded_object_key or consent.upload_object_scope.object_key
            self._require_scoped_object_key(command, session, consent, object_key)
            safe_object_key = object_key
            self._heartbeat(command)
            stored = self._get_object_with_heartbeat(command, session, object_key)
            self._heartbeat(command)
            self._verify_object(
                session,
                consent.upload_object_scope.object_key,
                stored.key,
                stored.size_bytes,
                stored.media_type,
                stored.digest,
            )
            session.state = ImportSessionState.VALIDATING
            raw_items, content_items, content_versions, normalized_payload_digest = (
                normalize_csv_import(
                    session, stored.body, heartbeat=lambda: self._heartbeat(command)
                )
            )
            self._heartbeat(command)
            manifest = ImportManifest(
                id=deterministic_id("import-manifest", session.id, normalized_payload_digest),
                workspace_id=session.workspace_id,
                import_session_id=session.id,
                source_connection_id=session.source_connection_id,
                file_digest=session.file_digest,
                uploaded_object_key=stored.key,
                uploaded_object_digest=stored.digest,
                parser_version=session.parser_version,
                schema_version=session.schema_version,
                selected_scope_digest=session.selected_scope_digest,
                consent_record_id=consent.id,
                normalized_payload_digest=normalized_payload_digest,
                content_count=len(content_versions),
                finalized_at=now_utc(),
                data_authenticity=session.data_authenticity,
            )
            return self.domain.finalize_import(
                command, manifest, raw_items, content_items, content_versions
            )
        except ConsentError as exc:
            self._fail_handled(command, "CONSENT_EXPIRED_OR_REVOKED", retryable=False, cause=exc)
        except ObjectNotFoundError as exc:
            self._fail_handled(command, "OBJECT_NOT_FOUND", retryable=True, cause=exc)
        except ObjectVerificationError as exc:
            if safe_object_key is not None:
                self.object_store.quarantine_import_object(
                    workspace_id=session.workspace_id,
                    import_session_id=session.id,
                    key=safe_object_key,
                    reason="object verification failed",
                )
            self._fail_handled(command, "OBJECT_SCOPE_MISMATCH", retryable=False, cause=exc)
        except ObjectUnavailableError as exc:
            self._fail_handled(command, "OBJECT_UNAVAILABLE", retryable=True, cause=exc)
        except RetryableJobError as exc:
            self._fail_handled(command, "RETRYABLE_WORKER_ERROR", retryable=True, cause=exc)
        except SourcePointerError as exc:
            self._fail_handled(command, "STALE_SOURCE_POINTER", retryable=False, cause=exc)
        except (ValueError, TypeError, UnicodeError, csv.Error) as exc:
            self._fail_handled(command, "VALIDATION_ERROR", retryable=False, cause=exc)
        except KeyError as exc:
            self._fail_handled(command, "OBJECT_NOT_FOUND", retryable=True, cause=exc)

    def _verify_object(
        self,
        session: ImportSession,
        consent_object_key: str,
        stored_key: str,
        stored_size: int,
        stored_media_type: str,
        stored_digest: str,
    ) -> None:
        if stored_key != consent_object_key:
            raise ObjectVerificationError("object key does not match consent scope")
        if session.uploaded_object_key and stored_key != session.uploaded_object_key:
            raise ObjectVerificationError("object key does not match uploaded session key")
        if stored_size != session.file_size_bytes:
            raise ObjectVerificationError("object size mismatch")
        if stored_media_type != session.media_type:
            raise ObjectVerificationError("object media type mismatch")
        if stored_digest != session.expected_upload_digest:
            raise ObjectVerificationError("object digest mismatch")
        if session.uploaded_object_digest and stored_digest != session.uploaded_object_digest:
            raise ObjectVerificationError(
                "object digest does not match upload-complete observation"
            )

    @staticmethod
    def _require_scoped_object_key(
        command: ImportFinalizationCommand,
        session: ImportSession,
        consent: TransferConsentRecord,
        object_key: str,
    ) -> None:
        if (
            command.workspace_id != session.workspace_id
            or consent.workspace_id != session.workspace_id
            or consent.destination_workspace_id != session.workspace_id
            or consent.import_session_id != session.id
            or consent.upload_object_scope.object_key != object_key
        ):
            raise ObjectVerificationError("object key is outside the import workspace")
        try:
            require_import_payload_object_key(session.workspace_id, session.id, object_key)
            if session.uploaded_object_key is not None:
                require_import_payload_object_key(
                    session.workspace_id,
                    session.id,
                    session.uploaded_object_key,
                )
        except ObjectScopeMismatch as exc:
            raise ObjectVerificationError("object key is outside the import workspace") from exc

    def _heartbeat(self, command: ImportFinalizationCommand) -> None:
        self.domain.heartbeat_import_finalization(command, now_utc(), self.lease_for)

    def _fail_handled(
        self,
        command: ImportFinalizationCommand,
        failure_code: str,
        retryable: bool,
        cause: BaseException,
    ) -> NoReturn:
        self.domain.fail_import_finalization(command, failure_code, retryable)
        raise ImportFinalizationHandledError(failure_code, retryable) from cause

    def _get_object_with_heartbeat(
        self,
        command: ImportFinalizationCommand,
        session: ImportSession,
        key: str,
    ) -> StoredObject:
        interval_seconds = max(1.0, min(30.0, self.lease_for.total_seconds() / 3))
        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="glint-import-object")
        future = executor.submit(
            self.object_store.get_import_object,
            workspace_id=session.workspace_id,
            import_session_id=session.id,
            key=key,
        )
        try:
            while True:
                try:
                    return future.result(timeout=interval_seconds)
                except FutureTimeout:
                    self._heartbeat(command)
        finally:
            executor.shutdown(wait=future.done(), cancel_futures=True)
