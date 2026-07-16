"""Source connection and explicit import-transfer contracts."""

from __future__ import annotations

import hashlib
from typing import Annotated, Literal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    AwareDatetime,
    Field,
    HttpUrl,
    StringConstraints,
    field_validator,
    model_validator,
)

from ..base import ContractModel, Digest, JsonObject, NonEmptyString, VersionString
from ..enums import (
    CollectionRunState,
    ConnectorCapability,
    DataAuthenticity,
    DataScope,
    ImportFinalizationJobState,
    ImportSessionState,
    ModelEgressAuthorization,
    SourceConnectorType,
    SourceFreshnessState,
    SourceHealthState,
    SourceKind,
    SourceRuntime,
    SourceStatus,
    SourceValidationCommand,
    SourceValidationJobState,
    TransferConsentDecision,
    WatchlistCadence,
)
from .common import ImmutableResource, MutableResource


def _validate_source_pair(source_kind: SourceKind, runtime: SourceRuntime) -> None:
    expected = {
        SourceKind.CLOUD: SourceRuntime.CLOUD,
        SourceKind.LOCAL: SourceRuntime.MAC_DEVICE,
        SourceKind.IMPORTED_DATASET: SourceRuntime.STATIC_IMPORT,
    }
    if expected[source_kind] != runtime:
        raise ValueError("source_kind and runtime are incompatible")


CredentialReference = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=8,
        max_length=250,
        pattern=r"^(vault|keychain|stronghold|env)://[A-Za-z0-9][A-Za-z0-9/_.:-]*$",
    ),
]
GitHubSlug = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=100,
        pattern=r"^[A-Za-z0-9_.-]+$",
    ),
]


def _validate_timezone(value: str) -> str:
    try:
        ZoneInfo(value)
    except ZoneInfoNotFoundError as exc:
        raise ValueError("timezone must be a valid IANA time zone") from exc
    return value


class GitHubRepositoryConfig(ContractModel):
    owner: GitHubSlug
    repository: GitHubSlug
    include_issues: bool = True
    include_discussions: bool = True
    include_releases: bool = True

    @model_validator(mode="after")
    def require_capability(self) -> GitHubRepositoryConfig:
        if not (self.include_issues or self.include_discussions or self.include_releases):
            raise ValueError("GitHub repository config must enable at least one capability")
        return self


class GitHubSourceConfig(ContractModel):
    connector_type: Literal["github"] = "github"
    repositories: list[GitHubRepositoryConfig] = Field(min_length=1, max_length=1)

    @model_validator(mode="after")
    def unique_repositories(self) -> GitHubSourceConfig:
        identities = [
            (item.owner.casefold(), item.repository.casefold()) for item in self.repositories
        ]
        if len(identities) != len(set(identities)):
            raise ValueError("GitHub repositories must be unique")
        return self


class RSSFeedConfig(ContractModel):
    name: NonEmptyString
    feed_url: HttpUrl

    @field_validator("feed_url")
    @classmethod
    def require_safe_https_url(cls, value: HttpUrl) -> HttpUrl:
        if value.scheme != "https" or value.username is not None or value.password is not None:
            raise ValueError("RSS feed URL must use HTTPS without userinfo")
        return value


class RSSSourceConfig(ContractModel):
    connector_type: Literal["rss"] = "rss"
    feeds: list[RSSFeedConfig] = Field(min_length=1, max_length=1)

    @model_validator(mode="after")
    def unique_feeds(self) -> RSSSourceConfig:
        urls = [str(item.feed_url) for item in self.feeds]
        if len(urls) != len(set(urls)):
            raise ValueError("RSS feed URLs must be unique")
        return self


CloudSourceConfig = Annotated[
    GitHubSourceConfig | RSSSourceConfig,
    Field(discriminator="connector_type"),
]


