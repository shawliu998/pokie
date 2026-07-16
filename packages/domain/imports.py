"""Import coordination state and exact-scope transfer-consent invariants."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum

from .canonical import canonical_digest, require_sha256_digest
from .errors import (
    ConsentRejected,
    InvalidTransition,
    InvariantViolation,
    ObjectScopeMismatch,
    WorkspaceScopeViolation,
)


class ImportState(StrEnum):
    DRAFT = "draft"
    CONSENTED = "consented"
    UPLOADED = "uploaded"
    VALIDATING = "validating"
    FINALIZED = "finalized"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ConsentDecision(StrEnum):
    GRANT = "grant"
    REVOKE = "revoke"


class ModelEgressAuthorization(StrEnum):
    NONE = "none"


TERMINAL_IMPORT_STATES = frozenset({ImportState.FINALIZED, ImportState.CANCELLED})
ACTIVE_IMPORT_STATES = frozenset(
    {
        ImportState.DRAFT,
        ImportState.CONSENTED,
        ImportState.UPLOADED,
        ImportState.VALIDATING,
        ImportState.FAILED,
    }
)

_NORMAL_TRANSITIONS: dict[ImportState, frozenset[ImportState]] = {
    ImportState.DRAFT: frozenset({ImportState.CONSENTED, ImportState.CANCELLED}),
    ImportState.CONSENTED: frozenset(
        {ImportState.UPLOADED, ImportState.FAILED, ImportState.CANCELLED}
    ),
    ImportState.UPLOADED: frozenset(
        {ImportState.VALIDATING, ImportState.FAILED, ImportState.CANCELLED}
    ),
    ImportState.VALIDATING: frozenset(
        {ImportState.FINALIZED, ImportState.FAILED, ImportState.CANCELLED}
    ),
    ImportState.FAILED: frozenset({ImportState.CANCELLED}),
    ImportState.FINALIZED: frozenset(),
    ImportState.CANCELLED: frozenset(),
}


def _aware_utc(value: datetime, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise InvariantViolation(f"{field} must be timezone-aware.")
    return value.astimezone(UTC)


def _validate_object_key(value: str) -> None:
    parts = value.split("/")
    if (
        not value
        or value.startswith("/")
        or "\\" in value
        or "://" in value
        or any(part in {"", ".", ".."} for part in parts)
    ):
        raise InvariantViolation("Upload object key must be a safe relative object key.")


def require_safe_object_key(value: str) -> str:
    """Return a safe, non-normalizing relative object key or fail closed."""

    _validate_object_key(value)
    return value


def _validate_object_key_segment(value: str, field: str) -> None:
    if not value or value in {".", ".."} or "/" in value or "\\" in value or "://" in value:
        raise InvariantViolation(f"{field} must be a safe object-key segment.")


def import_payload_object_key(workspace_id: str, import_session_id: str) -> str:
    """Build the one canonical object key authorized for an import session."""

    _validate_object_key_segment(workspace_id, "workspace_id")
    _validate_object_key_segment(import_session_id, "import_session_id")
    return f"workspaces/{workspace_id}/imports/{import_session_id}/payload.csv"


def require_import_payload_object_key(
    workspace_id: str,
    import_session_id: str,
    object_key: str,
) -> str:
    """Require exact workspace/session containment before any object-store operation."""

    try:
        require_safe_object_key(object_key)
        expected = import_payload_object_key(workspace_id, import_session_id)
    except InvariantViolation as exc:
        raise ObjectScopeMismatch("The upload object key is outside its workspace scope.") from exc
    if object_key != expected:
        raise ObjectScopeMismatch("The upload object key is outside its workspace scope.")
    return object_key


@dataclass(frozen=True, slots=True)
class ImportPins:
    workspace_id: str
    source_connection_id: str
    expected_source_row_version: int
    expected_current_import_manifest_id: str | None
    local_manifest_digest: str
    file_digest: str
    expected_upload_digest: str
    selected_scope_digest: str
    parser_version: str
    schema_version: str

    def __post_init__(self) -> None:
        if self.expected_source_row_version < 1:
            raise InvariantViolation("expected_source_row_version must be positive.")
        for field in (
            "local_manifest_digest",
            "file_digest",
            "expected_upload_digest",
            "selected_scope_digest",
        ):
            require_sha256_digest(getattr(self, field), field=field)
        if not self.workspace_id or not self.source_connection_id:
            raise InvariantViolation("Import pins require workspace and source IDs.")
        if not self.parser_version or not self.schema_version:
            raise InvariantViolation("Parser and schema versions must be pinned.")

    @property
    def digest(self) -> str:
        return canonical_digest(
            {
                "workspace_id": self.workspace_id,
                "source_connection_id": self.source_connection_id,
                "expected_source_row_version": self.expected_source_row_version,
                "expected_current_import_manifest_id": self.expected_current_import_manifest_id,
                "local_manifest_digest": self.local_manifest_digest,
                "file_digest": self.file_digest,
                "expected_upload_digest": self.expected_upload_digest,
                "selected_scope_digest": self.selected_scope_digest,
                "parser_version": self.parser_version,
                "schema_version": self.schema_version,
            }
        )


@dataclass(frozen=True, slots=True)
class ImportSessionSnapshot:
    id: str
    pins: ImportPins
    state: ImportState = ImportState.DRAFT
    file_size_bytes: int = 0
    media_type: str = "text/csv"
    row_version: int = 1
    retryable: bool = False
    failure_code: str | None = None

    def __post_init__(self) -> None:
        try:
            object.__setattr__(self, "state", ImportState(self.state))
        except ValueError as exc:
            raise InvariantViolation("ImportSession has an unknown state.") from exc
        if not self.id:
            raise InvariantViolation("ImportSession requires an ID.")
        if self.file_size_bytes < 0:
            raise InvariantViolation("file_size_bytes cannot be negative.")
        if not self.media_type:
            raise InvariantViolation("media_type is required.")
        if self.row_version < 1:
            raise InvariantViolation("row_version must be positive.")
        if self.state is not ImportState.FAILED and self.retryable:
            raise InvariantViolation("Only a failed ImportSession can be retryable.")
        if self.state is ImportState.FAILED and not self.failure_code:
            raise InvariantViolation("A failed ImportSession requires failure_code.")

    @property
    def workspace_id(self) -> str:
        return self.pins.workspace_id


@dataclass(frozen=True, slots=True)
class TransferConsentRecord:
    id: str
    workspace_id: str
    import_session_id: str
    decision: ConsentDecision
    local_manifest_digest: str
    file_digest: str
    expected_upload_digest: str
    selected_scope_digest: str
    destination_workspace_id: str
    upload_object_key: str
    max_bytes: int
    media_type: str
    policy_version: str
    actor_id: str
    recorded_at: datetime
    expires_at: datetime | None = None
    supersedes_id: str | None = None
    model_egress_authorization: ModelEgressAuthorization = ModelEgressAuthorization.NONE

    def __post_init__(self) -> None:
        try:
            object.__setattr__(self, "decision", ConsentDecision(self.decision))
            object.__setattr__(
                self,
                "model_egress_authorization",
                ModelEgressAuthorization(self.model_egress_authorization),
            )
        except ValueError as exc:
            raise InvariantViolation("Transfer consent contains an unknown enum value.") from exc
        if not self.id or not self.import_session_id or not self.actor_id:
            raise InvariantViolation("Consent records require record, session and actor IDs.")
        for field in (
            "local_manifest_digest",
            "file_digest",
            "expected_upload_digest",
            "selected_scope_digest",
        ):
            require_sha256_digest(getattr(self, field), field=field)
        _aware_utc(self.recorded_at, "recorded_at")
        if self.decision is ConsentDecision.GRANT:
            if self.expires_at is None:
                raise InvariantViolation("A transfer grant requires expires_at.")
            if _aware_utc(self.expires_at, "expires_at") <= _aware_utc(
                self.recorded_at, "recorded_at"
            ):
                raise InvariantViolation("A transfer grant must expire after it is recorded.")
            if self.supersedes_id is not None:
                raise InvariantViolation("A transfer grant cannot supersede another record.")
            if not self.upload_object_key or self.max_bytes < 1 or not self.media_type:
                raise InvariantViolation("A grant requires an exact object scope and byte limit.")
            require_import_payload_object_key(
                self.workspace_id,
                self.import_session_id,
                self.upload_object_key,
            )
        else:
            if not self.supersedes_id:
                raise InvariantViolation("A revoke must supersede an exact grant ID.")
        if self.model_egress_authorization is not ModelEgressAuthorization.NONE:
            raise InvariantViolation("Import upload consent cannot authorize model egress.")


@dataclass(frozen=True, slots=True)
class EffectiveConsent:
    grant: TransferConsentRecord
    resolved_at: datetime


@dataclass(frozen=True, slots=True)
class ObservedUpload:
    object_key: str
    size_bytes: int
    media_type: str
    digest: str
    exists: bool = True

    def __post_init__(self) -> None:
        require_sha256_digest(self.digest, field="uploaded_object_digest")
        if self.size_bytes < 0:
            raise InvariantViolation("Observed object size cannot be negative.")


def transition_import_session(
    session: ImportSessionSnapshot,
    target: ImportState,
    *,
    retryable: bool = False,
    failure_code: str | None = None,
    original_pins: ImportPins | None = None,
) -> ImportSessionSnapshot:
    """Apply one legal transition and return a new immutable snapshot."""

    try:
        target = ImportState(target)
    except ValueError as exc:
        raise InvariantViolation("ImportSession transition target is unknown.") from exc
    if session.state is ImportState.FAILED and target is ImportState.VALIDATING:
        if not session.retryable:
            raise InvalidTransition("ImportSession", session.state.value, "retry_validation")
        if original_pins is not None and original_pins != session.pins:
            raise InvariantViolation(
                "A failed import may retry only with all pinned inputs unchanged."
            )
    elif target not in _NORMAL_TRANSITIONS[session.state]:
        raise InvalidTransition("ImportSession", session.state.value, target.value)

    if target is ImportState.FAILED and not failure_code:
        raise InvariantViolation("A failed transition requires failure_code.")
    if target is not ImportState.FAILED and (retryable or failure_code is not None):
        raise InvariantViolation("Retry metadata is valid only for a failed transition.")

    return replace(
        session,
        state=target,
        retryable=retryable if target is ImportState.FAILED else False,
        failure_code=failure_code if target is ImportState.FAILED else None,
        row_version=session.row_version + 1,
    )


def _assert_grant_matches_session(
    session: ImportSessionSnapshot, grant: TransferConsentRecord
) -> None:
    if grant.workspace_id != session.workspace_id:
        raise WorkspaceScopeViolation()
    if grant.destination_workspace_id != session.workspace_id:
        raise ConsentRejected("Consent destination does not match the import workspace.")
    if grant.import_session_id != session.id:
        raise ConsentRejected("Consent belongs to a different import session.")
    expected = {
        "local_manifest_digest": session.pins.local_manifest_digest,
        "file_digest": session.pins.file_digest,
        "expected_upload_digest": session.pins.expected_upload_digest,
        "selected_scope_digest": session.pins.selected_scope_digest,
    }
    for field, value in expected.items():
        if getattr(grant, field) != value:
            raise ConsentRejected(
                f"Consent no longer matches pinned {field}.",
                code="CONSENT_SCOPE_MISMATCH",
                details={"field": field},
            )
    if grant.media_type != session.media_type:
        raise ConsentRejected(
            "Consent media type no longer matches the import session.",
            code="CONSENT_SCOPE_MISMATCH",
        )
    if grant.max_bytes < session.file_size_bytes:
        raise ConsentRejected(
            "Consent byte limit is smaller than the pinned file size.",
            code="CONSENT_SCOPE_MISMATCH",
        )


def consent_import_session(
    session: ImportSessionSnapshot,
    grant: TransferConsentRecord,
    *,
    now: datetime,
) -> ImportSessionSnapshot:
    """Validate an exact grant before atomically entering ``consented``."""

    if session.state is not ImportState.DRAFT:
        raise InvalidTransition("ImportSession", session.state.value, "upload_consent")
    if grant.decision is not ConsentDecision.GRANT:
        raise ConsentRejected("upload_consent requires a grant record.")
    _assert_grant_matches_session(session, grant)
    current_time = _aware_utc(now, "now")
    if _aware_utc(grant.recorded_at, "recorded_at") > current_time:
        raise ConsentRejected("The transfer grant is not effective yet.")
    assert grant.expires_at is not None
    if current_time >= _aware_utc(grant.expires_at, "expires_at"):
        raise ConsentRejected("The transfer grant has expired.")
    return transition_import_session(session, ImportState.CONSENTED)


def resolve_effective_consent(
    session: ImportSessionSnapshot,
    records: Iterable[TransferConsentRecord],
    *,
    now: datetime,
) -> EffectiveConsent:
    """Resolve the latest exact, unexpired grant with no later exact revoke.

    The resolver intentionally derives authorization from the append-only ledger
    on every call; ImportSession.state is coordination state, not authorization.
    """

    resolved_at = _aware_utc(now, "now")
    if session.state in {ImportState.DRAFT, ImportState.FINALIZED, ImportState.CANCELLED}:
        raise ConsentRejected(
            f"ImportSession state {session.state.value!r} cannot use upload consent.",
            code="INVALID_STATE",
        )

    ledger = list(records)
    session_records = [record for record in ledger if record.import_session_id == session.id]
    if any(record.workspace_id != session.workspace_id for record in session_records):
        raise WorkspaceScopeViolation()
    grants = [record for record in session_records if record.decision is ConsentDecision.GRANT]
    if not grants:
        raise ConsentRejected("No transfer grant exists for this import session.")

    grants.sort(key=lambda item: (_aware_utc(item.recorded_at, "recorded_at"), item.id))
    grant = grants[-1]
    _assert_grant_matches_session(session, grant)
    if _aware_utc(grant.recorded_at, "recorded_at") > resolved_at:
        raise ConsentRejected("The transfer grant is not effective yet.")
    assert grant.expires_at is not None
    if resolved_at >= _aware_utc(grant.expires_at, "expires_at"):
        raise ConsentRejected("The transfer grant has expired.")

    revoked = any(
        record.decision is ConsentDecision.REVOKE
        and record.supersedes_id == grant.id
        and _aware_utc(record.recorded_at, "recorded_at")
        >= _aware_utc(grant.recorded_at, "recorded_at")
        and _aware_utc(record.recorded_at, "recorded_at") <= resolved_at
        for record in session_records
    )
    if revoked:
        raise ConsentRejected("The transfer grant has been revoked.")
    return EffectiveConsent(grant=grant, resolved_at=resolved_at)


def verify_observed_upload(
    session: ImportSessionSnapshot,
    consent: EffectiveConsent,
    observed: ObservedUpload,
) -> None:
    """Validate object-store observations; no client assertion is trusted."""

    grant = consent.grant
    _assert_grant_matches_session(session, grant)
    if not observed.exists:
        raise ObjectScopeMismatch("The scoped upload object does not exist.")
    if observed.object_key != grant.upload_object_key:
        raise ObjectScopeMismatch("Observed upload object key is outside the grant scope.")
    if observed.size_bytes > grant.max_bytes:
        raise ObjectScopeMismatch("Observed upload exceeds the consent byte limit.")
    if observed.size_bytes != session.file_size_bytes:
        raise ObjectScopeMismatch("Observed upload size differs from the pinned file size.")
    if observed.media_type != grant.media_type or observed.media_type != session.media_type:
        raise ObjectScopeMismatch("Observed upload media type differs from the grant scope.")
    if observed.digest != session.pins.expected_upload_digest:
        raise ObjectScopeMismatch("Observed upload digest differs from the pinned payload.")


def complete_verified_upload(
    session: ImportSessionSnapshot,
    consent: EffectiveConsent,
    observed: ObservedUpload,
) -> ImportSessionSnapshot:
    """Verify server-observed bytes before atomically entering ``uploaded``."""

    if session.state is not ImportState.CONSENTED:
        raise InvalidTransition("ImportSession", session.state.value, "upload_complete")
    verify_observed_upload(session, consent, observed)
    return transition_import_session(session, ImportState.UPLOADED)


def assert_import_pins_unchanged(expected: ImportPins, actual: ImportPins) -> None:
    if expected != actual:
        raise InvariantViolation(
            "Import source pointer, digests, parser, schema and scope are immutable per session.",
            code="STALE_SOURCE_VERSION",
        )
