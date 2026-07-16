"""Common envelopes and cursor pagination."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import Field, HttpUrl

from ..base import ContractModel, NonEmptyString, TimestampedModel
from ..enums import ErrorCode


class PageInfo(ContractModel):
    next_cursor: str | None = None
    has_more: bool


class CursorPagination(ContractModel):
    limit: int = Field(default=50, ge=1, le=100)
    cursor: str | None = None


class CursorPage[ItemT](ContractModel):
    items: list[ItemT]
    page: PageInfo


class ErrorBody(ContractModel):
    code: ErrorCode
    message: NonEmptyString
    request_id: UUID
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorEnvelope(ContractModel):
    error: ErrorBody


class AcceptedCommand(ContractModel):
    resource_id: UUID
    status_url: HttpUrl
    request_id: UUID
    trace_id: str | None = None


class MutableResource(TimestampedModel):
    id: UUID
    workspace_id: UUID
    row_version: int = Field(ge=1)


class ImmutableResource(ContractModel):
    id: UUID
    workspace_id: UUID