class SourceFreshness(ContractModel):
    last_success_at: AwareDatetime | None = None
    state: SourceFreshnessState

    @model_validator(mode="after")
    def validate_projection(self) -> SourceFreshness:
        if self.state == SourceFreshnessState.NEVER and self.last_success_at is not None:
            raise ValueError("never-fetched source cannot have last_success_at")
        if self.state != SourceFreshnessState.NEVER and self.last_success_at is None:
            raise ValueError("current or stale freshness requires last_success_at")
        return self


class SourceHealth(ContractModel):
    state: SourceHealthState
    checked_at: AwareDatetime | None = None
    last_error_code: str | None = None


class ImportManifestSummary(ContractModel):
    id: UUID
    content_count: int = Field(ge=0)
    finalized_at: AwareDatetime
    data_authenticity: DataAuthenticity


class SourceConnectionCreateRequest(ContractModel):
    name: NonEmptyString
    source_kind: SourceKind
    runtime: SourceRuntime
    connector_type: SourceConnectorType
    connector_version: VersionString
    data_scope: DataScope
    source_config: CloudSourceConfig | None = None
    credential_ref: CredentialReference | None = None
    cadence: WatchlistCadence | None = None
    timezone: NonEmptyString | None = None

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str | None) -> str | None:
        return _validate_timezone(value) if value is not None else None

    @model_validator(mode="after")
    def validate_runtime(self) -> SourceConnectionCreateRequest:
        _validate_source_pair(self.source_kind, self.runtime)
        if self.source_kind == SourceKind.CLOUD:
            if self.connector_type not in {SourceConnectorType.GITHUB, SourceConnectorType.RSS}:
                raise ValueError("cloud source requires a GitHub or RSS connector")
            if self.source_config is None:
                raise ValueError("cloud source requires strict source_config")
            if self.source_config.connector_type != self.connector_type.value:
                raise ValueError("source_config must match connector_type")
            if self.cadence is None or self.timezone is None:
                raise ValueError("cloud source requires cadence and timezone")
        elif self.source_kind == SourceKind.IMPORTED_DATASET:
            if self.connector_type not in {
                SourceConnectorType.CSV,
                SourceConnectorType.SEED_FIXTURE,
            }:
                raise ValueError("imported dataset requires csv or seed_fixture connector")
            if self.source_config is not None or self.credential_ref is not None:
                raise ValueError("imported dataset cannot have cloud config or credential_ref")
            if self.cadence is not None or self.timezone is not None:
                raise ValueError("imported dataset cannot have a collection cadence")
        return self


class SourceConnectionUpdateRequest(ContractModel):
    name: NonEmptyString | None = None
    data_scope: DataScope | None = None
    source_config: CloudSourceConfig | None = None
    credential_ref: CredentialReference | None = None
    cadence: WatchlistCadence | None = None
    timezone: NonEmptyString | None = None
    expected_row_version: int = Field(ge=1)

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str | None) -> str | None:
        return _validate_timezone(value) if value is not None else None

    @model_validator(mode="after")
    def require_change(self) -> SourceConnectionUpdateRequest:
        if self.model_fields_set == {"expected_row_version"}:
            raise ValueError("source update must change at least one field")
        return self


