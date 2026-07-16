"""Append-only, redacted audit projections."""

from __future__ import annotations

from uuid import UUID

from pydantic import AwareDatetime

from ..base import ContractModel, Digest, NonEmptyString
from ..enums import DataAuthenticity
from .common import ImmutableResource


class AuditLogResponse(ImmutableResource):
    actor_id: UUID
    action: NonEmptyString
    target_type: NonEmptyString
    target_id: UUID
    before_digest: Digest | None = None
    after_digest: Digest | None = None
    reason: str | None = None
    request_id: UUID
    occurred_at: AwareDatetime
    data_authenticity: DataAuthenticity


class AuditLogFilter(ContractModel):
    action: str | None = None
    target_type: str | None = None
    target_id: UUID | None = None
    actor_id: UUID | None = None
    occurred_after: AwareDatetime | None = None
    occurred_before: AwareDatetime | None = None
