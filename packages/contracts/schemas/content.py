"""Logical content and immutable content-version projections."""

from __future__ import annotations

from uuid import UUID

from pydantic import AwareDatetime, Field, HttpUrl

from ..base import ContractModel, Digest, JsonObject, NonEmptyString, VersionString
from ..enums import ContentAvailability, DataAuthenticity, DataScope, SourceKind
from .common import ImmutableResource, MutableResource


class ContentItemResponse(MutableResource):
    source_connection_id: UUID
    source_item_id: NonEmptyString
    canonical_url: HttpUrl | None = None
    identity_key: NonEmptyString
    title: NonEmptyString
    current_version_id: UUID
    duplicate_cluster_id: UUID | None = None
    data_authenticity: DataAuthenticity


class ContentSummary(ContractModel):
    content_item_id: UUID
    content_version_id: UUID
    source_connection_id: UUID
    title: NonEmptyString
    canonical_url: HttpUrl | None = None
    published_at: AwareDatetime | None = None
    captured_at: AwareDatetime
    version_number: int = Field(ge=1)
    content_digest: Digest
    locality: DataScope
    availability: ContentAvailability
    duplicate_cluster_id: UUID | None = None
    independence_group_id: UUID | None = None
    data_authenticity: DataAuthenticity


class ContentVersionResponse(ImmutableResource):
    content_item_id: UUID
    source_connection_id: UUID
    source_name: NonEmptyString
    source_kind: SourceKind
    source_item_id: NonEmptyString
    identity_key: NonEmptyString
    title: NonEmptyString
    canonical_url: HttpUrl | None = None
    duplicate_cluster_id: UUID | None = None
    independence_group_id: UUID | None = None
    version_number: int = Field(ge=1)
    content_digest: Digest
    normalized_title: NonEmptyString
    normalized_body: str
    metadata_json: JsonObject = Field(default_factory=dict)
    published_at: AwareDatetime | None = None
    captured_at: AwareDatetime
    parser_version: VersionString
    availability: ContentAvailability
    availability_last_checked_at: AwareDatetime
    availability_reason: NonEmptyString | None = None
    data_scope: DataScope
    data_authenticity: DataAuthenticity