class SourceConnectionResponse(MutableResource):
    name: NonEmptyString
    source_kind: SourceKind
    runtime: SourceRuntime
    connector_type: SourceConnectorType
    connector_version: VersionString
    status: SourceStatus
    source_config: CloudSourceConfig | None = None
    cadence: WatchlistCadence | None = None
    timezone: NonEmptyString | None = None
    last_run_at: AwareDatetime | None = None
    last_success_at: AwareDatetime | None = None
    health: SourceHealth
    freshness: SourceFreshness
    capabilities: list[ConnectorCapability]
    data_scope: DataScope
    current_import_manifest: ImportManifestSummary | None = None
    data_authenticity: DataAuthenticity

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str | None) -> str | None:
        return _validate_timezone(value) if value is not None else None

    @model_validator(mode="after")
    def validate_runtime(self) -> SourceConnectionResponse:
        _validate_source_pair(self.source_kind, self.runtime)
        if self.source_kind == SourceKind.CLOUD:
            if self.source_config is None or self.cadence is None or self.timezone is None:
                raise ValueError("cloud source response requires config, cadence, and timezone")
            if self.source_config.connector_type != self.connector_type.value:
                raise ValueError("source_config must match connector_type")
        if self.source_kind == SourceKind.IMPORTED_DATASET:
            if self.connector_type not in {
                SourceConnectorType.CSV,
                SourceConnectorType.SEED_FIXTURE,
            }:
                raise ValueError("imported dataset requires csv or seed_fixture connector")
            if self.capabilities:
                raise ValueError("imported datasets do not expose scheduled connector capabilities")
            if (
                self.source_config is not None
                or self.cadence is not None
                or self.timezone is not None
            ):
                raise ValueError("imported datasets do not have cloud config or cadence")
        if self.last_success_at != self.freshness.last_success_at:
            raise ValueError("last_success_at must equal the freshness projection")
        return self


class SourceValidationRequest(ContractModel):
    expected_row_version: int = Field(ge=1)
    reason: NonEmptyString


class SourceValidationJobResponse(ContractModel):
    id: UUID
    workspace_id: UUID
    source_connection_id: UUID
    command: SourceValidationCommand
    state: SourceValidationJobState
    expected_source_row_version: int = Field(ge=1)
    attempt: int = Field(ge=0)
    result_source_status: SourceStatus | None = None
    failure_code: str | None = None
    failure_reason: str | None = None
    lease_expires_at: AwareDatetime | None = None
    created_at: AwareDatetime
    updated_at: AwareDatetime
    data_authenticity: DataAuthenticity

    @model_validator(mode="after")
    def validate_outcome(self) -> SourceValidationJobResponse:
        terminal_statuses = {
            SourceStatus.HEALTHY,
            SourceStatus.DEGRADED,
            SourceStatus.AUTH_REQUIRED,
            SourceStatus.FAILED,
        }
        if self.state == SourceValidationJobState.COMPLETED:
            if self.result_source_status not in terminal_statuses:
                raise ValueError("completed validation requires a terminal source status")
        elif self.state == SourceValidationJobState.FAILED:
            if self.result_source_status != SourceStatus.FAILED or self.failure_code is None:
                raise ValueError("failed validation requires a failure code and failed source")
        elif any(
            value is not None
            for value in (self.result_source_status, self.failure_code, self.failure_reason)
        ):
            raise ValueError("non-terminal validation cannot have an outcome")
        if self.state == SourceValidationJobState.CLAIMED:
            if self.lease_expires_at is None or self.attempt < 1:
                raise ValueError("claimed validation requires an active lease projection")
        elif self.lease_expires_at is not None:
            raise ValueError("only claimed validation can expose a lease")
        return self


class ImportSessionCreateRequest(ContractModel):
    source_connection_id: UUID
    expected_source_row_version: int = Field(ge=1)
    expected_current_import_manifest_id: UUID | None = None
    local_manifest_digest: Digest
    file_digest: Digest
    expected_upload_digest: Digest
    client_file_name: NonEmptyString
    file_size_bytes: int = Field(gt=0)
    media_type: NonEmptyString
    parser_version: VersionString
    schema_version: VersionString
    selected_scope_json: JsonObject
    selected_scope_digest: Digest

    @field_validator("client_file_name")
    @classmethod
    def reject_filesystem_path(cls, value: str) -> str:
        if value in {".", ".."} or "/" in value or "\\" in value or "\x00" in value:
            raise ValueError("client_file_name must be a base name, not a filesystem path")
        return value


class ImportSessionResponse(MutableResource):
    source_connection_id: UUID
    expected_source_row_version: int = Field(ge=1)
    expected_current_import_manifest_id: UUID | None = None
    local_manifest_digest: Digest
    file_digest: Digest
    expected_upload_digest: Digest
    client_file_name: NonEmptyString
    file_size_bytes: int = Field(gt=0)
    media_type: NonEmptyString
    parser_version: VersionString
    schema_version: VersionString
    selected_scope_json: JsonObject
    selected_scope_digest: Digest
    state: ImportSessionState
    uploaded_object_key: str | None = None
    uploaded_object_digest: Digest | None = None
    terminal_manifest_id: UUID | None = None
    failure_code: str | None = None
    retryable: bool
    data_authenticity: DataAuthenticity

    @field_validator("client_file_name")
    @classmethod
    def reject_filesystem_path(cls, value: str) -> str:
        return ImportSessionCreateRequest.reject_filesystem_path(value)


class UploadObjectScope(ContractModel):
    object_key: NonEmptyString
    max_bytes: int = Field(gt=0)
    media_type: NonEmptyString


class UploadConsentPreviewRequest(ContractModel):
    expected_row_version: int = Field(ge=1)


class UploadConsentScopeBinding(ContractModel):
    """Exact destination and optimistic-concurrency scope shown before consent."""

    destination_workspace_id: UUID
    import_session_id: UUID
    import_session_row_version: int = Field(ge=1)
    source_connection_id: UUID
    source_row_version: int = Field(ge=1)
    current_import_manifest_id: UUID | None = None
    local_manifest_digest: Digest
    file_digest: Digest
    expected_upload_digest: Digest
    selected_scope_digest: Digest
    upload_object_scope: UploadObjectScope
    policy_version: VersionString


class UploadConsentPreviewResponse(ContractModel):
    preview_scope: UploadConsentScopeBinding
    scope_digest: Digest
    data_authenticity: DataAuthenticity


class UploadConsentRequest(ContractModel):
    preview_scope: UploadConsentScopeBinding
    scope_digest: Digest
    expires_at: AwareDatetime
    confirmation: bool


class TransferConsentRecordResponse(ImmutableResource):
    import_session_id: UUID
    decision: TransferConsentDecision
    local_manifest_digest: Digest
    file_digest: Digest
    expected_upload_digest: Digest
    selected_scope_json: JsonObject
    selected_scope_digest: Digest
    destination_workspace_id: UUID
    upload_object_scope: UploadObjectScope
    model_egress_authorization: ModelEgressAuthorization
    policy_version: VersionString
    actor_id: UUID
    recorded_at: AwareDatetime
    expires_at: AwareDatetime | None = None
    supersedes_id: UUID | None = None
    data_authenticity: DataAuthenticity


class UploadGrantMetadata(ContractModel):
    """Non-secret information needed to correlate a separately issued upload capability."""

    object_key: NonEmptyString
    maximum_bytes: int = Field(gt=0)
    media_type: NonEmptyString
    expires_at: AwareDatetime


class UploadConsentResponse(ContractModel):
    import_session: ImportSessionResponse
    consent_record: TransferConsentRecordResponse
    upload: UploadGrantMetadata
    data_authenticity: DataAuthenticity


class UploadCompleteRequest(ContractModel):
    expected_row_version: int = Field(ge=1)
    object_key: NonEmptyString


class ImportFinalizeRequest(ContractModel):
    expected_row_version: int = Field(ge=1)


class ImportFinalizationJobResponse(ContractModel):
    id: UUID
    command_id: UUID
    workspace_id: UUID
    import_session_id: UUID
    expected_session_row_version: int = Field(ge=1)
    expected_source_row_version: int = Field(ge=1)
    expected_current_import_manifest_id: UUID | None = None
    consent_record_id: UUID
    state: ImportFinalizationJobState
    attempt: int = Field(ge=1)
    result_manifest_id: UUID | None = None
    failure_code: str | None = None
    lease_expires_at: AwareDatetime | None = None
    created_at: AwareDatetime
    updated_at: AwareDatetime
    data_authenticity: DataAuthenticity

    @model_validator(mode="after")
    def validate_terminal_outcome(self) -> ImportFinalizationJobResponse:
        if self.state == ImportFinalizationJobState.COMPLETED:
            if self.result_manifest_id is None or self.failure_code is not None:
                raise ValueError("completed finalization requires only a result manifest")
        elif self.state == ImportFinalizationJobState.FAILED:
            if self.failure_code is None or self.result_manifest_id is not None:
                raise ValueError("failed finalization requires only a failure code")
        elif self.result_manifest_id is not None or self.failure_code is not None:
            raise ValueError("non-terminal finalization cannot have an outcome")
        return self


class ImportRecoveryItem(ContractModel):
    import_session: ImportSessionResponse
    finalization_job: ImportFinalizationJobResponse | None = None
    data_authenticity: DataAuthenticity


class ImportCancelRequest(ContractModel):
    expected_row_version: int = Field(ge=1)
    reason: NonEmptyString


class ImportManifestResponse(ImmutableResource):
    import_session_id: UUID
    source_connection_id: UUID
    file_digest: Digest
    uploaded_object_key: NonEmptyString
    uploaded_object_digest: Digest
    parser_version: VersionString
    schema_version: VersionString
    selected_scope_digest: Digest
    consent_record_id: UUID
    normalized_payload_digest: Digest
    content_count: int = Field(ge=0)
    finalized_at: AwareDatetime
    data_authenticity: DataAuthenticity


class ImportManifestProposal(ContractModel):
    """Worker-produced terminal manifest fields; the API validates and persists them verbatim."""

    id: UUID
    workspace_id: UUID
    import_session_id: UUID
    source_connection_id: UUID
    file_digest: Digest
    uploaded_object_key: NonEmptyString
    uploaded_object_digest: Digest
    parser_version: VersionString
    schema_version: VersionString
    selected_scope_digest: Digest
    consent_record_id: UUID
    normalized_payload_digest: Digest
    content_count: int = Field(ge=1)
    finalized_at: AwareDatetime
    data_authenticity: DataAuthenticity


class NormalizedRawContentProposal(ContractModel):
    id: UUID
    workspace_id: UUID
    source_connection_id: UUID
    source_item_id: NonEmptyString
    title: NonEmptyString
    body: NonEmptyString
    canonical_url: str | None = None
    author: str | None = None
    published_at: AwareDatetime | None = None
    captured_at: AwareDatetime
    content_digest: Digest
    data_authenticity: DataAuthenticity
    metadata: JsonObject = Field(default_factory=dict)


class NormalizedContentItemProposal(ContractModel):
    id: UUID
    workspace_id: UUID
    source_connection_id: UUID
    source_item_id: NonEmptyString
    canonical_url: str | None = None
    identity_key: NonEmptyString
    title: NonEmptyString
    current_version_id: UUID
    duplicate_cluster_id: UUID | None = None
    independence_group_id: UUID | None = None
    data_authenticity: DataAuthenticity


class NormalizedContentVersionProposal(ContractModel):
    id: UUID
    workspace_id: UUID
    content_item_id: UUID
    version_number: int = Field(ge=1)
    content_digest: Digest
    normalized_title: NonEmptyString
    normalized_body: NonEmptyString
    captured_at: AwareDatetime
    parser_version: VersionString
    canonical_url: str | None = None
    author: str | None = None
    data_authenticity: DataAuthenticity
    metadata: JsonObject = Field(default_factory=dict)


class ImportNormalizationProposal(ContractModel):
    """Exact normalized graph emitted by the sole Worker import finalizer."""

    manifest: ImportManifestProposal
    raw_items: list[NormalizedRawContentProposal] = Field(min_length=1)
    content_items: list[NormalizedContentItemProposal] = Field(min_length=1)
    content_versions: list[NormalizedContentVersionProposal] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_frozen_graph(self) -> ImportNormalizationProposal:
        count = len(self.content_versions)
        if len(self.raw_items) != count or len(self.content_items) != count:
            raise ValueError("normalized raw/content/version collections must be one-to-one")
        if self.manifest.content_count != count:
            raise ValueError("manifest content_count must match normalized versions")
        for values, label in (
            (self.raw_items, "raw item"),
            (self.content_items, "content item"),
            (self.content_versions, "content version"),
        ):
            if len({value.id for value in values}) != len(values):
                raise ValueError(f"normalized {label} IDs must be unique")
        for raw, item, version in zip(
            self.raw_items, self.content_items, self.content_versions, strict=True
        ):
            expected_workspace = self.manifest.workspace_id
            if (
                raw.workspace_id != expected_workspace
                or item.workspace_id != expected_workspace
                or version.workspace_id != expected_workspace
            ):
                raise ValueError("normalized graph crosses workspace scope")
            if (
                raw.source_connection_id != self.manifest.source_connection_id
                or item.source_connection_id != self.manifest.source_connection_id
            ):
                raise ValueError("normalized graph crosses source scope")
            if raw.source_item_id != item.source_item_id:
                raise ValueError("raw and content source item IDs must match")
            if item.current_version_id != version.id or version.content_item_id != item.id:
                raise ValueError("normalized content/version lineage is invalid")
            if raw.content_digest != version.content_digest:
                raise ValueError("raw and normalized content digests must match")
            if (
                raw.canonical_url != item.canonical_url
                or item.canonical_url != version.canonical_url
            ):
                raise ValueError("canonical URL must be stable across normalized lineage")
            if raw.title != item.title or item.title != version.normalized_title:
                raise ValueError("normalized title must be stable across lineage")
            if (
                len(
                    {
                        raw.data_authenticity,
                        item.data_authenticity,
                        version.data_authenticity,
                        self.manifest.data_authenticity,
                    }
                )
                != 1
            ):
                raise ValueError("normalized lineage authenticity must match the manifest")
        normalized_digest = (
            "sha256:"
            + hashlib.sha256(
                "\n".join(str(version.content_digest) for version in self.content_versions).encode()
            ).hexdigest()
        )
        if self.manifest.normalized_payload_digest != normalized_digest:
            raise ValueError("manifest normalized_payload_digest does not match versions")
        return self


class CollectionInputWindow(ContractModel):
    start: AwareDatetime
    end: AwareDatetime

    @model_validator(mode="after")
    def validate_order(self) -> CollectionInputWindow:
        if self.end <= self.start:
            raise ValueError("collection input window end must be after start")
        return self


class CollectionCounters(ContractModel):
    fetched: int = Field(ge=0)
    created: int = Field(ge=0)
    updated: int = Field(ge=0)
    skipped: int = Field(ge=0)
    failed: int = Field(ge=0)
    signal_candidate_count: int = Field(default=0, ge=0)
    signal_count: int = Field(default=0, ge=0)


class CollectionRunResponse(MutableResource):
    watchlist_id: UUID
    source_connection_id: UUID
    state: CollectionRunState
    cadence: WatchlistCadence
    timezone: NonEmptyString
    scheduled_for: AwareDatetime
    input_window: CollectionInputWindow
    attempt_number: int = Field(ge=1)
    attempt_of: UUID | None = None
    backoff_until: AwareDatetime | None = None
    partial_success: bool
    counters: CollectionCounters
    freshness: SourceFreshness
    started_at: AwareDatetime | None = None
    finished_at: AwareDatetime | None = None
    data_authenticity: DataAuthenticity

    @model_validator(mode="after")
    def validate_partial_success(self) -> CollectionRunResponse:
        expected = self.state == CollectionRunState.PARTIAL_SUCCESS
        if self.partial_success != expected:
            raise ValueError("partial_success must match the collection state")
        return self
